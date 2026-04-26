import json
from pathlib import Path
from types import SimpleNamespace

from core.config import ModelConfig, StudioNodeConfig
from services.inventory.cache import InventoryCache
from services.inventory.contract import inventory_snapshot
from services.router.route.contract import list_routes_response, route_from_entry


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "proto_json_golden"


def _load_fixture(name: str) -> object:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        backend_name="studio",
        active_model="oracle-pro",
        studio_node="oracle-pro-home",
        llamacpp_node="",
        models={
            "oracle-pro": ModelConfig(
                name="oracle-pro",
                model_id="qwen3-oracle-14b-v8-q4km",
                provider="studio",
                role="pro",
                tools_enabled=True,
                description="Oracle Pro",
            ),
        },
        studio_nodes={
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
                hostd_url="http://127.0.0.1:8766",
            ),
        },
    )


def test_golden_route_list_payload_matches_fixture() -> None:
    state = _state()
    entries = [
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "description": "Windows tunnel",
            "resolved": "oracle-pro-home",
            "aliases": ["home"],
        },
    ]
    payload = list_routes_response(state, entries)
    assert payload == _load_fixture("route_list.json")


def test_golden_inventory_snapshot_matches_fixture(monkeypatch) -> None:
    state = _state()
    cache = InventoryCache(ttl_ms=5000)
    cache.generation = 7
    state.inventory_cache = cache

    monkeypatch.setattr(
        "services.inventory.contract.timestamp_now",
        lambda: "2026-01-01T00:00:00Z",
    )

    snapshot = inventory_snapshot(
        state,
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "resolved": "oracle-pro-home",
        },
        loaded_models=[
            {
                "identifier": "oracle-pro",
                "model_key": "qwen3-oracle-14b-v8-q4km",
                "display_name": "Oracle Pro",
                "size_bytes": 14,
            }
        ],
        connected=True,
        detail="port=1234",
        ttl_ms=cache.ttl_ms,
        generation=cache.generation,
    )
    assert snapshot == _load_fixture("inventory_snapshot.json")


def test_golden_ui_event_route_selected_matches_fixture(monkeypatch) -> None:
    state = _state()
    monkeypatch.setattr(
        "services.inventory.contract.timestamp_now",
        lambda: "2026-01-01T00:00:00Z",
    )

    route = route_from_entry(
        state,
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "description": "Windows tunnel",
            "resolved": "oracle-pro-home",
            "aliases": ["home"],
        },
    )
    route["health"] = "HEALTH_STATE_UNKNOWN"

    event = {
        "kind": "UI_EVENT_KIND_ROUTE_SELECTED",
        "requestId": "req-1",
        "routeName": "oracle-pro-5090",
        "message": "Route set to oracle-pro-5090",
        "health": "HEALTH_STATE_UNKNOWN",
        "observedAt": "2026-01-01T00:00:00Z",
        "route": route,
    }
    assert event == _load_fixture("ui_event_route_selected.json")


def test_golden_ui_event_inventory_updated_matches_fixture(monkeypatch) -> None:
    state = _state()
    cache = InventoryCache(ttl_ms=5000)
    cache.generation = 7
    state.inventory_cache = cache

    monkeypatch.setattr(
        "services.inventory.contract.timestamp_now",
        lambda: "2026-01-01T00:00:00Z",
    )

    snapshot = inventory_snapshot(
        state,
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "resolved": "oracle-pro-home",
        },
        loaded_models=[
            {
                "identifier": "oracle-pro",
                "model_key": "qwen3-oracle-14b-v8-q4km",
                "display_name": "Oracle Pro",
                "size_bytes": 14,
            }
        ],
        connected=True,
        detail="port=1234",
        ttl_ms=cache.ttl_ms,
        generation=cache.generation,
    )

    event = {
        "kind": "UI_EVENT_KIND_INVENTORY_UPDATED",
        "requestId": "req-2",
        "routeName": "oracle-pro-5090",
        "message": "Inventory updated",
        "health": "HEALTH_STATE_HEALTHY",
        "observedAt": "2026-01-01T00:00:00Z",
        "inventory": snapshot,
    }
    assert event == _load_fixture("ui_event_inventory_updated.json")
