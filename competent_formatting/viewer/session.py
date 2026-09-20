"""Seeding a session config from CLI flags, and reconciling it on restart.

The CLI only ever *seeds* the config.  On a restart against an existing workdir
an explicitly-passed flag that contradicts what was persisted is a loud error,
never a silent overwrite -- see spec 5.3.
"""

from pathlib import Path

from .config import (
    CLEAN_PROFILE,
    FULL_PROFILE,
    Document,
    Hook,
    MacroTransform,
    Profile,
    SessionConfig,
    assign_document_id,
)


class ReconciliationError(Exception):
    """Raised when explicit CLI flags contradict the persisted config."""

    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__(self.render())

    def render(self):
        lines = ["CLI flags contradict the config already in this workdir:", ""]
        for flag, cli_value, stored_value in self.conflicts:
            lines.append(f"  {flag}: CLI={cli_value!r} vs workdir={stored_value!r}")
        lines += [
            "",
            "Resolve by doing one of:",
            "  * re-run without the conflicting flag (the stored value is kept),",
            "  * pass --overwrite_config to make the CLI values win,",
            "  * edit competent_viewer.toml in the workdir by hand,",
            "  * or choose a fresh --workdir.",
        ]
        return "\n".join(lines)


def parse_labelled(value, what):
    """Parse ``LABEL=VALUE``; an unlabelled document path gets its stem as label."""
    if "=" in value:
        label, _, rest = value.partition("=")
        label, rest = label.strip(), rest.strip()
        if not label or not rest:
            raise ValueError(f"malformed {what}: {value!r}")
        return label, rest
    if what == "--doc":
        return Path(value).stem, value
    raise ValueError(f"{what} needs the form LABEL=VALUE, got {value!r}")


def resolve_tex(path):
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"no such file: {resolved}")
    return str(resolved)


def clean_transforms(opened_macros, removed_macros):
    """Build the transform list for the aggregate ``clean`` profile."""
    transforms = [MacroTransform(macro_name=name, mode="unwrap") for name in opened_macros]
    transforms += [MacroTransform(macro_name=name, mode="remove") for name in removed_macros]
    return transforms


def make_profiles(transforms):
    profiles = [Profile(name=FULL_PROFILE)]
    if transforms:
        profiles.append(
            Profile(name=CLEAN_PROFILE, transforms=[t.model_copy() for t in transforms])
        )
    return profiles


def seed_config(spec):
    """Create a brand-new config from CLI values."""
    transforms = clean_transforms(spec["opened_macros"], spec["removed_macros"])
    config = SessionConfig(
        host=spec["host"],
        port=spec["port"],
        latex_cmd=spec["latex_cmd"],
        global_hooks=[Hook(command=command) for command in spec["pre_scripts"]],
    )
    taken = set()
    for label, path in spec["docs"]:
        doc_id = assign_document_id(label, taken)
        taken.add(doc_id)
        config.documents.append(
            Document(
                id=doc_id,
                label=label,
                main_tex=resolve_tex(path),
                profiles=make_profiles(transforms),
                hooks=[
                    Hook(command=command)
                    for hook_label, command in spec["doc_pre_scripts"]
                    if hook_label == label
                ],
            )
        )
    _check_dangling_doc_hooks(spec, config)
    return config


def _check_dangling_doc_hooks(spec, config):
    labels = {document.label for document in config.documents}
    for hook_label, _ in spec["doc_pre_scripts"]:
        if hook_label not in labels:
            raise ValueError(
                f"--doc_pre_script refers to unknown document label {hook_label!r}; "
                f"known labels: {sorted(labels) or 'none'}"
            )


