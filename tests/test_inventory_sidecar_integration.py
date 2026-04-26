import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.inventory_client import InventoryClient
from app.serve import _schedule_inventory_refresh
from core.config import ModelConfig, StudioNodeConfig


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        backend_name="studio",
        active_model="oracle-pro",
        studio_node="oracle-pro-home",
        llamacpp_node="",
        studio_api_base="http://127.0.0.1:2234/v1",
        llamacpp_api_base="",
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
                hostd_url="",
            ),
        },
        llamacpp_nodes={},
        inventory_ttl_ms=5000,
    )


class InventorySidecarIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_inventory_refresh_emits_refreshing_then_updated(self) -> None:
        state = _state()
        events: list[tuple[str, object]] = []

        async def slow_snapshot_for_entry(self, entry, *, force_refresh=False):  # type: ignore[no-untyped-def]
            del self, entry, force_refresh
            await asyncio.sleep(0.02)
            return {"health": "HEALTH_STATE_HEALTHY", "observedAt": "2026-01-01T00:00:00Z"}

        def notify(method: str, params=None):  # type: ignore[no-untyped-def]
            events.append((method, params))

        with (
            patch("app.serve._notify", side_effect=notify),
            patch.object(InventoryClient, "snapshot_for_entry", slow_snapshot_for_entry),
        ):
            _schedule_inventory_refresh(state, request_id="req-1", route_name="oracle-pro-5090")
            await asyncio.sleep(0.06)

        ui_events = [params for method, params in events if method == "ui/event" and isinstance(params, dict)]
        kinds = [str(ev.get("kind") or "") for ev in ui_events]
        self.assertIn("UI_EVENT_KIND_INVENTORY_REFRESHING", kinds)
        self.assertIn("UI_EVENT_KIND_INVENTORY_UPDATED", kinds)
        self.assertLess(kinds.index("UI_EVENT_KIND_INVENTORY_REFRESHING"), kinds.index("UI_EVENT_KIND_INVENTORY_UPDATED"))

    async def test_inventoryclient_sidecar_snapshot_falls_back_to_inprocess(self) -> None:
        state = _state()
        state.inventory_transport = "sidecar"

        class FailingSidecar:
            async def request(self, method, params=None):  # type: ignore[no-untyped-def]
                del method, params
                raise RuntimeError("boom")

        client = InventoryClient(state)
        with patch.object(InventoryClient, "_sidecar", return_value=FailingSidecar()):
            snapshot = await client.snapshot_for_entry(
                {
                    "name": "oracle-pro-5090",
                    "backend": "studio",
                    "model": "oracle-pro",
                    "resolved": "oracle-pro-home",
                },
                force_refresh=False,
            )

        self.assertIsInstance(snapshot, dict)
        self.assertEqual(snapshot.get("source"), "oracle-pro-5090")
        self.assertIn("detail", snapshot)

    async def test_inventoryclient_sidecar_query_plumbs_route_names(self) -> None:
        state = _state()
        state.inventory_transport = "sidecar"

        calls: list[tuple[str, dict[str, object]]] = []

        class RecordingSidecar:
            async def request(self, method, params=None):  # type: ignore[no-untyped-def]
                calls.append((method, dict(params or {})))
                return {"snapshots": [{"source": "oracle-pro-5090"}]}

        client = InventoryClient(state)
        with patch.object(InventoryClient, "_sidecar", return_value=RecordingSidecar()):
            snapshots = await client.snapshots_for_entries(
                [{"name": "oracle-pro-5090", "backend": "studio", "model": "oracle-pro", "resolved": "oracle-pro-home"}],
                force_refresh=False,
            )

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].get("source"), "oracle-pro-5090")
        self.assertTrue(calls)
        method, params = calls[0]
        self.assertEqual(method, "inventory/query")
        self.assertEqual(params.get("routeNames"), ["oracle-pro-5090"])
