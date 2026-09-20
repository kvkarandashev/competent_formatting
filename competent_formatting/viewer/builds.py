"""Build pipeline: copy sources, transform the copy, compile, capture logs.

Sources are never mutated.  Every build lives in
``<workdir>/build/<doc_id>/<profile>/`` and is materialized by content, so files
that did not change keep their mtime and ``latexmk`` stays incremental.
"""

import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .transforms import TransformError, transform_source_text

MANIFEST_NAME = ".cf_view_sources.json"

# Artifacts of a compile the user may have run in their own source directory.
# Copying these in would confuse latexmk; figures (.pdf/.png/...) are kept.
AUX_SUFFIXES = {
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".lof",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".toc",
    ".vrb",
}
SKIP_DIR_NAMES = {".git", "__pycache__", ".ipynb_checkpoints"}


@dataclass
class BuildResult:
    doc_id: str
    profile: str
    status: str  # "ok" | "warning" | "failed"
    returncode: Optional[int] = None
    pdf_path: Optional[Path] = None
    driver_log_path: Optional[Path] = None
    tex_log_path: Optional[Path] = None
    message: str = ""
    duration_s: float = 0.0

    @property
    def ok(self):
        return self.status in ("ok", "warning")


@dataclass
class HookResult:
    scope: str
    command: str
    returncode: int
    output: str = ""
    log_path: Optional[Path] = None
    duration_s: float = 0.0

    @property
    def ok(self):
        return self.returncode == 0


def build_dir_for(workdir, doc_id, profile_name):
    return Path(workdir) / "build" / doc_id / profile_name


def driver_log_path_for(workdir, doc_id, profile_name):
    return Path(workdir) / "logs" / f"{doc_id}__{profile_name}.log"


def _should_skip(path, skip_roots):
    if path.suffix in AUX_SUFFIXES or path.name.endswith(".synctex.gz"):
        return True
    for part in path.parts:
        if part in SKIP_DIR_NAMES:
            return True
    resolved = path.resolve()
    return any(_is_within(resolved, root) for root in skip_roots)


