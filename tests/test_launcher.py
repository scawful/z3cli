import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.launcher import (
    build_ink_frontend_command,
    first_positional_arg,
    is_backend_only_invocation,
    repo_root_from_app_file,
    strip_legacy_repl_flag,
)


class LauncherPolicyTests(unittest.TestCase):
    def test_plain_invocation_uses_ink(self) -> None:
        self.assertFalse(is_backend_only_invocation([]))
        self.assertFalse(is_backend_only_invocation(["--model", "oracle", "--mode", "oracle"]))

    def test_control_commands_stay_on_backend_path(self) -> None:
        self.assertTrue(is_backend_only_invocation(["route", "list"]))
        self.assertTrue(is_backend_only_invocation(["models", "catalog"]))
        self.assertTrue(is_backend_only_invocation(["--registry", "config.toml", "route", "smoke", "oracle"]))
        self.assertTrue(is_backend_only_invocation(["--api-base", "http://127.0.0.1:1234/v1", "route", "list"]))

    def test_one_shot_backend_flags_stay_on_backend_path(self) -> None:
        self.assertTrue(is_backend_only_invocation(["--prompt", "hello"]))
        self.assertTrue(is_backend_only_invocation(["--prompt=hello"]))
        self.assertTrue(is_backend_only_invocation(["--status"]))
        self.assertTrue(is_backend_only_invocation(["--smoke", "oracle-pro"]))

    def test_frontend_resume_is_not_mistaken_for_control_command(self) -> None:
        self.assertEqual(first_positional_arg(["--resume", "last"]), "")
        self.assertFalse(is_backend_only_invocation(["--resume", "last"]))

    def test_legacy_flag_is_removed_and_reported(self) -> None:
        argv, legacy = strip_legacy_repl_flag(["--model", "oracle", "--legacy-repl"])
        self.assertTrue(legacy)
        self.assertEqual(argv, ["--model", "oracle"])

    def test_frontend_command_prefers_built_dist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist = root / "frontend" / "dist" / "index.js"
            dist.parent.mkdir(parents=True)
            dist.write_text("#!/usr/bin/env node\n", encoding="utf-8")

            self.assertEqual(
                build_ink_frontend_command(root, ["--model", "oracle"]),
                ["node", str(dist), "--model", "oracle"],
            )

    def test_frontend_command_uses_local_tsx_during_checkout_development(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tsx = root / "frontend" / "node_modules" / ".bin" / "tsx"
            source = root / "frontend" / "src" / "index.tsx"
            tsx.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            tsx.write_text("", encoding="utf-8")
            source.write_text("", encoding="utf-8")

            self.assertEqual(
                build_ink_frontend_command(root, ["--resume", "last"]),
                [str(tsx), str(source), "--resume", "last"],
            )

    def test_repo_root_finds_checkout_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_file = root / "src" / "app" / "__main__.py"
            package = root / "frontend" / "package.json"
            app_file.parent.mkdir(parents=True)
            package.parent.mkdir(parents=True)
            app_file.write_text("", encoding="utf-8")
            package.write_text("{}", encoding="utf-8")

            self.assertEqual(repo_root_from_app_file(app_file), root.resolve())

    def test_repo_root_can_use_checkout_cwd_for_installed_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            checkout = temp_root / "checkout"
            package = checkout / "frontend" / "package.json"
            package.parent.mkdir(parents=True)
            package.write_text("{}", encoding="utf-8")

            installed_app = temp_root / "site-packages" / "app" / "__main__.py"
            installed_app.parent.mkdir(parents=True)
            installed_app.write_text("", encoding="utf-8")

            old_cwd = Path.cwd()
            try:
                os.chdir(checkout)
                self.assertEqual(repo_root_from_app_file(installed_app), checkout.resolve())
            finally:
                os.chdir(old_cwd)

    def test_repo_root_respects_explicit_repo_root_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "frontend" / "package.json"
            package.parent.mkdir(parents=True)
            package.write_text("{}", encoding="utf-8")

            app_file = root / "elsewhere" / "app" / "__main__.py"
            app_file.parent.mkdir(parents=True)
            app_file.write_text("", encoding="utf-8")

            with patch.dict(os.environ, {"Z3CLI_REPO_ROOT": str(root)}):
                self.assertEqual(repo_root_from_app_file(app_file), root.resolve())


if __name__ == "__main__":
    unittest.main()
