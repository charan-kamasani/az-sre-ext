import os
from pathlib import Path
import tempfile
import unittest

from scripts.generate_sre_extension import remove_tree


class RemoveTreeTests(unittest.TestCase):
    def test_removes_paths_longer_than_windows_limit(self):
        root = Path(tempfile.mkdtemp())
        deep = os.path.join(str(root), *(["d" * 40] * 8))
        if os.name == "nt":
            deep = "\\\\?\\" + deep
        os.makedirs(deep)
        with open(os.path.join(deep, "f.txt"), "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertGreater(len(deep), 260)

        remove_tree(root)

        self.assertFalse(root.exists())

    def test_missing_path_is_ignored(self):
        remove_tree(Path(tempfile.gettempdir()) / "sre-remove-tree-does-not-exist")


if __name__ == "__main__":
    unittest.main()
