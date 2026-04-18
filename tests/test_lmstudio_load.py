import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from z3cli.app.backends import LMStudioBackend
from z3cli.core.config import ModelConfig, load_registry
from z3cli.protocol.lmstudio import ensure_model_loaded, normalize_loaded_model_entry, parse_estimated_memory_output, unload_model


class LMStudioLoadTests(unittest.TestCase):
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
model_id = "gguf/zelda/switchhook-27b-v1-q4km.gguf"
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
model_id = "gguf/zelda/switchhook-27b-v1-q4km.gguf"
allow_auto_load = false
""".strip(),
                encoding="utf-8",
            )

            models, _routers = load_registry(registry_path)

            self.assertFalse(models["oracle"].allow_auto_load)

    def test_backend_forwards_model_load_profile(self) -> None:
        target = ModelConfig(
            name="oracle-main-plan",
            model_id="gguf/zelda/switchhook-27b-v1-q4km.gguf",
            provider="studio",
            lmstudio_context_length=2048,
            lmstudio_parallel=1,
            lmstudio_gpu="0.80",
            lmstudio_ttl=900,
        )

        backend = LMStudioBackend(api_base="http://127.0.0.1:1234/v1", host="127.0.0.1", port=1234)

        with patch("z3cli.app.backends.ensure_model_loaded", return_value=target.name) as ensure:
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
        with patch("z3cli.protocol.lmstudio.loaded_models", return_value=[]), patch(
            "z3cli.protocol.lmstudio.run_lms",
        ) as run_lms:
            with self.assertRaisesRegex(RuntimeError, "skip automatic LM Studio loads"):
                ensure_model_loaded(
                    alias="oracle",
                    model_id="gguf/zelda/switchhook-27b-v1-q4km.gguf",
                    host="127.0.0.1",
                    port=1234,
                    auto_load=True,
                    allow_auto_load=False,
                )

        run_lms.assert_not_called()

    def test_ensure_model_loaded_manual_load_overrides_manual_only_guard(self) -> None:
        with patch("z3cli.protocol.lmstudio.loaded_models", return_value=[]), patch(
            "z3cli.protocol.lmstudio.run_lms",
            return_value="",
        ) as run_lms:
            request_name = ensure_model_loaded(
                alias="oracle",
                model_id="gguf/zelda/switchhook-27b-v1-q4km.gguf",
                host="127.0.0.1",
                port=1234,
                auto_load=True,
                allow_auto_load=False,
                manual_load=True,
            )

        self.assertEqual(request_name, "oracle")
        run_lms.assert_called_once()

    def test_unload_model_uses_loaded_identifier(self) -> None:
        with patch("z3cli.protocol.lmstudio.loaded_models", return_value=[
            {
                "identifier": "nayru",
                "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            },
        ]), patch("z3cli.protocol.lmstudio.run_lms", return_value="") as run_lms:
            result = unload_model("127.0.0.1", 1234, "gguf/zelda/nayru-9b-q8_0.gguf")

        self.assertEqual(result, {"all": False, "unloaded": ["nayru"]})
        run_lms.assert_called_once_with(
            ["unload", "nayru"],
            "127.0.0.1",
            1234,
            timeout=60.0,
        )


class LMStudioLoadAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_list_loaded_model_details_merges_estimates(self) -> None:
        backend = LMStudioBackend(api_base="http://127.0.0.1:1234/v1", host="127.0.0.1", port=1234)

        with patch("z3cli.app.backends.available_models_async", return_value=[{
            "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            "sizeBytes": 9_527_501_152,
        }]), patch("z3cli.app.backends.loaded_models_async", return_value=[{
            "identifier": "nayru",
            "modelKey": "gguf/zelda/nayru-9b-q8_0.gguf",
            "sizeBytes": 9_527_501_152,
            "contextLength": 262144,
        }]), patch("z3cli.app.backends.estimate_model_memory_async", return_value={
            "estimated_gpu_bytes": int(9.95 * 1024 ** 3),
            "estimated_total_bytes": int(9.95 * 1024 ** 3),
        }):
            details = await backend.list_loaded_model_details()

        self.assertEqual(details[0]["identifier"], "nayru")
        self.assertEqual(details[0]["estimated_gpu_bytes"], int(9.95 * 1024 ** 3))


if __name__ == "__main__":
    unittest.main()
