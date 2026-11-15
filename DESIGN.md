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
| `0.28s cubic-bezier(.2, .8, .3, 1)` | Entrada de un diálogo: sube 16 px y aparece; el fondo oscuro aparece a la vez. El cierre es inmediato |
| `0.6s` + tres pulsos de `1.4s` | Llegada del anillo que marca una posición en el cielo (§7.11) |

- **El cambio de foto del parpadeo es un corte seco**, sin fundido. Un fundido mezcla dos fechas y
  esconde justo el movimiento que se quiere ver.
- El zoom y el desplazamiento de la imagen siguen al cursor o al dedo, sin inercia ni animación.
  **La excepción es el cielo** (§7.11): al soltarlo después de un arrastre sigue girando hacia donde
  se lanzó y frena (pierde 1/e de la velocidad extra cada 0.4 s). Si giraba solo antes del arrastre,
  en vez de pararse se asienta en el giro en reposo, en la dirección del arrastre.
- **Nada se mueve solo más de cinco segundos** sin un botón de pausa (WCAG 2.2.2). Por eso el anillo
  del cielo da tres pulsos y se queda quieto, y el giro del cielo lleva su pausa.
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
- **Leyenda:** el primer bloque del panel, para que se vea sin desplazar. Cada línea es un interruptor
  de la marca que nombra (posición predicha, centro medido, trayectoria, píxeles marcados), con una
  casilla propia de 18 px y radio 4 que, marcada, se rellena del color de esa marca y muestra un
  check en `--bc-cosmos`; sin marcar, la línea y su icono se atenúan. «All» y «None» encienden o
  apagan las cuatro. Los píxeles marcados se pintan sobre la imagen desde las máscaras del paquete:
  los malos en `--bc-muted` al 45 % y los saturados en `--bc-error` al 50 %.
- **Avisos científicos:** sólo en el nivel avanzado (§7.13). En pantallas de más de 1100 px van en
  la columna de la imagen, debajo de la línea de fechas, como tarjetas (§7.8) en dos columnas si
  caben y sin franja de color al lado; en una columna van después del panel, al final.

### 7.2 Controles de reproducción

| Control | Especificación |
|---|---|
| Anterior / siguiente | Botones de icono de 44 × 44, `aria-label="Previous frame"` / `"Next frame"`. Con reproducir / pausa forman un grupo que no se separa |
| Reproducir / pausa | Botón de icono de 44 × 44, `aria-pressed`; el icono y la etiqueta cambian |
| Velocidad | `<input type="range">` de 0.5 a **3 fotos por segundo** (§8), con valor en texto y `tabular-nums`. Va en la misma fila que anterior / pausa / siguiente y ocupa lo que sobra, como la barra de un reproductor. En móvil su rótulo «Speed» queda sólo para lectores de pantalla. Por debajo de 380 px los tres botones se centran en su fila y la barra se estira debajo |
| Zoom | Botones de alejar, acercar y «reset» (icono de encuadre: cuatro esquinas), con el nivel en texto entre ellos; también rueda o pellizco sobre el lienzo. Los cuatro forman un grupo: si no caben en la fila, bajan juntos. Acercar y alejar se desactivan en su tope, y «reset» en 1×, para que nadie pulse un botón que no hace nada (§7.7) |
| Mapa de diferencia | Chip con `aria-pressed`; sólo en el nivel avanzado (§7.13) |
| Banda | Desplegable (§7.12) con «All bands» y una opción por banda, cada una con su número de fotos |
| Línea de fechas | Un punto por foto, separados en proporción al tiempo real, con un mínimo de 14 px entre vecinos para que las fotos de días seguidos no se amontonen; el activo en `--bc-estrella` y más grande; cada punto es un botón con la fecha en su `aria-label`. Debajo sólo van tres fechas: la primera, la última y la de la foto activa, bajo su punto; una fecha de extremo se oculta si la activa le cae encima |

En una serie densa los puntos quedan a menos de 44 px. Ahí cada punto recibe como zona de toque el
espacio hasta la mitad de la distancia a sus vecinos, y los botones de anterior y siguiente son la
vía de 44 × 44 para llegar a cualquier foto. Si ni los 14 px caben (muchas fotos en una pantalla
estrecha), los puntos se reparten por igual y la marca baja de 10 a 6 px.

