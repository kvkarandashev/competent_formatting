"""FastAPI application: state, PDF/log serving, SSE, and the config-editing menu API."""

import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .builds import build_dir_for, driver_log_path_for
from .config import (
    CLEAN_PROFILE,
    FULL_PROFILE,
    Document,
    EnvironmentTransform,
    Hook,
    MacroTransform,
    Profile,
    assign_document_id,
    save_config,
)
from .worker import CompileWorker, EventBus

STATIC_DIR = Path(__file__).parent / "static"


class ViewerState:
    """Server-side state: the persisted config plus transient UI/job state."""

    def __init__(self, workdir, config):
        self.workdir = Path(workdir)
        self.config = config
        self.lock = threading.Lock()
        self._active_profiles = {}

    def active_profile_for(self, doc_id):
        document = self.config.document(doc_id)
        if document is None:
            return FULL_PROFILE
        chosen = self._active_profiles.get(doc_id)
        if chosen in document.profile_names:
            return chosen
        return document.profile_names[0] if document.profiles else FULL_PROFILE

    def set_active_profile(self, doc_id, profile_name):
        self._active_profiles[doc_id] = profile_name

    def persist(self):
        save_config(self.workdir, self.config)


# ---------------------------------------------------------------- request bodies


class RecompileBody(BaseModel):
    target: str = "all"
    current: str | None = None


class TransformBody(BaseModel):
    """One entry of the clean profile: a macro name or an environment name, never both."""

    macro_name: str | None = None
    environment_name: str | None = None
    mode: str = "unwrap"


class DocumentBody(BaseModel):
    label: str
    main_tex: str
    profiles: list[str] | None = None


class DocumentPatchBody(BaseModel):
    label: str | None = None
    main_tex: str | None = None
    clean_transforms: list[TransformBody] | None = None


class HookBody(BaseModel):
    command: str
    cwd: str | None = None


