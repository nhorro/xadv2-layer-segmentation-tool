from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from layer_segmentation.project import BackgroundProject
from layer_segmentation.workspace import discover_projects


class WorkspaceTests(unittest.TestCase):
    def test_discovers_only_initialized_scene_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "source.png"
            Image.fromarray(np.zeros((4, 6, 3), dtype=np.uint8)).save(source)
            BackgroundProject.create(workspace / "office", source)
            (workspace / "notes").mkdir()
            self.assertEqual(discover_projects(workspace), ["office"])

    def test_missing_workspace_is_empty(self):
        self.assertEqual(discover_projects(Path("/definitely/not/a/workspace")), [])


if __name__ == "__main__":
    unittest.main()