**Iconos.** Los botones redondos llevan iconos dibujados en SVG dentro del propio HTML, sin librería:
trazo de 1.6 px con extremos redondos sobre una cuadrícula de 16 px, en `currentColor`. No se usan
caracteres como ❚❚ o ⟲: cada teléfono los pinta con otra fuente y otro tamaño.

**Etiqueta flotante.** Todo botón de icono lleva su nombre en `data-tip`, y el CSS lo muestra al
pasar el ratón o al llegar con el teclado: placa `rgba(4, 7, 11, 0.94)` con borde `--bc-border`,
radio 4 px, `--bc-fs-xs` / 500, encima del botón (a la izquierda en la columna del cielo). En
pantallas táctiles no se muestra. El nombre accesible sigue siendo el `aria-label`.

**Teclado** (sólo con el foco dentro del visor, para no robar teclas a la página): `Space`
reproducir o pausar, `←` / `→` foto anterior o siguiente, `+` / `−` zoom, `0` restablecer.

### 7.3 Panel de metadatos

- Lista de definiciones (`<dl>`): etiqueta en `--bc-fs-xs` / `--bc-muted` / mayúsculas; valor en
  `--bc-fs-base` / `--bc-blanco` / `tabular-nums`.
- Por foto: fecha y hora **en UTC** (formato ISO, `2026-05-04 07:12 UTC`), longitud de onda en µm,
  detector, entrega (DR1 o QR3), ángulo de posición y estado de calidad. Entrega, ángulo de posición,
  distancia a Gaia y la media anchura del filtro (`4.231 ± 0.018 µm`, el `±` en `--bc-muted`) sólo
  en el nivel avanzado (§7.13). Los valores no parten línea (`white-space: nowrap`).
- El valor que cambia al pasar de foto se actualiza dentro de una región `aria-live="polite"` (sólo
  cuando el usuario cambia de foto a mano, no en reproducción automática).

### 7.4 Comprobaciones de la foto (antes, badges)

Cuatro celdas **fijas** bajo los metadatos, en dos columnas, siempre las mismas y en el mismo orden,
para que el panel mida lo mismo en todas las fotos y nada brinque durante la reproducción. Celda:
padding 8 × 10 px, borde `--bc-border-soft`, radio 4 px, fondo `rgba(4, 7, 11, 0.35)`; etiqueta en
`--bc-fs-micro` / mayúsculas / `--bc-muted`; valor en `--bc-fs-xs` / 500, de una sola línea
(`text-overflow: ellipsis`), con el texto completo en `title`. En teléfonos de hasta 400 px el valor
baja a `--bc-fs-micro`. Las celdas sustituyen a las pills, que cambiaban de número y de alto.

| Celda | Valores y color |
|---|---|
| Roll | `↻ 180°, aligned` (acento) · `✓ 0°, as taken` (ok) · `↻ Aligned (0°)` en el mapa de diferencia · `↻ All north-up` en la pila (§7.14) |
| Core | `⚠ Saturated` (aviso) · `✓ Not saturated` (ok) · `— Not applicable` (`--bc-muted`; también en la pila) |
| vs Gaia | `✓ 0.31″ off` (ok, hasta 0.5″) · `⚠ 3.27″ off` (aviso) · `— Unmeasured` (`--bc-muted`) · `± Dipole ΔI` · en la pila: `✓ Detected 10.2σ` (ok) · `— Not detected, 2.1σ` (`--bc-muted`) |
| Wavelength | `✓ Same as before` (ok) · `⚠ 2.29→4.23 µm` (aviso, salto mayor de 0.05 µm) · `— First frame` · `Δλ 0.012 µm` · `⚠ Mixed` en la pila (aviso) |

### 7.5 Entrada de coordenadas

- Dos campos (RA y Dec) más un campo de búsqueda por nombre. RA y Dec aceptan grados decimales y
  sexagesimales; el `placeholder` muestra los dos formatos.
- Input: alto mínimo 48 px, radio 4 px, fondo `--bc-noche`, borde `--bc-border`, foco con el contorno
  del sistema. Fuente `--bc-font-mono`.
- Error en línea bajo el campo, en `--bc-error`, con icono y texto («Dec must be between −90° and
  +90°»), enlazado con `aria-describedby`. El campo no cambia sólo de color.