def reconcile(config, spec, explicit, overwrite=False):
    """Merge explicitly-passed CLI values into an existing config.

    Returns the list of human-readable changes applied.  Raises
    :class:`ReconciliationError` when a contradiction is found and ``overwrite``
    is false.
    """
    conflicts = []
    changes = []

    for flag, key in (("--host", "host"), ("--port", "port"), ("--latex_cmd", "latex_cmd")):
        if key not in explicit:
            continue
        cli_value = spec[key]
        stored_value = getattr(config, key)
        if cli_value == stored_value:
            continue
        if overwrite:
            setattr(config, key, cli_value)
            changes.append(f"{key}: {stored_value!r} -> {cli_value!r}")
        else:
            conflicts.append((flag, cli_value, stored_value))

    _reconcile_macros(config, spec, explicit, overwrite, conflicts, changes)
    _reconcile_docs(config, spec, explicit, overwrite, conflicts, changes)
    _reconcile_hooks(config, spec, explicit, changes)

    if conflicts and not overwrite:
        raise ReconciliationError(conflicts)
    return changes


def _stored_transforms(config):
    for document in config.documents:
        profile = document.profile(CLEAN_PROFILE)
        if profile is not None:
            return {t.macro_name: t.mode for t in profile.transforms}
    return {}


def _reconcile_macros(config, spec, explicit, overwrite, conflicts, changes):
    if not ({"opened_macros", "removed_macros"} & set(explicit)):
        return
    wanted = {
        t.macro_name: t.mode
        for t in clean_transforms(spec["opened_macros"], spec["removed_macros"])
    }
    stored = _stored_transforms(config)

    for name, mode in wanted.items():
        if name in stored and stored[name] != mode:
            flag = "--opened_macro" if mode == "unwrap" else "--removed_macro"
            if overwrite:
                changes.append(f"macro {name}: {stored[name]} -> {mode}")
            else:
                conflicts.append((f"{flag} {name}", mode, stored[name]))
    if conflicts and not overwrite:
        return

    merged = dict(stored)
    merged.update(wanted)
    if merged == stored:
        return
    transforms = [MacroTransform(macro_name=n, mode=m) for n, m in merged.items()]
    for document in config.documents:
        profile = document.profile(CLEAN_PROFILE)
        if profile is None:
            document.profiles.append(
                Profile(name=CLEAN_PROFILE, transforms=[t.model_copy() for t in transforms])
            )
        else:
            profile.transforms = [t.model_copy() for t in transforms]
    added = sorted(set(merged) - set(stored))
    if added:
        changes.append(f"clean profile: added macros {', '.join(added)}")


def _reconcile_docs(config, spec, explicit, overwrite, conflicts, changes):
    if "docs" not in explicit:
        return
    for label, path in spec["docs"]:
        resolved = resolve_tex(path)
        existing = config.document_by_label(label)
        if existing is None:
            taken = {document.id for document in config.documents}
            transforms = [
                MacroTransform(macro_name=n, mode=m) for n, m in _stored_transforms(config).items()
            ]
            config.documents.append(
                Document(
                    id=assign_document_id(label, taken),
                    label=label,
                    main_tex=resolved,
                    profiles=make_profiles(transforms),
                )
            )
            changes.append(f"added document {label!r} -> {resolved}")
        elif existing.main_tex != resolved:
            if overwrite:
                changes.append(f"document {label!r}: {existing.main_tex} -> {resolved}")
                existing.main_tex = resolved
            else:
                conflicts.append((f"--doc {label}", resolved, existing.main_tex))


def _reconcile_hooks(config, spec, explicit, changes):
    """Hooks are purely additive: a new command is added, a known one is a no-op."""
    if "pre_scripts" in explicit:
        known = {hook.command for hook in config.global_hooks}
        for command in spec["pre_scripts"]:
            if command not in known:
                config.global_hooks.append(Hook(command=command))
                changes.append(f"added global hook: {command}")
    if "doc_pre_scripts" in explicit:
        for label, command in spec["doc_pre_scripts"]:
            document = config.document_by_label(label)
            if document is None:
                raise ValueError(f"--doc_pre_script refers to unknown document label {label!r}")
            if command not in {hook.command for hook in document.hooks}:
                document.hooks.append(Hook(command=command))
                changes.append(f"added hook for {label!r}: {command}")
