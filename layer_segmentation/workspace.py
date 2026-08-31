from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .model_catalog import MODEL_BY_LABEL, MODEL_SPECS, model_from_key
from .project import BackgroundProject, ProjectError, slugify
from .theme import apply_dark_theme


IMAGE_TYPES = (
    ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
    ("All files", "*"),
)


def discover_projects(workspace: Path) -> list[str]:
    """Return initialized scene projects directly below a workspace."""
    if not workspace.is_dir():
        return []
    return [
        path.name
        for path in sorted(workspace.iterdir())
        if path.is_dir() and (path / "project.yml").is_file()
    ]


class WorkspaceApp(tk.Tk):
    def __init__(
        self,
        workspace: Path | str = Path("workspace"),
        device: str = "auto",
        default_model: str = "small",
    ):
        super().__init__()
        apply_dark_theme(self)
        self.title("XADV2 Layer Segmentation")
        self.geometry("920x310")
        self.minsize(720, 260)
        self.device = device
        self.default_model_spec = model_from_key(default_model)
        self.workspace_root = Path(workspace).expanduser()
        self.editor = None
        self.editor_window = None

        self.workspace_var = tk.StringVar(value=str(self.workspace_root))
        self.project_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value=self.default_model_spec.label)
        self.status_var = tk.StringVar(value="Choose or create a scene project.")
        self._build_ui()
        self.scan_projects()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=12)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(container, text="Workspace:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(container, textvariable=self.workspace_var).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6
        )
        ttk.Button(container, text="Browse…", command=self.choose_workspace).grid(
            row=0, column=2, padx=3, pady=6
        )
        ttk.Button(container, text="Scan", command=self.scan_projects).grid(
            row=0, column=3, padx=3, pady=6
        )

        ttk.Label(container, text="Scene:").grid(row=1, column=0, sticky="w", pady=6)
        self.project_combo = ttk.Combobox(
            container, textvariable=self.project_var, values=(), state="readonly"
        )
        self.project_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self.project_combo.bind("<<ComboboxSelected>>", self.on_project_selected)
        self.project_combo.bind("<Double-Button-1>", lambda _event: self.open_project())
        ttk.Button(container, text="Open", command=self.open_project).grid(
            row=1, column=2, padx=3, pady=6
        )
        ttk.Button(container, text="New scene…", command=self.create_project).grid(
            row=1, column=3, padx=3, pady=6
        )

        ttk.Label(container, text="Model:").grid(row=2, column=0, sticky="w", pady=6)
        self.model_combo = ttk.Combobox(
            container,
            textvariable=self.model_var,
            values=tuple(spec.label for spec in MODEL_SPECS),
            state="readonly",
        )
        self.model_combo.grid(row=2, column=1, sticky="ew", padx=6, pady=6)
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_selected)
        ttk.Label(container, text="Saved to project.yml").grid(
            row=2, column=2, columnspan=2, sticky="w", padx=3, pady=6
        )

        ttk.Separator(container).grid(row=3, column=0, columnspan=4, sticky="ew", pady=10)
        ttk.Label(container, textvariable=self.status_var, wraplength=840).grid(
            row=4, column=0, columnspan=4, sticky="w"
        )

    def workspace_path(self) -> Path:
        return Path(self.workspace_var.get() or "workspace").expanduser().resolve()

    def choose_workspace(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            title="Choose scene workspace",
            initialdir=str(Path(self.workspace_var.get() or ".").expanduser()),
        )
        if selected:
            self.workspace_var.set(selected)
            self.scan_projects()

    def scan_projects(self, preferred: str | None = None) -> None:
        workspace = self.workspace_path()
        self.workspace_root = workspace
        projects = discover_projects(workspace)
        self.project_combo.configure(values=projects)
        current = preferred or self.project_var.get()
        if current not in projects:
            current = projects[0] if projects else ""
        self.project_var.set(current)
        self.on_project_selected()
        if projects:
            self.status_var.set(
                f"{len(projects)} scene project(s) in {workspace}. Select one and press Open."
            )
        else:
            self.status_var.set(f"No scene projects in {workspace}. Use New scene…")

    def selected_model_spec(self):
        try:
            return MODEL_BY_LABEL[self.model_var.get()]
        except KeyError as exc:
            raise ValueError(f"Unknown model selection: {self.model_var.get()}") from exc

    def on_project_selected(self, _event=None) -> None:
        name = self.project_var.get()
        if not name:
            self.model_var.set(self.default_model_spec.label)
            return
        try:
            project = BackgroundProject.load(self.workspace_root / name)
            spec = next(
                item
                for item in MODEL_SPECS
                if (item.backend, item.model) == (project.backend, project.model)
            )
        except (ProjectError, OSError, ValueError, StopIteration):
            return
        self.model_var.set(spec.label)

    def on_model_selected(self, _event=None) -> None:
        spec = self.selected_model_spec()
        if spec.backend == "rmbg":
            self.status_var.set(
                "RMBG-2.0 is prompt-free and gated under CC BY-NC 4.0; "
                "commercial use requires a BRIA license. Press Open to save this choice."
            )
        else:
            self.status_var.set(
                f"{spec.label} supports box and positive/negative point prompts. "
                "Press Open to save this choice."
            )

    def create_project(self) -> None:
        workspace = self.workspace_path()
        try:
            workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Workspace error", str(exc), parent=self)
            return

        name = simpledialog.askstring(
            "New scene",
            "Scene name (lowercase kebab-case):",
            parent=self,
        )
        if name is None:
            return
        name = name.strip()
        if not name or slugify(name) != name:
            messagebox.showerror(
                "Invalid scene name",
                "Use lowercase kebab-case, for example office-lobby.",
                parent=self,
            )
            return

        source = filedialog.askopenfilename(
            parent=self,
            title="Choose the source background",
            initialdir=str(workspace),
            filetypes=IMAGE_TYPES,
        )
        if not source:
            return
        try:
            spec = self.selected_model_spec()
            project = BackgroundProject.create(
                workspace / name,
                Path(source),
                name=name,
                backend=spec.backend,
                model=spec.model,
            )
        except (ProjectError, OSError, ValueError) as exc:
            messagebox.showerror("Could not create scene", str(exc), parent=self)
            return

        self.workspace_var.set(str(workspace))
        self.scan_projects(preferred=project.root.name)
        self.open_project()

    def resolved_device(self) -> str:
        if self.device != "auto":
            return self.device
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"

    def open_project(self) -> None:
        name = self.project_var.get()
        if not name:
            messagebox.showinfo("No scene", "Select or create a scene first.", parent=self)
            return
        try:
            project = BackgroundProject.load(self.workspace_root / name)
            spec = self.selected_model_spec()
            model_changed = (project.backend, project.model) != (spec.backend, spec.model)
            if model_changed:
                project.backend = spec.backend
                project.model = spec.model
                # Preserve masks from the previous backend until the author
                # explicitly recomputes them in the editor.
                project.save(save_artifacts=False)
            device = self.resolved_device()
            if device == "cuda":
                import torch

                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but is unavailable")
        except (ProjectError, RuntimeError, OSError, ValueError) as exc:
            messagebox.showerror("Could not open scene", str(exc), parent=self)
            return

        if self.editor_window is not None and self.editor_window.winfo_exists():
            self.editor.on_close()

        self.status_var.set(f"Loading {project.name} with {spec.label} on {device}…")
        self.update_idletasks()
        try:
            from .gui import LayerExtractorApp

            self.editor_window = tk.Toplevel(self)
            self.editor = LayerExtractorApp(self.editor_window, project, device)
            if model_changed:
                self.editor.status_var.set(
                    f"Model changed to {spec.label}; existing masks were preserved. "
                    "Recompute each layer when ready."
                )
        except Exception as exc:
            if self.editor_window is not None and self.editor_window.winfo_exists():
                self.editor_window.destroy()
            self.editor = None
            self.editor_window = None
            messagebox.showerror("Could not open scene", str(exc), parent=self)
            self.status_var.set(f"Failed to open {project.name}.")
            return
        self.status_var.set(f"Editing {project.root}")


def main(
    workspace: Path | str = Path("workspace"),
    device: str = "auto",
    model: str = "small",
) -> int:
    app = WorkspaceApp(workspace=workspace, device=device, default_model=model)
    app.mainloop()
    return 0
