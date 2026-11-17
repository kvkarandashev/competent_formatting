"""The tailnet address ``cf_view`` prints next to its local URL."""

from competent_formatting.viewer import tailscale

NODE = "fatboy.example.ts.net"
RUNNING = {
    "BackendState": "Running",
    "Self": {"DNSName": NODE + ".", "TailscaleIPs": ["100.64.0.1", "fd7a::1"]},
}


def serve_config(proxy="http://127.0.0.1:8765", listen="443", https=True, mount="/"):
    return {
        "TCP": {listen: {"HTTPS": https}},
        "Web": {f"{NODE}:{listen}": {"Handlers": {mount: {"Proxy": proxy}}}},
    }


def fake_query(status, serve):
    def query(*args):
        return status if args[0] == "status" else serve

    return query


def test_serve_url_for_a_proxied_port():
    assert tailscale.serve_urls(serve_config(), 8765) == [(f"https://{NODE}/", False)]


def test_serve_url_keeps_a_non_default_port_and_mount_path():
    config = serve_config(listen="8443", mount="/notes")
    assert tailscale.serve_urls(config, 8765) == [(f"https://{NODE}:8443/notes/", False)]


def test_serve_url_over_plain_http():
    config = serve_config(listen="80", https=False)
    assert tailscale.serve_urls(config, 8765) == [(f"http://{NODE}/", False)]


def test_serve_handlers_for_other_ports_are_ignored():
    assert tailscale.serve_urls(serve_config(), 8000) == []
    assert tailscale.serve_urls(serve_config(proxy="http://10.0.0.5:8765"), 8765) == []
    assert tailscale.serve_urls({}, 8765) == []
    assert tailscale.serve_urls(None, 8765) == []


def test_proxy_target_spellings():
    assert tailscale.proxies_to("http://localhost:8765", 8765)
    assert tailscale.proxies_to("127.0.0.1:8765", 8765)
    assert tailscale.proxies_to("8765", 8765)
    assert not tailscale.proxies_to("http://127.0.0.1:87650", 8765)
    assert not tailscale.proxies_to(None, 8765)


def test_funnel_is_flagged_as_public():
    config = serve_config()
    config["AllowFunnel"] = {f"{NODE}:443": True}
    assert tailscale.serve_urls(config, 8765) == [(f"https://{NODE}/", True)]


def test_direct_url_only_for_a_tailnet_reachable_bind():
    assert tailscale.direct_url(RUNNING, "127.0.0.1", 8765) is None
    assert tailscale.direct_url(RUNNING, "0.0.0.0", 8765) == f"http://{NODE}:8765/"
    assert tailscale.direct_url(RUNNING, "100.64.0.1", 8765) == f"http://{NODE}:8765/"
    assert tailscale.direct_url({"BackendState": "Stopped"}, "0.0.0.0", 8765) is None


def test_describe_reports_the_served_address(monkeypatch):
    monkeypatch.setattr(tailscale, "query", fake_query(RUNNING, serve_config()))
    assert tailscale.describe("127.0.0.1", 8765) == [f"tailscale: https://{NODE}/"]


def test_describe_hints_when_nothing_routes_to_the_viewer(monkeypatch):
    monkeypatch.setattr(tailscale, "query", fake_query(RUNNING, serve_config()))
    assert tailscale.describe("127.0.0.1", 8766) == [
        "tailscale: not shared -- to share it, run: tailscale serve --bg 8766"
    ]


def test_describe_is_silent_without_tailscale(monkeypatch):
    monkeypatch.setattr(tailscale, "query", fake_query(None, None))
    assert tailscale.describe("127.0.0.1", 8765) == []
    monkeypatch.setattr(tailscale, "query", fake_query({"BackendState": "Stopped"}, None))
    assert tailscale.describe("127.0.0.1", 8765) == []


def test_query_survives_a_missing_binary(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert tailscale.query("status") is None
