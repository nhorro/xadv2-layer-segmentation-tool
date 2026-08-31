import unittest

import numpy as np
import torch
from torchvision import transforms

from layer_segmentation.model_catalog import model_from_config, model_from_key
from layer_segmentation.segmentation import RMBGSegmenter


class ModelCatalogTests(unittest.TestCase):
    def test_legacy_sam_alias_and_rmbg_config_resolve(self):
        self.assertEqual(model_from_key("large").key, "sam2-large")
        rmbg = model_from_config("rmbg", "rmbg-2.0")
        self.assertEqual(rmbg.label, "BRIA RMBG 2.0")
        self.assertFalse(rmbg.supports_points)


class _FakeRMBGModel(torch.nn.Module):
    def forward(self, input_tensor):
        height, width = input_tensor.shape[-2:]
        logits = torch.zeros((1, 1, height, width), device=input_tensor.device)
        logits[:, :, :, width // 2:] = 2.0
        return [logits]


class RMBGSegmenterTests(unittest.TestCase):
    def test_soft_alpha_is_mapped_only_inside_the_box(self):
        segmenter = object.__new__(RMBGSegmenter)
        segmenter.model = _FakeRMBGModel().eval()
        segmenter.transform = transforms.Compose(
            [transforms.Resize((8, 8)), transforms.ToTensor()]
        )
        segmenter.device = "cpu"
        segmenter.image = np.zeros((10, 12, 3), dtype=np.uint8)

        result = segmenter.segment(np.asarray([3.2, 2.2, 8.1, 7.1]))
        permitted = np.zeros((10, 12), dtype=bool)
        permitted[2:8, 3:9] = True
        self.assertFalse(np.any(result.alpha[~permitted]))
        self.assertGreater(len(np.unique(result.alpha[permitted])), 1)


if __name__ == "__main__":
    unittest.main()