- **Los cinco objetos de prueba** van en un desplegable (§7.12) junto a los campos: Barnard's Star,
  Epsilon Indi B, WISE 0855−0714, RW Aurigae, R Draconis. Elegir uno rellena RA y Dec con su posición
  de hoy; escribir una posición quita la elección.
- **Búsqueda por nombre libre** (se quitó el 15 nov y volvió ese mismo día): un campo «Object name»
  junto al desplegable. El nombre se consulta en SIMBAD al pulsar el botón principal, nunca mientras
  se escribe. Objeto de prueba, nombre y posición son tres formas de decir lo mismo y vale la última
  que se tocó: elegir un objeto borra el nombre, escribir un nombre quita la elección y la posición,
  y escribir una posición quita la elección y el nombre. Si SIMBAD no encuentra el nombre o no
  responde, el error va bajo el campo y ofrece la salida («…or enter RA and Dec»).

### 7.6 Estados de carga, vacío y error

Todo estado lleva **frase + qué puede hacer la persona**. Nunca un spinner solo.

| Estado | Qué se ve |
|---|---|
| Cargando | «Loading SPHEREx frames…» y, si pasa más de 1.2 s sin respuesta, **el viaje de los datos** (abajo). Una respuesta de caché abre el visor directo, sin escena |
| Sin cobertura | «SPHEREx has no images of this position yet.» + enlace a los objetos de prueba |
| Servicio caído | «The NASA/IPAC archive (IRSA) is not responding. Try again or open a test object.» |
| Error de datos | «This frame could not be read.» y el visor sigue con las demás fotos |

Gradiente de progreso:

```css
background: linear-gradient(90deg, #060a16 0%, #122a52 30%, #2f5e9e 55%, #5b93cf 78%, #bfe0ff 100%);
```

**El viaje de los datos.** Una pedida nueva al servidor tarda de uno a varios minutos (busca en IRSA,
descarga un recorte por visita y los alinea). Mientras, el diálogo enseña por qué, sin barra que
mienta: no hay porcentaje porque el servidor no lo da.

- **Escena:** un SVG en el HTML (640 × 240, ancho completo hasta 640 px), sin imágenes ni
  librerías. De izquierda a derecha: una estrella, el telescopio (tres conos anidados y un cuerpo,
  silueta genérica, sin marcas de la misión), el archivo de IRSA (una pared de 20 teselas) y «tu
  pantalla» (un monitor con tres recortes apilados). Unidos por una línea de puntos en
  `--viz-trayectoria`. Trazo de 1.6 px en `--bc-estrella`, como los iconos; rótulos en
  `--bc-fs-micro` / mayúsculas / `--bc-muted`, ocultos por debajo de 520 px.
- **Qué se mueve:** fotones (puntos blancos) de la estrella al telescopio; el telescopio flota;
  las teselas del archivo se encienden en barrido y cinco quedan encendidas (las que coinciden);
  paquetes (cuadrados de 10 px, uno en `--bc-aviso`) del archivo a la pantalla; el recorte de
  arriba llega girado 180° y se endereza; el anillo de Gaia (el de la leyenda) cae sobre la pila.
  Sólo transformaciones y opacidad, en bucles de 2.4 a 5 s. Con `prefers-reduced-motion` todo
  queda quieto y en su estado final.
- **Tres estaciones** bajo la escena, numeradas, que siguen **la fase real del trabajo** en el
  servidor: 1 «Asking IRSA which SPHEREx images saw this patch of sky» (`queued`), 2 «Downloading a
  cutout of every visit (about 4 MB each) and turning them all north up» (`running`), 3 «Placing
  Gaia's predicted position on every date» (al recibir el resultado). La activa lleva el número
  relleno en `--bc-estrella` y el texto en `--bc-texto`; las otras, en `--bc-muted`. En la escena,
  el nodo de la estación activa va a opacidad 1 y los demás a 0.55.
- **Texto honesto:** «The first time for a patch of sky this takes a few minutes. Next time it
  opens in seconds.» y un contador «Elapsed m:ss» en `--bc-blanco`. El contador es el único número.
- Las tres estaciones se apilan por debajo de 760 px.

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

### 7.11 Vista del cielo (prototipo, pendiente de que el equipo lo confirme)

La portada: el cielo entero a pantalla completa, visto desde dentro, girando despacio. Encima flotan
el buscador y los controles; al llegar a una posición se abre el visor del §7.1 en un diálogo.
Sale de la prueba de `mockup/sky.js`.

