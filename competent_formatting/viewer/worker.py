"""Background compile worker and the SSE event bus feeding the browser.

Compilation never happens on a request handler: routes enqueue a batch and
return immediately, while a single worker thread drains the queue in order.
"""

import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .builds import build_dir_for, compile_build, run_hook


@dataclass
class BuildStatus:
    """Last known state of one ``(document, profile)`` build, for /api/state."""

    doc_id: str
    profile: str
    status: str = "unknown"  # unknown | queued | building | ok | warning | failed
    returncode: Optional[int] = None
    message: str = ""
    duration_s: float = 0.0
    finished_at: Optional[float] = None
    driver_log_path: Optional[str] = None
    tex_log_path: Optional[str] = None

    def key(self):
        return (self.doc_id, self.profile)


class EventBus:
    """Fan-out of worker events to every connected SSE client.

    ``publish`` is called from the worker thread; subscribers live on the event
    loop, so delivery hops through ``call_soon_threadsafe``.
    """

    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()
        self._loop = None

    def bind_loop(self, loop):
        self._loop = loop

    def subscribe(self):
        import asyncio

        subscriber = asyncio.Queue()
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

    def publish(self, event_type, payload=None):
        event = {"type": event_type, "payload": payload or {}, "t": time.time()}
        with self._lock:
            subscribers = list(self._subscribers)
        if self._loop is None:
            return event
        for subscriber in subscribers:
            try:
                self._loop.call_soon_threadsafe(subscriber.put_nowait, event)
            except RuntimeError:
                pass
        return event


@dataclass
class Batch:
    """One recompile request: an ordered queue of (document, profile) builds."""

    target: str  # "all" or a doc_id
    current: Optional[str] = None
    documents: list = field(default_factory=list)


class CompileWorker:
    """Single-threaded, ordered compile queue."""

    def __init__(self, state, bus):
        self.state = state  # ViewerState, see app.py
        self.bus = bus
        self.queue = queue.Queue()
        self.statuses = {}
        self.current_job = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="cf-view-compile", daemon=True)

    def start(self):
        self._thread.start()

    def status_for(self, doc_id, profile_name):
        with self._lock:
            status = self.statuses.get((doc_id, profile_name))
        if status is None:
            return BuildStatus(doc_id=doc_id, profile=profile_name)
        return status

    def all_statuses(self):
        with self._lock:
            return [asdict(status) for status in self.statuses.values()]

    def _set_status(self, doc_id, profile_name, **fields):
        with self._lock:
            status = self.statuses.setdefault(
                (doc_id, profile_name), BuildStatus(doc_id=doc_id, profile=profile_name)
            )
            for key, value in fields.items():
                setattr(status, key, value)
            return status

    def enqueue(self, target, current=None):
        """Queue a recompile batch; returns the ordered list of doc ids."""
        config = self.state.config
        if target == "all":
            documents = list(config.documents)
            # Spec 8: start with whatever the user is looking at right now.
            if current is not None:
                documents.sort(key=lambda d: 0 if d.id == current else 1)
        else:
            document = config.document(target)
            if document is None:
                raise KeyError(target)
            documents = [document]

        return self._enqueue_documents(documents, target, current)

    def enqueue_missing(self):
        """Queue only the documents that have no built PDF yet.

        Used at startup so opening a freshly cloned session shows compiled
        documents rather than "not built yet", without redoing work that the
        workdir already holds.
        """
        documents = [
            document
            for document in self.state.config.documents
            if self._missing_profiles(document)
        ]
        if not documents:
            return []
        return self._enqueue_documents(documents, "missing", None)

    def _missing_profiles(self, document):
        missing = []
        for profile in self._profiles_for(document):
            pdf_path = (
                build_dir_for(self.state.workdir, document.id, profile.name)
                / f"{document.main_stem}.pdf"
            )
            if not pdf_path.is_file():
                missing.append(profile.name)
        return missing

    def _enqueue_documents(self, documents, target, current):
        for document in documents:
            for profile in self._profiles_for(document):
                self._set_status(document.id, profile.name, status="queued", message="")

        batch = Batch(target=target, current=current, documents=documents)
        self.queue.put(batch)
        return [document.id for document in documents]

    def _profiles_for(self, document):
        if self.state.config.compile_all_profiles:
            return list(document.profiles)
        active = self.state.active_profile_for(document.id)
        profile = document.profile(active) or (document.profiles[0] if document.profiles else None)
        return [profile] if profile is not None else []

    def _run(self):
        while True:
            batch = self.queue.get()
            try:
                self._run_batch(batch)
            except Exception as error:  # a worker crash must not kill the server
                self.bus.publish(
                    "batch_finished", {"ok": False, "failed": [], "error": str(error)}
                )
            finally:
                self.queue.task_done()

    def _run_batch(self, batch):
        config = self.state.config
        workdir = self.state.workdir
        queued = [
            {"doc_id": document.id, "profiles": [p.name for p in self._profiles_for(document)]}
            for document in batch.documents
        ]
        self.bus.publish(
            "batch_started",
            {"targets": [batch.target], "queue": queued, "current": batch.current},
        )
        failed = []

        for hook in config.global_hooks:
            self._run_hook(hook, "global", workdir)

        for document in batch.documents:
            for hook in document.hooks:
                self._run_hook(hook, document.id, workdir)
            for profile in self._profiles_for(document):
                result = self._run_build(document, profile, workdir, config.latex_cmd)
                if not result.ok:
                    failed.append(f"{document.id}/{profile.name}")

        self.bus.publish("batch_finished", {"ok": not failed, "failed": failed})

    def _run_hook(self, hook, scope, workdir):
        self.bus.publish("hook_started", {"scope": scope, "command": hook.command})
        result = run_hook(
            hook,
            scope,
            workdir,
            on_line=lambda line: self.bus.publish(
                "log_line", {"doc_id": scope, "profile": "hook", "line": line}
            ),
        )
        self.bus.publish(
            "hook_finished",
            {"scope": scope, "command": hook.command, "exit_code": result.returncode},
        )
        return result

    def _run_build(self, document, profile, workdir, latex_cmd):
        self.current_job = (document.id, profile.name)
        self._set_status(document.id, profile.name, status="building", message="")
        self.bus.publish("build_started", {"doc_id": document.id, "profile": profile.name})

        def on_line(line):
            self.bus.publish(
                "log_line", {"doc_id": document.id, "profile": profile.name, "line": line}
            )

        result = compile_build(document, profile, workdir, latex_cmd, on_line=on_line)
        self._set_status(
            document.id,
            profile.name,
            status=result.status,
            returncode=result.returncode,
            message=result.message,
            duration_s=result.duration_s,
            finished_at=time.time(),
            driver_log_path=str(result.driver_log_path) if result.driver_log_path else None,
            tex_log_path=str(result.tex_log_path) if result.tex_log_path else None,
        )
        self.current_job = None
        self.bus.publish(
            "build_finished",
            {
                "doc_id": document.id,
                "profile": profile.name,
                "ok": result.ok,
                "status": result.status,
                "message": result.message,
                "returncode": result.returncode,
                "duration_s": round(result.duration_s, 2),
                "pdf_url": f"/api/pdf/{document.id}/{profile.name}",
                "log_url": f"/api/log/{document.id}/{profile.name}",
                "driver_log_path": str(result.driver_log_path) if result.driver_log_path else None,
                "tex_log_path": str(result.tex_log_path) if result.tex_log_path else None,
            },
        )
        return result
