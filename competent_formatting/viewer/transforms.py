"""Source transforms applied to a *copy* of a document's sources before compiling.

A transform is a pure ``source tree -> source tree`` step.  Both kinds wrap
:func:`competent_formatting.processing.macro_removal.remove_macros`: revision
markup written as a macro (``\\revised{text}``) and the same idea written as an
environment (``\\begin{revblock} ... \\end{revblock}``).
"""

from pathlib import Path

from ..processing.macro_removal import IncompleteSpecialMacro, remove_macros

TEX_SUFFIXES = {".tex"}


class TransformError(Exception):
    """Raised when a transform cannot be applied to a source file."""


def split_transforms(transforms):
    """Split transforms into the four name lists ``remove_macros`` expects."""
    fields = {"removed_fields": [], "opened_fields": [], "removed_envs": [], "opened_envs": []}
    for transform in transforms:
        removed = transform.mode == "remove"
        if transform.kind == "strip_macro":
            key = "removed_fields" if removed else "opened_fields"
            fields[key].append(transform.macro_name)
        elif transform.kind == "strip_environment":
            key = "removed_envs" if removed else "opened_envs"
            fields[key].append(transform.environment_name)
        else:
            raise TransformError(f"unsupported transform kind: {transform.kind}")
    return fields


def split_macro_transforms(transforms):
    """``(removed_fields, opened_fields)`` -- the macro half, kept for older callers."""
    fields = split_transforms(transforms)
    return fields["removed_fields"], fields["opened_fields"]


def transform_source_text(text, transforms):
    """Apply every transform to one LaTeX source string."""
    fields = split_transforms(transforms)
    if not any(fields.values()):
        return text
    return remove_macros(text, **fields)


def iter_tex_files(root):
    for path in sorted(Path(root).rglob("*")):
        if path.is_file() and path.suffix in TEX_SUFFIXES:
            yield path


def apply_transforms(build_dir, transforms):
    """Rewrite every ``.tex`` file under ``build_dir`` in place.

    Returns the list of files that were actually changed, so the caller can log
    what a profile did.  Never touches anything outside ``build_dir`` -- the
    tree has already been copied by the caller.
    """
    if not transforms:
        return []
    changed = []
    for path in iter_tex_files(build_dir):
        original = path.read_text(encoding="utf-8", errors="replace")
        try:
            rewritten = transform_source_text(original, transforms)
        except IncompleteSpecialMacro as error:
            raise TransformError(f"{path}: unbalanced revision macro: {error}") from error
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed.append(path)
    return changed