def _is_within(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def iter_source_files(source_dir, skip_roots):
    source_dir = Path(source_dir)
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        if _should_skip(relative, []) or _should_skip(path, skip_roots):
            continue
        yield relative


def materialize_build_dir(document, profile, build_dir, skip_roots=()):
    """Copy + transform the document's sources into ``build_dir``.

    Only files whose *content* changes are rewritten, so unchanged inputs keep
    their mtime.  Files copied by a previous build that have since disappeared
    from the sources are pruned; compiler artifacts are left alone.
    """
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    source_dir = document.source_dir
    skip_roots = [Path(root).resolve() for root in skip_roots]

    written = []
    current = []
    for relative in iter_source_files(source_dir, skip_roots):
        current.append(str(relative))
        source_path = source_dir / relative
        target_path = build_dir / relative
        raw = source_path.read_bytes()
        if relative.suffix == ".tex" and profile.transforms:
            text = raw.decode("utf-8", errors="replace")
            payload = transform_source_text(text, profile.transforms).encode("utf-8")
        else:
            payload = raw
        if not target_path.exists() or target_path.read_bytes() != payload:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
            written.append(str(relative))

    _prune_stale(build_dir, current)
    (build_dir / MANIFEST_NAME).write_text(json.dumps(sorted(current), indent=1), encoding="utf-8")
    return written


def _prune_stale(build_dir, current):
    manifest_path = build_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return
    try:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for relative in set(previous) - set(current):
        stale = build_dir / relative
        if stale.is_file():
            stale.unlink()


def _newest_input_mtime(build_dir):
    """Newest mtime among the source files this build was materialized from."""
    manifest_path = Path(build_dir) / MANIFEST_NAME
    if not manifest_path.is_file():
        return None
    try:
        relatives = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    mtimes = []
    for relative in relatives:
        candidate = Path(build_dir) / relative
        if candidate.is_file():
            mtimes.append(candidate.stat().st_mtime)
    return max(mtimes) if mtimes else None


def compile_build(document, profile, workdir, latex_cmd, on_line=None):
    """Materialize and compile one ``(document, profile)`` pair."""
    started = time.monotonic()
    build_dir = build_dir_for(workdir, document.id, profile.name)
    driver_log_path = driver_log_path_for(workdir, document.id, profile.name)
    driver_log_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path = build_dir / f"{document.main_stem}.pdf"
    tex_log_path = build_dir / f"{document.main_stem}.log"

    def emit(line):
        if on_line is not None:
            on_line(line)

    try:
        materialize_build_dir(document, profile, build_dir, skip_roots=[workdir])
    except TransformError as error:
        message = f"transform failed: {error}"
        emit(message)
        driver_log_path.write_text(message + "\n", encoding="utf-8")
        return BuildResult(
            doc_id=document.id,
            profile=profile.name,
            status="failed",
            driver_log_path=driver_log_path,
            message=message,
            duration_s=time.monotonic() - started,
        )

    main_in_build = build_dir / Path(document.main_tex).name
    command = latex_cmd.format(main=shlex.quote(main_in_build.name))

    lines = []
    emit(f"$ {command}")
    lines.append(f"$ {command}")
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=str(build_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    for raw_line in process.stdout:
        line = raw_line.rstrip("\n")
        lines.append(line)
        emit(line)
    returncode = process.wait()

    pdf_mtime_after = pdf_path.stat().st_mtime if pdf_path.is_file() else None

    # The exit code alone cannot tell "fine" from "broken": latexmk re-reports a
    # cached BibTeX error on every no-op rerun, so a perfectly good build would
    # otherwise flag as failed forever.  What matters is whether the PDF on disk
    # is at least as new as the inputs it was made from.
    driver_name = Path(latex_cmd.split()[0]).name
    newest_input = _newest_input_mtime(build_dir)
    pdf_up_to_date = pdf_mtime_after is not None and (
        newest_input is None or pdf_mtime_after >= newest_input
    )

    if pdf_mtime_after is None:
        status = "failed"
        message = f"{driver_name} exited {returncode} and produced no PDF."
    elif not pdf_up_to_date:
        status = "failed"
        message = (
            f"{driver_name} exited {returncode} and left the PDF older than the sources; "
            "the previous one is still being shown."
        )
    elif returncode == 0:
        status, message = "ok", ""
    else:
        status = "warning"
        message = (
            f"{driver_name} exited {returncode} but the PDF is up to date; "
            "check the log for unresolved references or BibTeX errors."
        )

    if message:
        lines.append("")
        lines.append(f"[cf_view] {message}")
        emit(f"[cf_view] {message}")
    driver_log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return BuildResult(
        doc_id=document.id,
        profile=profile.name,
        status=status,
        returncode=returncode,
        pdf_path=pdf_path if pdf_path.is_file() else None,
        driver_log_path=driver_log_path,
        tex_log_path=tex_log_path if tex_log_path.is_file() else None,
        message=message,
        duration_s=time.monotonic() - started,
    )


def run_hook(hook, scope, workdir, on_line=None):
    """Run one pre-compile hook, capturing combined output."""
    started = time.monotonic()
    cwd = hook.cwd or str(workdir)
    lines = [f"$ {hook.command}"]
    if on_line is not None:
        on_line(lines[0])
    process = subprocess.Popen(
        hook.command,
        shell=True,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    for raw_line in process.stdout:
        line = raw_line.rstrip("\n")
        lines.append(line)
        if on_line is not None:
            on_line(line)
    returncode = process.wait()
    return HookResult(
        scope=scope,
        command=hook.command,
        returncode=returncode,
        output="\n".join(lines),
        duration_s=time.monotonic() - started,
    )
