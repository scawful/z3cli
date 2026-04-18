import json
import tempfile
import unittest
from pathlib import Path

from z3cli.app.write_review import (
    build_review_preview,
    detect_changes,
    prepare_write_context,
    restore_write_context,
)


class WriteReviewTests(unittest.TestCase):
    def test_prepare_detect_preview_and_restore_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            target = workspace / "src" / "main.asm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("lda #$01\n", encoding="utf-8")

            context = prepare_write_context(
                workspace,
                "edit_file",
                '{"path":"src/main.asm","edits":[{"oldText":"lda #$01\\n","newText":"lda #$02\\n"}]}',
                "call-1",
            )
            self.assertIsNotNone(context)

            target.write_text("lda #$02\n", encoding="utf-8")

            assert context is not None
            changes = detect_changes(context)
            self.assertEqual(len(changes), 1)
            preview = build_review_preview(workspace, "review-1", changes)
            self.assertIsNotNone(preview)
            assert preview is not None
            self.assertIn("src/main.asm", preview.summary)
            self.assertTrue(any(line.startswith("-lda #$01") for line in preview.diff_lines))
            self.assertTrue(any(line.startswith("+lda #$02") for line in preview.diff_lines))

            restore_write_context(context)
            self.assertEqual(target.read_text(encoding="utf-8"), "lda #$01\n")

    def test_restore_removes_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            context = prepare_write_context(
                workspace,
                "write_file",
                '{"path":"notes.txt","content":"hello"}',
                "call-2",
            )
            self.assertIsNotNone(context)

            created = workspace / "notes.txt"
            created.write_text("hello", encoding="utf-8")

            assert context is not None
            changes = detect_changes(context)
            self.assertEqual(changes[0].status, "added")

            restore_write_context(context)
            self.assertFalse(created.exists())

    def test_restore_handles_more_than_twelve_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            paths = []
            for idx in range(13):
                target = workspace / "src" / f"file_{idx}.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"before-{idx}\n", encoding="utf-8")
                paths.append(str(target.relative_to(workspace)))

            context = prepare_write_context(
                workspace,
                "apply_patch",
                json.dumps({"paths": paths, "content": "updated"}),
                "call-many",
            )
            self.assertIsNotNone(context)
            assert context is not None
            self.assertEqual(len(context.files), 13)

            for idx in range(13):
                (workspace / "src" / f"file_{idx}.txt").write_text(f"after-{idx}\n", encoding="utf-8")

            changes = detect_changes(context)
            self.assertEqual(len(changes), 13)

            restore_write_context(context)

            for idx in range(13):
                restored = (workspace / "src" / f"file_{idx}.txt").read_text(encoding="utf-8")
                self.assertEqual(restored, f"before-{idx}\n")


if __name__ == "__main__":
    unittest.main()
