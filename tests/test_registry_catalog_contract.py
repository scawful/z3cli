from core.config import load_registry
from app.runtime import resolve_targets_with_reason


def test_default_registry_points_visible_specialists_at_installed_lmstudio_paths() -> None:
    models, _routers = load_registry()

    assert models["din"].model_id == "gguf/lmstudio/din-v4.gguf"
    assert models["nayru"].model_id == "gguf/lmstudio/nayru-v9-q8_0.gguf"
    assert models["navi"].model_id == "gguf/lmstudio/farore-v5-q8_0.gguf"


def test_default_registry_uses_installed_oracle_v8_for_canonical_oracle() -> None:
    models, _routers = load_registry()

    expected = "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf"
    assert models["oracle"].model_id == expected
    assert models["oracle-pro"].model_id == expected
    assert models["oracle-pro"].visibility == "advanced"


def test_uninstalled_oracle_lanes_are_advanced_until_artifacts_exist() -> None:
    models, _routers = load_registry()

    assert models["oracle-fast"].visibility == "advanced"
    assert models["oracle-qwen35-9b"].visibility == "advanced"
    assert models["oracle-fast"].hide_if_unavailable
    assert models["oracle-qwen35-9b"].hide_if_unavailable


def test_oracle_routing_ignores_advanced_lanes_by_default() -> None:
    models, routers = load_registry()

    targets, _decisions = resolve_targets_with_reason(
        models=models,
        routers=routers,
        active_model="oracle",
        mode="oracle",
        prompt="answer fast",
        broadcast_models=[],
        backend_name="studio",
        llamacpp_model="oracle-fast",
        temperature=0.2,
        max_tokens=256,
    )

    assert [target.name for target in targets] == ["oracle"]
