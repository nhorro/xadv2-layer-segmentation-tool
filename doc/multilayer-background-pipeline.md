---
title: "Pipeline de generación de escenarios multicapa"
subtitle: "De una imagen base a capas registradas para XADV2"
lang: es-AR
date: 2026-08-27
version: "0.1"
status: "draft"
---

# 1. Objetivo y alcance

Este documento describe el pipeline para transformar una imagen base de un escenario 2D en una escena multicapa apta para composición, oclusión y animación parcial en XADV2.

El objetivo no es reconstruir una escena 3D ni separar físicamente iluminación, materiales y geometría. Se busca producir una representación 2D práctica que permita:

- colocar personajes entre capas;
- ocultarlos correctamente detrás de objetos;
- separar foreground decorativo;
- aislar props potencialmente animables;
- conservar la composición y perspectiva exactas de la imagen generada;
- reconstruir la escena original al recomponer las capas.

La estrategia parte de **una única imagen base coherente**. No se generan las capas independientemente, porque ese enfoque puede producir inconsistencias de perspectiva, geometría y estilo.

# 2. Principio central

```text
imagen base coherente
        ↓
plan de capas
        ↓
segmentación asistida
        ↓
refinado de alpha
        ↓
cropping + registro espacial
        ↓
reconstrucción de zonas ocultas cuando sea necesaria
        ↓
escena multicapa
```

La imagen base es la referencia geométrica canónica.

Todas las capas extraídas deben permanecer registradas respecto del mismo canvas original.

# 3. Restricciones recomendadas para la imagen fuente

Aunque la segmentación se realiza después de generar la imagen, conviene diseñar el background para facilitarla.

## 3.1. Cámara y perspectiva

Para personajes 2D que no cambian su perspectiva interna:

- composición frontal;
- profundidad comprimida;
- perspectiva aplanada o cuasi-ortográfica;
- poco escorzo;
- evitar gran angular;
- verticales estables;
- plano caminable claramente legible.

No se busca ortografía geométrica estricta: debe conservarse suficiente profundidad para que la escena se lea espacialmente.

## 3.2. Dirección visual

Favorecer:

- siluetas claras;
- separación visual entre objetos;
- contornos relativamente legibles;
- texturas controladas;
- iluminación suave;
- pocas sombras proyectadas entre objetos de distintas capas.

Una estética con line art o bordes más explícitos puede mejorar tanto la segmentación como la integración con personajes ilustrados.

## 3.3. Iluminación

La iluminación general seguirá estando horneada en la imagen.

Conviene minimizar:

- sombras largas entre capas;
- haces de luz que atraviesen varios objetos;
- reflejos compartidos fuertes;
- highlights especulares que fusionen visualmente superficies.

# 4. Definición de capas

No es necesario separar cada objeto visible.

Sólo deben extraerse elementos con utilidad de composición o gameplay.

Tipos típicos:

## 4.1. Base

Parte más profunda de la escena:

- paredes;
- piso;
- puertas;
- ventanas;
- estanterías estructurales;
- elementos que nunca deben pasar delante del personaje.

## 4.2. Occluders / midground

Elementos detrás de los cuales puede pasar un personaje:

- escritorio;
- mostrador;
- mesa;
- columna;
- mobiliario.

## 4.3. Obstáculos

Elementos que además de ocultar al personaje pueden afectar navegación o colisión.

Ejemplo:

- ventilador de pie;
- carrito;
- maceta grande.

La navegación no forma parte de esta primera tool, pero la clasificación puede conservarse como metadata.

## 4.4. Foreground

Elementos decorativos de primer plano:

- plantas;
- cajas;
- libros;
- muebles cortados por el borde inferior.

Pueden cubrir la zona inferior no caminable de la pantalla.

## 4.5. Props animables

Elementos candidatos a animación independiente:

- ventilador;
- cortina;
- lámpara;
- humo;
- reflejos;
- hojas.

Una capa animable puede requerir reconstrucción adicional de regiones ocultas.

# 5. Proyecto de background

```text
<scene-name>/
├── project.yml
│
├── source/
│   ├── background.png
│   ├── prompts.md
│   └── style-references/
│
├── layers/
│   └── <layer-name>/
│       ├── sam-mask.png
│       ├── manual-alpha.png
│       ├── final-mask.png
│       ├── session.json
│       └── rgba.png
│
├── work/
│   ├── clean-plate.png
│   ├── inpaint-masks/
│   └── cropped/
│
└── export/
    ├── base.png
    ├── layers/
    └── scene-layers.yml
```

