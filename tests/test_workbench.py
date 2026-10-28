"""Tests for the workbench/* RPC helpers."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import workbench


def _status(dir_: Path, name: str, pid: int, **extra) -> Path:
    path = dir_ / f"mesen2-{name}.status"
    path.write_text(json.dumps({"pid": pid, "socketPath": str(dir_ / f"mesen2-{name}.sock"), **extra}))
    return path


class EmulatorDiscoveryTests(unittest.TestCase):
    def test_live_dead_and_orphan_sockets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _status(d, "live", os.getpid(), paused=True, romHash="AB")
            _status(d, "dead", 2**22 + 12345)
            (d / "mesen2-orphan.sock").touch()
            (d / "mesen2-broken.status").write_text("{not json")
            entries = {e["name"]: e for e in workbench.list_emulators(d)}
        self.assertEqual(set(entries), {"live", "dead", "orphan"})
        self.assertTrue(entries["live"]["alive"])
        self.assertTrue(entries["live"]["paused"])
        self.assertFalse(entries["dead"]["alive"])
        self.assertIsNone(entries["orphan"]["alive"])


class EmulatorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # AF_UNIX paths are limited to ~104 bytes on macOS.
        self._tmp = tempfile.TemporaryDirectory(dir="/tmp")
        self.dir = Path(self._tmp.name)
        self.sock = self.dir / "mesen2-t.sock"
        self.received: list[dict] = []

        async def handle(reader, writer):
            line = await reader.readline()
            self.received.append(json.loads(line))
            writer.write(b'{"success": true, "data": "PONG"}\n')
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_unix_server(handle, path=str(self.sock))
        _status(self.dir, "t", os.getpid())

    async def asyncTearDown(self) -> None:
        self.server.close()
        await self.server.wait_closed()
        self._tmp.cleanup()

    async def test_sends_newline_framed_command_and_reads_reply(self) -> None:
        reply = await workbench.emulator_command(str(self.sock), "ping", status_dir=self.dir)
        self.assertEqual(reply["data"], "PONG")
        self.assertEqual(self.received, [{"type": "PING"}])

    async def test_rejects_commands_outside_allowlist(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.emulator_command(str(self.sock), "WRITE_MEMORY", status_dir=self.dir)
        self.assertEqual(self.received, [])

    async def test_rejects_unknown_socket(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.emulator_command("/tmp/elsewhere.sock", "PING", status_dir=self.dir)

    async def test_rejects_socket_of_dead_instance(self) -> None:
        _status(self.dir, "t", 2**22 + 12345)
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.emulator_command(str(self.sock), "PING", status_dir=self.dir)


class RegistryTests(unittest.TestCase):
    def test_null_paths_do_not_shift_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry.json"
            gguf = Path(tmp) / "a.gguf"
            gguf.touch()
            reg.write_text(json.dumps({"models": [
                {"name": "a", "gguf_path": str(gguf), "mlx_path": None},
                {"name": "b", "gguf_path": None, "mlx_path": None},
            ]}))
            models = workbench.list_registry_models(reg)["models"]
        self.assertEqual([m["name"] for m in models], ["a", "b"])
        self.assertTrue(models[0]["gguf_exists"])
        self.assertIsNone(models[0]["mlx_path"])
        self.assertFalse(models[1]["gguf_exists"])

    def test_missing_registry_reports_error(self) -> None:
        result = workbench.list_registry_models(Path("/nonexistent/registry.json"))
        self.assertIn("error", result)
        self.assertEqual(result["models"], [])


class LmStudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreachable_host_is_reported_not_raised(self) -> None:
        hosts = await workbench.lmstudio_models({"nowhere": "http://127.0.0.1:9"}, timeout_s=1)
        self.assertFalse(hosts[0]["reachable"])
        self.assertEqual(hosts[0]["models"], [])


class TrainingStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_caches_and_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            counter = Path(tmp) / "n"
            script = Path(tmp) / "status.py"
            script.write_text(
                "import json, pathlib\n"
                f"p = pathlib.Path({str(counter)!r})\n"
                "n = int(p.read_text()) + 1 if p.exists() else 1\n"
                "p.write_text(str(n))\n"
                "print(json.dumps({'runs': [], 'n': n}))\n",
            )
            status = workbench.TrainingStatus(script)
            first = await status.get()
            second = await status.get()
            refreshed = await status.get(refresh=True)
            self.assertEqual((first["n"], first["cached"]), (1, False))
            self.assertEqual((second["n"], second["cached"]), (1, True))
            self.assertEqual(refreshed["n"], 2)

            slow = Path(tmp) / "slow.py"
            slow.write_text("import time; time.sleep(5)\n")
            result = await workbench.TrainingStatus(slow, timeout_s=0.5).get()
            self.assertIn("timed out", result["error"])


class TrainingActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_unsupported_action(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "windows", "action": "destroy"})

    async def test_actions_are_scoped_per_backend(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "windows", "action": "start", "host": "mm"})
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "vast", "action": "launch", "instance_id": "1"})
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "gcp", "action": "stop"})

    async def test_rejects_invalid_host_or_task(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "windows", "action": "stop", "host": "bad;host"})
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_action({"backend": "windows", "action": "stop", "task": "bad|task"})

    async def test_windows_ctl_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "windows_ctl.py"
            script.write_text(
                "import sys, json\n"
                "print(json.dumps({'received': sys.argv[1:]}))\n",
            )
            result = await workbench.training_action(
                {"backend": "windows", "action": "stop", "host": "mm", "task": "qwen"},
                windows_ctl=script,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["received"], ["stop", "--host", "mm", "--task", "qwen"])

    async def test_vast_ops_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "vast_ops.sh"
            script.write_text(
                "#!/bin/sh\n"
                "echo \"vast $1 $2\"\n",
            )
            script.chmod(0o755)
            for action in ("start", "stop"):
                result = await workbench.training_action(
                    {"backend": "vast", "action": action, "instance_id": "12345"},
                    vast_ops=script,
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["output"], f"vast {action} 12345")


class TrainingEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_invalid_model_slug(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.training_eval({"model_slug": "bad slug; rm -rf"})

    async def test_training_eval_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "readiness.py"
            script.write_text(
                "import sys, json\n"
                "print(json.dumps({'overall_status': 'pass', 'model': sys.argv[4]}))\n",
            )
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("{}")
            result = await workbench.training_eval(
                {
                    "model_slug": "oracle-9b-v5",
                    "manifest": str(manifest),
                    "eval_dir": str(tmp),
                    "packs_dir": str(tmp),
                },
                script=script,
            )
            self.assertEqual(result["overall_status"], "pass")
            self.assertEqual(result["model"], "oracle-9b-v5")


class TrainingPromoteTests(unittest.TestCase):
    def test_rejects_missing_paths(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            workbench.training_promote({"name": "test-model"})

    def test_rejects_nonexistent_files(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            workbench.training_promote({"name": "test-model", "gguf_path": "/nonexistent.gguf"})

    def test_promote_adds_and_updates_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            gguf_file = Path(tmp) / "model.gguf"
            gguf_file.touch()

            # First promotion creates entry
            res1 = workbench.training_promote(
                {"name": "zelda-expert", "gguf_path": str(gguf_file)},
                registry_path=reg_path,
            )
            self.assertTrue(res1["ok"])
            self.assertEqual(res1["models_count"], 1)

            # Second promotion updates entry
            mlx_dir = Path(tmp) / "model_mlx"
            mlx_dir.mkdir()
            res2 = workbench.training_promote(
                {"name": "zelda-expert", "mlx_path": str(mlx_dir)},
                registry_path=reg_path,
            )
            self.assertTrue(res2["ok"])
            self.assertEqual(res2["models_count"], 1)

            # Check saved registry content
            data = json.loads(reg_path.read_text())
            m = data["models"][0]
            self.assertEqual(m["name"], "zelda-expert")
            self.assertEqual(m["gguf_path"], str(gguf_file.resolve()))
            self.assertEqual(m["mlx_path"], str(mlx_dir.resolve()))

    def test_rejects_wrong_path_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg_path = Path(tmp) / "registry.json"
            with self.assertRaises(workbench.WorkbenchError):
                workbench.training_promote({"name": "m", "gguf_path": tmp}, registry_path=reg_path)
            gguf_file = Path(tmp) / "model.gguf"
            gguf_file.touch()
            with self.assertRaises(workbench.WorkbenchError):
                workbench.training_promote({"name": "m", "mlx_path": str(gguf_file)}, registry_path=reg_path)
            self.assertFalse(reg_path.exists())


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_training_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "windows_ctl.py"
            script.write_text("import sys, json; print(json.dumps({'argv': sys.argv[1:]}))\n")
            orig = workbench.DEFAULT_WINDOWS_CTL
            try:
                workbench.DEFAULT_WINDOWS_CTL = script
                res = await workbench.dispatch("workbench/training_action", {
                    "backend": "windows", "action": "status", "host": "mm",
                })
                self.assertTrue(res["ok"])
                self.assertEqual(res["data"]["argv"], ["status", "--host", "mm"])
            finally:
                workbench.DEFAULT_WINDOWS_CTL = orig

    async def test_dispatches_training_promote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = Path(tmp) / "registry.json"
            gguf = Path(tmp) / "a.gguf"
            gguf.touch()
            orig = workbench.DEFAULT_REGISTRY
            try:
                workbench.DEFAULT_REGISTRY = reg
                res = await workbench.dispatch("workbench/training_promote", {
                    "name": "a", "gguf_path": str(gguf),
                })
                self.assertTrue(res["ok"])
                self.assertEqual(res["promoted"], "a")
            finally:
                workbench.DEFAULT_REGISTRY = orig

    async def test_unknown_method_raises(self) -> None:
        with self.assertRaises(workbench.WorkbenchError):
            await workbench.dispatch("workbench/nope", {})


if __name__ == "__main__":
    unittest.main()
