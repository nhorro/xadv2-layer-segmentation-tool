from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from .alpha import apply_edge_cleanup, clip_to_box, compose_alpha, crop_rect
from .model_catalog import model_from_config


PROJECT_VERSION = 1
ROLES = ("occluder", "obstacle", "foreground", "animated-prop", "other")


class ProjectError(RuntimeError):
    pass


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    return value.strip("-.") or "layer"


@dataclass
class LayerState:
    name: str
    role: str = "other"
    z: int = 0
    box: np.ndarray | None = None
    points: list[list[float]] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    base_mask: np.ndarray | None = None
    mask_input: np.ndarray | None = None
    score: float | None = None
    manual_alpha: np.ndarray | None = None
    erode_px: int = 0
    feather_px: float = 0.0
    crop_rect: tuple[int, int, int, int] | None = None


class BackgroundProject:
    """Filesystem-backed authoring project independent of the Tk UI."""

    def __init__(
        self,
        root: Path,
        name: str,
        source_image: Path,
        width: int,
        height: int,
        backend: str = "sam2",
        model: str = "small",
        crop_threshold: int = 10,
        crop_margin: int = 2,
        layers: list[LayerState] | None = None,
    ):
        self.root = root.resolve()
        self.name = name
        self.source_image = source_image.resolve()
        self.width = int(width)
        self.height = int(height)
        self.backend = backend
        self.model = model
        self.crop_threshold = int(crop_threshold)
        self.crop_margin = int(crop_margin)
        self.layers = layers or []

    @property
    def project_file(self) -> Path:
        return self.root / "project.yml"

    @classmethod
    def create(
        cls,
        root: Path,
        input_image: Path,
        name: str | None = None,
        backend: str = "sam2",
        model: str = "small",
    ) -> "BackgroundProject":
        try:
            model_from_config(backend, model)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        root = root.resolve()
        input_image = input_image.resolve()
        if not input_image.is_file():
            raise ProjectError(f"Source image not found: {input_image}")
        if (root / "project.yml").exists():
            raise ProjectError(f"Project already exists: {root}")
        for relative in ("source", "layers", "work/cropped", "export/layers"):
            (root / relative).mkdir(parents=True, exist_ok=True)

        original = root / "source" / f"original{input_image.suffix.lower()}"
        canonical = root / "source" / "background.png"
        if original.exists() or canonical.exists():
            raise ProjectError(
                f"Refusing to overwrite existing source artifacts in {root / 'source'}"
            )
        shutil.copy2(input_image, original)

        with Image.open(input_image) as source:
            rgb = source.convert("RGB")
            width, height = rgb.size
            rgb.save(canonical)

        project = cls(
            root=root,
            name=name or input_image.stem,
            source_image=canonical,
            width=width,
            height=height,
            backend=backend,
            model=model,
        )
        project.save()
        return project

    @classmethod
    def load(cls, root: Path) -> "BackgroundProject":
        root = root.resolve()
        project_file = root / "project.yml"
        if not project_file.is_file():
            raise ProjectError(f"Not an XADV2 background project: {root}")

        data = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
        if data.get("version") != PROJECT_VERSION:
            raise ProjectError(f"Unsupported project version: {data.get('version')}")

        source_data = data.get("source", {})
        source_image = root / source_data.get("image", "source/background.png")
        if not source_image.is_file():
            raise ProjectError(f"Project source image is missing: {source_image}")

        crop = data.get("crop", {})
        segmentation = data.get("segmentation", {})
        backend = str(segmentation.get("backend", "sam2"))
        model = str(segmentation.get("model", "small"))
        try:
            model_from_config(backend, model)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        project = cls(
            root=root,
            name=str(data.get("name") or root.name),
            source_image=source_image,
            width=int(source_data.get("width", 0)),
            height=int(source_data.get("height", 0)),
            backend=backend,
            model=model,
            crop_threshold=int(crop.get("alpha_threshold", 10)),
            crop_margin=int(crop.get("margin", 2)),
        )
        with Image.open(source_image) as source:
            actual_size = source.size
        if actual_size != (project.width, project.height):
            raise ProjectError(
                "Source dimensions do not match project.yml: "
                f"expected {project.width}x{project.height}, got {actual_size[0]}x{actual_size[1]}"
            )

        for key, layer_data in (data.get("layers") or {}).items():
            if str(key) != slugify(str(key)):
                raise ProjectError(f"Unsafe layer key in project.yml: {key}")
            display_name = str(layer_data.get("name") or key)
            points_data = layer_data.get("points") or []
            layer = LayerState(
                name=display_name,
                role=str(layer_data.get("role", "other")),
                z=int(layer_data.get("z", 0)),
                box=(
                    np.asarray(layer_data["box"], dtype=np.float32)
                    if layer_data.get("box") is not None
                    else None
                ),
                points=[[float(p["x"]), float(p["y"])] for p in points_data],
                labels=[int(p["label"]) for p in points_data],
                score=layer_data.get("score"),
                erode_px=int(layer_data.get("edge_cleanup", {}).get("erode_px", 0)),
                feather_px=float(layer_data.get("edge_cleanup", {}).get("feather_px", 0)),
            )
            rect = layer_data.get("crop_rect")
            if rect:
                layer.crop_rect = (
                    int(rect["x"]), int(rect["y"]),
                    int(rect["width"]), int(rect["height"]),
                )
            project._load_layer_artifacts(layer, key)
            project.layers.append(layer)

        project.validate_unique_names()
        return project

    def _load_layer_artifacts(self, layer: LayerState, key: str) -> None:
        layer_dir = self.root / "layers" / key
        sam_path = layer_dir / "sam-mask.png"
        if sam_path.is_file():
            with Image.open(sam_path) as sam_image:
                # SAM masks are binary, while RMBG produces a soft alpha matte.
                # Keep the grayscale values so either backend round-trips.
                loaded_mask = np.asarray(sam_image.convert("L"), dtype=np.uint8)
                layer.base_mask = clip_to_box(loaded_mask, layer.box)
            self._validate_artifact_shape(layer.base_mask, sam_path)

        manual_path = layer_dir / "manual-alpha.png"
        if manual_path.is_file():
            layer.manual_alpha = np.full((self.height, self.width), -1, dtype=np.int16)
            with Image.open(manual_path) as manual_image:
                if manual_image.mode == "LA":
                    value, present = np.asarray(manual_image).transpose(2, 0, 1)
                    self._validate_artifact_shape(value, manual_path)
                    layer.manual_alpha[present > 0] = value[present > 0]
                else:
                    # Compatibility with the prototype's grayscale encoding,
                    # where 128 meant "no override".
                    value = np.asarray(manual_image.convert("L"))
                    self._validate_artifact_shape(value, manual_path)
                    overridden = value != 128
                    layer.manual_alpha[overridden] = value[overridden]
        else:
            layer.manual_alpha = np.full((self.height, self.width), -1, dtype=np.int16)

    def _validate_artifact_shape(self, artifact: np.ndarray, path: Path) -> None:
        if artifact.shape[:2] != (self.height, self.width):
            raise ProjectError(
                f"Artifact dimensions do not match the source canvas: {path}"
            )

    def layer_key(self, layer: LayerState) -> str:
        return slugify(layer.name)

    def validate_unique_names(self) -> None:
        keys = [self.layer_key(layer) for layer in self.layers]
        if len(keys) != len(set(keys)):
            raise ProjectError("Layer names must remain unique after filename normalization")

    def save(self, save_artifacts: bool = True) -> None:
        try:
            model_from_config(self.backend, self.model)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        self.validate_unique_names()
        self.project_file.parent.mkdir(parents=True, exist_ok=True)
        if save_artifacts:
            for layer in self.layers:
                self._save_layer_authoring(layer)

        layers = {}
        for layer in self.layers:
            item = {
                "name": layer.name,
                "role": layer.role,
                "z": int(layer.z),
                "box": layer.box.tolist() if layer.box is not None else None,
                "points": [
                    {"x": float(x), "y": float(y), "label": int(label)}
                    for (x, y), label in zip(layer.points, layer.labels)
                ],
                "score": float(layer.score) if layer.score is not None else None,
                "edge_cleanup": {
                    "erode_px": int(layer.erode_px),
                    "feather_px": float(layer.feather_px),
                },
            }
            if layer.crop_rect is not None:
                x, y, width, height = layer.crop_rect
                item["crop_rect"] = {"x": x, "y": y, "width": width, "height": height}
            layers[self.layer_key(layer)] = item

        data = {
            "version": PROJECT_VERSION,
            "name": self.name,
            "source": {
                "image": self.source_image.relative_to(self.root).as_posix(),
                "width": self.width,
                "height": self.height,
            },
            "segmentation": {"backend": self.backend, "model": self.model},
            "crop": {
                "alpha_threshold": self.crop_threshold,
                "margin": self.crop_margin,
            },
            "layers": layers,
            "anchors": {"canvas_origin": {"x": 0, "y": 0}},
        }
        temporary = self.project_file.with_suffix(".yml.tmp")
        temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        temporary.replace(self.project_file)

    def _save_layer_authoring(self, layer: LayerState) -> None:
        layer_dir = self.root / "layers" / self.layer_key(layer)
        layer_dir.mkdir(parents=True, exist_ok=True)
        if layer.base_mask is not None:
            layer.base_mask = clip_to_box(layer.base_mask, layer.box)
            sam_alpha = compose_alpha(layer.base_mask, None)
            Image.fromarray(sam_alpha, mode="L").save(layer_dir / "sam-mask.png")

        if layer.manual_alpha is not None:
            values = layer.manual_alpha.clip(0, 255).astype(np.uint8)
            present = (layer.manual_alpha >= 0).astype(np.uint8) * 255
            Image.merge(
                "LA", (Image.fromarray(values, mode="L"), Image.fromarray(present, mode="L"))
            ).save(layer_dir / "manual-alpha.png")

        session = {
            "name": layer.name,
            "backend": self.backend,
            "model": self.model,
            "box": layer.box.tolist() if layer.box is not None else None,
            "points": [
                {"x": float(x), "y": float(y), "label": int(label)}
                for (x, y), label in zip(layer.points, layer.labels)
            ],
            "score": layer.score,
        }
        (layer_dir / "session.json").write_text(
            json.dumps(session, indent=2) + "\n", encoding="utf-8"
        )

    def final_alpha(self, layer: LayerState, cleanup: bool = True) -> np.ndarray | None:
        alpha = compose_alpha(layer.base_mask, layer.manual_alpha)
        if alpha is not None:
            alpha = clip_to_box(alpha, layer.box)
            if cleanup:
                alpha = apply_edge_cleanup(alpha, layer.erode_px, layer.feather_px)
                # Feathering is allowed to soften the inner edge but never to
                # expand the hard authoring scope selected by the box.
                alpha = clip_to_box(alpha, layer.box)
        return alpha

    def export_layer(self, layer: LayerState, rgb: np.ndarray) -> Path:
        alpha = self.final_alpha(layer)
        if alpha is None:
            raise ProjectError(f"Layer '{layer.name}' has no model mask")

        authoring_dir = self.root / "layers" / self.layer_key(layer)
        authoring_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(alpha, mode="L").save(authoring_dir / "final-mask.png")
        rgba = np.dstack([rgb, alpha])
        Image.fromarray(rgba, mode="RGBA").save(authoring_dir / "rgba.png")

        rect = crop_rect(alpha, self.crop_threshold, self.crop_margin)
        layer.crop_rect = rect
        x, y, width, height = rect
        if not width or not height:
            raise ProjectError(f"Layer '{layer.name}' is empty at the crop threshold")

        cropped = rgba[y:y + height, x:x + width]
        work_path = self.root / "work" / "cropped" / f"{self.layer_key(layer)}.png"
        export_path = self.root / "export" / "layers" / f"{self.layer_key(layer)}.png"
        work_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(cropped, mode="RGBA").save(work_path)
        Image.fromarray(cropped, mode="RGBA").save(export_path)
        return export_path

    def base_rgba(self, rgb: np.ndarray, respect_crop: bool = False) -> np.ndarray:
        """Return the source with extracted layer coverage removed from alpha."""
        remaining = np.ones((self.height, self.width), dtype=np.float32)
        for layer in self.layers:
            alpha = self.final_alpha(layer)
            if alpha is not None:
                coverage = alpha.astype(np.float32) / 255.0
                if respect_crop:
                    clipped = np.zeros_like(coverage)
                    x, y, width, height = layer.crop_rect or (0, 0, 0, 0)
                    clipped[y:y + height, x:x + width] = coverage[y:y + height, x:x + width]
                    coverage = clipped
                remaining *= 1.0 - coverage
        # A partially transparent layer cannot by itself replace an opaque
        # source pixel: A + base*(1-A) reaches 1 only when base remains opaque.
        # Remove pixels only where the exported layer stack is fully opaque;
        # retain the source beneath feathered silhouettes for exact rebuilding.
        base_alpha = np.where(remaining <= 0.0, 0, 255).astype(np.uint8)
        return np.dstack([rgb, base_alpha])

    def composed_rgba(self, rgb: np.ndarray) -> np.ndarray:
        """Rebuild the scene from the derived base and z-ordered full-canvas layers."""
        composed = Image.fromarray(self.base_rgba(rgb), mode="RGBA")
        for layer in sorted(
            (item for item in self.layers if item.base_mask is not None), key=lambda item: item.z
        ):
            alpha = self.final_alpha(layer)
            rgba = Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA")
            composed.alpha_composite(rgba)
        return np.asarray(composed, dtype=np.uint8)

    def export_all(self, rgb: np.ndarray) -> list[Path]:
        export_root = self.root / "export"
        export_root.mkdir(parents=True, exist_ok=True)
        paths = [self.export_layer(layer, rgb) for layer in self.layers if layer.base_mask is not None]
        expected_layer_files = {path.name for path in paths}
        for stale_path in (export_root / "layers").glob("*.png"):
            if stale_path.name not in expected_layer_files:
                stale_path.unlink()
        Image.fromarray(self.base_rgba(rgb, respect_crop=True), mode="RGBA").save(
            export_root / "base.png"
        )
        self.save()

        manifest_layers = []
        for layer in sorted(
            (item for item in self.layers if item.base_mask is not None), key=lambda item: item.z
        ):
            x, y, width, height = layer.crop_rect or (0, 0, 0, 0)
            manifest_layers.append({
                "name": layer.name,
                "image": f"layers/{self.layer_key(layer)}.png",
                "role": layer.role,
                "z": layer.z,
                "source_rect": {"x": x, "y": y, "width": width, "height": height},
                "anchors": {"canvas_origin": {"x": -x, "y": -y}},
            })
        manifest = {
            "version": 1,
            "source_size": {"width": self.width, "height": self.height},
            "base": {"image": "base.png"},
            "layers": manifest_layers,
        }
        (export_root / "scene-layers.yml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )
        return paths