# 6. Fase 1 — Imagen base

La imagen generada se guarda sin modificaciones en:

```text
source/background.png
```

También se conservan:

- prompt;
- referencias;
- modelo/servicio;
- fecha;
- información necesaria para regenerar una variante.

### Quality gate

La imagen debe rechazarse antes de segmentar si:

- la perspectiva es incompatible con los personajes;
- existen objetos importantes fusionados de manera difícil de separar;
- la zona caminable resulta confusa;
- un objeto que debe actuar como occluder queda parcialmente fuera del canvas;
- el layout no admite la interacción prevista.

# 7. Fase 2 — Plan de capas

Antes de segmentar se define una lista explícita:

```yaml
layers:
  - name: desk
    role: occluder
    z: 20

  - name: fan
    role: obstacle
    z: 30

  - name: foreground-bottom
    role: foreground
    z: 100
```

El objetivo es evitar segmentar elementos sin utilidad real.

La propiedad `z` expresa orden lógico de composición, no necesariamente el valor runtime final de XADV2.

# 8. Fase 3 — Segmentación asistida

La implementación inicial utiliza SAM2.1.

Workflow por capa:

1. crear la capa y asignarle nombre;
2. dibujar bounding box;
3. obtener máscara inicial;
4. agregar puntos positivos;
5. agregar puntos negativos;
6. inspeccionar sobre la imagen;
7. aceptar la máscara semántica.

Se conservan:

- bounding box;
- clicks positivos/negativos;
- modelo;
- score;
- máscara SAM.

Estos datos permiten reproducir o continuar la sesión.

# 9. Fase 4 — Corrección manual de alpha

La máscara SAM no debe editarse destructivamente.

Se mantiene:

```text
SAM mask
+
manual alpha override
=
final alpha
```

Esto permite:

- continuar refinando con SAM;
- borrar artefactos manuales;
- restaurar regiones;
- conservar provenance.

## 9.1. Edición fina

La herramienta debe permitir:

- zoom alto;
- pan;
- borrador;
- restauración;
- visualización sobre transparencia;
- fondos de preview contrastantes.

El pincel debería admitir posteriormente alpha parcial/soft brush.

# 10. Fase 5 — Edge cleanup

Los bordes de una capa pueden contener píxeles contaminados por el background original.

El pipeline puede aplicar opcionalmente un filtro no destructivo de edge cleanup.

No conviene aplicar un blur global de la máscara.

Parámetros propuestos:

```yaml
edge_cleanup:
  erode_px: 1
  feather_px: 1
```

Proceso conceptual:

1. partir del `final alpha`;
2. contraer levemente la región opaca;
3. generar una transición de alpha sólo alrededor del nuevo borde;
4. preservar interiores opacos.

Una implementación posible es utilizar distance transform + `smoothstep`.

### Riesgo

Un erosionado excesivo destruye:

- cables;
- patas finas;
- hojas;
- pelo;
- objetos angostos.

Por lo tanto:

- debe ser opcional;
- configurable por capa;
- previsualizable;
- reversible.

# 11. Fase 6 — Cropping

Una vez establecido el alpha final, se calcula el bounding rectangle de los píxeles cuyo alpha supera un threshold configurable.

Ejemplo:

```yaml
crop:
  alpha_threshold: 10
  margin: 2
```

El crop:

- no modifica `rgba.png` fuente;
- genera un artefacto derivado;
- se expande por `margin`;
- queda limitado al canvas original.

# 12. Registro espacial y pivots

El crop no debe alterar la posición aparente de la capa.

Toda capa conserva:

```yaml
source_size:
  width: 1792
  height: 768

source_rect:
  x: 642
  y: 260
  width: 430
  height: 304
```

Esto alcanza para reconstruir su ubicación en el canvas original.

## 12.1. Canvas origin

Se define además un anchor conceptual común:

```text
canvas_origin = (0, 0)
```

Para una capa croppeada cuyo `source_rect` comienza en `C`:

```text
local canvas_origin = (0, 0) - C
```

Si todas las capas posicionan ese anchor en el origen de la escena, recuperan automáticamente la composición original.

