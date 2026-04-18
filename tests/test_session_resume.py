import json
import tempfile
import unittest
from pathlib import Path

from z3cli.core.session import (
    Session,
    export_training,
    find_session,
    list_sessions,
    load_session_bundle,
    load_session_bundle_without_thinking,
)


class SessionResumeTests(unittest.TestCase):
    def test_load_session_bundle_restores_final_state_and_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Path(tmp))
            session.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="/tmp/ws/game.sfc",
                tools_enabled=True,
                broadcast_models=["nayru"],
                llamacpp_model="oracle-fast",
                tools_write=False,
                focus_path="",
            )
            path = session.path
            assert path is not None

            session.append_state_update({
                "mode": "broadcast",
                "workspace": "/tmp/ws-next",
                "tools_write": True,
                "focus_path": "/tmp/ws-next/main.asm",
            })
            session.append_model_switch("nayru", "farore")
            session.append_backend_switch("studio", "llamacpp")
            session.append_engine_msg("farore", {"role": "user", "content": "inspect this"})
            session.append_engine_msg("farore", {
                "role": "assistant",
                "content": "Calling a tool.",
                "thinking": "Inspecting the room header before patching.",
                "tool_calls": [{
                    "name": "read_file",
                    "arguments": "{\"path\":\"main.asm\"}",
                    "server": "afs",
                }],
            })
            session.append_engine_msg("farore", {
                "role": "tool",
                "name": "read_file",
                "content": "lda #$01",
            })
            session.close()

            loaded = load_session_bundle(path)

            self.assertEqual(loaded.meta["active_model"], "farore")
            self.assertEqual(loaded.meta["backend"], "llamacpp")
            self.assertEqual(loaded.meta["mode"], "broadcast")
            self.assertEqual(loaded.meta["workspace"], "/tmp/ws-next")
            self.assertTrue(loaded.meta["tools_write"])
            self.assertEqual(loaded.meta["focus_path"], "/tmp/ws-next/main.asm")

            self.assertEqual(
                [msg["role"] for msg in loaded.transcript],
                ["system", "system", "user", "assistant", "tool", "tool"],
            )
            self.assertEqual(loaded.transcript[3]["model"], "farore")
            self.assertEqual(
                loaded.transcript[3]["thinking"],
                "Inspecting the room header before patching.",
            )
            self.assertEqual(loaded.transcript[4]["toolName"], "read_file")
            self.assertEqual(loaded.transcript[4]["toolServer"], "afs")
            self.assertEqual(loaded.transcript[5]["content"], "lda #$01")
            restored_history = loaded.model_messages["farore"]
            self.assertEqual(restored_history[1]["tool_calls"][0]["type"], "function")
            self.assertEqual(
                restored_history[1]["tool_calls"][0]["function"],
                {
                    "name": "read_file",
                    "arguments": "{\"path\":\"main.asm\"}",
                },
            )
            self.assertEqual(restored_history[2]["tool_call_id"], "restored_call_1")

    def test_resume_reuses_saved_file_and_removes_empty_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)

            original = Session(session_dir)
            original.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            original.append_engine_msg("nayru", {"role": "user", "content": "hello"})
            original_path = original.path
            assert original_path is not None
            original.close()

            placeholder = Session(session_dir)
            placeholder.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            placeholder_path = placeholder.path
            assert placeholder_path is not None and placeholder_path.exists()

            placeholder.resume(original_path, message_count=7)
            self.assertEqual(placeholder.path, original_path.resolve())
            self.assertEqual(placeholder.message_count, 7)
            self.assertFalse(placeholder_path.exists())

            placeholder.append_engine_msg("nayru", {"role": "assistant", "content": "continued"})
            placeholder.close()

            lines = original_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(json.loads(lines[-1])["msg"]["content"], "continued")

    def test_load_session_bundle_without_thinking_strips_reasoning_from_transcript_and_subagents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Path(tmp))
            session.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            path = session.path
            assert path is not None

            session.append_engine_msg("nayru", {"role": "user", "content": "inspect this"})
            session.append_engine_msg("nayru", {
                "role": "assistant",
                "content": "done",
                "thinking": "inspect the room header",
            })
            session.append_subagent_event("start", {
                "id": "sub-1",
                "name": "helper",
                "model": "worker",
                "provider": "studio",
                "depth": 1,
                "parent_id": "",
            })
            session.append_subagent_event("thinking", {
                "id": "sub-1",
                "delta": "read the map first",
            })
            session.append_subagent_event("done", {
                "id": "sub-1",
                "name": "helper",
                "model": "worker",
                "text": "done",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "tool_calls": 0,
                "error": "",
                "cancelled": False,
            })
            session.close()

            loaded = load_session_bundle_without_thinking(path)

            self.assertIsNone(loaded.transcript[1].get("thinking"))
            self.assertEqual(loaded.subagents[0]["thinking"], "")

    def test_find_session_prefers_exact_match_and_rejects_ambiguous_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            alpha = session_dir / "2026-01-01_000000_alpha.jsonl"
            alphabet = session_dir / "2026-01-01_000001_alphabet.jsonl"
            payload = json.dumps({
                "type": "meta",
                "started": "2026-01-01T00:00:00+00:00",
                "backend": "studio",
                "active_model": "nayru",
                "mode": "manual",
            })
            alpha.write_text(payload + "\n", encoding="utf-8")
            alphabet.write_text(payload + "\n", encoding="utf-8")

            self.assertEqual(find_session(alpha.stem, session_dir)["name"], alpha.stem)
            with self.assertRaises(ValueError):
                find_session("alpha", session_dir)

    def test_list_sessions_tracks_preview_metrics_and_visible_message_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp)
            session = Session(session_dir)
            session.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            session.append_engine_msg("nayru", {"role": "user", "content": "scan rooms"})
            session.append_engine_msg("nayru", {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "name": "read_file",
                    "arguments": "{\"path\":\"room.asm\"}",
                    "server": "afs",
                }],
            })
            session.append_engine_msg("nayru", {
                "role": "tool",
                "name": "read_file",
                "content": "room data",
            })
            session.append_engine_msg("nayru", {"role": "assistant", "content": "Found the room script."})
            session.append_state_update({
                "prompt_tokens": 123,
                "completion_tokens": 45,
                "tool_call_count": 1,
                "last_active_at": "2026-04-13T12:34:56+00:00",
            })
            session.close()

            sessions = list_sessions(session_dir)
            self.assertEqual(len(sessions), 1)
            entry = sessions[0]
            self.assertEqual(entry["messages"], 2)
            self.assertEqual(entry["tool_calls"], 1)
            self.assertEqual(entry["prompt_tokens"], 123)
            self.assertEqual(entry["completion_tokens"], 45)
            self.assertEqual(entry["updated"], "2026-04-13T12:34:56+00:00")
            self.assertEqual(entry["preview"], "Found the room script.")

    def test_load_session_bundle_prefers_display_content_and_preserves_attachments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Path(tmp))
            session.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            path = session.path
            assert path is not None

            session.append_engine_msg("nayru", {
                "role": "user",
                "content": "summarize this\n\nAttached file context:\n@src/test.asm\n```asm\nlda #$01\n```",
                "display_content": "summarize this @src/test.asm",
                "attachments": [{"path": "src/test.asm", "lines": 2, "chars": 10}],
                "construct_refs": [{
                    "kind": "room",
                    "query": "0x45",
                    "token": "#room:0x45",
                    "id": "0x45",
                    "label": "Glacia Estate (Jail Cells)",
                }],
            })
            session.close()

            loaded = load_session_bundle(path)

            self.assertEqual(loaded.model_messages["nayru"][0]["content"].splitlines()[0], "summarize this")
            self.assertNotIn("display_content", loaded.model_messages["nayru"][0])
            self.assertNotIn("attachments", loaded.model_messages["nayru"][0])
            self.assertEqual(loaded.transcript[0]["content"], "summarize this @src/test.asm")
            self.assertEqual(loaded.transcript[0]["attachments"][0]["path"], "src/test.asm")
            self.assertEqual(loaded.transcript[0]["constructRefs"][0]["token"], "#room:0x45")

    def test_load_session_bundle_restores_subagent_panel_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Path(tmp))
            session.start(
                active_model="oracle-main-plan",
                backend="studio",
                mode="orchestrator",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["oracle-main-plan"],
            )
            path = session.path
            assert path is not None

            session.append_subagent_event("start", {
                "id": "sub-1-planner",
                "name": "planner",
                "model": "planner",
                "provider": "anthropic",
                "depth": 1,
                "parent_id": "",
            })
            session.append_subagent_event("text", {
                "id": "sub-1-planner",
                "delta": "Scanning files",
            })
            session.append_subagent_event("tool_call", {
                "id": "sub-1-planner",
                "name": "search",
                "server": "github",
                "arguments": "{\"query\":\"resume\"}",
                "call_id": "call-1",
            })
            session.append_subagent_event("tool_result", {
                "id": "sub-1-planner",
                "name": "search",
                "result": "done",
                "call_id": "call-1",
            })
            session.append_subagent_event("start", {
                "id": "sub-2-worker",
                "name": "worker",
                "model": "worker",
                "provider": "studio",
                "depth": 2,
                "parent_id": "sub-1-planner",
            })
            session.append_subagent_event("done", {
                "id": "sub-2-worker",
                "name": "worker",
                "model": "worker",
                "text": "Patched resume path",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "tool_calls": 0,
                "error": "",
                "cancelled": False,
            })
            session.close()

            loaded = load_session_bundle(path)

            self.assertEqual(len(loaded.subagents), 2)
            root = loaded.subagents[0]
            child = loaded.subagents[1]
            self.assertEqual(root["id"], "sub-1-planner")
            self.assertEqual(root["status"], "cancelled")
            self.assertEqual(root["text"], "Scanning files")
            self.assertEqual(root["toolCallCount"], 1)
            self.assertEqual(child["id"], "sub-2-worker")
            self.assertEqual(child["parentId"], "sub-1-planner")
            self.assertEqual(child["status"], "done")
            self.assertEqual(child["promptTokens"], 10)
            self.assertEqual(child["completionTokens"], 5)

    def test_export_training_strips_thinking_by_default_and_allows_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Path(tmp))
            session.start(
                active_model="nayru",
                backend="studio",
                mode="manual",
                workspace="/tmp/ws",
                rom_path="",
                tools_enabled=True,
                broadcast_models=["nayru"],
            )
            path = session.path
            assert path is not None

            session.append_engine_msg("nayru", {"role": "user", "content": "inspect this"})
            session.append_engine_msg("nayru", {
                "role": "assistant",
                "content": "done",
                "thinking": "inspect the room header",
            })
            session.close()

            default_out = Path(tmp) / "default.training.jsonl"
            include_out = Path(tmp) / "include.training.jsonl"

            self.assertEqual(export_training(path, default_out), 1)
            self.assertEqual(export_training(path, include_out, include_thinking=True), 1)

            default_sample = json.loads(default_out.read_text(encoding="utf-8").strip())
            include_sample = json.loads(include_out.read_text(encoding="utf-8").strip())

            self.assertNotIn("thinking", default_sample["messages"][1])
            self.assertEqual(include_sample["messages"][1]["thinking"], "inspect the room header")


if __name__ == "__main__":
    unittest.main()
