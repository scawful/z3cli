import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.config import ModelConfig, StudioNodeConfig
from services.inventory.cache import InventoryCache
from services.inventory.runtime import InventoryRuntime, refresh_inventory_snapshot


def test_refresh_inventory_snapshot_probes_configured_route(monkeypatch) -> None:
    asyncio.run(_test_refresh_inventory_snapshot_probes_configured_route(monkeypatch))


async def _test_refresh_inventory_snapshot_probes_configured_route(monkeypatch) -> None:
    state = SimpleNamespace(
        backend_name="studio",
        models={"oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro")},
        studio_nodes={
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        },
    )
    entry = {
        "name": "oracle-pro-5090",
        "backend": "studio",
        "model": "oracle-pro",
        "resolved": "oracle-pro-home",
    }
    cache = InventoryCache(ttl_ms=5000)

    backend = SimpleNamespace(
        check_connection=AsyncMock(return_value=SimpleNamespace(connected=True, detail="ok")),
        list_loaded_model_details=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("services.inventory.runtime.backend_for_route_entry", lambda *_: backend)

    snapshot = await refresh_inventory_snapshot(state, entry, cache=cache)
    assert snapshot["source"] == "oracle-pro-5090"
    assert snapshot["health"] == "HEALTH_STATE_HEALTHY"


def test_inventory_runtime_refresh_all_caches_snapshots(monkeypatch) -> None:
    asyncio.run(_test_inventory_runtime_refresh_all_caches_snapshots(monkeypatch))


async def _test_inventory_runtime_refresh_all_caches_snapshots(monkeypatch) -> None:
    state = SimpleNamespace(
        backend_name="studio",
        models={"oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro", role="pro")},
        studio_nodes={
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        },
    )
    entries = [
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "resolved": "oracle-pro-home",
        }
    ]
    runtime = InventoryRuntime.from_ttl_ms(ttl_ms=5000, poll_interval_ms=5000)

    backend = SimpleNamespace(
        check_connection=AsyncMock(return_value=SimpleNamespace(connected=True, detail="ok")),
        list_loaded_model_details=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr("services.inventory.runtime.backend_for_route_entry", lambda *_: backend)

    snapshots = await runtime.refresh_all(state, entries, force_refresh=True)
    assert snapshots[0]["source"] == "oracle-pro-5090"
    assert runtime.cache.get("oracle-pro-5090") is not None
