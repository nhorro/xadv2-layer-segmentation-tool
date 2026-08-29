import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from layer_segmentation.project import BackgroundProject, LayerState


class ProjectTests(unittest.TestCase):
    def test_create_can_adopt_a_nonempty_scene_directory_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scene = root / "office"
            legacy = scene / "original"
            legacy.mkdir(parents=True)
            source = legacy / "office.png"
            Image.fromarray(np.zeros((4, 5, 3), dtype=np.uint8), mode="RGB").save(source)
            project = BackgroundProject.create(scene, source)
            self.assertTrue(project.project_file.is_file())
            self.assertTrue(source.is_file())

    def test_project_round_trip_and_registered_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.png"
            rgb = np.zeros((6, 8, 3), dtype=np.uint8)
            rgb[..., 1] = 120
            Image.fromarray(rgb, mode="RGB").save(source)

            project = BackgroundProject.create(root / "scene", source, name="Scene")
            mask = np.zeros((6, 8), dtype=bool)
            mask[2:5, 3:7] = True
            manual = np.full((6, 8), -1, dtype=np.int16)
            manual[2, 3] = 0
            project.layers.append(
                LayerState(
                    name="Front Desk", role="occluder", z=20,
                    box=np.array([3, 2, 7, 5], dtype=np.float32),
                    base_mask=mask, manual_alpha=manual,
                )
            )
            project.save()

            loaded = BackgroundProject.load(project.root)
            self.assertEqual(loaded.layers[0].role, "occluder")
            self.assertEqual(int(loaded.layers[0].manual_alpha[2, 3]), 0)
            stale = loaded.root / "export" / "layers" / "removed-layer.png"
            stale.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.zeros((1, 1, 4), dtype=np.uint8), mode="RGBA").save(stale)
            loaded.export_all(rgb)
            self.assertFalse(stale.exists())

            recomposed = loaded.composed_rgba(rgb)
            np.testing.assert_array_equal(recomposed[..., :3], rgb)
            np.testing.assert_array_equal(recomposed[..., 3], np.full((6, 8), 255))

            manifest = yaml.safe_load(
                (project.root / "export" / "scene-layers.yml").read_text()
            )
            rect = manifest["layers"][0]["source_rect"]
            self.assertEqual(rect, {"x": 1, "y": 0, "width": 7, "height": 6})
            self.assertEqual(
                manifest["layers"][0]["anchors"]["canvas_origin"], {"x": -1, "y": 0}
            )
            with Image.open(project.root / "export" / "base.png") as base_image:
                reconstructed = base_image.convert("RGBA")
            for exported_layer in manifest["layers"]:
                with Image.open(project.root / "export" / exported_layer["image"]) as image:
                    layer_image = image.convert("RGBA")
                source_rect = exported_layer["source_rect"]
                reconstructed.alpha_composite(
                    layer_image, dest=(source_rect["x"], source_rect["y"])
                )
            np.testing.assert_array_equal(np.asarray(reconstructed)[..., :3], rgb)
            np.testing.assert_array_equal(
                np.asarray(reconstructed)[..., 3], np.full((6, 8), 255)
            )

    def test_export_reconstructs_when_crop_threshold_discards_feather_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.png"
            rgb = np.full((30, 30, 3), [25, 100, 180], dtype=np.uint8)
            Image.fromarray(rgb, mode="RGB").save(source)
            project = BackgroundProject.create(root / "scene", source)
            project.crop_threshold = 100
            mask = np.zeros((30, 30), dtype=bool)
            mask[10:20, 10:20] = True
            project.layers.append(
                LayerState(
                    name="soft", base_mask=mask, feather_px=3,
                    manual_alpha=np.full((30, 30), -1, dtype=np.int16),
                )
            )
            project.export_all(rgb)
            manifest = yaml.safe_load(
                (project.root / "export" / "scene-layers.yml").read_text()
            )
            with Image.open(project.root / "export" / "base.png") as base:
                reconstructed = base.convert("RGBA")
            entry = manifest["layers"][0]
            with Image.open(project.root / "export" / entry["image"]) as image:
                rect = entry["source_rect"]
                reconstructed.alpha_composite(image.convert("RGBA"), dest=(rect["x"], rect["y"]))
            np.testing.assert_array_equal(np.asarray(reconstructed)[..., :3], rgb)
            np.testing.assert_array_equal(
                np.asarray(reconstructed)[..., 3], np.full((30, 30), 255)
            )


if __name__ == "__main__":
    unittest.main()