- **Lienzo:** ocupa toda la ventana, fondo `--bc-abismo`. El este queda a la izquierda, como en
  cualquier carta del cielo. Aquí la imagen sí se suaviza al ampliar: es un telón de fondo, no el
  dato. La regla de píxeles nítidos del §7.1 sigue valiendo para las fotos del visor.
- **Hasta dónde acerca:** hasta que un píxel de pantalla muestre medio píxel del mapa, y nunca a
  menos de 30° de campo. El lector de coordenadas avisa con «closest view».
- **Superficie flotante («glass»):** fondo `rgba(8, 12, 20, 0.78)`, borde de 1 px
  `rgba(123, 168, 212, 0.23)`, radio 16 px, `backdrop-filter: blur(14px)` y la sombra de diálogo
  del §5. Sólo para lo que flota sobre el cielo, nunca sobre una foto de SPHEREx.
- **Buscador:** panel «glass» abajo al centro (880 px como máximo), con etiqueta pequeña, la pregunta
  como título y dos filas: arriba qué buscar (el desplegable de los cinco objetos de prueba, «or»,
  y el nombre); abajo dónde (RA y Dec) y el botón principal (§7.5). En pantallas de hasta 900 px
  son dos columnas, sin el «or», con el botón en su propia fila a todo el ancho; hasta 520 px la
  columna izquierda es más ancha (1.5 a 1) para que quepa el nombre más largo del desplegable. El
  panel no crece en móvil por tener el campo de nombre. Lleva un botón «Hide» / «Search». Se pliega solo durante el viaje. Nada viaja
  hasta pulsar el botón principal. Plegado, en móvil es una barra a todo el ancho, como la barra
  inferior de una app; en escritorio se queda del ancho de su contenido.
- **Capas del cielo:** un desplegable (§7.12) arriba a la izquierda, con un pie que dice siempre qué mapa
  se ve, de qué fechas y si es un dibujo o un promedio. El cambio de capa es un fundido de 0.4 s
  (aquí sí, porque no se comparan fechas). El falso color es la única imagen a color del sistema
  (excepción al §2.6) y su pie dice qué longitud de onda va en cada canal.
- **Lector de coordenadas:** la posición y el campo de la vista, bajo el desplegable de capas. En
  móvil (≤ 760 px) queda oculto y un botón de icono «i» junto al desplegable lo muestra a petición.
- **Posición bajo el puntero:** bajo el desplegable se muestran RA y Dec con 4 decimales al
  mover el puntero o tocar el lienzo. En móvil aparece sin abrir «i» y conserva la última posición
  al levantar el dedo, identificada con «Last touch».
- **Retícula ecuatorial:** el botón «Coordinate grid» de los controles empieza apagado. Dibuja
  meridianos cada 30° de RA y paralelos cada 15° de Dec en `--bc-estrella` con transparencia.
  Destaca el meridiano de RA 0° y el ecuador de Dec 0°.
- **Pie de la capa en móvil:** también se guarda tras el botón «i», para despejar el cielo. Aun así
  aparece solo durante 5 segundos al cargar la página y cada vez que se cambia de capa, para que
  nadie tome el telón de fondo por una fotografía sin haberlo leído. Abierto con el botón, se queda
  hasta que se cierra. En escritorio sigue siempre visible.
- **Cabecera en móvil:** por debajo de 520 px sólo caben el nombre del equipo y «Credits»; el
  nombre del proyecto se oculta. La interfaz no se presenta como maqueta en ningún sitio.
- **Controles:** columna de botones de icono de 44 × 44 a la derecha (acercar, alejar, pausa y
  volver al cielo completo, con el icono de encuadre de cuatro esquinas); en móvil, arriba a la
  derecha. Cada uno lleva su etiqueta flotante (§7.2). Acercar se desactiva en la vista más cercana,
  alejar en los 170° y «cielo completo» cuando ya se ve el cielo completo y no hay posición marcada.
- **Giro en reposo:** 1.5° por segundo, con botón de pausa (WCAG 2.2.2). Se detiene al tocar el
  cielo, durante el viaje y mientras el diálogo está abierto. Con `prefers-reduced-motion` no gira
  y el viaje es un salto. Al soltar un arrastre el cielo sigue hacia donde se lanzó y frena (§6);
  si giraba antes del arrastre, vuelve a girar solo en esa dirección. Un toque sin arrastre no
  cambia nada.
