import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

from app.backends import LMStudioBackend
from core.config import ModelConfig, load_registry
from protocol.lmstudio import (
    ensure_model_loaded,
    loaded_request_name,
    normalize_loaded_model_entry,
    parse_estimated_memory_output,
    resolve_available_model_id,
    server_status,
    unload_model,
)


class LMStudioLoadTests(unittest.TestCase):
    def test_resolve_available_model_id_matches_trimmed_local_name(self) -> None:
        resolved = resolve_available_model_id(
            "qwen3-oracle-8b-v1-corrective2-q4km",
            [{
                "modelKey": "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf",
                "displayName": "8B corrective Oracle · q4km",
            }],
        )

        self.assertEqual(resolved, "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf")

    def test_parse_estimated_memory_output_reads_gpu_and_total_bytes(self) -> None:
        estimates = parse_estimated_memory_output(
            "\n".join([
                "Model: gguf/zelda/nayru-9b-q8_0.gguf",
                "Estimated GPU Memory:   9.95 GiB",
                "Estimated Total Memory: 12.50 GiB",
            ]),
        )

        self.assertEqual(estimates["estimated_gpu_bytes"], int(9.95 * 1024 ** 3))
        self.assertEqual(estimates["estimated_total_bytes"], int(12.50 * 1024 ** 3))

    def test_normalize_loaded_model_entry_preserves_memory_and_runtime_fields(self) -> None:
        entry = normalize_loaded_model_entry({
            "identifier": "nayru",
            "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            "displayName": "Nayru 9B",
            "sizeBytes": 9_527_501_152,
            "status": "idle",
            "parallel": 4,
            "contextLength": 262144,
            "maxContextLength": 262144,
            "architecture": "qwen35",
            "quantization": {"name": "Q8_0"},
        })

        self.assertEqual(entry["identifier"], "nayru")
        self.assertEqual(entry["size_bytes"], 9_527_501_152)
        self.assertEqual(entry["status"], "idle")
        self.assertEqual(entry["parallel"], 4)
        self.assertEqual(entry["quantization"], "Q8_0")

    def test_load_registry_parses_lmstudio_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle-main-plan"
