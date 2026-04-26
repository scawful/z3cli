import unittest
from types import SimpleNamespace

from services.inventory.daemon.session_sync import apply_session_sync


class InventoryDaemonSessionSyncTests(unittest.TestCase):
    def test_apply_session_sync_updates_routing_fields(self) -> None:
        state = SimpleNamespace(
            backend_name="studio",
            active_model="",
            studio_node="",
            llamacpp_node="",
        )
        apply_session_sync(
            state,
            {
                "active": {
                    "backend": "llamacpp",
                    "model": "oracle-fast",
                    "studio_node": "",
                    "llamacpp_node": "edge-node",
                },
            },
        )
        self.assertEqual(state.backend_name, "llamacpp")
        self.assertEqual(state.active_model, "oracle-fast")
        self.assertEqual(state.studio_node, "")
        self.assertEqual(state.llamacpp_node, "edge-node")

    def test_apply_session_sync_partial_does_not_clear_unmentioned_fields(self) -> None:
        state = SimpleNamespace(
            backend_name="studio",
            active_model="oracle-pro",
            studio_node="oracle-pro-home",
            llamacpp_node="",
        )
        apply_session_sync(state, {"active": {"model": "nayru"}})
        self.assertEqual(state.backend_name, "studio")
        self.assertEqual(state.active_model, "nayru")
        self.assertEqual(state.studio_node, "oracle-pro-home")


if __name__ == "__main__":
    unittest.main()
