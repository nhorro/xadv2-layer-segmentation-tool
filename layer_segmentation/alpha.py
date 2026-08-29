from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter


def compose_alpha(
    sam_mask: np.ndarray | None,
    manual_alpha: np.ndarray | None,
) -> np.ndarray | None:
    """Compose a SAM mask and tri-state manual overrides into uint8 alpha."""
    if sam_mask is None:
        return None

    if sam_mask.dtype == np.bool_:
        alpha = sam_mask.astype(np.uint8) * 255
    else:
        alpha = np.asarray(sam_mask)
        if np.issubdtype(alpha.dtype, np.floating) and alpha.max(initial=0) <= 1:
            alpha = alpha * 255
        alpha = alpha.clip(0, 255).astype(np.uint8)

    if manual_alpha is not None:
        overridden = manual_alpha >= 0
        alpha = alpha.copy()
        alpha[overridden] = manual_alpha[overridden].clip(0, 255).astype(np.uint8)

    return alpha


def apply_edge_cleanup(
    alpha: np.ndarray,
    erode_px: int = 0,
    feather_px: float = 0,
) -> np.ndarray:
    """Apply reversible edge cleanup to a composed alpha mask.

    Erosion removes contaminated edge pixels; feathering then softens only the
    resulting transition. The input array is never modified.
    """
    erode_px = max(0, int(erode_px))
    feather_px = max(0.0, float(feather_px))
    image = Image.fromarray(np.asarray(alpha, dtype=np.uint8), mode="L")

    if erode_px:
        image = image.filter(ImageFilter.MinFilter(erode_px * 2 + 1))
    if feather_px:
        image = image.filter(ImageFilter.GaussianBlur(radius=feather_px))

    return np.asarray(image, dtype=np.uint8)


def crop_rect(
    alpha: np.ndarray,
    threshold: int = 10,
    margin: int = 2,
) -> tuple[int, int, int, int]:
    """Return an in-bounds (x, y, width, height) alpha crop rectangle."""
    alpha = np.asarray(alpha)
    height, width = alpha.shape[:2]
    ys, xs = np.nonzero(alpha > max(0, min(255, int(threshold))))
    if not len(xs):
        return (0, 0, 0, 0)

    margin = max(0, int(margin))
    x0 = max(0, int(xs.min()) - margin)
    y0 = max(0, int(ys.min()) - margin)
    x1 = min(width, int(xs.max()) + 1 + margin)
    y1 = min(height, int(ys.max()) + 1 + margin)
    return (x0, y0, x1 - x0, y1 - y0)


def paint_alpha_disk(
    base_alpha: np.ndarray,
    manual_alpha: np.ndarray,
    x: float,
    y: float,
    radius: int,
    feather_px: float,
    target_alpha: int,
) -> tuple[int, int, int, int]:
    """Paint one anti-aliased alpha dab into a tri-state override buffer.

    Pixels without an override use ``base_alpha`` as their starting value.
    ``feather_px`` is the width of the linear falloff inside the brush radius.
    The returned rectangle is the modified source-space region.
    """
    base_alpha = np.asarray(base_alpha, dtype=np.uint8)
    if manual_alpha.shape != base_alpha.shape:
        raise ValueError("manual_alpha and base_alpha must have the same shape")

    height, width = base_alpha.shape
    radius = max(1, int(radius))
    feather_px = max(0.0, min(float(radius), float(feather_px)))
    target_alpha = max(0, min(255, int(target_alpha)))
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = max(0, cx - radius), min(width, cx + radius + 1)
    y0, y1 = max(0, cy - radius), min(height, cy + radius + 1)

    yy, xx = np.ogrid[y0:y1, x0:x1]
    distance = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    if feather_px == 0:
        weight = (distance <= radius).astype(np.float32)
    else:
        weight = np.clip((radius - distance) / feather_px, 0.0, 1.0).astype(np.float32)

    region = manual_alpha[y0:y1, x0:x1]
    base_region = base_alpha[y0:y1, x0:x1]
    current = np.where(region >= 0, region, base_region).astype(np.float32)
    painted = np.rint(current + (target_alpha - current) * weight).astype(np.int16)
    affected = weight > 0
    region[affected] = painted[affected]
    return (x0, y0, x1 - x0, y1 - y0)
