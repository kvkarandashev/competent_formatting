"""Skip the viewer tests when the optional ``view`` dependencies are absent.

These tests import `competent_formatting.viewer`, which needs pydantic and
tomli-w.  Without this guard a core-only install (`pip install .`) would fail
`make test` at collection time rather than simply not running these.
"""

try:
    import pydantic  # noqa: F401
    import tomli_w  # noqa: F401
except ImportError:  # pragma: no cover - depends on how the package was installed
    collect_ignore_glob = ["test_viewer_*.py"]
