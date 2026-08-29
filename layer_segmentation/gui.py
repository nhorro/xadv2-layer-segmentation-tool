#!/usr/bin/env python3

from __future__ import annotations

import math
import sys
import tkinter as tk
from contextlib import nullcontext
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import numpy as np
import torch
from PIL import Image, ImageTk

ROOM_TEST_ROOT = Path(__file__).resolve().parents[1]
SAM2_REPO = ROOM_TEST_ROOT / "sam2"
if str(ROOM_TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(ROOM_TEST_ROOT))
if str(SAM2_REPO) not in sys.path:
    sys.path.insert(0, str(SAM2_REPO))

from .project import (
    ROLES,
    BackgroundProject,
    LayerState as Layer,
    slugify,
)
from .alpha import compose_alpha, paint_alpha_disk

from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


# -----------------------------------------------------------------------------
# Project layout / models
# -----------------------------------------------------------------------------

MODEL_PRESETS = {
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


# -----------------------------------------------------------------------------
# SAM
# -----------------------------------------------------------------------------

def load_predictor(
    model_name: str,
    device: str,
) -> SAM2ImagePredictor:
    preset = MODEL_PRESETS[model_name]
    checkpoint_path = preset["checkpoint"]

    if not checkpoint_path.exists():
        raise FileNotFoundError(
            f"Checkpoint not found: {checkpoint_path}"
        )

    model = build_sam2(
        preset["config"],
        str(checkpoint_path),
        device=device,
    )

    return SAM2ImagePredictor(model)


# -----------------------------------------------------------------------------
# Application
# -----------------------------------------------------------------------------

class LayerExtractorApp:
    MODES = (
        ("Box", "box"),
        ("Foreground +", "positive"),
        ("Background -", "negative"),
        ("Erase α", "erase"),
        ("Restore α", "restore"),
    )

    def __init__(
        self,
        root: tk.Tk,
        project: BackgroundProject,
        device: str,
    ):
        self.root = root
        self.project = project
        self.image_path = project.source_image
        self.model_name = project.model
        self.device = device

        self.root.title(f"XADV2 Layer Segmentation — {project.name}")
        self.root.geometry("1500x900")

        # Image
        self.image_pil = Image.open(self.image_path).convert("RGB")
        self.image_np = np.asarray(self.image_pil)
        self.image_h, self.image_w = self.image_np.shape[:2]
        yy, xx = np.indices((self.image_h, self.image_w))
        checker = ((xx // 12 + yy // 12) % 2).astype(np.uint8)
        checker_gray = np.where(checker == 0, 72, 120).astype(np.uint8)
        self.checker_bg = np.repeat(checker_gray[..., None], 3, axis=2)

        # Model
        self.status_var = tk.StringVar(value="Loading SAM2...")
        self.root.update_idletasks()

        self.predictor = load_predictor(
            self.model_name,
            device,
        )

        autocast = (
            torch.autocast("cuda", dtype=torch.bfloat16)
            if device == "cuda"
            else nullcontext()
        )

        with torch.inference_mode(), autocast:
            self.predictor.set_image(self.image_np)

        # State
        self.layers = self.project.layers
        self.current_layer_index: int | None = None

        self.mode = tk.StringVar(value="box")
        self.preview_mode = tk.StringVar(value="overlay")
        self.overlay_opacity = tk.DoubleVar(value=0.45)
        self.brush_size = tk.IntVar(value=16)
        self.brush_feather = tk.DoubleVar(value=4.0)
        self.role_var = tk.StringVar(value="other")
        self.z_var = tk.IntVar(value=0)
        self.erode_var = tk.IntVar(value=0)
        self.feather_var = tk.DoubleVar(value=0.0)
        self.crop_threshold_var = tk.IntVar(value=self.project.crop_threshold)
        self.crop_margin_var = tk.IntVar(value=self.project.crop_margin)
        self.show_annotations = tk.BooleanVar(value=True)
        self.pointer_var = tk.StringVar(value="x: —  y: —")

        self.zoom = 1.0
        self.photo: ImageTk.PhotoImage | None = None
        self.image_item = None

        # Mouse interaction
        self.drag_start_image: tuple[float, float] | None = None
        self.temp_box_item = None
        self.brushing = False
        self.last_brush_image: tuple[float, float] | None = None
        self.space_down = False
        self._render_job: str | None = None
        self._save_job: str | None = None

        self._build_ui()
        self.refresh_layer_list()
        if self.layers:
            self.layer_list.selection_set(0)
            self.current_layer_index = 0
            self.sync_layer_controls()

        self.status_var.set(
            f"{self.image_path.name} — {self.image_w}×{self.image_h} — "
            f"{self.model_name} on {self.device}"
        )

        self.root.after(100, self.fit_to_window)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Left panel
        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="ns")
        left.rowconfigure(2, weight=1)

        ttk.Label(
            left,
            text="Layers",
            font=("TkDefaultFont", 11, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Button(
            left,
            text="+ Add",
            command=self.add_layer,
        ).grid(row=1, column=0, sticky="ew", pady=(5, 5))

        ttk.Button(
            left,
            text="Rename",
            command=self.rename_layer,
        ).grid(row=1, column=1, sticky="ew", pady=(5, 5))

        ttk.Button(
            left,
            text="Delete",
            command=self.delete_layer,
        ).grid(row=1, column=2, sticky="ew", pady=(5, 5))

        self.layer_list = tk.Listbox(
            left,
            width=28,
            exportselection=False,
        )
        self.layer_list.grid(
            row=2,
            column=0,
            columnspan=3,
            sticky="nsew",
        )
        self.layer_list.bind(
            "<<ListboxSelect>>",
            self.on_layer_selected,
        )

        ttk.Label(left, text="Role").grid(row=3, column=0, sticky="w")
        role_box = ttk.Combobox(
            left, textvariable=self.role_var, values=ROLES, state="readonly", width=14
        )
        role_box.grid(row=3, column=1, columnspan=2, sticky="ew")
        role_box.bind("<<ComboboxSelected>>", self.on_layer_settings_changed)

        ttk.Label(left, text="Z order").grid(row=4, column=0, sticky="w")
        z_spin = ttk.Spinbox(
            left, from_=-10000, to=10000, textvariable=self.z_var, width=8,
            command=self.on_layer_settings_changed,
        )
        z_spin.grid(row=4, column=1, sticky="ew")
        z_spin.bind("<FocusOut>", self.on_layer_settings_changed)
        z_spin.bind("<Return>", self.on_layer_settings_changed)

        ttk.Button(left, text="↑", width=3, command=lambda: self.move_layer(-1)).grid(
            row=4, column=2, sticky="w"
        )
        ttk.Button(left, text="↓", width=3, command=lambda: self.move_layer(1)).grid(
            row=4, column=2, sticky="e"
        )

        sep = ttk.Separator(left, orient="horizontal")
        sep.grid(
            row=5,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=10,
        )

        ttk.Label(
            left,
            text="Mode",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=6, column=0, columnspan=3, sticky="w")

        row = 7
        for text, value in self.MODES:
            ttk.Radiobutton(
                left,
                text=text,
                value=value,
                variable=self.mode,
                command=self.render,
            ).grid(
                row=row,
                column=0,
                columnspan=3,
                sticky="w",
            )
            row += 1

        ttk.Separator(left, orient="horizontal").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=10,
        )
        row += 1

        ttk.Label(left, text="Brush size").grid(
            row=row, column=0, sticky="w"
        )
        ttk.Spinbox(
            left,
            from_=1,
            to=200,
            increment=1,
            textvariable=self.brush_size,
        ).grid(
            row=row,
            column=1,
            columnspan=2,
            sticky="ew",
        )
        row += 1

        ttk.Label(left, text="Brush feather").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(
            left,
            from_=0,
            to=200,
            increment=0.25,
            textvariable=self.brush_feather,
        ).grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1

        ttk.Label(left, text="Preview").grid(
            row=row, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Combobox(
            left,
            textvariable=self.preview_mode,
            values=(
                "overlay", "cutout-checker", "cutout-black", "cutout-white",
                "mask", "composition",
            ),
            state="readonly",
            width=12,
        ).grid(
            row=row,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )
        self.preview_mode.trace_add(
            "write",
            lambda *_: self.render(),
        )
        row += 1

        ttk.Checkbutton(
            left,
            text="Show box and points",
            variable=self.show_annotations,
            command=self.render,
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        ttk.Label(left, text="Erode px").grid(row=row, column=0, sticky="w")
        erode_spin = ttk.Spinbox(
            left, from_=0, to=12, increment=1, textvariable=self.erode_var, width=8,
            command=self.on_layer_settings_changed,
        )
        erode_spin.grid(row=row, column=1, columnspan=2, sticky="ew")
        erode_spin.bind("<Return>", self.on_layer_settings_changed)
        erode_spin.bind("<FocusOut>", self.on_layer_settings_changed)
        row += 1

        ttk.Label(left, text="Feather px").grid(row=row, column=0, sticky="w")
        feather_spin = ttk.Spinbox(
            left, from_=0, to=12, increment=0.25, textvariable=self.feather_var, width=8,
            command=self.on_layer_settings_changed,
        )
        feather_spin.grid(row=row, column=1, columnspan=2, sticky="ew")
        feather_spin.bind("<Return>", self.on_layer_settings_changed)
        feather_spin.bind("<FocusOut>", self.on_layer_settings_changed)
        row += 1

        ttk.Label(left, text="Crop α >").grid(row=row, column=0, sticky="w")
        crop_threshold_spin = ttk.Spinbox(
            left, from_=0, to=254, textvariable=self.crop_threshold_var, width=8,
            command=self.on_project_settings_changed,
        )
        crop_threshold_spin.grid(row=row, column=1, columnspan=2, sticky="ew")
        crop_threshold_spin.bind("<Return>", self.on_project_settings_changed)
        crop_threshold_spin.bind("<FocusOut>", self.on_project_settings_changed)
        row += 1

        ttk.Label(left, text="Crop margin").grid(row=row, column=0, sticky="w")
        crop_margin_spin = ttk.Spinbox(
            left, from_=0, to=128, textvariable=self.crop_margin_var, width=8,
            command=self.on_project_settings_changed,
        )
        crop_margin_spin.grid(row=row, column=1, columnspan=2, sticky="ew")
        crop_margin_spin.bind("<Return>", self.on_project_settings_changed)
        crop_margin_spin.bind("<FocusOut>", self.on_project_settings_changed)
        row += 1

        ttk.Label(left, text="Overlay α").grid(
            row=row, column=0, sticky="w"
        )
        ttk.Scale(
            left,
            from_=0.05,
            to=0.9,
            variable=self.overlay_opacity,
            orient="horizontal",
            command=lambda _v: self.render(),
        ).grid(
            row=row,
            column=1,
            columnspan=2,
            sticky="ew",
        )
        row += 1

        ttk.Separator(left, orient="horizontal").grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=10,
        )
        row += 1

        ttk.Button(
            left,
            text="Undo point",
            command=self.undo_point,
        ).grid(row=row, column=0, sticky="ew")
        ttk.Button(
            left,
            text="Clear points",
            command=self.clear_points,
        ).grid(row=row, column=1, columnspan=2, sticky="ew")
        row += 1

        ttk.Button(
            left,
            text="Recompute SAM mask",
            command=self.recompute_current_mask,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(5, 0),
        )
        row += 1

        ttk.Button(
            left,
            text="Clear manual mask edits",
            command=self.clear_manual_edits,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(5, 0),
        )
        row += 1

        ttk.Button(
            left,
            text="Save project",
            command=self.save_project,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(12, 0),
        )
        row += 1

        ttk.Button(
            left,
            text="Generate layer artifacts",
            command=self.export_current,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(5, 0),
        )
        row += 1

        ttk.Button(
            left,
            text="Export composed scene",
            command=self.export_all,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(5, 0),
        )

        # Center canvas
        center = ttk.Frame(self.root)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            center,
            background="#202020",
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        xscroll = ttk.Scrollbar(
            center,
            orient="horizontal",
            command=self.on_xscroll,
        )
        xscroll.grid(row=1, column=0, sticky="ew")

        yscroll = ttk.Scrollbar(
            center,
            orient="vertical",
            command=self.on_yscroll,
        )
        yscroll.grid(row=0, column=1, sticky="ns")

        self.canvas.configure(
            xscrollcommand=xscroll.set,
            yscrollcommand=yscroll.set,
        )

        # Toolbar
        toolbar = ttk.Frame(center, padding=(5, 3))
        toolbar.grid(row=2, column=0, sticky="ew")

        ttk.Button(
            toolbar,
            text="−",
            width=3,
            command=lambda: self.set_zoom(self.zoom / 1.25),
        ).pack(side="left")

        ttk.Button(
            toolbar,
            text="+",
            width=3,
            command=lambda: self.set_zoom(self.zoom * 1.25),
        ).pack(side="left")

        ttk.Button(
            toolbar,
            text="Fit",
            command=self.fit_to_window,
        ).pack(side="left", padx=(5, 0))

        self.zoom_label = ttk.Label(toolbar, text="100%")
        self.zoom_label.pack(side="left", padx=10)

        ttk.Label(toolbar, textvariable=self.pointer_var, width=20).pack(side="left", padx=4)

        ttk.Button(
            toolbar,
            text="Composition",
            command=lambda: self.preview_mode.set("composition"),
        ).pack(side="left", padx=(4, 0))

        ttk.Label(
            toolbar,
            textvariable=self.status_var,
        ).pack(side="left", padx=10)

        # Canvas events
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Motion>", self.on_pointer_motion)
        self.canvas.bind("<Leave>", self.on_pointer_leave)

        self.canvas.bind("<ButtonPress-3>", self.on_right_click)

        # Middle mouse pan
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)

        # Wheel scrolls; Shift+wheel scrolls horizontally; Ctrl+wheel zooms.
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-4>", lambda event: self.on_linux_wheel(event, -1))
        self.canvas.bind("<Button-5>", lambda event: self.on_linux_wheel(event, 1))

        self.root.bind("<KeyPress-space>", self.on_space_press)
        self.root.bind("<KeyRelease-space>", self.on_space_release)
        self.root.bind("<Control-s>", lambda _event: self.save_project())
        self.root.bind("<Control-z>", lambda _event: self.undo_point())
        for key, value in (("b", "box"), ("f", "positive"), ("n", "negative"),
                           ("e", "erase"), ("r", "restore")):
            self.root.bind(key, lambda event, mode=value: self.set_mode_shortcut(event, mode))

    # ------------------------------------------------------------------
    # Layer helpers
    # ------------------------------------------------------------------

    def current_layer(self) -> Layer | None:
        if self.current_layer_index is None:
            return None
        if self.current_layer_index >= len(self.layers):
            return None
        return self.layers[self.current_layer_index]

    def add_layer(self):
        name = simpledialog.askstring(
            "New layer",
            "Layer/object name:",
            parent=self.root,
        )
        if not name:
            return

        name = name.strip()
        if not name:
            return

        existing = {self.project.layer_key(layer) for layer in self.layers}
        if slugify(name) in existing:
            messagebox.showerror(
                "Duplicate name",
                f"A layer named '{name}' already exists.",
            )
            return

        layer = Layer(
            name=name,
            z=(max((item.z for item in self.layers), default=-10) + 10),
            manual_alpha=np.full(
                (self.image_h, self.image_w),
                -1,
                dtype=np.int16,
            ),
        )

        self.layers.append(layer)
        self.refresh_layer_list()

        self.layer_list.selection_clear(0, tk.END)
        self.layer_list.selection_set(len(self.layers) - 1)
        self.layer_list.activate(len(self.layers) - 1)

        self.current_layer_index = len(self.layers) - 1
        self.mode.set("box")
        self.sync_layer_controls()
        self.schedule_save()

        self.status_var.set(
            f"Layer '{name}': draw a bounding box."
        )
        self.render()

    def rename_layer(self):
        layer = self.current_layer()
        if layer is None:
            return

        name = simpledialog.askstring(
            "Rename layer",
            "New name:",
            initialvalue=layer.name,
            parent=self.root,
        )
        if not name:
            return

        name = name.strip()
        if not name:
            return

        if any(
            other is not layer and other.name == name
            for other in self.layers
        ):
            messagebox.showerror(
                "Duplicate name",
                f"A layer named '{name}' already exists.",
            )
            return

        old_key = self.project.layer_key(layer)
        new_key = slugify(name)
        if any(
            other is not layer and self.project.layer_key(other) == new_key
            for other in self.layers
        ):
            messagebox.showerror(
                "Duplicate filename",
                f"'{name}' conflicts with another layer after filename normalization.",
            )
            return

        layer.name = name
        old_dir = self.project.root / "layers" / old_key
        new_dir = self.project.root / "layers" / new_key
        if old_dir.is_dir() and old_dir != new_dir and not new_dir.exists():
            old_dir.rename(new_dir)
        self.refresh_layer_list()
        self.schedule_save()

    def delete_layer(self):
        layer = self.current_layer()
        if layer is None:
            return

        if not messagebox.askyesno(
            "Delete layer",
            f"Delete '{layer.name}'?",
        ):
            return

        index = self.current_layer_index
        del self.layers[index]

        self.current_layer_index = None
        self.refresh_layer_list()

        if self.layers:
            new_index = min(index, len(self.layers) - 1)
            self.layer_list.selection_set(new_index)
            self.current_layer_index = new_index
            self.sync_layer_controls()

        self.schedule_save()
        self.render()

    def move_layer(self, offset: int):
        index = self.current_layer_index
        if index is None:
            return
        new_index = max(0, min(len(self.layers) - 1, index + offset))
        if new_index == index:
            return
        layer = self.layers.pop(index)
        self.layers.insert(new_index, layer)
        self.current_layer_index = new_index
        self.refresh_layer_list()
        self.schedule_save()

    def sync_layer_controls(self):
        layer = self.current_layer()
        if layer is None:
            return
        self.role_var.set(layer.role)
        self.z_var.set(layer.z)
        self.erode_var.set(layer.erode_px)
        self.feather_var.set(layer.feather_px)

    def on_layer_settings_changed(self, _event=None):
        layer = self.current_layer()
        if layer is None:
            return
        try:
            layer.z = int(self.z_var.get())
            layer.erode_px = max(0, int(self.erode_var.get()))
            layer.feather_px = max(0.0, float(self.feather_var.get()))
        except (tk.TclError, ValueError):
            self.sync_layer_controls()
            return
        layer.role = self.role_var.get() if self.role_var.get() in ROLES else "other"
        self.schedule_save()
        self.render()

    def on_project_settings_changed(self, _event=None):
        try:
            self.project.crop_threshold = max(0, min(254, int(self.crop_threshold_var.get())))
            self.project.crop_margin = max(0, int(self.crop_margin_var.get()))
        except (tk.TclError, ValueError):
            self.crop_threshold_var.set(self.project.crop_threshold)
            self.crop_margin_var.set(self.project.crop_margin)
            return
        self.schedule_save()

    def refresh_layer_list(self):
        selected = self.current_layer_index

        self.layer_list.delete(0, tk.END)

        for layer in self.layers:
            if layer.base_mask is not None:
                marker = "✓"
            elif layer.box is not None:
                marker = "□"
            else:
                marker = "·"

            self.layer_list.insert(
                tk.END,
                f"{marker} {layer.name}",
            )

        if (
            selected is not None
            and selected < len(self.layers)
        ):
            self.layer_list.selection_set(selected)

    def on_layer_selected(self, _event=None):
        selection = self.layer_list.curselection()
        if not selection:
            return

        self.current_layer_index = int(selection[0])
        self.sync_layer_controls()
        self.render()

    # ------------------------------------------------------------------
    # SAM inference
    # ------------------------------------------------------------------

    def autocast_context(self):
        if self.device == "cuda":
            return torch.autocast(
                "cuda",
                dtype=torch.bfloat16,
            )
        return nullcontext()

    def predict_initial(self, layer: Layer):
        if layer.box is None:
            return

        self.set_busy("SAM2: initial segmentation...")

        with torch.inference_mode(), self.autocast_context():
            masks, scores, logits = self.predictor.predict(
                box=layer.box,
                multimask_output=True,
            )

        best = int(np.argmax(scores))

        layer.base_mask = masks[best]
        layer.mask_input = logits[best:best + 1]
        layer.score = float(scores[best])

        self.set_busy(
            f"{layer.name}: score {layer.score:.4f}"
        )
        self.refresh_layer_list()
        self.render()
        self.schedule_save()

    def refine(self, layer: Layer):
        if layer.box is None:
            return

        if not layer.points:
            self.predict_initial(layer)
            return

        coords = np.asarray(
            layer.points,
            dtype=np.float32,
        )
        labels = np.asarray(
            layer.labels,
            dtype=np.int32,
        )

        self.set_busy(
            f"SAM2: refining with {len(layer.points)} point(s)..."
        )

        with torch.inference_mode(), self.autocast_context():
            masks, scores, logits = self.predictor.predict(
                point_coords=coords,
                point_labels=labels,
                box=layer.box,
                mask_input=layer.mask_input,
                multimask_output=False,
            )

        layer.base_mask = masks[0]
        layer.mask_input = logits
        layer.score = float(scores[0])

        self.set_busy(
            f"{layer.name}: {len(layer.points)} points, "
            f"score {layer.score:.4f}"
        )
        self.render()
        self.schedule_save()

    def recompute_layer(self, layer: Layer):
        """
        Rebuild SAM state after undo/clear. Manual alpha overrides are kept.
        """
        layer.mask_input = None

        if layer.box is None:
            return

        if not layer.points:
            self.predict_initial(layer)
            return

        coords = np.asarray(
            layer.points,
            dtype=np.float32,
        )
        labels = np.asarray(
            layer.labels,
            dtype=np.int32,
        )

        self.set_busy("SAM2: recomputing...")

        with torch.inference_mode(), self.autocast_context():
            masks, scores, logits = self.predictor.predict(
                point_coords=coords,
                point_labels=labels,
                box=layer.box,
                multimask_output=False,
            )

        layer.base_mask = masks[0]
        layer.mask_input = logits[0:1]
        layer.score = float(scores[0])

        self.set_busy(
            f"{layer.name}: score {layer.score:.4f}"
        )
        self.render()
        self.schedule_save()

    # ------------------------------------------------------------------
    # Mask composition
    # ------------------------------------------------------------------

    def final_alpha(self, layer: Layer) -> np.ndarray | None:
        return self.project.final_alpha(layer)

    def clear_manual_edits(self):
        layer = self.current_layer()
        if layer is None:
            return

        layer.manual_alpha.fill(-1)
        self.schedule_save()
        self.render()

    # ------------------------------------------------------------------
    # Point editing
    # ------------------------------------------------------------------

    def undo_point(self):
        layer = self.current_layer()
        if layer is None or not layer.points:
            return

        layer.points.pop()
        layer.labels.pop()
        self.recompute_layer(layer)

    def clear_points(self):
        layer = self.current_layer()
        if layer is None:
            return

        layer.points.clear()
        layer.labels.clear()
        layer.mask_input = None

        if layer.box is not None:
            self.predict_initial(layer)

    def recompute_current_mask(self):
        layer = self.current_layer()
        if layer is None or layer.box is None:
            self.status_var.set("Select a layer with a bounding box first.")
            return
        self.recompute_layer(layer)

    # ------------------------------------------------------------------
    # Coordinates / zoom / rendering
    # ------------------------------------------------------------------

    def canvas_to_image(
        self,
        event,
    ) -> tuple[float, float]:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)

        return (
            cx / self.zoom,
            cy / self.zoom,
        )

    def on_pointer_motion(self, event):
        x, y = self.canvas_to_image(event)
        self.canvas.delete("brush-cursor")
        if 0 <= x < self.image_w and 0 <= y < self.image_h:
            self.pointer_var.set(f"x: {int(x):4d}  y: {int(y):4d}")
            if self.mode.get() in ("erase", "restore"):
                try:
                    brush_size = max(1.0, float(self.brush_size.get()))
                    feather = min(brush_size, float(self.brush_feather.get()))
                except (tk.TclError, ValueError):
                    brush_size, feather = 1.0, 0.0
                radius = brush_size * self.zoom
                sx, sy = x * self.zoom, y * self.zoom
                self.canvas.create_oval(
                    sx - radius, sy - radius, sx + radius, sy + radius,
                    outline="white", width=1, tags="brush-cursor",
                )
                inner = max(0.0, brush_size - feather) * self.zoom
                if inner > 0:
                    self.canvas.create_oval(
                        sx - inner, sy - inner, sx + inner, sy + inner,
                        outline="#80d8ff", dash=(3, 2), width=1, tags="brush-cursor",
                    )
        else:
            self.pointer_var.set("x: —  y: —")

    def on_pointer_leave(self, _event=None):
        self.pointer_var.set("x: —  y: —")
        self.canvas.delete("brush-cursor")

    def set_zoom(self, zoom: float, event=None):
        widget_x = event.x if event is not None else self.canvas.winfo_width() / 2
        widget_y = event.y if event is not None else self.canvas.winfo_height() / 2
        image_x = self.canvas.canvasx(widget_x) / self.zoom
        image_y = self.canvas.canvasy(widget_y) / self.zoom

        self.zoom = max(
            0.05,
            min(16.0, float(zoom)),
        )

        self.zoom_label.configure(
            text=f"{self.zoom * 100:.0f}%"
        )

        target_w = max(1, int(self.image_w * self.zoom))
        target_h = max(1, int(self.image_h * self.zoom))
        self.canvas.configure(scrollregion=(0, 0, target_w, target_h))
        left = image_x * self.zoom - widget_x
        top = image_y * self.zoom - widget_y
        self.canvas.xview_moveto(max(0.0, min(1.0, left / target_w)))
        self.canvas.yview_moveto(max(0.0, min(1.0, top / target_h)))
        self.render()

    def fit_to_window(self):
        self.root.update_idletasks()

        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        zx = cw / self.image_w
        zy = ch / self.image_h

        self.set_zoom(
            min(zx, zy) * 0.98
        )

        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def render(self):
        layer = self.current_layer()
        mode = self.preview_mode.get()

        if mode == "composition":
            display = Image.fromarray(self.project.composed_rgba(self.image_np), mode="RGBA").convert("RGB")
        elif (
            layer is None
            or layer.base_mask is None
        ):
            display = self.image_pil
        else:
            alpha = self.final_alpha(layer)

            if mode == "mask":
                display = Image.fromarray(
                    alpha,
                    mode="L",
                ).convert("RGB")

            elif mode.startswith("cutout-"):
                background = mode.removeprefix("cutout-")
                if background == "checker":
                    bg = self.checker_bg
                else:
                    value = 0 if background == "black" else 255
                    bg = np.full_like(self.image_np, value)
                a = alpha.astype(np.float32)[..., None] / 255.0
                comp = (
                    self.image_np.astype(np.float32) * a
                    + bg.astype(np.float32) * (1.0 - a)
                ).astype(np.uint8)

                display = Image.fromarray(comp)

            else:
                arr = self.image_np.astype(
                    np.float32
                ).copy()

                a = (
                    alpha.astype(np.float32) / 255.0
                )[..., None]

                opacity = float(
                    self.overlay_opacity.get()
                )

                green = np.zeros_like(arr)
                green[..., 1] = 255

                mix = a * opacity
                arr = (
                    arr * (1.0 - mix)
                    + green * mix
                )

                display = Image.fromarray(
                    arr.clip(0, 255).astype(np.uint8)
                )

        target_w = max(
            1,
            int(self.image_w * self.zoom),
        )
        target_h = max(
            1,
            int(self.image_h * self.zoom),
        )

        self.canvas.configure(scrollregion=(0, 0, target_w, target_h))
        viewport_w = max(1, self.canvas.winfo_width())
        viewport_h = max(1, self.canvas.winfo_height())
        world_x = max(0.0, self.canvas.canvasx(0))
        world_y = max(0.0, self.canvas.canvasy(0))
        source_x0 = max(0, int(math.floor(world_x / self.zoom)))
        source_y0 = max(0, int(math.floor(world_y / self.zoom)))
        source_x1 = min(
            self.image_w,
            max(source_x0 + 1, int(math.ceil((world_x + viewport_w) / self.zoom)) + 1),
        )
        source_y1 = min(
            self.image_h,
            max(source_y0 + 1, int(math.ceil((world_y + viewport_h) / self.zoom)) + 1),
        )
        display = display.crop((source_x0, source_y0, source_x1, source_y1))
        tile_w = max(1, int(round((source_x1 - source_x0) * self.zoom)))
        tile_h = max(1, int(round((source_y1 - source_y0) * self.zoom)))
        display = display.resize(
            (tile_w, tile_h),
            Image.Resampling.NEAREST if self.zoom >= 4.0 else Image.Resampling.BILINEAR,
        )

        self.photo = ImageTk.PhotoImage(display)

        self.canvas.delete("all")

        self.image_item = self.canvas.create_image(
            source_x0 * self.zoom,
            source_y0 * self.zoom,
            anchor="nw",
            image=self.photo,
        )

        if layer is not None and self.show_annotations.get():
            self.draw_annotations(layer)

    def draw_annotations(self, layer: Layer):
        if layer.box is not None:
            x1, y1, x2, y2 = (
                layer.box * self.zoom
            )

            self.canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline="yellow",
                width=2,
            )

        radius = max(3, int(5 * self.zoom))

        for (x, y), label in zip(
            layer.points,
            layer.labels,
        ):
            sx = x * self.zoom
            sy = y * self.zoom

            color = "#00ff44" if label == 1 else "#ff3333"

            self.canvas.create_oval(
                sx - radius,
                sy - radius,
                sx + radius,
                sy + radius,
                outline=color,
                width=3,
            )

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def on_left_press(self, event):
        self.canvas.focus_set()
        if self.space_down:
            self.on_pan_start(event)
            return

        layer = self.current_layer()
        if layer is None:
            self.status_var.set(
                "Add/select a layer first."
            )
            return

        x, y = self.canvas_to_image(event)

        if not (
            0 <= x < self.image_w
            and 0 <= y < self.image_h
        ):
            return

        mode = self.mode.get()

        if mode == "box":
            self.drag_start_image = (x, y)

        elif mode == "positive":
            layer.points.append([x, y])
            layer.labels.append(1)
            self.refine(layer)

        elif mode == "negative":
            layer.points.append([x, y])
            layer.labels.append(0)
            self.refine(layer)

        elif mode in ("erase", "restore"):
            self.brushing = True
            self.last_brush_image = (x, y)
            self.apply_brush(layer, x, y, mode)

    def on_left_motion(self, event):
        if self.space_down:
            self.on_pan_move(event)
            return

        layer = self.current_layer()
        if layer is None:
            return

        mode = self.mode.get()
        x, y = self.canvas_to_image(event)

        if mode == "box" and self.drag_start_image is not None:
            sx, sy = self.drag_start_image

            if self.temp_box_item is not None:
                self.canvas.delete(
                    self.temp_box_item
                )

            self.temp_box_item = (
                self.canvas.create_rectangle(
                    sx * self.zoom,
                    sy * self.zoom,
                    x * self.zoom,
                    y * self.zoom,
                    outline="#00e5ff",
                    width=2,
                )
            )

        elif (
            mode in ("erase", "restore")
            and self.brushing
        ):
            if (
                0 <= x < self.image_w
                and 0 <= y < self.image_h
            ):
                self.apply_brush_line(layer, self.last_brush_image, (x, y), mode)
                self.last_brush_image = (x, y)
                self.queue_render()

    def on_left_release(self, event):
        if self.space_down:
            return

        layer = self.current_layer()
        if layer is None:
            return

        mode = self.mode.get()

        if mode == "box":
            if self.drag_start_image is None:
                return

            x0, y0 = self.drag_start_image
            x1, y1 = self.canvas_to_image(event)

            self.drag_start_image = None

            if self.temp_box_item is not None:
                self.canvas.delete(
                    self.temp_box_item
                )
                self.temp_box_item = None

            x_min = max(
                0,
                min(x0, x1),
            )
            y_min = max(
                0,
                min(y0, y1),
            )
            x_max = min(
                self.image_w,
                max(x0, x1),
            )
            y_max = min(
                self.image_h,
                max(y0, y1),
            )

            if (
                x_max - x_min < 5
                or y_max - y_min < 5
            ):
                return

            layer.box = np.asarray(
                [
                    x_min,
                    y_min,
                    x_max,
                    y_max,
                ],
                dtype=np.float32,
            )

            layer.points.clear()
            layer.labels.clear()
            layer.base_mask = None
            layer.mask_input = None
            layer.score = None

            self.predict_initial(layer)
            self.mode.set("positive")

        elif mode in ("erase", "restore"):
            self.brushing = False
            self.last_brush_image = None
            self.render()
            self.schedule_save()

    def on_right_click(self, event):
        layer = self.current_layer()
        if layer is None:
            return

        # Right click is always a negative SAM point unless brushing.
        if self.mode.get() in ("erase", "restore", "box"):
            return

        x, y = self.canvas_to_image(event)

        if (
            0 <= x < self.image_w
            and 0 <= y < self.image_h
        ):
            layer.points.append([x, y])
            layer.labels.append(0)
            self.refine(layer)

    def apply_brush(
        self,
        layer: Layer,
        x: float,
        y: float,
        mode: str,
        render: bool = True,
    ):
        if layer.base_mask is None:
            return

        if layer.manual_alpha is None:
            layer.manual_alpha = np.full(
                (self.image_h, self.image_w),
                -1,
                dtype=np.int16,
            )

        try:
            brush_feather = max(0.0, float(self.brush_feather.get()))
        except (tk.TclError, ValueError):
            brush_feather = 0.0
            self.brush_feather.set(0.0)
        base_alpha = compose_alpha(layer.base_mask, None)
        paint_alpha_disk(
            base_alpha,
            layer.manual_alpha,
            x,
            y,
            radius=max(1, int(self.brush_size.get())),
            feather_px=brush_feather,
            target_alpha=0 if mode == "erase" else 255,
        )

        if render:
            self.render()

    def apply_brush_line(
        self,
        layer: Layer,
        start: tuple[float, float] | None,
        end: tuple[float, float],
        mode: str,
    ):
        if start is None:
            self.apply_brush(layer, *end, mode, render=False)
            return
        distance = math.dist(start, end)
        spacing = max(1.0, float(self.brush_size.get()) * 0.35)
        samples = max(1, int(math.ceil(distance / spacing)))
        for index in range(1, samples + 1):
            amount = index / samples
            x = start[0] + (end[0] - start[0]) * amount
            y = start[1] + (end[1] - start[1]) * amount
            self.apply_brush(layer, x, y, mode, render=False)

    def queue_render(self):
        if self._render_job is None:
            self._render_job = self.root.after(33, self._render_queued)

    def _render_queued(self):
        self._render_job = None
        self.render()

    # ------------------------------------------------------------------
    # Pan / wheel
    # ------------------------------------------------------------------

    def on_pan_start(self, event):
        self.canvas.scan_mark(
            event.x,
            event.y,
        )

    def on_pan_move(self, event):
        self.canvas.scan_dragto(
            event.x,
            event.y,
            gain=1,
        )
        self.queue_render()

    def on_xscroll(self, *args):
        self.canvas.xview(*args)
        self.queue_render()

    def on_yscroll(self, *args):
        self.canvas.yview(*args)
        self.queue_render()

    def on_mousewheel(self, event):
        direction = -1 if event.delta > 0 else 1
        return self.handle_wheel(event, direction)

    def on_linux_wheel(self, event, direction: int):
        return self.handle_wheel(event, direction)

    def handle_wheel(self, event, direction: int):
        if event.state & 0x4:
            factor = 1.15 if direction < 0 else 1 / 1.15
            self.set_zoom(self.zoom * factor, event)
        elif event.state & 0x1:
            self.canvas.xview_scroll(direction * 3, "units")
            self.queue_render()
        else:
            self.canvas.yview_scroll(direction * 3, "units")
            self.queue_render()
        return "break"

    def on_space_press(self, _event):
        self.space_down = True
        self.canvas.configure(cursor="fleur")

    def on_space_release(self, _event):
        self.space_down = False
        self.canvas.configure(cursor="")

    def set_mode_shortcut(self, event, mode: str):
        if event.widget.winfo_class() in {"Entry", "TEntry", "Spinbox", "TSpinbox"}:
            return
        self.mode.set(mode)
        self.render()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_layer(self, layer: Layer):
        path = self.project.export_layer(layer, self.image_np)
        self.project.save()
        return path

    def export_current(self):
        layer = self.current_layer()
        if layer is None:
            return

        try:
            path = self.export_layer(layer)
        except Exception as exc:
            messagebox.showerror(
                "Export failed",
                str(exc),
            )
            return

        self.status_var.set(
            f"Exported: {path}"
        )

    def export_all(self):
        try:
            exported = self.project.export_all(self.image_np)
        except Exception as exc:
            messagebox.showerror(
                "Export failed",
                str(exc),
            )
            return

        self.status_var.set(
            f"Exported {len(exported)} layer(s)."
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(500, self.save_project)

    def save_project(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
            self._save_job = None
        try:
            self.on_project_settings_changed_no_save()
            self.project.save()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.status_var.set(f"Saved: {self.project.project_file}")

    def on_project_settings_changed_no_save(self):
        try:
            self.project.crop_threshold = max(0, min(254, int(self.crop_threshold_var.get())))
            self.project.crop_margin = max(0, int(self.crop_margin_var.get()))
        except (tk.TclError, ValueError):
            pass

    def on_close(self):
        self.save_project()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def set_busy(self, text: str):
        self.status_var.set(text)
        self.root.update_idletasks()
