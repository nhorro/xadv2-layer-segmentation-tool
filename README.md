# XADV2 Layer Segmentation Tool

Desktop authoring application for turning a background image into registered
RGBA layers for XADV2 point-and-click scenes. SAM 2.1 supplies initial masks;
the application preserves prompts, manual alpha corrections, intermediate
masks, crops, and runtime exports in a scene project.

![Screenshot](./doc/assets/screenshot.png)

All maintained application code lives in `layer_segmentation/`. A workspace is
a directory containing one project per scene.

## Setup

Python 3.10 or newer and Tk are required. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e ./sam2
python -m pip install -e .
```

The repository's existing shared environment can run the application directly:

```bash
../.venv/bin/python layer_segmentation --workspace=./workspace
```

Equivalent installed and module entry points are:

```bash
layer-segmentation --workspace=./workspace
python -m layer_segmentation --workspace=./workspace
```

`--workspace` defaults to `./workspace`. Use a different path to keep the scenes
for each game or content project isolated. `--device=auto|cuda|cpu` selects the
SAM inference device, and `--model=tiny|small|base_plus|large` sets the default
for newly created scenes.

## Workspace workflow

The startup window discovers scene projects immediately below the selected
workspace. Use **New scene…** to assign a lowercase kebab-case name and select
its source background. The application creates the canonical project structure,
copies the original source, and opens the scene editor. Existing projects can be
selected and reopened without recomputing their masks.

Inside the editor:

1. Add a uniquely named layer such as `desk`, then assign its role and z order.
2. Draw a bounding box and refine the SAM mask with positive and negative points.
   The box is a hard boundary: SAM output, saved masks, manual alpha, and final
   feathered artifacts are always transparent outside it.
3. Zoom and pan for detail work. The toolbar reports source pixel coordinates in
   real time.
4. Use alpha erase/paint with an exact brush radius and a configurable feather
   width. Radius `0` affects exactly one source pixel; larger radii show their
   outer footprint and fully affected inner region while hovering. Partial alpha
   is stored separately from the SAM mask.
5. Optionally apply reversible per-layer erosion and final-edge feathering.
6. Use **Generate layer artifacts** to materialize the selected layer's final
   mask, full-canvas RGBA, and cropped PNG.
7. Select **Composition** to preview the derived base plus every current layer in
   z order.
8. Use **Export composed scene** to generate the base, cropped layers, and YAML
   registration metadata together.

Changes autosave after a short delay; `Ctrl+S` saves immediately.

## Canvas controls

- Wheel: vertical scroll
- Shift+wheel: horizontal scroll
- Ctrl+wheel: pointer-centered zoom
- Middle-drag or Space+drag: pan
- `B`, `F`, `N`, `E`, `R`: box, positive, negative, erase, restore modes
- Right-click: negative SAM point while using a point mode
- `Ctrl+Z`: remove the last SAM point

SAM positive/negative prompts are single coordinates, so their hover cursor is a
fixed crosshair and one-pixel cell at high zoom; the region changed by SAM is
model-determined and has no brush radius or feather. Radius and feather apply to
the manual **Erase α** and **Paint α** modes, whose hover rings match the pixels
modified by clicking or dragging.

Zoom ranges up to 1600%. High zoom renders only the visible source tile, keeping
memory use bounded while exposing individual pixels.

## Project layout

```text
<workspace>/<scene>/
├── project.yml
├── source/
│   ├── background.png
│   └── original.<ext>
├── layers/<layer>/
│   ├── sam-mask.png
│   ├── manual-alpha.png
│   ├── final-mask.png
│   ├── rgba.png
│   └── session.json
├── work/cropped/<layer>.png
└── export/
    ├── base.png
    ├── layers/<layer>.png
    └── scene-layers.yml
```

`manual-alpha.png` is an LA PNG. Its luminance stores the override value and its
alpha channel distinguishes an override from “use the SAM mask.” Recomputing SAM
therefore does not destroy hand-painted corrections.

`export/base.png` is an RGBA base with fully opaque extracted-layer coverage
removed from its alpha channel. Source pixels remain beneath partially transparent
feathered fringes because that is required to reconstruct the original opaque
scene exactly. Compositing the base with the cropped layers in YAML z order
rebuilds the source. Each layer entry records
`source_rect` plus a local `canvas_origin` offset, allowing the crop to be placed
back on the source canvas exactly.

This is a visible-only separation: moving or deleting an extracted object can
reveal an unreconstructed region. Clean-plate inpainting remains a later stage.

## Tests

```bash
python -m unittest discover -s tests -v
```

See [the authoring specification](doc/xadv2-layer-segmentation-tool-spec.md) and
[the multilayer background pipeline](doc/multilayer-background-pipeline.md) for
the broader design.
