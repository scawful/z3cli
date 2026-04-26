from types import SimpleNamespace

from core.config import ModelConfig, StudioNodeConfig
from services.router.route.contract import list_routes_response, route_from_entry


def test_route_from_entry_uses_proto_json_field_names() -> None:
    state = SimpleNamespace(
        models={
            "oracle-pro": ModelConfig(
                name="oracle-pro",
                model_id="qwen3-oracle-14b-v8-q4km",
                provider="studio",
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

    assert route["name"] == "oracle-pro-5090"
    assert route["model"] == {
        "name": "oracle-pro",
        "modelId": "qwen3-oracle-14b-v8-q4km",
        "provider": "studio",
    }
    assert route["backend"] == "SERVING_BACKEND_STUDIO"
    assert route["inferenceEndpoint"]["uri"] == "http://127.0.0.1:2234/v1"
    assert route["controlEndpoint"]["uri"] == "http://127.0.0.1:8766"
    assert route["aliases"] == ["home"]


def test_list_routes_response_resolves_active_route_from_node() -> None:
    state = SimpleNamespace(
        backend_name="studio",
        active_model="oracle-pro",
        studio_node="oracle-pro-home",
        llamacpp_node="",
        models={"oracle-pro": ModelConfig(name="oracle-pro", model_id="oracle-pro")},
        studio_nodes={
            "oracle-pro-home": StudioNodeConfig(
                name="oracle-pro-home",
                api_base="http://127.0.0.1:2234/v1",
                model="oracle-pro",
            ),
        },
    )

    response = list_routes_response(
        state,
        [
            {
                "name": "oracle-pro-5090",
                "backend": "studio",
                "model": "oracle-pro",
                "resolved": "oracle-pro-home",
            },
        ],
    )

    assert response["activeRoute"] == "oracle-pro-5090"
    assert response["routes"][0]["name"] == "oracle-pro-5090"
