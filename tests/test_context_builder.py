import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_dev_council import context_builder


class TestIterSourceFiles(unittest.TestCase):
    def test_excludes_git_and_pycache_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hi')", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("x", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "app.cpython-312.pyc").write_text("x", encoding="utf-8")

            files = context_builder.iter_source_files(root)

        relative_paths = [p.relative_to(root).as_posix() for p in files]
        self.assertEqual(relative_paths, ["app.py"])

    def test_sorted_by_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.py").write_text("b", encoding="utf-8")
            (root / "a.py").write_text("a", encoding="utf-8")

            files = context_builder.iter_source_files(root)

        self.assertEqual([p.name for p in files], ["a.py", "b.py"])


class TestBuildCodeContext(unittest.TestCase):
    def test_includes_file_path_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('hello')", encoding="utf-8")

            context = context_builder.build_code_context(root)

        self.assertIn("app.py", context)
        self.assertIn("print('hello')", context)

    def test_truncates_when_exceeding_max_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "big.py").write_text("x" * 1000, encoding="utf-8")

            with_patch = context_builder._MAX_TOTAL_CHARS
            context_builder._MAX_TOTAL_CHARS = 10
            try:
                context = context_builder.build_code_context(root)
            finally:
                context_builder._MAX_TOTAL_CHARS = with_patch

        self.assertIn("上限", context)


class TestBuildTestResultsSummary(unittest.TestCase):
    def test_reports_success(self):
        summary = context_builder.build_test_results_summary(
            {"success": True, "subtype": "success", "result_text": "全テスト成功"}
        )
        self.assertIn("成功", summary)
        self.assertIn("全テスト成功", summary)

    def test_reports_failure_subtype(self):
        summary = context_builder.build_test_results_summary(
            {"success": False, "subtype": "error_max_turns", "result_text": "途中で終了"}
        )
        self.assertIn("error_max_turns", summary)


if __name__ == "__main__":
    unittest.main()
