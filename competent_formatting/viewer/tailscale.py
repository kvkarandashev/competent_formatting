"""Work out the tailnet URLs a ``cf_view`` server is reachable at, if any.

Purely informational: ``cf_view`` prints what this finds next to its local URL.
Nothing here changes the Tailscale configuration, and every failure (no
``tailscale`` binary, daemon stopped, unexpected JSON) yields "nothing found"
rather than an error, so the viewer starts the same with or without Tailscale.

Kept free of third-party imports, like ``defaults.py``.
"""

import json
import subprocess
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
WILDCARD_HOSTS = {"0.0.0.0", "::"}
QUERY_TIMEOUT = 3  # seconds; the CLI answers at once when the daemon is up


def query(*args):
    """Run ``tailscale <args> --json`` and return the parsed output, or ``None``."""
    try:
        completed = subprocess.run(
            ["tailscale", *args, "--json"],
            capture_output=True,
            text=True,
            timeout=QUERY_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def proxies_to(target, port):
    """Whether a serve handler's proxy target is a local server on ``port``.

    ``tailscale serve`` records the target as a full URL
    (``http://127.0.0.1:8765``), but a bare port or ``host:port`` is accepted
    too, in case an older or newer release stores what the user typed.
    """
    if not isinstance(target, str) or not target:
        return False
    if target.isdigit():
        return int(target) == port
    parts = urlsplit(target if "://" in target else f"http://{target}")
    try:
        target_port = parts.port
    except ValueError:
        return False
    return target_port == port and (parts.hostname or "") in LOOPBACK_HOSTS


def serve_urls(serve_config, port):
    """URLs under which ``tailscale serve`` (or funnel) proxies to local ``port``.

    Returns ``(url, public)`` pairs; ``public`` marks an address that funnel
    exposes to the whole internet rather than to the tailnet alone.
    """
    if not serve_config:
        return []
    tcp = serve_config.get("TCP") or {}
    funnelled = serve_config.get("AllowFunnel") or {}
    found = []
    for host_port, web in sorted((serve_config.get("Web") or {}).items()):
        name, _, listen_port = host_port.rpartition(":")
        if not name:
            continue
        https = bool((tcp.get(listen_port) or {}).get("HTTPS"))
        scheme = "https" if https else "http"
        default_port = "443" if https else "80"
        authority = name if listen_port == default_port else f"{name}:{listen_port}"
        for mount, handler in sorted(((web or {}).get("Handlers") or {}).items()):
            if not proxies_to((handler or {}).get("Proxy"), port):
                continue
            path = mount if mount.endswith("/") else mount + "/"
            found.append((f"{scheme}://{authority}{path}", bool(funnelled.get(host_port))))
    return found


def direct_url(status, host, port):
    """The tailnet URL of a server bound straight to a Tailscale address.

    Applies when ``host`` is this node's Tailscale IP or a wildcard bind; a
    loopback bind is reachable from the tailnet only through ``tailscale serve``.
    """
    if not status or status.get("BackendState") != "Running":
        return None
    node = status.get("Self") or {}
    addresses = node.get("TailscaleIPs") or []
    if host not in WILDCARD_HOSTS and host not in addresses:
        return None
    name = (node.get("DNSName") or "").rstrip(".")
    if not name:
        name = host if host in addresses else next(iter(addresses), "")
    if not name:
        return None
    if ":" in name:  # a bare IPv6 address
        name = f"[{name}]"
    return f"http://{name}:{port}/"


def describe(host, port):
    """Lines telling the user where on the tailnet the viewer can be opened.

    Empty when Tailscale is absent or not running. When it is running but
    nothing routes to the viewer, the single line is the command that would.
    """
    status = query("status", "--peers=false")
    if not status or status.get("BackendState") != "Running":
        return []
    lines = []
    for url, public in serve_urls(query("serve", "status"), port):
        note = "  (funnel: reachable from the public internet)" if public else ""
        lines.append(f"tailscale: {url}{note}")
    direct = direct_url(status, host, port)
    if direct:
        lines.append(f"tailscale: {direct}")
    if not lines and host in LOOPBACK_HOSTS:
        lines.append(f"tailscale: not shared -- to share it, run: tailscale serve --bg {port}")
    return lines
