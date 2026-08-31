---
title: "XADV2 Layer Segmentation Tool"
subtitle: "Especificación preliminar de authoring para backgrounds multicapa"
lang: es-AR
date: 2026-08-27
version: "0.1"
status: "draft"
related:
  - multilayer-background-pipeline.md
  - xadv2-content-authoring-workspace.md
---

# 1. Propósito

Esta herramienta permite tomar una imagen base de background y definir un conjunto de capas RGBA registradas respecto del canvas original.

Su función principal es resolver de forma eficiente la segmentación interactiva y preparar los artefactos necesarios para el pipeline de escenarios multicapa.

El motor de segmentación inicial es SAM2.1.

# 2. Estado validado experimentalmente

El prototipo actual ya demostró que es viable:

- cargar SAM2 localmente sobre GPU;
- definir múltiples capas;
- dibujar bounding boxes;
- refinar con puntos positivos y negativos;
- visualizar la máscara;
- aplicar correcciones manuales de alpha;
- exportar mask/cutout/session.

La segmentación, considerada el principal riesgo técnico, ha dado resultados suficientemente prometedores.

# 3. Alcance del MVP

El MVP debe cubrir:

1. gestión de proyecto;
2. definición de capas;
3. segmentación SAM2;
4. refinamiento interactivo;
5. edición manual de alpha;
6. cropping;
7. registro espacial;
8. preview de composición;
9. export de capas y metadata.

Inpainting puede integrarse después como una fase adicional.

# 4. Modelo de proyecto

Un proyecto representa una escena base:

```text
<workspace>/<scene-name>/
├── project.yml
├── source/
├── layers/
├── work/
└── export/
```

`project.yml` es la fuente de verdad de authoring.

# 5. Requerimientos funcionales

## 5.1. Proyecto

**LS-F-01.** Crear un nuevo proyecto a partir de una imagen fuente.

**LS-F-02.** Abrir un proyecto existente.

**LS-F-03.** Guardar automáticamente o de forma explícita el estado de authoring.

**LS-F-04.** No modificar destructivamente la imagen fuente.

**LS-F-05.** Seleccionar un workspace y descubrir/crear escenas directamente
dentro de él desde la UI.

## 5.2. Gestión de capas

**LS-F-10.** Agregar una capa con nombre único.

**LS-F-11.** Renombrar una capa.

**LS-F-12.** Eliminar una capa.

**LS-F-13.** Reordenar capas.

**LS-F-14.** Asignar opcionalmente rol:

```text
occluder
obstacle
foreground
animated-prop
other
```

**LS-F-15.** Definir z-order.

## 5.3. Bounding box

**LS-F-20.** Dibujar el bounding box directamente sobre el canvas.

**LS-F-21.** Redibujarlo sin recrear la capa.

**LS-F-22.** Actualizar la segmentación al modificarlo.

**LS-F-23.** El bounding box es un límite duro: máscaras y derivados deben ser
transparentes fuera de la región seleccionada, incluso después de feathering.

## 5.4. SAM prompts

**LS-F-30.** Click positivo para foreground.

**LS-F-31.** Click negativo para background.

**LS-F-32.** Deshacer el último prompt.

**LS-F-33.** Limpiar prompts.

**LS-F-34.** Conservar prompts en el proyecto.

**LS-F-35.** Reutilizar embeddings de imagen para evitar recomputación innecesaria.

## 5.5. Alpha manual

**LS-F-40.** Borrador de alpha.

**LS-F-41.** Restauración de alpha.

**LS-F-42.** Ajuste de tamaño del pincel.

Radio `0` representa exactamente un píxel del canvas fuente.

**LS-F-43.** Los retoques manuales deben persistir separadamente de la máscara SAM.

**LS-F-44.** Recalcular SAM no debe destruir los overrides manuales.

**LS-F-45.** Soft brush con transición de alpha/feather configurable.

## 5.6. Navegación del canvas

**LS-F-50.** Zoom in/out.

**LS-F-51.** Zoom suficiente para edición pixel-level.

Valor objetivo preliminar:

