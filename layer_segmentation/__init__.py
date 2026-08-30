"""Core project and alpha-processing support for the XADV2 layer tool."""

from .alpha import apply_edge_cleanup, clip_to_box, compose_alpha, crop_rect, paint_alpha_disk
from .project import BackgroundProject, LayerState, ProjectError, slugify

__all__ = [
    "BackgroundProject",
    "LayerState",
    "ProjectError",
    "apply_edge_cleanup",
    "clip_to_box",
    "compose_alpha",
    "crop_rect",
    "paint_alpha_disk",
    "slugify",
]
