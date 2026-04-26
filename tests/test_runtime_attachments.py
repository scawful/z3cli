import tempfile
import unittest
from pathlib import Path

from app.runtime import (
    add_attachment_context_packs,
    add_construct_context_packs,
    build_oracle_prefetch_forced_reply,
    build_oracle_prefetch_session_records,
    build_oracle_answer_after_grounding_prompt,
    build_unavailable_tool_forced_reply,
    build_focus_context_content,
    collect_oracle_context_packs,
    enrich_prompt_with_construct_refs,
    enrich_prompt_with_attachments,
    enrich_prompt_with_oracle_context,
    extract_lsp_symbol_queries,
    plan_oracle_context_prefetch,
    resolve_lsp_context_settings,
    resolve_message_attachments,
    resolve_message_construct_refs,
)
from protocol.z3lsp_bridge import OpenDocument, Z3LspBridge


class FakeZ3LspBridge(Z3LspBridge):
    def __init__(self, summary_prefix: str = "z3lsp summary") -> None:
        self.summary_prefix = summary_prefix
        self.calls: list[dict[str, object]] = []

    async def build_context_pack(  # type: ignore[override]
        self,
        file_path: str,
        *,
        query: str = "",
        symbol_queries: list[str] | None = None,
        max_chars: int = 1600,
        diagnostic_limit: int | None = None,
        symbol_limit: int | None = None,
        symbol_detail_limit: int = 0,
        reference_limit: int = 0,
        include_clean_diagnostics: bool = True,
        include_diagnostic_snippets: bool = False,
        include_symbol_hover: bool = False,
    ) -> str:
        self.calls.append({
            "file_path": file_path,
            "query": query,
            "symbol_queries": list(symbol_queries or []),
            "diagnostic_limit": diagnostic_limit,
            "symbol_limit": symbol_limit,
            "symbol_detail_limit": symbol_detail_limit,
            "reference_limit": reference_limit,
            "include_clean_diagnostics": include_clean_diagnostics,
            "include_diagnostic_snippets": include_diagnostic_snippets,
            "include_symbol_hover": include_symbol_hover,
        })
        pack = f"{self.summary_prefix} for {Path(file_path).name}"
        return pack[:max_chars]


class WorkspaceFallbackZ3LspBridge(Z3LspBridge):
    def __init__(self, workspace: Path, workspace_symbols: list[dict[str, object]]) -> None:
        self.workspace = workspace
        self.proc = object()
        self._docs = {}
        self._workspace_symbols = workspace_symbols

    async def _ensure_document(self, file_path: str):  # type: ignore[override]
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.workspace / path).resolve()
        text = path.read_text(encoding="utf-8", errors="replace")
        document = OpenDocument(uri=path.as_uri(), text=text, diagnostics=[])
        self._docs[path] = document
        return path, document

    async def _request(self, method: str, params: dict[str, object], timeout: float | None = None):  # type: ignore[override]
        del timeout
        if method == "textDocument/documentSymbol":
            return []
        if method == "workspace/symbol":
            query = str(params.get("query", "") or "").lower()
            return [
                item for item in self._workspace_symbols
                if query in str(item.get("name", "") or "").lower()
            ]
        if method == "textDocument/hover":
            return {"contents": {"value": "workspace symbol hover"}}
        return []


class FakeRomBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_openai_tools(self) -> list[dict]:
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "dungeon_describe_room":
            return "Room 0x45: Glacia Estate (Jail Cells)"
        if name == "dungeon_list_objects":
            return "Object 0x10 at (4,4)"
        if name == "dungeon_list_sprites":
            return "Sprite 0x07 Village Elder"
        if name == "dungeon_list_chests":
            return "Chest 0x01"
        if name == "message_read":
            return "Message 0x143: The ice has memories."
        return ""

    def get_tool_server(self, tool_name: str) -> str:
        return "rom"

    @property
    def tool_count(self) -> int:
        return 0

    @property
    def server_names(self) -> list[str]:
        return ["rom"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"rom": 0}

    async def close(self) -> None:
        return None


class FakeOracleBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_openai_tools(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": "label_lookup"}},
            {"type": "function", "function": {"name": "register_doc"}},
            {"type": "function", "function": {"name": "disasm_at"}},
            {"type": "function", "function": {"name": "grep_disasm"}},
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "register_doc":
            return "### MDMAEN ($420B)\nDMA enable register"
        if name == "label_lookup":
            return "Underworld_LoadSongBankIfNeeded at $0088EC"
        if name == "disasm_at":
            return "$0088EC: JSR Underworld_LoadSongBankIfNeeded"
        if name == "grep_disasm":
            return "xref: Underworld_LoadSongBankIfNeeded"
        return ""

    def get_tool_server(self, tool_name: str) -> str:
        return "oracle"

    @property
    def tool_count(self) -> int:
        return 4

    @property
    def server_names(self) -> list[str]:
        return ["oracle"]

    @property
    def server_tool_counts(self) -> dict[str, int]:
        return {"oracle": 4}

    async def close(self) -> None:
        return None


class FakeUnknownRegisterBridge(FakeOracleBridge):
    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "register_doc":
            return f"Unknown register: {arguments.get('query')}"
        return await super().call_tool(name, arguments)


class FakeFailingRegisterBridge(FakeOracleBridge):
    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "register_doc":
            raise RuntimeError("register table offline")
        return await super().call_tool(name, arguments)


class FakeFailingLabelLookupBridge(FakeOracleBridge):
    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        if name == "label_lookup":
            return "Error: Unknown tool 'z3lsp_symbols'"
        return await super().call_tool(name, arguments)


class FakeMissingRegisterToolBridge(FakeOracleBridge):
    def get_openai_tools(self) -> list[dict]:
        return [
            {"type": "function", "function": {"name": "label_lookup"}},
            {"type": "function", "function": {"name": "disasm_at"}},
        ]


def write_minimal_yaze_object_header(
    root: Path,
    *,
    type1: list[str],
    type2: list[str] | None = None,
    type3: list[str] | None = None,
) -> None:
    header_dir = root / "yaze" / "src" / "zelda3" / "dungeon"
    header_dir.mkdir(parents=True, exist_ok=True)
    type2 = type2 or ["Extended Object"]
    type3 = type3 or ["Special Object"]

    def render(name: str, values: list[str]) -> str:
        body = "\n".join(f'    "{value}",' for value in values)
        return f"constexpr static inline const char* {name}[] = {{\n{body}\n}};"

    (header_dir / "room_object.h").write_text(
        "\n\n".join([
            render("Type1RoomObjectNames", type1),
            render("Type2RoomObjectNames", type2),
            render("Type3RoomObjectNames", type3),
        ]),
        encoding="utf-8",
    )


class RuntimeAttachmentTests(unittest.TestCase):

    def test_auto_lsp_context_scales_with_model_size(self) -> None:
        small = resolve_lsp_context_settings("auto", model=None)
        medium = resolve_lsp_context_settings(
            "auto",
            model=type("M", (), {
                "name": "oracle-9b",
                "model_id": "oracle-9b",
                "description": "9B model",
                "role": "",
                "context_budget": 0,
                "is_cloud": False,
            })(),
        )
        large = resolve_lsp_context_settings(
            "auto",
            model=type("M", (), {
                "name": "switchhook-27b",
                "model_id": "switchhook-27b",
                "description": "27B model",
                "role": "",
                "context_budget": 0,
                "is_cloud": False,
            })(),
        )

        self.assertEqual(small.resolved_mode, "balanced")
        self.assertEqual(medium.resolved_mode, "minimal")
        self.assertEqual(large.resolved_mode, "rich")
        self.assertEqual(medium.symbol_detail_limit, 0)
        self.assertEqual(large.symbol_detail_limit, 2)

    def test_resolve_message_attachments_reads_workspace_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "src" / "main.asm").write_text("lda #$01\nsta $7E0010\n", encoding="utf-8")

            attachments = resolve_message_attachments(workspace, "inspect @src/main.asm please")

            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["path"], "src/main.asm")
            self.assertIn("lda #$01", attachments[0]["content"])

    def test_enrich_prompt_with_attachments_appends_context_block(self) -> None:
        prompt = "inspect this file"
        enriched = enrich_prompt_with_attachments(prompt, [{
            "path": "src/main.asm",
            "content": "lda #$01",
            "lines": 1,
            "chars": 8,
        }])

        self.assertIn("inspect this file", enriched)
        self.assertIn("Attached file context:", enriched)
        self.assertIn("@src/main.asm", enriched)
        self.assertIn("lda #$01", enriched)

    def test_resolve_message_attachments_accepts_structured_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "src").mkdir()
            (workspace / "src" / "main.asm").write_text("lda #$03\n", encoding="utf-8")

            attachments = resolve_message_attachments(
                workspace,
                "inspect this",
                requested=[{"path": "src/main.asm"}],
            )

            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0]["path"], "src/main.asm")
            self.assertIn("lda #$03", attachments[0]["content"])

    def test_resolve_message_construct_refs_uses_active_project_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            labels_path = workspace / "Docs" / "Dev" / "Planning"
            labels_path.mkdir(parents=True, exist_ok=True)
            (labels_path / "oracle_resource_labels.json").write_text(
                '{"room":{"0x45":"Glacia Estate (Jail Cells)"},"sprite":{"0x07":"Village Elder"}}',
                encoding="utf-8",
            )

            refs = resolve_message_construct_refs(
                workspace,
                "inspect #room:glacia-estate and #sprite:0x07.",
            )

            self.assertEqual(len(refs), 2)
            self.assertEqual(refs[0]["id"], "0x45")
            self.assertEqual(refs[0]["label"], "Glacia Estate (Jail Cells)")
            self.assertEqual(refs[1]["token"], "#sprite:0x07")

    def test_resolve_message_construct_refs_uses_sprite_catalog_for_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            catalog_path = workspace / "Docs" / "Technical"
            catalog_path.mkdir(parents=True, exist_ok=True)
            (catalog_path / "sprite_catalog.md").write_text(
                "\n".join([
                    "## Objects (8 files)",
                    "| Sprite | Status | Location | Purpose | Notes |",
                    "|--------|--------|----------|---------|-------|",
                    "| **Minecart** | ✅ Done | D6 (Goron Mines) | Rideable puzzle system | Complex track persistence |",
                ]),
                encoding="utf-8",
            )

            refs = resolve_message_construct_refs(workspace, "inspect #object:minecart")

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["id"], "minecart")
            self.assertEqual(refs[0]["label"], "Minecart")

    def test_resolve_message_construct_refs_uses_object_handler_metadata_for_raw_object_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            object_dir = workspace / "Dungeons" / "Objects"
            object_dir.mkdir(parents=True, exist_ok=True)
            (object_dir / "object_handler.asm").write_text(
                "\n".join([
                    "org $018262 ; Object ID 0x31 ; @hook module=Dungeons",
                    "  dw ExpandedObject",
                    "",
                    "CustomObjectHandler:",
                    "{",
                    ".ObjOffset",
                    "  dw .LeftRight-.ObjData ; 00",
                    "  dw .TrackAny-.ObjData ; 14",
                    ".ObjData",
                    "}",
                ]),
                encoding="utf-8",
            )

            refs = resolve_message_construct_refs(workspace, "inspect #object:0x31")

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["id"], "0x31")
            self.assertEqual(refs[0]["label"], "Custom track object")

    def test_resolve_message_construct_refs_uses_key_object_docs_for_vanilla_object_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            docs_dir = workspace / "Docs" / "World" / "Dungeons"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "TestDungeon_Map.md").write_text(
                "\n".join([
                    "| Room | Notes |",
                    "|------|-------|",
                    "| Key Objects | Floor tiles (0x22×5), big key door (0x010C) |",
                ]),
                encoding="utf-8",
            )

            refs = resolve_message_construct_refs(workspace, "inspect #object:0x22 and #object:0x010C")

            self.assertEqual(len(refs), 2)
            self.assertEqual(refs[0]["label"], "Floor tiles")
            self.assertEqual(refs[1]["label"], "big key door")

    def test_resolve_message_construct_refs_prefers_canonical_yaze_object_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "oracle-of-secrets"
            workspace.mkdir(parents=True, exist_ok=True)
            docs_dir = workspace / "Docs" / "World" / "Dungeons"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "TestDungeon_Map.md").write_text(
                "\n".join([
                    "| Room | Notes |",
                    "|------|-------|",
                    "| Key Objects | Floor tiles (0x22×5) |",
                ]),
                encoding="utf-8",
            )
            type1 = [f"Object {index:02X}" for index in range(0x23)]
            type1[0x22] = "Canonical Rail"
            write_minimal_yaze_object_header(Path(tmp), type1=type1)

            refs = resolve_message_construct_refs(workspace, "inspect #object:0x22")

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["label"], "Canonical Rail")

    def test_enrich_prompt_with_construct_refs_appends_context_block(self) -> None:
        prompt = "inspect this room"
        enriched = enrich_prompt_with_construct_refs(prompt, [{
            "kind": "room",
            "query": "0x45",
            "token": "#room:0x45",
            "summary": "Room 0x45: Glacia Estate (Jail Cells)",
        }])

        self.assertIn("inspect this room", enriched)
        self.assertIn("Referenced game context:", enriched)
        self.assertIn("#room:0x45", enriched)
        self.assertIn("Glacia Estate (Jail Cells)", enriched)

    def test_extract_lsp_symbol_queries_filters_prompt_tokens(self) -> None:
        queries = extract_lsp_symbol_queries(
            "inspect Link_Main and SprState in @src/main.asm with quick notes",
            limit=4,
        )

        self.assertEqual(queries, ["Link_Main", "SprState"])

    def test_plan_oracle_context_prefetch_includes_register_label_and_disasm_hints(self) -> None:
        calls = plan_oracle_context_prefetch(
            "Why does $420B behave differently near Underworld_LoadSongBankIfNeeded at $0088EC? Please inspect the hook contract."
        )

        names = [item.tool_name for item in calls]
        self.assertIn("register_doc", names)
        self.assertIn("label_lookup", names)
        self.assertIn("disasm_at", names)
        self.assertTrue(any(item.arguments.get("query") == "$420B" for item in calls if item.tool_name == "register_doc"))
        self.assertTrue(any(item.arguments.get("query") == "Underworld_LoadSongBankIfNeeded" for item in calls if item.tool_name == "label_lookup"))

    def test_enrich_prompt_with_oracle_context_appends_prefetch_section(self) -> None:
        prompt = "Why does $420B not start DMA?"
        enriched = enrich_prompt_with_oracle_context(prompt, [
            {
                "label": "register_doc($420B)",
                "content": "### MDMAEN ($420B)\nDMA enable register",
            }
        ])

        self.assertIn("Oracle preloaded context:", enriched)
        self.assertIn("register_doc($420B)", enriched)
        self.assertIn("DMA enable register", enriched)


class RuntimeAttachmentAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_oracle_context_packs_uses_bridge_for_oracle_family(self) -> None:
        bridge = FakeOracleBridge()
        model = type("M", (), {"name": "oracle-pro"})()

        contexts = await collect_oracle_context_packs(
            "Compare $420B and Underworld_LoadSongBankIfNeeded at $0088EC.",
            bridge=bridge,
            model=model,
        )

        self.assertGreaterEqual(len(contexts), 2)
        labels = [str(item["label"]) for item in contexts]
        self.assertIn("register_doc($420B)", labels)
        self.assertTrue(any(label.startswith("label_lookup(") for label in labels))

    async def test_collect_oracle_context_packs_keeps_unknown_register_results(self) -> None:
        bridge = FakeUnknownRegisterBridge()
        model = type("M", (), {"name": "oracle-pro"})()

        contexts = await collect_oracle_context_packs(
            "What does $4310 do?",
            bridge=bridge,
            model=model,
        )

        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["tool_name"], "register_doc")
        self.assertIn("Unknown register", contexts[0]["content"])

    async def test_collect_oracle_context_packs_keeps_register_tool_failures(self) -> None:
        bridge = FakeFailingRegisterBridge()
        model = type("M", (), {"name": "oracle-pro"})()

        contexts = await collect_oracle_context_packs(
            "What does $420B do?",
            bridge=bridge,
            model=model,
        )

        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["tool_name"], "register_doc")
        self.assertIn("register table offline", contexts[0]["content"])

    async def test_collect_oracle_context_packs_drops_failed_non_register_prefetch(self) -> None:
        bridge = FakeFailingLabelLookupBridge()
        model = type("M", (), {"name": "oracle-pro"})()

        contexts = await collect_oracle_context_packs(
            "Use workspace_read on docs/HANDOFF_ZELDA_MODEL_WORK_20260425.md before answering.",
            bridge=bridge,
            model=model,
        )

        self.assertEqual(contexts, [])
        self.assertTrue(any(name == "label_lookup" for name, _args in bridge.calls))

    async def test_collect_oracle_context_packs_keeps_unavailable_planned_tools(self) -> None:
        bridge = FakeMissingRegisterToolBridge()
        model = type("M", (), {"name": "oracle-pro"})()

        contexts = await collect_oracle_context_packs(
            "What does $420B do?",
            bridge=bridge,
            model=model,
        )

        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["tool_name"], "register_doc")
        self.assertEqual(contexts[0]["server"], "unavailable")
        self.assertIn("not available", contexts[0]["content"])

    def test_build_oracle_prefetch_session_records_keeps_register_doc_history(self) -> None:
        records = build_oracle_prefetch_session_records(
            "Explain what $420B and $420C do.",
            [
                {
                    "tool_name": "register_doc",
                    "arguments": {"query": "$420B"},
                    "server": "oracle",
                    "label": "register_doc($420B)",
                    "content": "### MDMAEN ($420B)\nDMA enable register",
                },
                {
                    "tool_name": "register_doc",
                    "arguments": {"query": "$420C"},
                    "server": "oracle",
                    "label": "register_doc($420C)",
                    "content": "### HDMAEN ($420C)\nHDMA enable register",
                },
                {
                    "tool_name": "label_lookup",
                    "arguments": {"query": "MDMAEN"},
                    "server": "oracle",
                    "label": "label_lookup(MDMAEN)",
                    "content": "not used here",
                },
            ],
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["tool_name"], "register_doc")
        self.assertEqual(records[0]["arguments_json"], '{"query": "$420B"}')
        self.assertEqual(records[1]["arguments_json"], '{"query": "$420C"}')

    def test_build_oracle_prefetch_forced_reply_for_unknown_register(self) -> None:
        reply = build_oracle_prefetch_forced_reply(
            "What does $4310 do?",
            [{
                "tool_name": "register_doc",
                "arguments": {"query": "$4310"},
                "server": "oracle",
                "label": "register_doc($4310)",
                "content": "Unknown register: $4310",
            }],
        )

        self.assertIn("couldn't find", reply.lower())
        self.assertNotIn("$4310", reply)

    def test_build_oracle_prefetch_forced_reply_for_failed_register_lookup(self) -> None:
        reply = build_oracle_prefetch_forced_reply(
            "What does $420B do?",
            [{
                "tool_name": "register_doc",
                "arguments": {"query": "$420B"},
                "server": "oracle",
                "label": "register_doc($420B)",
                "content": "Error: Oracle grounding tool `register_doc` failed: offline",
            }],
        )

        self.assertIn("couldn't retrieve", reply.lower())
        self.assertIn("don't want to answer from memory", reply.lower())

    def test_build_unavailable_tool_forced_reply_for_filesystem_prompt(self) -> None:
        reply = build_unavailable_tool_forced_reply("Try filesystem tools", FakeOracleBridge())

        self.assertIn("don't have general filesystem browsing tools", reply)

    def test_build_oracle_answer_after_grounding_prompt_for_simple_trace(self) -> None:
        prompt = build_oracle_answer_after_grounding_prompt("Let's take a look at the Minecart sprite.")

        self.assertIn("answer from the current evidence", prompt)

    def test_build_oracle_answer_after_grounding_prompt_skips_debug_turns(self) -> None:
        prompt = build_oracle_answer_after_grounding_prompt("Debug this minecart crash regression.")

        self.assertEqual(prompt, "")

    def test_build_oracle_answer_after_grounding_prompt_skips_broad_repo_discovery(self) -> None:
        prompt = build_oracle_answer_after_grounding_prompt(
            "What are some pending tasks in this repo? Explore the docs and codebase."
        )

        self.assertEqual(prompt, "")

    async def test_add_attachment_context_packs_adds_z3lsp_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "main.asm"
            file_path.write_text("lda #$05\n", encoding="utf-8")

            attachments = [{
                "path": "main.asm",
                "full_path": str(file_path),
                "content": "lda #$05\n",
                "lines": 1,
                "chars": 9,
            }]

            bridge = FakeZ3LspBridge()
            enriched = await add_attachment_context_packs(
                attachments,
                bridge=bridge,
                prompt_query="inspect Link_Main in @main.asm",
            )

            self.assertEqual(enriched[0]["context_pack"], "z3lsp summary for main.asm")
            self.assertEqual(bridge.calls[0]["symbol_queries"], ["Link_Main"])
            self.assertEqual(bridge.calls[0]["query"], "Link_Main")

    async def test_build_focus_context_content_includes_z3lsp_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            focus_path = Path(tmp) / "main.asm"
            focus_path.write_text("lda #$07\n", encoding="utf-8")

            bridge = FakeZ3LspBridge("focus pack")
            enriched = await build_focus_context_content(
                focus_path,
                "lda #$07\n",
                bridge=bridge,
                prompt_query="trace SprState in this file",
            )

            self.assertIn("--- z3lsp Context ---", enriched)
            self.assertIn("focus pack for main.asm", enriched)
            self.assertIn("--- File Content ---", enriched)
            self.assertIn("lda #$07", enriched)
            self.assertEqual(bridge.calls[0]["symbol_queries"], ["SprState"])

    async def test_add_construct_context_packs_reads_room_details_from_rom_bridge(self) -> None:
        refs = [{
            "kind": "room",
            "query": "0x45",
            "id": "0x45",
            "token": "#room:0x45",
            "label": "Glacia Estate (Jail Cells)",
        }]

        bridge = FakeRomBridge()
        enriched = await add_construct_context_packs(refs, bridge=bridge, workspace=Path("/tmp"))

        self.assertIn("Room overview:", enriched[0]["context_pack"])
        self.assertIn("Object 0x10", enriched[0]["context_pack"])
        self.assertIn("Sprite 0x07", enriched[0]["context_pack"])
        self.assertEqual([call[0] for call in bridge.calls], [
            "dungeon_describe_room",
            "dungeon_list_objects",
            "dungeon_list_sprites",
            "dungeon_list_chests",
        ])

    async def test_add_construct_context_packs_uses_sprite_catalog_for_sprite_and_object_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            labels_path = workspace / "Docs" / "Dev" / "Planning"
            labels_path.mkdir(parents=True, exist_ok=True)
            (labels_path / "oracle_resource_labels.json").write_text(
                '{"sprite":{"0x07":"Village Elder"}}',
                encoding="utf-8",
            )
            catalog_path = workspace / "Docs" / "Technical"
            catalog_path.mkdir(parents=True, exist_ok=True)
            (catalog_path / "sprite_catalog.md").write_text(
                "\n".join([
                    "## NPCs (26 files)",
                    "| Sprite | Status | Location | Role | Notes |",
                    "|--------|--------|----------|------|-------|",
                    "| **Village Elder** | ✅ Done | Wayward Village | Tutorial NPC | Progress-based dialogue |",
                    "",
                    "## Objects (8 files)",
                    "| Sprite | Status | Location | Purpose | Notes |",
                    "|--------|--------|----------|---------|-------|",
                    "| **Minecart** | ✅ Done | D6 (Goron Mines) | Rideable puzzle system | Complex track persistence |",
                ]),
                encoding="utf-8",
            )

            refs = [
                {"kind": "sprite", "query": "0x07", "id": "0x07", "label": "Village Elder", "token": "#sprite:0x07"},
                {"kind": "object", "query": "minecart", "id": "minecart", "label": "Minecart", "token": "#object:minecart"},
            ]

            enriched = await add_construct_context_packs(refs, bridge=None, workspace=workspace)

            self.assertIn("Catalog section: NPCs", enriched[0]["context_pack"])
            self.assertIn("Registry ID: 0x07", enriched[0]["context_pack"])
            self.assertIn("Tutorial NPC", enriched[0]["context_pack"])
            self.assertIn("Catalog section: Objects", enriched[1]["context_pack"])
            self.assertIn("Rideable puzzle system", enriched[1]["context_pack"])

    async def test_add_construct_context_packs_uses_object_handler_metadata_for_raw_object_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            object_dir = workspace / "Dungeons" / "Objects"
            object_dir.mkdir(parents=True, exist_ok=True)
            (object_dir / "object_handler.asm").write_text(
                "\n".join([
                    "org $018262 ; Object ID 0x31 ; @hook module=Dungeons",
                    "  dw ExpandedObject",
                    "",
                    "CustomObjectHandler:",
                    "{",
                    ".ObjOffset",
                    "  dw .LeftRight-.ObjData ; 00",
                    "  dw .TrackAny-.ObjData ; 14",
                    ".ObjData",
                    "}",
                ]),
                encoding="utf-8",
            )

            refs = [{"kind": "object", "query": "0x31", "id": "0x31", "label": "Custom track object", "token": "#object:0x31"}]
            enriched = await add_construct_context_packs(refs, bridge=None, workspace=workspace)

            self.assertIn("Object ID: 0x31", enriched[0]["context_pack"])
            self.assertIn("Aliases: track object, custom object, rail object", enriched[0]["context_pack"])
            self.assertIn("Subtype map:", enriched[0]["context_pack"])
            self.assertIn("0: Left Right", enriched[0]["context_pack"])

    async def test_add_construct_context_packs_uses_key_object_docs_for_vanilla_object_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            docs_dir = workspace / "Docs" / "World" / "Dungeons"
            docs_dir.mkdir(parents=True, exist_ok=True)
            (docs_dir / "TestDungeon_Map.md").write_text(
                "\n".join([
                    "| Room | Notes |",
                    "|------|-------|",
                    "| Key Objects | Floor tiles (0x22×5), big key door (0x010C) |",
                ]),
                encoding="utf-8",
            )

            refs = [{"kind": "object", "query": "0x22", "id": "0x22", "label": "Floor tiles", "token": "#object:0x22"}]
            enriched = await add_construct_context_packs(refs, bridge=None, workspace=workspace)

            self.assertIn("Object ID: 0x22", enriched[0]["context_pack"])
            self.assertIn("Aliases: Floor tiles", enriched[0]["context_pack"])
            self.assertIn("TestDungeon_Map.md", enriched[0]["context_pack"])

    async def test_add_construct_context_packs_uses_canonical_yaze_object_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "oracle-of-secrets"
            workspace.mkdir(parents=True, exist_ok=True)
            type1 = [f"Object {index:02X}" for index in range(0x23)]
            type1[0x22] = "Canonical Rail"
            write_minimal_yaze_object_header(Path(tmp), type1=type1)

            refs = [{"kind": "object", "query": "0x22", "id": "0x22", "label": "Canonical Rail", "token": "#object:0x22"}]
            enriched = await add_construct_context_packs(refs, bridge=None, workspace=workspace)

            self.assertIn("Object ID: 0x22", enriched[0]["context_pack"])
            self.assertIn("../yaze/src/zelda3/dungeon/room_object.h", enriched[0]["context_pack"])

    async def test_enrich_prompt_with_attachments_renders_context_pack_before_file(self) -> None:
        prompt = "inspect this file"
        attachments = await add_attachment_context_packs(
            [{
                "path": "src/main.asm",
                "full_path": "/tmp/src/main.asm",
                "content": "lda #$01",
                "lines": 1,
                "chars": 8,
            }],
            bridge=FakeZ3LspBridge(),
        )

        enriched = enrich_prompt_with_attachments(prompt, attachments)

        self.assertIn("@src/main.asm z3lsp", enriched)
        self.assertIn("z3lsp summary for main.asm", enriched)
        self.assertIn("@src/main.asm", enriched)
        self.assertIn("lda #$01", enriched)

    async def test_build_focus_context_content_falls_back_to_workspace_symbol_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            focus_path = workspace / "src" / "main.asm"
            focus_path.parent.mkdir(parents=True, exist_ok=True)
            focus_path.write_text("lda #$07\n", encoding="utf-8")
            symbol_path = workspace / "src" / "link.asm"
            symbol_path.write_text("\n" * 11 + "Link_Main:\n", encoding="utf-8")

            bridge = WorkspaceFallbackZ3LspBridge(
                workspace,
                workspace_symbols=[
                    {
                        "name": "Link_Main",
                        "location": {
                            "uri": symbol_path.as_uri(),
                            "range": {
                                "start": {"line": 11, "character": 0},
                            },
                        },
                    },
                ],
            )

            enriched = await build_focus_context_content(
                focus_path,
                "lda #$07\n",
                bridge=bridge,
                lsp_context_mode="rich",
                prompt_query="trace Link_Main from this file",
            )

            self.assertIn("Workspace symbol matches:", enriched)
            self.assertIn("Link_Main", enriched)
            self.assertIn("link.asm:12:1", enriched)
            self.assertIn("workspace symbol hover", enriched)


if __name__ == "__main__":
    unittest.main()