```text
800%–1600%
```

**LS-F-52.** Mouse wheel debe scrollear verticalmente cuando no modifica zoom.

**LS-F-53.** Shift + wheel debería scrollear horizontalmente.

**LS-F-54.** Ctrl + wheel o gesto equivalente debería controlar zoom.

**LS-F-55.** Pan mediante botón central o Space + drag.

**LS-F-56.** Fit-to-window.

**LS-F-57.** Mostrar coordenadas de píxel del canvas fuente en tiempo real.

## 5.7. Preview

**LS-F-60.** Preview overlay.

**LS-F-61.** Preview mask.

**LS-F-62.** Preview cutout.

**LS-F-63.** Preview sobre checkerboard.

**LS-F-64.** Preview sobre negro/blanco/color seleccionable.

**LS-F-65.** Mostrar/ocultar bounding box y puntos.

**LS-F-66.** Previsualizar la composición de base + capas ordenadas por `z`.

## 5.8. Edge cleanup

**LS-F-70.** Edge cleanup opcional por capa.

**LS-F-71.** Parámetro `erode_px`.

**LS-F-72.** Parámetro `feather_px`.

**LS-F-73.** La operación debe ser no destructiva.

**LS-F-74.** Preview antes de exportar.

## 5.9. Cropping

**LS-F-80.** Calcular crop por alpha.

**LS-F-81.** Configurar alpha threshold.

**LS-F-82.** Configurar margin.

**LS-F-83.** Preservar `source_size`.

**LS-F-84.** Preservar `source_rect`.

**LS-F-85.** No alterar el asset RGBA full-canvas.

## 5.10. Registro espacial

**LS-F-90.** Definir `canvas_origin` común.

**LS-F-91.** Exportar el anchor local compensando el crop.

```text
local anchor = canvas anchor - crop top-left
```

**LS-F-92.** Permitir pivots adicionales para props transformables.

## 5.11. Export

**LS-F-100.** Exportar PNG croppeado por capa.

**LS-F-101.** Exportar máscara final.

**LS-F-102.** Exportar metadata espacial.

**LS-F-103.** Exportar manifest de escena.

**LS-F-104.** Exportar todas las capas en una operación.

# 6. Requerimientos de performance

## 6.1. SAM

La imagen debe codificarse una sola vez por proyecto/sesión mientras no cambie.

Los clicks de refinamiento sólo deben ejecutar las fases necesarias del predictor.

## 6.2. Pincel manual

El prototipo actual actualiza/re-renderiza demasiado contenido por cada evento de movimiento.

El pincel debe optimizarse evitando:

- reconstruir la imagen completa en cada pixel de mouse motion;
- reescalar todo el canvas por cada muestra;
- regenerar PhotoImage completo cuando sólo cambia una pequeña región.

Opciones:

- acumular strokes y renderizar a frecuencia limitada;
- dirty rectangles;
- editar buffer numpy/PIL de resolución nativa;
- refrescar preview a 30–60 Hz;
- aplicar el stroke final al soltar mouse.

El detalle de implementación queda abierto.

# 7. Arquitectura sugerida

Separar:

```text
layer_segmentation/
├── model/
│   ├── project.py
│   ├── layer.py
│   └── serialization.py
│
├── processing/
│   ├── sam2_backend.py
│   ├── alpha.py
│   ├── crop.py
│   └── edge_cleanup.py
│
├── export/
│   └── scene_export.py
│
├── ui/
│   ├── app.py
│   ├── canvas.py
│   └── layer_panel.py
│
└── cli.py
```

La lógica de proyecto, máscaras, cropping y export no debe depender de Tk.

# 8. Backend de segmentación

Definir una interfaz conceptual:

```python
class SegmentationBackend:
    def set_image(self, image): ...
    def segment_box(self, box): ...
    def refine(self, points, labels, previous_state=None): ...
```

SAM2 es la primera implementación interactiva. RMBG-2.0 es una implementación
prompt-free: ejecuta matting sobre el crop delimitado por el box, conserva su
alpha suave y delega el refinamiento posterior a los pinceles manuales.

