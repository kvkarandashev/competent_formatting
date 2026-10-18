"""Persisted session configuration for the ``cf_view`` web viewer.

The config file is the single source of truth for a session: the CLI seeds it,
the browser menu mutates it, the server reads it as state.  Nothing that
survives a restart lives only in process memory.
"""

import os
import re
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import tomli_w
import tomllib
from pydantic import BaseModel, Field

from .defaults import (  # noqa: F401  (re-exported for callers of this module)
    CLEAN_PROFILE,
    CONFIG_FILENAME,
    DEFAULT_LATEX_CMD,
    FULL_PROFILE,
    LOCK_FILENAME,
    WORKDIR_DIRNAME,
)


class MacroTransform(BaseModel):
    """Strip a revision macro from a copy of the sources.

    ``unwrap`` keeps the marked-up content and drops only the macro itself
    (``\\revised{text}`` -> ``text``); ``remove`` drops content and all
    (``\\collaboratorcomment{note}`` -> ``""``).
    """

    kind: Literal["strip_macro"] = "strip_macro"
    macro_name: str
    mode: Literal["unwrap", "remove"] = "unwrap"


class EnvironmentTransform(BaseModel):
    """Strip a revision *environment* from a copy of the sources.

    The environment form of the same idea as :class:`MacroTransform`: ``unwrap`` keeps the
    body (``\\begin{revblock}text\\end{revblock}`` -> ``text``), ``remove`` drops it with the
    body. Separate from the macro transform because a name can be both -- a ``\\rev`` macro
    and a ``revblock`` environment are different things to strip.
    """

    kind: Literal["strip_environment"] = "strip_environment"
    environment_name: str
    mode: Literal["unwrap", "remove"] = "unwrap"


# Discriminated by ``kind``, so a config written before environments existed still loads:
# every transform in it carries kind = "strip_macro".
Transform = Annotated[Union[MacroTransform, EnvironmentTransform], Field(discriminator="kind")]


class Profile(BaseModel):
    name: str
    transforms: list[Transform] = Field(default_factory=list)


class Hook(BaseModel):
    command: str
    cwd: Optional[str] = None  # default: the workdir


class Document(BaseModel):
    id: str  # stable, slug-like; assigned once, never reused
    label: str  # display name; editable
    main_tex: str  # absolute path
    profiles: list[Profile] = Field(default_factory=list)
    hooks: list[Hook] = Field(default_factory=list)

    def profile(self, name):
        for profile in self.profiles:
            if profile.name == name:
                return profile
        return None

    @property
    def profile_names(self):
        return [profile.name for profile in self.profiles]

    @property
    def source_dir(self):
        return Path(self.main_tex).parent

    @property
    def main_stem(self):
        return Path(self.main_tex).stem


class SessionConfig(BaseModel):
    version: int = 1
    host: str = "127.0.0.1"
    port: int = 8000
    latex_cmd: str = DEFAULT_LATEX_CMD
    compile_all_profiles: bool = True
    # Build anything whose PDF is missing as soon as the server starts, so a
    # fresh checkout shows compiled documents instead of "not built yet".
    build_missing_on_start: bool = True
    global_hooks: list[Hook] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)

    def document(self, doc_id):
        for document in self.documents:
            if document.id == doc_id:
                return document
        return None

    def document_by_label(self, label):
        for document in self.documents:
            if document.label == label:
                return document
        return None


def slugify(label):
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_").lower()
    return slug or "doc"


def assign_document_id(label, taken):
    """Return a slug-like id for ``label`` that is not in ``taken``."""
    base = slugify(label)
    if base not in taken:
        return base
    index = 2
    while f"{base}_{index}" in taken:
        index += 1
    return f"{base}_{index}"


def config_path(workdir):
    return Path(workdir) / CONFIG_FILENAME


def find_workdir(start=None):
    """Find the nearest ``.cf_view`` session directory, walking up from ``start``.

    Mirrors how git locates ``.git``, so ``cf_view`` can be run bare from a
    manuscript directory or any subdirectory of it.  Returns ``None`` when no
    session directory is in scope.
    """
    current = Path(start or Path.cwd()).expanduser().resolve()
    for candidate in [current, *current.parents]:
        workdir = candidate / WORKDIR_DIRNAME
        if config_path(workdir).is_file():
            return workdir
    return None


def default_workdir(start=None):
    """Where a session lives: the discovered one, else ``<cwd>/.cf_view``."""
    found = find_workdir(start)
    if found is not None:
        return found
    return Path(start or Path.cwd()).expanduser().resolve() / WORKDIR_DIRNAME


def to_storage_path(main_tex, workdir):
    """Serialize a document path, relative to the workdir where that is sane.

    A session directory normally sits inside the project it describes, so
    documents end up stored as ``../main.tex``; the config then survives the
    project being cloned to a different path. Anything outside the project root
    is stored absolute.
    """
    path = Path(main_tex)
    project_root = Path(workdir).resolve().parent
    try:
        path.resolve().relative_to(project_root)
    except ValueError:
        return str(path)
    return os.path.relpath(path.resolve(), Path(workdir).resolve())


def from_storage_path(stored, workdir):
    """Resolve a stored document path back to an absolute one."""
    path = Path(stored).expanduser()
    if path.is_absolute():
        return str(path)
    return str((Path(workdir) / path).resolve())


def load_config(workdir):
    """Read the persisted config, or return ``None`` if there is none yet."""
    path = config_path(workdir)
    if not path.is_file():
        return None
    with open(path, "rb") as f:
        payload = tomllib.load(f)
    for document in payload.get("documents", []):
        if "main_tex" in document:
            document["main_tex"] = from_storage_path(document["main_tex"], workdir)
    return SessionConfig.model_validate(payload)


WORKDIR_GITIGNORE = """\
# Everything here except the config is regenerable; only competent_viewer.toml
# is worth committing, so a session can travel with the project it describes.
build/
logs/
.competent_viewer.lock
"""


def ensure_workdir_gitignore(workdir):
    """Give a session directory a .gitignore so builds and logs stay untracked.

    Written once, never overwritten: a session directory is normally committed
    alongside the manuscript, and its build/ and logs/ subtrees are not.
    """
    path = Path(workdir) / ".gitignore"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(WORKDIR_GITIGNORE, encoding="utf-8")
    return path


def save_config(workdir, config):
    """Write the config atomically (temp file + rename)."""
    path = config_path(workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_workdir_gitignore(workdir)
    payload = config.model_dump(mode="json", exclude_none=True)
    for document in payload.get("documents", []):
        document["main_tex"] = to_storage_path(document["main_tex"], workdir)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        tomli_w.dump(payload, f)
    tmp_path.replace(path)
    return path
