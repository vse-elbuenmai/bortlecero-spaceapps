# DESIGN.md · sistema de diseño del proyecto

Fuente única de diseño para la web del reto. Quien escriba interfaz (persona o agente) sigue este
archivo. Si algo no está aquí, se decide en equipo y se añade aquí en el mismo commit.

**De dónde sale.** Es una adaptación de **Noir Cósmico v2** (2 oct 2026), el design system que Miguel
escribió para los sitios de Bortle Cero (Puente Estelar, Firmamento, Observatorio de Bortle) antes del
hackatón y sin relación con Space Apps. **Se reutilizan los valores y las reglas** (paleta, escala
tipográfica, espaciado, radios, movimiento, accesibilidad). **No se copia código** de esos sitios
(regla 7 de [AGENTS.md](AGENTS.md)). Está citado en [docs/SOURCES.md](docs/SOURCES.md) como trabajo
previo.

**Lo nuevo de esta versión:** está pensada para un visor científico (parpadeo de imágenes, marcas sobre
la imagen, metadatos, avisos de calidad) y no para un sitio editorial. Va sólo en inglés y no lleva el
menú «Experiencias» de la familia Bortle Cero.

---

## 1. Principios

1. **El dato manda.** La imagen de SPHEREx es la protagonista: la interfaz se queda oscura, plana y
   callada alrededor de ella. Nada decorativo encima de la imagen.
2. **Honestidad visual.** Lo que se ve tiene que ser lo que mide el telescopio. El zoom no suaviza
   píxeles, una marca dice si es «predicha» o «medida», y una foto saturada o de otro color lo avisa.
3. **El estado nunca va sólo en el color.** Siempre lleva texto, icono o forma (regla heredada).
4. **Accesible por defecto.** Contraste AA, foco visible, objetivos de 44 px, teclado completo y
   respeto a `prefers-reduced-motion`. En un parpadeo, además, límite de destellos (§8).
5. **En inglés.** Todo texto visible, `alt`, `aria-label` y mensajes de error.

---

## 2. Color

Sólo tema oscuro (`color-scheme: dark`). Una imagen astronómica se lee mejor sobre negro, y el sistema
de origen no tiene tema claro.

### 2.1 Superficies (de más oscura a más clara)

| Token | Hex | Uso |
|---|---|---|
| `--bc-abismo` | `#04070b` | Fondo del lienzo del visor, halo de las marcas |
| `--bc-cosmos` | `#080c14` | Fondo de página |
| `--bc-noche` | `#0d1625` | Paneles, tarjetas, barra de controles |
| `--bc-horizonte` | `#1a2840` | Hover de filas, superficie elevada, pista del deslizador |

### 2.2 Texto (contraste medido sobre `--bc-cosmos`)

| Token | Hex | Contraste | Uso |
|---|---|---|---|
| `--bc-blanco` | `#f0f6ff` | 18.0:1 | Títulos, valores destacados, enlace activo |
| `--bc-texto` | `#c8d8ec` | 13.5:1 | **Texto de lectura** y texto de paneles |
| `--bc-estrella` | `#b8d4f0` | 12.8:1 | Botón principal, hover, estado activo, foco |
| `--bc-muted` | `#96a6ba` | 7.9:1 | **Sólo** secundario: unidades, notas, pies de foto |
| `--bc-acento` | `#7ba8d4` | 7.8:1 | Enlaces en el texto, eyebrows, etiquetas |
| `--bc-tenue` | `#4a6080` | 3.05:1 | **Nunca texto.** Bordes y ornamento |

- La lectura va en `--bc-texto`, no en `--bc-muted`.
- Sobre `--bc-horizonte`, `--bc-acento` baja a 5.91:1: ahí no usarlo por debajo de 14 px.

### 2.3 Bordes

| Token | Hex | Uso |
|---|---|---|
| `--bc-border` | `#2a4060` | Borde por defecto (1 px) |
| `--bc-border-soft` | `#1a2840` | Separadores suaves, línea bajo la cabecera |

Hover de borde: `--bc-acento`. Los bordes son de 1 px, nunca de 0.5 px.

### 2.4 Estado