- **Viaje:** 5 s: gira por el camino más corto mientras se aleja y después se acerca. Al llegar,
  un anillo discontinuo en `--bc-estrella` con halo marca la posición, con su nombre debajo. El
  anillo «aterriza» (entra un poco grande y se asienta en 0.6 s) y suelta tres pulsos lentos que se
  abren y se apagan; después se queda quieto. El diálogo se abre 0.9 s después de llegar, para que
  se vea el aterrizaje, y al cerrarlo el anillo repite los pulsos para volver a señalar el sitio.
- **Diálogo del visor:** `<dialog>` modal de 1180 px como máximo, fondo `--bc-cosmos`, borde
  `--bc-border`, radio 16 px, fondo oscurecido `rgba(4, 7, 11, 0.72)`. Cabecera con el nombre, la
  posición de hoy, el selector de nivel de detalle (§7.13) y un botón de cerrar de 44 × 44; por
  debajo de 520 px el selector y el cierre pasan a su propia fila, encima del nombre. Si no hay
  fotos para esa posición, lo dice y ofrece ir a un objeto que sí las tiene (§7.6).
- **Créditos:** como no hay pie de página, el botón «Credits» de la cabecera abre un diálogo con el
  texto del §7.10.
- **Enlace de salto:** «Skip to search».

### 7.12 Desplegable

Para elegir una opción entre pocas cuando una fila de chips no cabe: capa del cielo, banda y objeto
de prueba.

- Es el `<select>` nativo, para que el teléfono abra su propio selector y el teclado funcione sin
  código. Se le quita la apariencia del sistema y se viste como un input (§7.5): alto mínimo 48 px,
  radio 4 px, fondo `--bc-noche`, borde `--bc-border` (`--bc-acento` en hover), texto `--bc-blanco`
  de 15 px y peso 500.
- **Flecha:** un ángulo de 8 px en `--bc-estrella`, a 16 px del borde derecho y centrado en vertical.
  El texto deja 44 px libres a la derecha para no meterse debajo, y se corta con puntos suspensivos.
- **Etiqueta:** encima, como la de un campo (§7.5), o a la izquierda en la misma línea cuando el
  desplegable va solo en su fila (banda). Si la opción ya dice qué es («Visible light»), la etiqueta
  va sólo en `aria-label`.
- **No actúa solo cuando mueve la vista:** elegir un objeto no viaja hasta pulsar el botón principal,
  para que recorrer la lista con el teclado no dispare cinco viajes. Capa y banda sí cambian al
  elegir, porque sólo cambian lo que se ve en el sitio.
- Sobre el cielo lleva el fondo de superficie flotante, `rgba(8, 12, 20, 0.78)`.

### 7.13 Nivel de detalle del visor (básico y avanzado)

El visor tiene dos niveles. **Básico** (el inicial) enseña lo que hace falta para ver el parpadeo y
saber si la estrella se movió; **avanzado** añade los números con los que se comprueba. La elección
se recuerda en el navegador (`localStorage`, clave `viewer-detail`).

- **Selector:** un `radiogroup` de dos opciones («Basic», «Advanced») en la cabecera del diálogo,
  en forma de pill con borde `--bc-border` y fondo `rgba(13, 22, 37, 0.6)`; un pulgar en
  `--bc-estrella` se desliza (0.2 s) hasta la opción elegida, cuyo texto pasa a `--bc-cosmos`.
  Flechas izquierda y derecha cambian de opción.
- **Cómo se marca:** el diálogo lleva `data-mode="basic|advanced"` y lo que sólo es del nivel
  avanzado lleva la clase `adv`; en básico no se muestra (`display: none`).

| Siempre | Sólo en avanzado |
|---|---|
| Imagen, reproducción, velocidad, zoom, banda, línea de fechas | Botón «Difference Map» |
| Leyenda con sus interruptores | Entrega, ángulo de posición, «Measured vs Gaia» y el `±` de la longitud de onda |
| Número de foto, fecha, longitud de onda, detector | Bloque «Object» (nombre y posición de Gaia, que la cabecera ya da) |
| Las cuatro comprobaciones (§7.4) | «Scientific Warnings & Notes» |
| «What moved» y «How these frames were made» | «Data & Astrometry Citations» |
| Selector «Single frames \| Stack of N» y la pila con su veredicto, reducción de ruido y advertencia (§7.14) | En la pila: lo esperado por √N, el ruido en MJy/sr, el mayor desplazamiento aplicado y los píxeles rechazados |

