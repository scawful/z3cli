from types import SimpleNamespace

from core.config import ModelConfig, StudioNodeConfig
from services.inventory.contract import inventory_snapshot


def test_inventory_snapshot_uses_proto_json_field_names() -> None:
    state = SimpleNamespace(
        backend_name="studio",
        models={
            "oracle-pro": ModelConfig(
                name="oracle-pro",
                model_id="qwen3-oracle-14b-v8-q4km",
                role="pro",
                tools_enabled=True,
            ),
        },
        studio_nodes={
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
                description="Windows tunnel",
            ),
        },
    )

    snapshot = inventory_snapshot(
        state,
        {
            "name": "oracle-pro-5090",
            "backend": "studio",
            "model": "oracle-pro",
            "resolved": "oracle-pro-home",
        },
        loaded_models=[{
            "identifier": "oracle-pro",
            "model_key": "qwen3-oracle-14b-v8-q4km",
            "display_name": "Oracle Pro",
            "size_bytes": 14,
        }],
        connected=True,
        detail="port=1234",
    )

    assert snapshot["source"] == "oracle-pro-5090"
    assert snapshot["health"] == "HEALTH_STATE_HEALTHY"
    assert snapshot["endpoint"]["uri"] == "http://127.0.0.1:2234/v1"
    assert snapshot["availableModels"][0]["ref"]["name"] == "oracle-pro"
    assert snapshot["loadedModels"][0]["runtimeId"] == "oracle-pro"
    assert snapshot["loadedModels"][0]["sizeBytes"] == 14