| Token | Hex | Contraste | Uso |
|---|---|---|---|
| `--bc-ok` | `#4ade80` | 11.2:1 | Validación correcta (p. ej. «matches Gaia») |
| `--bc-aviso` | `#d4a870` | 9.0:1 | Precaución: saturación, color distinto, datos parciales |
| `--bc-error` | `#f87171` | 7.1:1 | Error, coordenada inválida, servicio caído |

### 2.5 Colores de datos (marcas sobre la imagen)

Las marcas tienen que verse sobre una imagen en escala de grises, tanto en el fondo negro como sobre
una estrella blanca. Por eso son **colores saturados** que no son gris, llevan **un halo oscuro**
(`--bc-abismo`, 1 px por fuera) y se distinguen **también por la forma**, no sólo por el color.

| Token | Hex | Marca | Forma |
|---|---|---|---|
| `--viz-predicha` | `#6dd5c0` (teal) | Dónde debería estar la estrella (Gaia/SIMBAD propagado a la fecha) | Círculo **discontinuo**, 2 px |
| `--viz-medida` | `#d4a870` (ámbar) | Centroide medido en la foto | Cruz **continua**, 2 px, con hueco central |
| `--viz-trayectoria` | `#b4a0f0` (violeta) | Recorrido entre fechas | Línea punteada de 1.5 px con un punto por fecha |
| `--viz-bandera` | `#f87171` al 35 % | Píxeles con bandera de FLAGS | Relleno semitransparente; se puede apagar |
| `--viz-reticula` | `#96a6ba` al 40 % | Rejilla de coordenadas, escala | Línea de 1 px |

Reglas:

- Toda marca tiene su entrada en la **leyenda** con texto («Predicted (Gaia DR3)», «Measured
  centroid»).
- El hueco central de la cruz y el círculo discontinuo dejan ver la estrella: **la marca no tapa el
  dato**.
- Con daltonismo rojo-verde, el teal y el ámbar se siguen separando por luminosidad y por la forma.

### 2.6 La imagen

- La imagen se muestra en **escala de grises**. Si el equipo usa un mapa de color, que sea
  perceptualmente uniforme (p. ej. *magma* o *inferno*) y que salga en la leyenda con su escala.
- El estirado (asinh u otro) se aplica al preparar los datos y es el mismo para todas las fotos de una
  serie. Si cambia, el parpadeo miente.
- Nada de filtros CSS sobre la imagen (`brightness`, `contrast`): alteran el dato sin decirlo.

---

## 3. Tipografía

**Space Grotesk** variable, autoalojada (licencia SIL OFL 1.1). No se carga desde Google Fonts.

```css
--bc-font: "Space Grotesk", system-ui, sans-serif;
--bc-font-mono: ui-monospace, "SFMono-Regular", Consolas, monospace; /* sólo para coordenadas */
```

### 3.1 Escala

| Token | Escritorio | Móvil (≤ 760 px) | Peso | Color | Uso |
|---|---|---|---|---|---|
| `--bc-fs-hero` | `clamp(46px, 5.2vw, 78px)` | igual | 300 | blanco | H1 de la portada |
| `--bc-fs-2xl` | `clamp(31px, 3.25vw, 49px)` | igual | 300–400 | blanco | H2 de sección |
| `--bc-fs-xl` | 32 px | 28 px | 400 | blanco | H1 interior («How it works») |
| `--bc-fs-lg` | 24 px | 22 px | 500 | blanco | Nombre del objeto en el visor |
| `--bc-fs-md` | 19 px | 18 px | 500 | blanco o texto | H3, título de panel |
| `--bc-fs-body` | 17 px | 16 px | 400 | texto | Párrafos |
| `--bc-fs-base` | 16 px | 15 px | 400 | texto | Texto de paneles y diálogos |
| `--bc-fs-ui` | 15 px | 15 px | 500 | según componente | Botones, pestañas, controles |
| `--bc-fs-sm` | 14 px | 14 px | 400 | muted | Notas, pies, fuentes |
| `--bc-fs-xs` | 13 px | 13 px | 400 | acento o muted | Etiquetas de metadatos, contadores |
| `--bc-fs-micro` | 12 px | 12 px | 500 | acento | Eyebrows y tags, en mayúsculas |

### 3.2 Reglas

- **Piso: 12 px.** Se permite 11 px sólo en rótulos de datos densos que no pueden crecer (unidades de
  un eje, cifras del HUD sobre la imagen), nunca en frases. Nada por debajo de 11 px.
