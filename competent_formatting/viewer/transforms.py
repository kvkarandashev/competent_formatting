"""Source transforms applied to a *copy* of a document's sources before compiling.

A transform is a pure ``source tree -> source tree`` step.  The only kind so
far wraps :func:`competent_formatting.processing.macro_removal.remove_macros`,
which is why revision markup must be expressed as macros
(``\\revised{text}``) rather than environments.
"""

from pathlib import Path

from ..processing.macro_removal import IncompleteSpecialMacro, remove_macros

TEX_SUFFIXES = {".tex"}


class TransformError(Exception):
    """Raised when a transform cannot be applied to a source file."""


def split_macro_transforms(transforms):
    """Split transforms into the two field lists ``remove_macros`` expects."""
    removed_fields = []
    opened_fields = []
    for transform in transforms:
        if transform.kind != "strip_macro":
            raise TransformError(f"unsupported transform kind: {transform.kind}")
        if transform.mode == "remove":
            removed_fields.append(transform.macro_name)
        else:
            opened_fields.append(transform.macro_name)
    return removed_fields, opened_fields


def transform_source_text(text, transforms):
    """Apply every transform to one LaTeX source string."""
    removed_fields, opened_fields = split_macro_transforms(transforms)
    if not removed_fields and not opened_fields:
        return text
    return remove_macros(text, removed_fields=removed_fields, opened_fields=opened_fields)


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
