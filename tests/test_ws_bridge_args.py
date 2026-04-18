"""Bridge CLI argument parsing (no network)."""

from z3cli.app.ws_bridge import parse_bridge_args


def test_parse_bridge_defaults() -> None:
    ns, serve = parse_bridge_args([])
    assert ns.bridge_host == "127.0.0.1"
    assert ns.bridge_port == 8765
    assert serve == []


def test_parse_bridge_known_flags_and_serve_tail() -> None:
    ns, serve = parse_bridge_args(
        [
            "--bridge-host",
            "0.0.0.0",
            "--bridge-port",
            "9999",
            "--bridge-token",
            "abc",
            "--workspace",
            "/tmp/ws",
        ],
    )
    assert ns.bridge_host == "0.0.0.0"
    assert ns.bridge_port == 9999
    assert ns.bridge_token == "abc"
    assert serve == ["--workspace", "/tmp/ws"]


def test_parse_bridge_token_from_env(monkeypatch) -> None:
    monkeypatch.setenv("Z3CLI_BRIDGE_TOKEN", "fromenv")
    ns, _serve = parse_bridge_args(["--bridge-host", "127.0.0.1"])
    assert ns.bridge_token == "fromenv"