### 7.14 Pila profunda («deep stack»)

Hay objetos (la enana marrón WISE 0855−0714 es el caso que lo motivó) que no se ven en ninguna foto
sola: todas dicen `— Unmeasured`. El motor suma todas las fotos útiles desplazando cada una para que
la posición predicha del objeto (movimiento propio + paralaje) quede quieta, como el modo cometa del
apilado en astrofotografía; el ruido baja más o menos como √N. Llega en el paquete (esquema 1.1.0)
como `deep_stack`, opcional, o `deep_stack_skipped_reason` si no se hizo.

- **Selector:** un `radiogroup` de dos opciones, «Single frames» y «Stack of N» (N = `frame_count`),
  con la misma pill y el mismo pulgar deslizante del nivel de detalle (§7.13); opciones de 38 px de
  alto para llegar a 44 con el marco. Va en su propia fila, justo bajo la imagen y encima de los
  controles, porque cambia lo que enseña la imagen. Flechas izquierda y derecha cambian de opción
  (sin cambiar de foto). «Single frames» es el inicial y vuelve a serlo con cada objeto nuevo.
- **Cuándo aparece:** con `deep_stack`, activo. Sin pila pero con `deep_stack_skipped_reason`, la
  opción de la pila va deshabilitada (`opacity: 0.45`) y al lado, en `--bc-fs-xs` / `--bc-muted`,
  el motivo: «Stack unavailable: too few usable exposures.» o «Stack unavailable: the star saturates
  the detector, so stacking cannot help.». Sin ninguno de los dos campos (paquetes anteriores a
  1.1.0) la fila no existe y el visor queda como antes.
- **Qué cambia en la vista de pila:** la imagen es la de la pila, en la misma cuadrícula y con el
  mismo estirado `asinh` y la misma paleta que las fotos, pero con su propia escala de brillo
  (el motor la calcula sobre la suma, que tiene menos ruido). Encima, el anillo de la posición predicha (en `target_pixel_x/y`) y
  la cruz del centro medido si lo hay; no hay trayectoria, porque la imagen sigue al objeto. Lo que
  sólo tiene sentido en una serie se pausa y se deshabilita **en su sitio**, sin ocultarlo, para que
  nada se mueva: reproducir, anterior / siguiente, velocidad, banda y «Difference Map». La línea de
  fechas queda atenuada (0.45) e inerte y enseña sólo la primera y la última fecha. Zoom, arrastre y
  leyenda siguen funcionando.
- **Panel:** el encabezado dice «Stack of N exposures»; la fecha es el intervalo
  (`2025-05-05 → 2026-05-13`, también en la placa de la imagen), la longitud de onda el rango
  (`3.82–4.98 µm`) y el detector las bandas (`Bands 5–6`). Las cuatro celdas del §7.4 siguen, con
  los valores de la pila. «What moved» cede su sitio a **«What the stack shows»**:
  - el veredicto en `--bc-fs-base` / `--bc-blanco`: «Detected in the stack: 10.2σ, 0.8″ from the
    predicted position.» o «Not detected in the stack (peak 2.1σ, below the 5σ threshold).»;
  - «Noise 3.1× lower than in a single frame» (no «÷3.1»: en letra pequeña el `÷` se lee como `+`);
  - sólo si sumar sin seguir el movimiento da más de 1σ menos y el desplazamiento mayor pasa de
    0.3 px: «Without following the predicted motion: 6.0σ»;
  - en avanzado, en `--bc-muted`: lo esperado por √N, el ruido de la pila y de una foto en MJy/sr,
    el mayor desplazamiento aplicado (px y ″) y los píxeles rechazados;
  - siempre, en `--bc-fs-xs` / `--bc-muted`, la advertencia: «The stack mixes wavelengths, so it
    shows that something is there and where, not how bright it is. Field stars may look slightly
    smeared because the image follows the target.»
- **Tolerancia:** cualquier número que llegue `null` o falte se omite o se escribe «N/A»; nunca se
  inventa.

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