- **El peso baja cuando el tamaño sube:** 300 sólo desde 32 px; de 18 a 31 px, 500 en títulos y 400 en
  texto corrido; menos de 18 px, 400 (500 en botones, eyebrows y estados activos).
- Interlineado: títulos 1.09–1.3, lectura 1.7–1.75, interfaz 1.4–1.6.
- Eyebrows y tags en mayúsculas con `letter-spacing` de 0.14–0.18em. Tracking negativo sólo desde 24 px.
- **Cifras:** `font-variant-numeric: tabular-nums` en toda cifra que cambie o se compare (fechas,
  longitud de onda, contador de fotos, coordenadas), para que no bailen al parpadear.
- **Coordenadas** (RA/Dec, sexagesimales) en `--bc-font-mono` a `--bc-fs-xs` o mayor.
- Si una etiqueta no cabe, **se acorta el texto**, no se baja el tamaño.

---

## 4. Espaciado y retícula

Escala base de 4 px.

| Token | Valor | Uso |
|---|---|---|
| `--bc-sp-2xs` | 4 px | Entre icono y texto en un control compacto |
| `--bc-sp-xs` | 8 px | Entre tags, iconos y botones de una barra |
| `--bc-sp-s` | 16 px | Padding de panel compacto, gaps internos |
| `--bc-sp-m` | 32 px | Entre bloques |
| `--bc-sp-l` | 60 px | Padding de sección |
| `--bc-sp-xl` | 100 px | Entre secciones grandes |

- **Contenedor:** `width: min(1360px, 100%)` con `padding-inline` de 64 px → 36 px (≤ 1100 px) →
  16 px (≤ 760 px). Sin scroll horizontal a 360 px de ancho.
- **Lectura** (página «How it works»): `max-width` de 740–860 px.
- **Visor:** ver §7.1 para su retícula propia.

---

## 5. Forma y elevación

| Elemento | Radio |
|---|---|
| Control pequeño: botón, input, chip | 4 px |
| Panel, tarjeta | 10 px (`--bc-radius`) |
| Contenedor grande, diálogo | 16 px |
| Pill, tag | 20 px |
| Botón de icono | 50 % |
| **Lienzo de la imagen** | **0**: los píxeles llegan al borde |

El sistema se apoya en superficies, no en sombras. Sólo hay tres:

```css
/* desplegable o diálogo */   box-shadow: 0 18px 40px #03060acc;
/* botón principal en hover */ box-shadow: 0 6px 20px rgba(123, 168, 212, 0.25);
/* barra de progreso */        box-shadow: 0 0 14px rgba(123, 168, 212, 0.6);
```

---

## 6. Movimiento

| Duración | Uso |
|---|---|
| `0.15s ease` | Color y borde (`--bc-transition`) |
| `0.2s ease` | Botones, hover de superficie, `translateY(-2px)` |
| `0.5s cubic-bezier(.4, 0, .2, 1)` | Barra de progreso de carga |

- **El cambio de foto del parpadeo es un corte seco**, sin fundido. Un fundido mezcla dos fechas y
  esconde justo el movimiento que se quiere ver.
- El zoom y el desplazamiento de la imagen siguen al cursor o al dedo, sin inercia ni animación.
- `prefers-reduced-motion: reduce` es obligatorio: se apagan transiciones y **el parpadeo no arranca
  solo** (§8).

```css
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
```

---

## 7. Componentes

### 7.1 Visor de parpadeo (el componente principal)

```
┌──────────────────────────────────────────────┬──────────────────────┐
│                                              │  OBJECT              │
│                                              │  Barnard's Star      │
│              lienzo de la imagen             │  RA / Dec · FOV      │
│          (cuadrado, norte arriba, este a     │──────────────────────│
│           la izquierda, marcas encima)       │  FRAME 2 / 3         │
│                                              │  2026-05-04 UTC      │
│  N ↑  E ←                         ── 30″     │  4.85 µm · det. 6    │
│                                              │  DR1 · PA 0°         │
├──────────────────────────────────────────────┤  ⚠ Saturated core    │
│  ◀  ▶❚❚  ▶   speed ──●── 1 fps   ⊕ ⊖ ⟲       │──────────────────────│
│  ●───────●───────────────●  (línea de fechas)│  Legend · Flags ☐    │
└──────────────────────────────────────────────┴──────────────────────┘
```