Este mecanismo es análogo a la preservación de pivots del pipeline de `AnimatedSprite`, donde:

```text
local anchor = canvas anchor - crop top-left
```

## 12.2. Pivots semánticos opcionales

Props transformables pueden agregar anchors específicos:

```text
rotation_pivot
hinge
fan_axis
interaction_point
```

Estos puntos se almacenan primero en coordenadas del canvas original y se traducen a coordenadas locales al exportar.

# 13. Fase 7 — Reconstrucción de regiones ocultas

Segmentar un objeto sólo recupera los píxeles visibles.

Los píxeles que estaban detrás de él no existen en la imagen fuente.

Por lo tanto hay dos niveles de capa:

## 13.1. Visible-only layer

Suficiente cuando:

- el objeto permanece siempre en su posición;
- sólo se necesita que un personaje pase delante/detrás;
- las partes ocultas nunca serán reveladas.

## 13.2. Complete layer

Necesaria cuando:

- el objeto se mueve;
- se anima;
- se elimina;
- puede revelar una región originalmente oculta.

En este caso se debe reconstruir por inpainting o edición manual.

# 14. Clean plate

Para obtener una base libre de occluders:

1. combinar las máscaras de objetos que deben removerse;
2. dilatar ligeramente la máscara de remoción para cubrir contaminación de borde;
3. reconstruir la región mediante inpainting;
4. inspeccionar manualmente.

La clean plate es un artefacto derivado:

```text
work/clean-plate.png
```

No reemplaza `source/background.png`.

# 15. Orden de reconstrucción

Cuando existen objetos superpuestos, el orden importa.

Regla recomendada:

> modelar explícitamente el z-order antes de reconstruir regiones ocultas.

No debe asumirse que la segmentación de un objeto produce automáticamente una versión completa del mismo.

La reconstrucción de props individuales debe tratarse como una fase adicional, no como parte de SAM.

# 16. Preview de composición

Antes de exportar se debe poder recomponer:

```text
base
+ layers ordenadas por z
```

y comparar contra `source/background.png`.

Idealmente se ofrece además:

```text
base
+ character test sprite
+ occluders
+ foreground
```

para validar la función real de las capas.

# 17. Export

Formato preliminar:

```text
export/
├── base.png
├── layers/
│   ├── desk.png
│   ├── fan.png
│   └── foreground-bottom.png
└── scene-layers.yml
```

Ejemplo conceptual:

```yaml
version: 1

source_size:
  width: 1792
  height: 768

base:
  image: base.png

layers:
  - name: desk
    image: layers/desk.png
    role: occluder
    z: 20

    source_rect:
      x: 642
      y: 260
      width: 430
      height: 304

    anchors:
      canvas_origin:
        x: -642
        y: -260
```

Este manifest todavía no debe considerarse formato runtime de XADV2.

# 18. Reproducibilidad

Por cada capa deben preservarse:

- nombre;
- rol;
- z-order;
- bounding box;
- positivos;
- negativos;
- modelo SAM;
- máscara SAM;
- manual alpha overrides;
- parámetros de edge cleanup;
- crop;
- source rect;
- pivots/anchors;
- inpainting source y máscara cuando aplique.

# 19. Quality gates

## 19.1. Segmentación

Aceptar cuando:

- el objeto completo está incluido;
- no hay regiones ajenas importantes;
- detalles finos necesarios permanecen;
- la corrección manual restante es razonable.

## 19.2. Bordes

Inspeccionar al menos sobre:

- negro;
- blanco;
- transparencia/checkerboard;
- fondo de juego representativo.

## 19.3. Cropping

Verificar que recomponer mediante `source_rect` o `canvas_origin` produce la misma posición que la imagen original.

## 19.4. Scene preview

Verificar:

- orden correcto;
- personaje detrás/delante de occluders;
- ausencia de halos obvios;
- foreground consistente;
- no aparecen huecos no reconstruidos.

# 20. Aspectos pendientes

- modelo y herramienta de inpainting;
- formato runtime definitivo de background multicapa en XADV2;
- soft brush y alpha parcial;
- edge cleanup óptimo;
- definición de roles runtime;
- integración con navegación;
- soporte de props animados;
- eventual packing de layers;
- máscaras de interacción/colisión;
- detección automática de objetos candidatos a capa.