provider = "studio"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"
lmstudio_load = { context_length = 2048, parallel = 1, gpu = "0.80", ttl = 900 }
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path)
            model = models["oracle-main-plan"]

            self.assertEqual(model.lmstudio_context_length, 2048)
            self.assertEqual(model.lmstudio_parallel, 1)
            self.assertEqual(model.lmstudio_gpu, "0.80")
            self.assertEqual(model.lmstudio_ttl, 900)

    def test_load_registry_parses_allow_auto_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "chat_registry.toml"
            registry_path.write_text(
                """
[[models]]
name = "oracle"
provider = "studio"
model_id = "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf"
allow_auto_load = false
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path)

            self.assertFalse(models["oracle"].allow_auto_load)

    def test_backend_forwards_model_load_profile(self) -> None:
        target = ModelConfig(
            name="oracle-main-plan",
            model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
            provider="studio",
            lmstudio_context_length=2048,
            lmstudio_parallel=1,
            lmstudio_gpu="0.80",
            lmstudio_ttl=900,
        )

        backend = LMStudioBackend(api_base="http://127.0.0.1:1234/v1", host="127.0.0.1", port=1234)

        with patch.object(backend, "_openai_model_entries", return_value=[]), patch(
            "app.backends.ensure_model_loaded",
            return_value=target.name,
        ) as ensure:
            request_name = backend.resolve_request_model(target, auto_load=True)

        self.assertEqual(request_name, target.name)
        ensure.assert_called_once_with(
            alias=target.name,
            model_id=target.model_id,
            host="127.0.0.1",
            port=1234,
            auto_load=True,
            allow_auto_load=True,
            manual_load=False,
            context_length=2048,
            parallel=1,
            gpu="0.80",
            ttl=900,
        )

    def test_ensure_model_loaded_rejects_background_load_for_manual_only_model(self) -> None:
        with patch("protocol.lmstudio.loaded_models", return_value=[]), patch(
            "protocol.lmstudio.run_lms",
        ) as run_lms:
            with self.assertRaisesRegex(RuntimeError, "skip automatic LM Studio loads"):
                ensure_model_loaded(
                    alias="oracle",
                    model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                    host="127.0.0.1",
                    port=1234,
                    auto_load=True,
                    allow_auto_load=False,
                )

        run_lms.assert_not_called()

    def test_ensure_model_loaded_manual_load_overrides_manual_only_guard(self) -> None:
        with patch("protocol.lmstudio.loaded_models", return_value=[]), patch(
            "protocol.lmstudio.run_lms",
            return_value="",
        ) as run_lms:
            request_name = ensure_model_loaded(
                alias="oracle",
                model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                host="127.0.0.1",
                port=1234,
                auto_load=True,
                allow_auto_load=False,
                manual_load=True,
            )

        self.assertEqual(request_name, "oracle")
        self.assertEqual(run_lms.call_count, 2)
        self.assertEqual(run_lms.call_args_list[0].args[:3], (["ls", "--json"], "127.0.0.1", 1234))
        self.assertEqual(
            run_lms.call_args_list[1].args[:3],
            (["load", "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf", "--yes", "--identifier", "oracle"], "127.0.0.1", 1234),
        )

    def test_unload_model_uses_loaded_identifier(self) -> None:
        with patch("protocol.lmstudio.loaded_models", return_value=[
            {
                "identifier": "nayru",
                "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            },
        ]), patch("protocol.lmstudio.run_lms", return_value="") as run_lms:
            result = unload_model("127.0.0.1", 1234, "gguf/zelda/nayru-9b-q8_0.gguf")

        self.assertEqual(result, {"all": False, "unloaded": ["nayru"]})
        run_lms.assert_called_once_with(
            ["unload", "nayru"],
            "127.0.0.1",
            1234,
            timeout=60.0,
        )

    def test_server_status_uses_remote_windows_host_when_configured(self) -> None:
        remote_payload = "{\"running\": true, \"port\": 1234}\n"

        with patch.dict(
            "os.environ",
            {"Z3CLI_LMSTUDIO_REMOTE_HOST": "medical-mechanica"},
            clear=False,
        ), patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = remote_payload
            run.return_value.stderr = ""

            status = server_status("127.0.0.1", 1234)

        self.assertTrue(status["running"])
        self.assertEqual(status["port"], 1234)
        ssh_args = run.call_args.args[0]
        self.assertEqual(ssh_args[0], "ssh")
        self.assertEqual(ssh_args[1], "medical-mechanica")
        self.assertIn("EncodedCommand", ssh_args[2])

    def test_server_status_prefers_afs_hostd_when_configured(self) -> None:
        with patch.dict(
            "os.environ",
            {"AFS_HOSTD_URL": "http://127.0.0.1:8765"},
            clear=False,
        ), patch("urllib.request.urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.return_value = b'{"server": {"running": true, "port": 1234}}'

            status = server_status("127.0.0.1", 1234)

        self.assertTrue(status["running"])
        self.assertEqual(status["port"], 1234)
        self.assertEqual(urlopen.call_args.args[0].full_url, "http://127.0.0.1:8765/v1/lmstudio/status")

    def test_ensure_model_loaded_uses_afs_hostd_when_configured(self) -> None:
        with patch.dict(
            "os.environ",
            {"AFS_HOSTD_URL": "http://127.0.0.1:8765"},
            clear=False,
        ), patch("urllib.request.urlopen") as urlopen:
            responses = [
                b'{"loaded": []}',
                b'{"identifier": "oracle-fast", "resolved_model_id": "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf"}',
            ]

            def fake_read():
                return responses.pop(0)

            urlopen.return_value.__enter__.return_value.read.side_effect = fake_read
            request_name = ensure_model_loaded(
                alias="oracle-fast",
                model_id="qwen3-oracle-8b-v1-corrective2-q4km",
                host="127.0.0.1",
                port=1234,
                auto_load=True,
            )

        self.assertEqual(request_name, "oracle-fast")
        self.assertEqual(urlopen.call_count, 2)

    def test_server_status_falls_back_to_api_when_afs_hostd_is_refused(self) -> None:
        with patch.dict(
            "os.environ",
            {"AFS_HOSTD_URL": "http://127.0.0.1:8765"},
            clear=False,
        ), patch(
            "protocol.lmstudio._hostd_request_json",
            side_effect=RuntimeError("afs-hostd request failed: [Errno 61] Connection refused"),
        ), patch(
            "protocol.lmstudio._api_endpoint_running",
            return_value=True,
        ), patch("protocol.lmstudio.run_lms") as run_lms:
            status = server_status("127.0.0.1", 2234)

        self.assertEqual(status, {"running": True, "port": 2234})
        run_lms.assert_not_called()

    def test_ensure_model_loaded_falls_back_to_loaded_api_model_when_afs_hostd_is_refused(self) -> None:
        with patch.dict(
            "os.environ",
            {"AFS_HOSTD_URL": "http://127.0.0.1:8765"},
            clear=False,
        ), patch(
            "protocol.lmstudio._hostd_request_json",
            side_effect=RuntimeError("afs-hostd request failed: [Errno 61] Connection refused"),
        ), patch(
            "protocol.lmstudio._loaded_entries_from_api",
            return_value=[{"identifier": "oracle-pro", "modelKey": "oracle-pro"}],
        ), patch("protocol.lmstudio.run_lms") as run_lms:
            request_name = ensure_model_loaded(
                alias="oracle-pro",
                model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                host="127.0.0.1",
                port=2234,
                auto_load=True,
            )

        self.assertEqual(request_name, "oracle-pro")
        run_lms.assert_not_called()

    def test_ensure_model_loaded_reports_hostd_outage_cleanly_when_model_is_not_loaded(self) -> None:
        with patch.dict(
            "os.environ",
            {"AFS_HOSTD_URL": "http://127.0.0.1:8765"},
            clear=False,
        ), patch(
            "protocol.lmstudio._hostd_request_json",
            side_effect=RuntimeError("afs-hostd request failed: [Errno 61] Connection refused"),
        ), patch(
            "protocol.lmstudio._loaded_entries_from_api",
            return_value=[],
        ), patch(
            "protocol.lmstudio._can_run_cli_fallback",
            return_value=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "restore the hostd tunnel"):
                ensure_model_loaded(
                    alias="oracle-pro",
                    model_id="gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                    host="127.0.0.1",
                    port=2234,
                    auto_load=True,
                )

    def test_loaded_request_name_accepts_identifier_equal_to_model_id(self) -> None:
        request_name = loaded_request_name(
            "oracle-pro",
            "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
            [{
                "identifier": "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf",
                "modelKey": "gguf/lmstudio/qwen3-oracle-14b-v7-q4km.gguf",
            }],
        )

        self.assertEqual(request_name, "gguf/zelda/qwen3-oracle-14b-v7-q4km.gguf")

    def test_loaded_request_name_matches_indexed_model_identifier(self) -> None:
        request_name = loaded_request_name(
            "oracle-pro",
            "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
            [{
                "identifier": "zelda",
                "modelKey": "gguf/lmstudio/qwen3-oracle-14b-v8-q4km.gguf",
                "indexedModelIdentifier": "gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
            }],
        )

        self.assertEqual(request_name, "zelda")

    def test_ensure_model_loaded_uses_remote_windows_inventory_for_fuzzy_match(self) -> None:
        def fake_remote_lms(command: list[str], *args, **kwargs) -> str:
            del args, kwargs
            encoded = command[2].split("EncodedCommand ", 1)[1]
            script = base64.b64decode(encoded).decode("utf-16le")
            if "$cliArgs = @('ps', '--json')" in script:
                return "[]\n"
            if "$cliArgs = @('ls', '--json')" in script:
                return "[{\"modelKey\": \"gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf\", \"displayName\": \"8B corrective Oracle · q4km\"}]\n"
            if "gguf/zelda/qwen3-oracle-8b-v1-corrective2-q4km.gguf" in script and "$cliArgs = @('load'" in script:
                return ""
            raise AssertionError(f"unexpected remote script:\n{script}")

        with patch.dict(
            "os.environ",
            {"Z3CLI_LMSTUDIO_REMOTE_HOST": "medical-mechanica"},
            clear=False,
        ), patch("subprocess.run") as run:
            run.side_effect = lambda *call_args, **call_kwargs: type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": fake_remote_lms(call_args[0]),
                    "stderr": "",
                },
            )()

            request_name = ensure_model_loaded(
                alias="oracle-fast",
                model_id="qwen3-oracle-8b-v1-corrective2-q4km",
                host="127.0.0.1",
                port=1234,
                auto_load=True,
            )

        self.assertEqual(request_name, "oracle-fast")
        self.assertEqual(run.call_count, 3)

    def test_studio_backend_resolves_remote_api_model_before_lms_load(self) -> None:
        backend = LMStudioBackend(api_base="http://127.0.0.1:2234/v1", host="127.0.0.1", port=1234)
        target = ModelConfig(
            name="oracle-pro",
            model_id="gguf/zelda/qwen3-oracle-14b-v8-q4km.gguf",
        )

        with patch.object(backend, "_openai_model_entries", return_value=[{
            "identifier": "gguf/lmstudio/qwen3-oracle-14b-v8-q4km.gguf",
            "modelKey": "gguf/lmstudio/qwen3-oracle-14b-v8-q4km.gguf",
        }]), patch("app.backends.ensure_model_loaded") as ensure:
            request_name = backend.resolve_request_model(target, auto_load=True)

        self.assertEqual(request_name, "gguf/lmstudio/qwen3-oracle-14b-v8-q4km.gguf")
        ensure.assert_not_called()


class LMStudioLoadAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_list_loaded_model_details_merges_estimates(self) -> None:
        backend = LMStudioBackend(api_base="http://127.0.0.1:1234/v1", host="127.0.0.1", port=1234)

        with patch("app.backends.available_models_async", return_value=[{
            "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            "sizeBytes": 9_527_501_152,
        }]), patch("app.backends.loaded_models_async", return_value=[{
            "identifier": "nayru",
            "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            "sizeBytes": 9_527_501_152,
            "contextLength": 262144,
        }]), patch("app.backends.estimate_model_memory_async", return_value={
            "estimated_gpu_bytes": int(9.95 * 1024 ** 3),
            "estimated_total_bytes": int(9.95 * 1024 ** 3),
        }):
            details = await backend.list_loaded_model_details()

        self.assertEqual(details[0]["identifier"], "nayru")
        self.assertEqual(details[0]["estimated_gpu_bytes"], int(9.95 * 1024 ** 3))


if __name__ == "__main__":
    unittest.main()