- **Lienzo:** cuadrado (`aspect-ratio: 1`), fondo `--bc-abismo`, radio 0. En escritorio ocupa ~2/3
  del ancho y el panel de datos el tercio restante; en ≤ 1100 px el panel pasa debajo.
- **Píxeles nítidos:** `image-rendering: pixelated` en la imagen y en el canvas. El zoom va por
  factores enteros (1×, 2×, 4×, 8×) para que cada píxel de SPHEREx (6.15″) se vea como un bloque
  parejo.
- **Orientación siempre visible:** rosa de N/E en una esquina y barra de escala en segundos de arco en
  otra, en `--bc-fs-xs` sobre una placa `rgba(4, 7, 11, 0.7)`.
- **Todas las fotos de una serie** van en la misma cuadrícula, con el mismo encuadre y el mismo estirado.
  Cambiar de foto no mueve el lienzo.

### 7.2 Controles de reproducción

| Control | Especificación |
|---|---|
| Anterior / siguiente | Botones de icono de 44 × 44, `aria-label="Previous frame"` / `"Next frame"` |
| Reproducir / pausa | Botón de icono de 44 × 44, `aria-pressed`; el icono y la etiqueta cambian |
| Velocidad | `<input type="range">` de 0.5 a **3 fotos por segundo** (§8), con valor en texto y `tabular-nums` |
| Zoom | Botones ⊕ ⊖ y «reset» (⟲); también rueda o pellizco sobre el lienzo |
| Línea de fechas | Un punto por foto, separados en proporción al tiempo real; el activo en `--bc-estrella` y más grande; cada punto es un botón con la fecha en su `aria-label` |

**Teclado** (sólo con el foco dentro del visor, para no robar teclas a la página): `Space`
reproducir o pausar, `←` / `→` foto anterior o siguiente, `+` / `−` zoom, `0` restablecer.

### 7.3 Panel de metadatos

- Lista de definiciones (`<dl>`): etiqueta en `--bc-fs-xs` / `--bc-muted` / mayúsculas; valor en
  `--bc-fs-base` / `--bc-blanco` / `tabular-nums`.
- Por foto: fecha y hora **en UTC** (formato ISO, `2026-05-04 07:12 UTC`), longitud de onda en µm,
  detector, entrega (DR1 o QR3), ángulo de posición y estado de calidad.
- El valor que cambia al pasar de foto se actualiza dentro de una región `aria-live="polite"` (sólo
  cuando el usuario cambia de foto a mano, no en reproducción automática).

### 7.4 Avisos de calidad (badges)

Pill de 20 px de radio, `--bc-fs-xs` / 500, icono + texto, fondo del color de estado al 10 % y borde
al 25 %. Siempre con texto; el icono va con `aria-hidden="true"`.

| Caso | Color | Texto de ejemplo |
|---|---|---|
| Núcleo saturado | aviso | `⚠ Saturated core` |
| La foto ve otro color que la anterior | aviso | `⚠ Different wavelength (4.85 → 3.10 µm)` |
| Imagen girada y corregida | acento | `↻ Rotated 180°, re-aligned` |
| Coincide con la predicción | ok | `✓ Within 0.3″ of Gaia` |
| Pocas fotos o datos parciales | aviso | `⚠ Only 2 epochs` |

### 7.5 Entrada de coordenadas

- Dos campos (RA y Dec) más un campo de búsqueda por nombre si el equipo lo implementa. Aceptan grados
  decimales y sexagesimales; el `placeholder` muestra los dos formatos.
- Input: alto mínimo 48 px, radio 4 px, fondo `--bc-noche`, borde `--bc-border`, foco con el contorno
  del sistema. Fuente `--bc-font-mono`.
- Error en línea bajo el campo, en `--bc-error`, con icono y texto («Dec must be between −90° and
  +90°»), enlazado con `aria-describedby`. El campo no cambia sólo de color.
- **Atajos a los cinco objetos de prueba** como chips de 44 px de alto: Barnard's Star, Epsilon Indi B,
  WISE 0855−0714, RW Aurigae, R Draconis.

### 7.6 Estados de carga, vacío y error