def create_app(state, bus=None, worker=None):
    bus = bus or EventBus()
    worker = worker or CompileWorker(state, bus)
    app = FastAPI(title="competent_formatting viewer")
    app.state.viewer = state
    app.state.bus = bus
    app.state.worker = worker

    @app.on_event("startup")
    async def _bind_loop():
        bus.bind_loop(asyncio.get_running_loop())
        worker.start()
        if state.config.build_missing_on_start:
            worker.enqueue_missing()

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ------------------------------------------------------------ frontend

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=500, detail="frontend assets are missing")
        return HTMLResponse(index_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ state

    def state_payload():
        config = state.config
        documents = []
        for document in config.documents:
            documents.append(
                {
                    **document.model_dump(mode="json"),
                    "active_profile": state.active_profile_for(document.id),
                    "source_dir": str(document.source_dir),
                    "builds": [
                        _build_payload(document.id, profile.name) for profile in document.profiles
                    ],
                }
            )
        return {
            "workdir": str(state.workdir),
            "config_path": str(state.workdir / "competent_viewer.toml"),
            "host": config.host,
            "port": config.port,
            "latex_cmd": config.latex_cmd,
            "compile_all_profiles": config.compile_all_profiles,
            "global_hooks": [hook.model_dump(mode="json") for hook in config.global_hooks],
            "documents": documents,
            "busy": worker.current_job is not None,
            "current_job": worker.current_job,
        }

    def _build_payload(doc_id, profile_name):
        status = worker.status_for(doc_id, profile_name)
        build_dir = build_dir_for(state.workdir, doc_id, profile_name)
        document = state.config.document(doc_id)
        stem = document.main_stem if document else "main"
        pdf_path = build_dir / f"{stem}.pdf"
        return {
            "doc_id": doc_id,
            "profile": profile_name,
            "status": status.status,
            "returncode": status.returncode,
            "message": status.message,
            "duration_s": round(status.duration_s, 2),
            "finished_at": status.finished_at,
            "has_pdf": pdf_path.is_file(),
            "pdf_url": f"/api/pdf/{doc_id}/{profile_name}",
            "log_url": f"/api/log/{doc_id}/{profile_name}",
            "build_dir": str(build_dir),
            "driver_log_path": str(driver_log_path_for(state.workdir, doc_id, profile_name)),
            "tex_log_path": str(build_dir / f"{stem}.log"),
        }

    @app.get("/api/state")
    async def get_state():
        return state_payload()

    # ------------------------------------------------------------ artifacts

    def _require_document(doc_id):
        document = state.config.document(doc_id)
        if document is None:
            raise HTTPException(status_code=404, detail=f"no such document: {doc_id}")
        return document

    @app.get("/api/pdf/{doc_id}/{profile}")
    async def get_pdf(doc_id: str, profile: str):
        document = _require_document(doc_id)
        pdf_path = build_dir_for(state.workdir, doc_id, profile) / f"{document.main_stem}.pdf"
        if not pdf_path.is_file():
            raise HTTPException(status_code=404, detail="not built yet")
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/log/{doc_id}/{profile}", response_class=PlainTextResponse)
    async def get_log(doc_id: str, profile: str, kind: str = "driver"):
        document = _require_document(doc_id)
        build_dir = build_dir_for(state.workdir, doc_id, profile)
        if kind == "tex":
            log_path = build_dir / f"{document.main_stem}.log"
        elif kind == "driver":
            log_path = driver_log_path_for(state.workdir, doc_id, profile)
        else:
            raise HTTPException(status_code=400, detail="kind must be 'driver' or 'tex'")
        if not log_path.is_file():
            return PlainTextResponse(f"[no {kind} log yet at {log_path}]", status_code=404)
        body = log_path.read_text(encoding="utf-8", errors="replace")
        return PlainTextResponse(f"# {log_path}\n\n{body}", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------ events

    @app.get("/api/events")
    async def events(request: Request):
        subscriber = bus.subscribe()

        async def stream():
            try:
                yield {"event": "hello", "data": "{}"}
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(subscriber.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield {"event": "ping", "data": "{}"}
                        continue
                    import json as _json

                    yield {"event": event["type"], "data": _json.dumps(event["payload"])}
            finally:
                bus.unsubscribe(subscriber)

        return EventSourceResponse(stream())

    # ------------------------------------------------------------ recompile

    @app.post("/api/recompile")
    async def recompile(body: RecompileBody):
        try:
            queued = worker.enqueue(body.target, current=body.current)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no such document: {body.target}")
        return {"queued": queued, "state": state_payload()}

    @app.post("/api/active-profile/{doc_id}/{profile}")
    async def set_active_profile(doc_id: str, profile: str):
        document = _require_document(doc_id)
        if profile not in document.profile_names:
            raise HTTPException(status_code=404, detail=f"no such profile: {profile}")
        state.set_active_profile(doc_id, profile)
        return state_payload()

    # ------------------------------------------------------------ menu: documents

    @app.post("/api/documents")
    async def add_document(body: DocumentBody):
        with state.lock:
            main_tex = str(Path(body.main_tex).expanduser().resolve())
            if not Path(main_tex).is_file():
                raise HTTPException(status_code=400, detail=f"no such file: {main_tex}")
            if state.config.document_by_label(body.label) is not None:
                raise HTTPException(status_code=409, detail=f"label already used: {body.label}")
            taken = {document.id for document in state.config.documents}
            document = Document(
                id=assign_document_id(body.label, taken),
                label=body.label,
                main_tex=main_tex,
                profiles=_default_profiles(state.config),
            )
            state.config.documents.append(document)
            state.persist()
        return state_payload()

    @app.patch("/api/documents/{doc_id}")
    async def patch_document(doc_id: str, body: DocumentPatchBody):
        with state.lock:
            document = _require_document(doc_id)
            if body.label is not None:
                other = state.config.document_by_label(body.label)
                if other is not None and other.id != doc_id:
                    raise HTTPException(status_code=409, detail="label already used")
                document.label = body.label
            if body.main_tex is not None:
                main_tex = str(Path(body.main_tex).expanduser().resolve())
                if not Path(main_tex).is_file():
                    raise HTTPException(status_code=400, detail=f"no such file: {main_tex}")
                document.main_tex = main_tex
            if body.clean_transforms is not None:
                transforms = []
                for item in body.clean_transforms:
                    if item.environment_name:
                        transforms.append(
                            EnvironmentTransform(
                                environment_name=item.environment_name, mode=item.mode
                            )
                        )
                    elif item.macro_name:
                        transforms.append(
                            MacroTransform(macro_name=item.macro_name, mode=item.mode)
                        )
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail="a transform needs either macro_name or environment_name",
                        )
                _set_clean_profile(document, transforms)
            state.persist()
        return state_payload()

    @app.delete("/api/documents/{doc_id}")
    async def delete_document(doc_id: str):
        with state.lock:
            document = _require_document(doc_id)
            state.config.documents.remove(document)
            state.persist()
        return state_payload()

    # ------------------------------------------------------------ menu: hooks

    @app.post("/api/hooks")
    async def add_global_hook(body: HookBody):
        with state.lock:
            state.config.global_hooks.append(Hook(command=body.command, cwd=body.cwd))
            state.persist()
        return state_payload()

    @app.delete("/api/hooks/{index}")
    async def delete_global_hook(index: int):
        with state.lock:
            if not 0 <= index < len(state.config.global_hooks):
                raise HTTPException(status_code=404, detail="no such hook")
            state.config.global_hooks.pop(index)
            state.persist()
        return state_payload()

    @app.post("/api/documents/{doc_id}/hooks")
    async def add_document_hook(doc_id: str, body: HookBody):
        with state.lock:
            document = _require_document(doc_id)
            document.hooks.append(Hook(command=body.command, cwd=body.cwd))
            state.persist()
        return state_payload()

    @app.delete("/api/documents/{doc_id}/hooks/{index}")
    async def delete_document_hook(doc_id: str, index: int):
        with state.lock:
            document = _require_document(doc_id)
            if not 0 <= index < len(document.hooks):
                raise HTTPException(status_code=404, detail="no such hook")
            document.hooks.pop(index)
            state.persist()
        return state_payload()

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    return app


def _default_profiles(config):
    """Mirror the clean-profile transforms already in use in this session."""
    transforms = []
    for document in config.documents:
        profile = document.profile(CLEAN_PROFILE)
        if profile is not None and profile.transforms:
            transforms = [t.model_copy() for t in profile.transforms]
            break
    profiles = [Profile(name=FULL_PROFILE)]
    if transforms:
        profiles.append(Profile(name=CLEAN_PROFILE, transforms=transforms))
    return profiles


def _set_clean_profile(document, transforms):
    profile = document.profile(CLEAN_PROFILE)
    if not transforms:
        if profile is not None:
            document.profiles.remove(profile)
        return
    if profile is None:
        document.profiles.append(Profile(name=CLEAN_PROFILE, transforms=transforms))
    else:
        profile.transforms = transforms
