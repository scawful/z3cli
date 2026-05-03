from core.config import get_registry_aliases, load_registry
from core.oracle_teacher_router import (
    PRIMARY_MODEL,
    ROUTER_NAME,
    TEACHER_MODEL,
    build_teacher_router_system_prompt,
    route_oracle_teacher_prompt,
)


def test_teacher_router_routes_songbank_blackout_to_guard() -> None:
    decision = route_oracle_teacher_prompt(
        "The underworld song bank load blacks out after APUIO ack near $0088EC."
    )

    assert decision.active
    assert decision.route == "primary_with_teacher_guard"
    assert decision.matched_family == "songbank_blackout"
    assert "song-bank" in decision.system_prompt
    assert "$0088EC/$0088EF" in decision.system_prompt
    assert PRIMARY_MODEL in decision.system_prompt
    assert TEACHER_MODEL in decision.system_prompt


def test_teacher_router_routes_jsr_rtl_contract_to_callsite_guard() -> None:
    decision = route_oracle_teacher_prompt(
        "Could this JSR into another bank need RTL instead of RTS?"
    )

    assert decision.active
    assert decision.matched_family == "jsr_rtl_contract"
    assert "JSR` pairs with `RTS" in decision.system_prompt
    assert "JSL` pairs with `RTL" in decision.system_prompt


def test_teacher_router_default_prompt_keeps_9b_primary() -> None:
    prompt = build_teacher_router_system_prompt("Explain the dungeon palette flow.", ROUTER_NAME)

    assert "Default to `oracle-9b-candidate-v5` behavior" in prompt
    assert "Router evidence source" in prompt


def test_default_registry_registers_oracle_9b_router_aliases() -> None:
    models, _routers = load_registry()

    model = models["oracle-9b-router"]
    assert model.model_id == "gguf/zelda/oracle-9b-candidate-v5-q4km.gguf"
    assert model.teacher_router == ROUTER_NAME
    assert model.tool_profile == "oracle"
    assert model.lmstudio_parallel == 1
    assert model.lmstudio_gpu == "max"
    assert model.reasoning_mode == "off"
    assert model.disable_reasoning_prefill
    assert model.thinking_tier == ""
    assert not model.native_tools
    assert model.hide_if_unavailable

    aliases = get_registry_aliases()
    assert aliases["oracle-v5-router"] == "oracle-9b-router"
    assert aliases["oracle-qwen35-9b-router"] == "oracle-9b-router"