Todo estado lleva **frase + qué puede hacer la persona**. Nunca un spinner solo.

| Estado | Qué se ve |
|---|---|
| Cargando | Barra de progreso con el gradiente del sistema y «Loading 2 of 3 frames…» |
| Sin cobertura | «SPHEREx has no images of this position yet.» + enlace a los objetos de prueba |
| Servicio caído | «The NASA/IPAC archive (IRSA) is not responding. Try again or open a test object.» |
| Error de datos | «This frame could not be read.» y el visor sigue con las demás fotos |

Gradiente de progreso:

```css
background: linear-gradient(90deg, #060a16 0%, #122a52 30%, #2f5e9e 55%, #5b93cf 78%, #bfe0ff 100%);
```

### 7.7 Botones

| Variante | Especificación |
|---|---|
| Base | `inline-flex`, alto mínimo 48 px, padding 14 × 22 px, radio 4 px, `--bc-fs-ui` / 500, borde 1 px transparente |
| Principal | fondo `--bc-estrella`, texto `--bc-cosmos`; hover `#d8eafe` + sombra del §5 + `translateY(-2px)` |
| Secundario | fondo transparente, borde `#40516a`, texto `--bc-estrella`; hover fondo `--bc-noche` y borde `--bc-acento` |
| De icono | círculo de 44 × 44, borde `--bc-border`, icono de 20 px |
| Deshabilitado | `opacity: 0.45`, `cursor: not-allowed` |

Un solo botón principal por pantalla.

### 7.8 Tarjeta y panel

Fondo `--bc-noche`, borde 1 px `--bc-border`, radio 10 px, padding 24 px. Hover (si es clicable):
borde `--bc-acento` y `translateY(-3px)`.

### 7.9 Cabecera

- Alto 64 px en escritorio y en móvil (es una herramienta, no un sitio editorial). Fondo
  `rgba(8, 12, 20, 0.94)` con `backdrop-filter: blur(16px)` y línea inferior `--bc-border-soft`.
- Marca: `BORTLE CERO` (14 px / 500 / 0.12em / blanco), separador de 1 px, y el **nombre del
  proyecto** en 12 px / 500 / mayúsculas / 0.18em / `--bc-acento`. El nombre lo decide el equipo.
- Enlaces: «Viewer», «How it works», «Sources». Hamburguesa en ≤ 760 px con botón de 44 × 44 y panel
  opaco `--bc-cosmos`.
- **Sin logos de la NASA ni identificadores de misión** (regla de Space Apps). El crédito de datos
  va en texto, en el pie.

### 7.10 Pie

- `--bc-fs-sm` / `--bc-muted`. Crédito de datos: «Data: NASA/JPL-Caltech/SPHEREx, via NASA/IPAC
  Infrared Science Archive (IRSA)», más los DOI de cada entrega usada.
- Enlaces a «Sources», «AI usage», la licencia (Apache 2.0) y el repositorio.
- «Built by team Bortle Cero for the NASA Space Apps Challenge 2026».

---

## 8. Accesibilidad

Es contrato, no recomendación.

- Contraste AA en todo texto (4.5:1; 3:1 desde 24 px).
- Foco visible: `outline: 2px solid var(--bc-estrella); outline-offset: 5px` (3 px dentro del
  visor). Nunca `outline: none` sin sustituto.
- Objetivos táctiles de 44 × 44 como mínimo. Botones de 48 px de alto.
- Enlace de salto («Skip to viewer»), oculto hasta recibir el foco.
- Todo el visor se maneja con teclado (§7.2).
- La imagen lleva un `alt` útil: «SPHEREx image of Barnard's Star, 2026-05-04, 4.85 µm».
- **Límite de destellos (WCAG 2.3.1):** el parpadeo no pasa de **3 cambios por segundo**. Es el tope
  del deslizador de velocidad.
- **`prefers-reduced-motion`:** el parpadeo empieza en pausa y la persona avanza foto a foto. Puede
  darle a reproducir si quiere.
- `color-scheme: dark` y `font-synthesis: none` en `:root`.
- `lang="en"` en `<html>`.

---

## 9. Contenido y tono (en inglés)

- Frases cortas y en voz activa. La persona usuaria es curiosa, no astrónoma: «The star moved 8″ north
  in 8 months», no «Proper motion vector detected».
