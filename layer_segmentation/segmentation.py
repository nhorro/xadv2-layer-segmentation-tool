"""Segmentation backends with a small common interface for the editor."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image

from .model_catalog import ModelSpec


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SAM2_REPO = PACKAGE_ROOT / "sam2"
RMBG_REPOSITORY = "briaai/RMBG-2.0"
# RMBG loads executable repository code with trust_remote_code=True. Pinning the
# reviewed upstream revision makes that behavior reproducible.
RMBG_REVISION = "5df4c9c76d8170882c34f6986e848ee07fd0ba43"

SAM2_PRESETS = {
    "tiny": {
        "config": "configs/sam2.1/sam2.1_hiera_t.yaml",
        "checkpoint": SAM2_REPO / "checkpoints" / "sam2.1_hiera_tiny.pt",
    },
    "small": {
        "config": "configs/sam2.1/sam2.1_hiera_s.yaml",
        "checkpoint": SAM2_REPO / "checkpoints" / "sam2.1_hiera_small.pt",
    },
    "base_plus": {
        "config": "configs/sam2.1/sam2.1_hiera_b+.yaml",
        "checkpoint": SAM2_REPO / "checkpoints" / "sam2.1_hiera_base_plus.pt",
    },
    "large": {
        "config": "configs/sam2.1/sam2.1_hiera_l.yaml",
        "checkpoint": SAM2_REPO / "checkpoints" / "sam2.1_hiera_large.pt",
    },
}


@dataclass
class SegmentationResult:
    alpha: np.ndarray
    score: float | None = None
    state: Any = None


class SAM2Segmenter:
    supports_points = True

    def __init__(self, model_name: str, device: str, image: np.ndarray):
        import sys

        if str(PACKAGE_ROOT) not in sys.path:
            sys.path.insert(0, str(PACKAGE_ROOT))
        if str(SAM2_REPO) not in sys.path:
            sys.path.insert(0, str(SAM2_REPO))

        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        preset = SAM2_PRESETS[model_name]
        checkpoint = Path(preset["checkpoint"])
        if not checkpoint.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")

        model = build_sam2(preset["config"], str(checkpoint), device=device)
        self.predictor = SAM2ImagePredictor(model)
        self.device = device
        with torch.inference_mode(), self._autocast():
            self.predictor.set_image(image)

    def _autocast(self):
        if self.device == "cuda":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            return torch.autocast("cuda", dtype=dtype)
        return nullcontext()

    def segment(
        self,
        box: np.ndarray,
        points: np.ndarray | None = None,
        labels: np.ndarray | None = None,
        state: Any = None,
    ) -> SegmentationResult:
        has_points = points is not None and len(points) > 0
        with torch.inference_mode(), self._autocast():
            masks, scores, logits = self.predictor.predict(
                point_coords=points if has_points else None,
                point_labels=labels if has_points else None,
                box=box,
                mask_input=state if has_points else None,
                multimask_output=not has_points,
            )
        best = int(np.argmax(scores))
        return SegmentationResult(
            alpha=masks[best],
            score=float(scores[best]),
            state=logits[best:best + 1],
        )


class RMBGSegmenter:
    """Prompt-free foreground matting applied inside the author's box."""

    supports_points = False
    input_size = (1024, 1024)

    def __init__(self, _model_name: str, device: str, image: np.ndarray):
        try:
            from transformers import AutoModelForImageSegmentation
        except ImportError as exc:
            raise RuntimeError(
                "RMBG-2.0 requires the 'transformers' and 'kornia' packages. "
                "Install the project requirements again."
            ) from exc

        try:
            model = AutoModelForImageSegmentation.from_pretrained(
                RMBG_REPOSITORY,
                revision=RMBG_REVISION,
                trust_remote_code=True,
                use_safetensors=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not download/load RMBG-2.0. Its weights are gated: Accept the terms at "
                "https://huggingface.co/briaai/RMBG-2.0 and authenticate locally "
                "with `hf auth login`, then reopen the scene. Original error: "
                f"{exc}"
            ) from exc
        try:
            self.model = model.eval().to(device)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Could not place RMBG-2.0 on {device}. Try another device or close "
                f"other GPU applications. Original error: {exc}"
            ) from exc

        from torchvision import transforms

        self.transform = transforms.Compose(
            [
                transforms.Resize(self.input_size),
                transforms.ToTensor(),
                transforms.Normalize(
                    [0.485, 0.456, 0.406],
                    [0.229, 0.224, 0.225],
                ),
            ]
        )
        self.device = device
        self.image = np.asarray(image, dtype=np.uint8)
        if device == "cuda":
            torch.set_float32_matmul_precision("high")

    def _autocast(self):
        if self.device == "cuda":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            return torch.autocast("cuda", dtype=dtype)
        return nullcontext()

    def segment(
        self,
        box: np.ndarray,
        points: np.ndarray | None = None,
        labels: np.ndarray | None = None,
        state: Any = None,
    ) -> SegmentationResult:
        del points, labels, state
        height, width = self.image.shape[:2]
        x0, y0, x1, y1 = (float(value) for value in box)
        left = max(0, min(width, int(np.floor(min(x0, x1)))))
        top = max(0, min(height, int(np.floor(min(y0, y1)))))
        right = max(0, min(width, int(np.ceil(max(x0, x1)))))
        bottom = max(0, min(height, int(np.ceil(max(y0, y1)))))
        if right <= left or bottom <= top:
            return SegmentationResult(np.zeros((height, width), dtype=np.uint8))

        crop = Image.fromarray(self.image[top:bottom, left:right], mode="RGB")
        input_tensor = self.transform(crop).unsqueeze(0).to(self.device)
        with torch.inference_mode(), self._autocast():
            prediction = self.model(input_tensor)[-1].sigmoid()
        prediction = torch.nn.functional.interpolate(
            prediction.float(),
            size=(bottom - top, right - left),
            mode="bilinear",
            align_corners=False,
        )[0, 0]
        crop_alpha = (
            prediction.clamp(0, 1).mul(255).round().to(torch.uint8).cpu().numpy()
        )
        alpha = np.zeros((height, width), dtype=np.uint8)
        alpha[top:bottom, left:right] = crop_alpha
        return SegmentationResult(alpha=alpha)


def load_segmenter(spec: ModelSpec, device: str, image: np.ndarray):
    if spec.backend == "sam2":
        return SAM2Segmenter(spec.model, device, image)
    if spec.backend == "rmbg":
        return RMBGSegmenter(spec.model, device, image)
    raise ValueError(f"Unsupported segmentation backend: {spec.backend}")
