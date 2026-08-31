"""Stable model identifiers shared by YAML, CLI, and Tk UI code."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    backend: str
    model: str
    supports_points: bool


MODEL_SPECS = (
    ModelSpec("sam2-tiny", "SAM 2.1 Tiny", "sam2", "tiny", True),
    ModelSpec("sam2-small", "SAM 2.1 Small", "sam2", "small", True),
    ModelSpec("sam2-base-plus", "SAM 2.1 Base Plus", "sam2", "base_plus", True),
    ModelSpec("sam2-large", "SAM 2.1 Large", "sam2", "large", True),
    ModelSpec("rmbg-2.0", "BRIA RMBG 2.0", "rmbg", "rmbg-2.0", False),
)

MODEL_BY_KEY = {spec.key: spec for spec in MODEL_SPECS}
MODEL_BY_LABEL = {spec.label: spec for spec in MODEL_SPECS}
MODEL_BY_CONFIG = {(spec.backend, spec.model): spec for spec in MODEL_SPECS}
MODEL_ALIASES = {
    "tiny": "sam2-tiny",
    "small": "sam2-small",
    "base_plus": "sam2-base-plus",
    "base-plus": "sam2-base-plus",
    "large": "sam2-large",
    "briaai/rmbg-2.0": "rmbg-2.0",
}


def model_from_key(value: str) -> ModelSpec:
    """Resolve a CLI/UI key, retaining the original SAM shorthand aliases."""
    normalized = str(value).strip().lower()
    normalized = MODEL_ALIASES.get(normalized, normalized)
    try:
        return MODEL_BY_KEY[normalized]
    except KeyError as exc:
        choices = ", ".join(MODEL_BY_KEY)
        raise ValueError(
            f"Unknown segmentation model '{value}'; choose one of: {choices}"
        ) from exc


def model_from_config(backend: str, model: str) -> ModelSpec:
    """Resolve the two explicit values stored under ``segmentation`` in YAML."""
    normalized_backend = str(backend).strip().lower()
    normalized_model = str(model).strip().lower()
    try:
        return MODEL_BY_CONFIG[(normalized_backend, normalized_model)]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported segmentation backend/model: {backend}/{model}"
        ) from exc