- Unidades siempre con símbolo y espacio fino o normal: `4.85 µm`, `6.15″`, `10.39″/yr`.
- Fechas en UTC y formato ISO. Coordenadas en grados con 4 decimales, o en sexagesimal si la persona
  las escribió así.
- Los nombres de los objetos van como en SIMBAD («Barnard's Star», «WISE 0855−0714», con signo menos
  real `−`).
- Cada número científico que se muestre lleva su fuente cerca o en «Sources».

---

## 10. Tokens

```css
:root {
  color-scheme: dark;
  font-synthesis: none;

  /* superficies */
  --bc-abismo: #04070b;
  --bc-cosmos: #080c14;
  --bc-noche: #0d1625;
  --bc-horizonte: #1a2840;

  /* texto */
  --bc-blanco: #f0f6ff;
  --bc-texto: #c8d8ec;
  --bc-estrella: #b8d4f0;
  --bc-muted: #96a6ba;
  --bc-acento: #7ba8d4;
  --bc-tenue: #4a6080; /* nunca texto */

  /* bordes */
  --bc-border: #2a4060;
  --bc-border-soft: #1a2840;

  /* estado */
  --bc-ok: #4ade80;
  --bc-aviso: #d4a870;
  --bc-error: #f87171;

  /* datos sobre la imagen */
  --viz-predicha: #6dd5c0;
  --viz-medida: #d4a870;
  --viz-trayectoria: #b4a0f0;
  --viz-bandera: rgba(248, 113, 113, 0.35);
  --viz-reticula: rgba(150, 166, 186, 0.4);
  --viz-halo: #04070b;

  /* tipografía */
  --bc-font: "Space Grotesk", system-ui, sans-serif;
  --bc-font-mono: ui-monospace, "SFMono-Regular", Consolas, monospace;
  --bc-fs-hero: clamp(46px, 5.2vw, 78px);
  --bc-fs-2xl: clamp(31px, 3.25vw, 49px);
  --bc-fs-xl: 32px;
  --bc-fs-lg: 24px;
  --bc-fs-md: 19px;
  --bc-fs-body: 17px;
  --bc-fs-base: 16px;
  --bc-fs-ui: 15px;
  --bc-fs-sm: 14px;
  --bc-fs-xs: 13px;
  --bc-fs-micro: 12px;

  /* espaciado */
  --bc-sp-2xs: 4px;
  --bc-sp-xs: 8px;
  --bc-sp-s: 16px;
  --bc-sp-m: 32px;
  --bc-sp-l: 60px;
  --bc-sp-xl: 100px;

  /* forma y movimiento */
  --bc-radius-sm: 4px;
  --bc-radius: 10px;
  --bc-radius-lg: 16px;
  --bc-radius-pill: 20px;
  --bc-transition: 0.15s ease;
  --bc-header-h: 64px;
}

@media (max-width: 760px) {
  :root {
    --bc-fs-xl: 28px;
    --bc-fs-lg: 22px;
    --bc-fs-md: 18px;
    --bc-fs-body: 16px;
    --bc-fs-base: 15px;
  }
}

body {
  margin: 0;
  background: var(--bc-cosmos);
  color: var(--bc-texto);
  font-family: var(--bc-font);
  font-size: var(--bc-fs-body);
  line-height: 1.7;
}

:focus-visible {
  outline: 2px solid var(--bc-estrella);
  outline-offset: 5px;
}

::selection {
  background: rgba(123, 168, 212, 0.25);
  color: var(--bc-blanco);
}
```

---

## 11. Antes de dar por buena una pantalla

- [ ] Ningún texto por debajo de 12 px (salvo los rótulos de datos del §3.2) ni en `--bc-tenue`.
- [ ] Se ve bien a 360, 768 y 1440 px de ancho, sin scroll horizontal.
- [ ] Todo se puede hacer con el teclado y el foco se ve.
- [ ] El parpadeo no pasa de 3 fotos por segundo y arranca en pausa con movimiento reducido.
- [ ] La imagen se ve pixelada al hacer zoom, no borrosa.
- [ ] Cada marca y cada aviso tiene texto o leyenda, no sólo color.
- [ ] Todo el texto visible está en inglés.
- [ ] El crédito de datos de la NASA está en el pie y la fuente nueva está en `docs/SOURCES.md`.
