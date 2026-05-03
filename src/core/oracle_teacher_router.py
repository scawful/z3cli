"""Runtime prompt guard for the Oracle 9B v5 + 14B teacher router.

The training repo's offline router keeps ``oracle-9b-candidate-v5`` as the
default and selects ``qwen3-oracle-14b-v8`` for a small set of eval-proven weak
spots.  z3cli does not run a two-model proxy yet, so this module turns that
router evidence into a compact per-turn system guard for the 9B runtime alias.
"""

from __future__ import annotations

from dataclasses import dataclass


ROUTER_NAME = "oracle-9b-v5-teacher-router"
PRIMARY_MODEL = "oracle-9b-candidate-v5"
TEACHER_MODEL = "qwen3-oracle-14b-v8"
EVIDENCE_DOC = "training/docs/ORACLE_9B_V5_TEACHER_ROUTER_20260502.md"


@dataclass(frozen=True)
class TeacherRouterFamily:
    name: str
    route: str
    keywords: tuple[str, ...]
    guard: str


@dataclass(frozen=True)
class TeacherRouterDecision:
    router: str
    route: str
    matched_family: str = ""
    matched_keywords: tuple[str, ...] = ()
    system_prompt: str = ""
    source: str = EVIDENCE_DOC
    primary_model: str = PRIMARY_MODEL
    teacher_model: str = TEACHER_MODEL

    @property
    def active(self) -> bool:
        return bool(self.system_prompt)


_FAMILIES: tuple[TeacherRouterFamily, ...] = (
    TeacherRouterFamily(
        name="songbank_blackout",
        route="primary_with_teacher_guard",
        keywords=(
            "songbank",
            "song bank",
            "loadsongbank",
            "underworld_loadsongbankifneeded",
            "apui0",
            "apuio",
            "music",
            "$0088ec",
            "$0088ef",
            "$7e0136",
        ),
        guard=(
            "Teacher-selected weak spot: `oracle_main_songbank_blackout`. "
            "For Oracle of Secrets music, APUIO, song-bank, or blackout issues, "
            "do not jump straight to entrance-table blame. First separate dark-room "
            "blanking from audio init, inspect the song-bank load path around "
            "`$0088EC/$0088EF`, `LoadSongBank`, `Underworld_LoadSongBankIfNeeded`, "
            "APUIO acknowledgement, and `$7E0136=01`/music state. Ask for or use "
            "trace/disassembly evidence before naming a root cause."
        ),
    ),
    TeacherRouterFamily(
        name="hook_stub_overwritten_logic",
        route="primary_with_teacher_guard",
        keywords=(
            "hook stub",
            "overwritten logic",
            "displaced",
            "trampoline",
            "$00a000",
            "$00a004",
            "jsl hook",
            "stub",
            "vanilla code",
        ),
        guard=(
            "Teacher-selected weak spot: `oracle_main_v2_hook_stub_overwritten_logic`. "
            "For hook stubs, preserve the overwritten vanilla instructions before "
            "`RTL`. A long hook entered by `JSL $00A000` returns to `$00A004`; the "
            "stub must perform the custom work, re-emit displaced logic in the "
            "expected width/register state, then `RTL`. Do not omit the displaced "
            "instruction contract."
        ),
    ),
    TeacherRouterFamily(
        name="jsr_rtl_contract",
        route="primary_with_teacher_guard",
        keywords=(
            "jsr",
            "jsl",
            "rtl",
            "rts",
            "return mismatch",
            "return contract",
            "stack",
            "long call",
            "short call",
        ),
        guard=(
            "Teacher-selected weak spot: `oracle_main_v2_jsr_rtl_contract_variant`. "
            "When diagnosing return mismatches, ground the answer in the actual call "
            "instruction: `JSR` pairs with `RTS`, and `JSL` pairs with `RTL`. The "
            "source file bank or destination bank does not by itself change the "
            "return type. Ask for/disassemble the call site before claiming a mismatch."
        ),
    ),
    TeacherRouterFamily(
        name="compile_hard_asar",
        route="primary_with_teacher_guard",
        keywords=(
            "asar",
            "assemble",
            "assemmbles",
            "does not assemble",
            "compile",
            "compile-hard",
            "phx",
            "plx",
            "macro",
            "syntax",
            "return only asm",
            "corrected asm",
        ),
        guard=(
            "Teacher-selected compile-hard family from `oracle_compile_hard_eval_v1`. "
            "For ASAR repair, return a minimal 65816 patch, preserve P/A/X/Y width and "
            "stack balance (`PHP`/`PLP`, `PHX`/`PLX`, `PHY`/`PLY` only when the target "
            "assembler/cpu mode supports them), avoid pseudo syntax unless it is known "
            "ASAR-valid, and do not claim the patch assembles unless a verifier/tool "
            "actually ran."
        ),
    ),
)

def route_oracle_teacher_prompt(
    prompt: str,
    *,
    router_name: str = ROUTER_NAME,
) -> TeacherRouterDecision:
    """Classify a user prompt and return the teacher-router guard, if any."""

    normalized = str(prompt or "").lower()
    for family in _FAMILIES:
        hits = tuple(keyword for keyword in family.keywords if keyword in normalized)
        if hits:
            return TeacherRouterDecision(
                router=router_name,
                route=family.route,
                matched_family=family.name,
                matched_keywords=hits,
                system_prompt=_format_guard(family),
            )
    return TeacherRouterDecision(router=router_name, route="primary")


def build_teacher_router_system_prompt(prompt: str, router_name: str = "") -> str:
    """Return a system prompt block for model configs that opt into the router."""

    if not str(router_name or "").strip():
        return ""
    decision = route_oracle_teacher_prompt(prompt, router_name=str(router_name).strip())
    if not decision.active:
        return (
            f"Oracle teacher-router `{decision.router}` is active. Default to "
            f"`{PRIMARY_MODEL}` behavior: concise, evidence-grounded, tool-first for "
            "workspace/ROM/emulator claims, and say when evidence is missing. "
            f"Router evidence source: `{EVIDENCE_DOC}`."
        )
    return decision.system_prompt


def _format_guard(family: TeacherRouterFamily) -> str:
    return "\n".join(
        [
            f"Oracle teacher-router `{ROUTER_NAME}` selected route `{family.route}`.",
            f"Primary runtime: `{PRIMARY_MODEL}`. Teacher evidence: `{TEACHER_MODEL}`.",
            f"Evidence source: `{EVIDENCE_DOC}`.",
            family.guard,
        ]
    )