La selección se persiste como el par `backend`/`model`. La UI debe habilitar
points positivos/negativos solamente si el backend declara esa capacidad.

Esto permite evaluar otros modelos sin reescribir la UI.

# 9. Alpha model

Por capa:

```text
sam_alpha
manual_override
edge_cleanup_parameters
        ↓
final_alpha
```

`manual_override` debe soportar un estado “sin override”.

No debe confundirse:

```text
alpha = 0
```

con:

```text
no manual override
```

# 10. Formato preliminar de `project.yml`

```yaml
version: 1
name: archivo-interior

source:
  image: source/background.png
  width: 1792
  height: 768

segmentation:
  backend: sam2
  model: small

crop:
  alpha_threshold: 10
  margin: 2

layers:
  desk:
    role: occluder
    z: 20

    box: [642, 260, 1072, 564]

    points:
      - {x: 850, y: 420, label: 1}
      - {x: 700, y: 350, label: 0}

    edge_cleanup:
      erode_px: 1
      feather_px: 1

    crop_rect:
      x: 650
      y: 275
      width: 412
      height: 282

    anchors:
      canvas_origin: {x: 0, y: 0}
```

Las coordenadas de authoring se expresan siempre respecto del canvas fuente.

Los anchors locales de export son derivados.

# 11. Artefactos por capa

```text
layers/<name>/
├── sam-mask.png
├── manual-alpha.png
├── final-mask.png
├── rgba.png
└── session.json
```

`work/cropped/<name>.png` es derivado y regenerable.

# 12. UX objetivo

Panel izquierdo:

- lista de layers;
- Add/Rename/Delete;
- role;
- z-order.

Canvas central:

- imagen;
- overlay;
- zoom/pan;
- prompts;
- brush.

Panel/toolbox:

- Box;
- FG+;
- BG-;
- Erase alpha;
- Restore alpha;
- brush size;
- edge cleanup;
- crop preview.

# 13. Atajos preliminares

```text
B        Box
F        Foreground
N        Background
E        Erase alpha
R        Restore alpha

Ctrl+Z   Undo
Wheel    Vertical scroll
Shift+Wheel Horizontal scroll
Ctrl+Wheel Zoom
Space+Drag Pan
```

La asignación final debe resolver conflictos de teclas.

# 14. Persistencia

La tool debe guardar estado antes de depender únicamente del export.

Cerrar/reabrir un proyecto no debe requerir repetir:

- bounding boxes;
- clicks;
- manual edits;
- z-order;
- roles;
- crop/edge settings.

# 15. Invalidación

Cambios deben invalidar sólo derivados necesarios.

Ejemplos:

```text
box / SAM points
  -> invalida sam-mask, final alpha, crop, export
  -> conserva manual override cuando siga siendo espacialmente válido

manual override
  -> invalida final alpha, crop, export
  -> no invalida SAM

edge cleanup
  -> invalida final alpha/crop/export
  -> no invalida SAM/manual input

crop settings
  -> invalida crop/export
  -> no invalida máscaras
```

# 16. MVP inmediato para Codex

Prioridad 1:

- package/repo limpio;
- workspace externo;
- project open/save;
- layers persistentes;
- box + positive/negative;
- manual alpha;
- zoom/pan/scroll robusto.

Prioridad 2:

- cropping + `source_rect`;
- canvas origin;
- edge cleanup;
- export manifest;
- composición de preview.

Prioridad 3:

- clean plate/inpainting;
- roles runtime;
- props animables;
- integración directa con XADV2.

# 17. Problemas conocidos del prototipo

No bloqueantes:

- eraser lento;
- wheel scroll incompleto;
- zoom máximo insuficiente;
- navegación todavía básica.

Estos problemas se consideran de implementación/UX, no riesgos del enfoque.

# 18. Fuera de alcance por ahora

- generación de la imagen base;
- generación de prompts;
- edición pictórica general;
- modelado 3D;
- navegación/pathfinding;
- animación de props;
- inpainting automático definitivo;
- formato runtime final de XADV2.
