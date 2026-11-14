# Guía para el Equipo de Frontend: Pipeline de Ingesta y Preprocesamiento SPHEREx (`spherex-ingest`)

> **Nota de idioma:** Este documento está redactado en español para el equipo de desarrollo web de **Bortle Cero** (sede Guadalajara) siguiendo las normas internas de trabajo en `AGENTS.md`. Todo el código, la API REST (OpenAPI/Swagger), el `README.md` y la interfaz pública están en inglés para cumplir las reglas del jurado global de NASA Space Apps 2026.

---

## 1. ¿Qué hace este módulo y por qué no podemos pedir los FITS crudos desde el navegador?

Cuando apuntas a una coordenada (RA/Dec) en el archivo de SPHEREx en IRSA, **no recibes un PNG ni un JPEG listo para animar**. Recibes archivos científicos **Multi-Extension FITS (MEF) Nivel 2b** de ~62–72 MB cada uno (o recortes de ~4 MB) con 6 extensiones (`IMAGE`, `FLAGS`, `VARIANCE`, `ZODI`, `PSF`, `WCS-WAVE`).

Además, **IRSA no envía cabeceras CORS (`Access-Control-Allow-Origin`)** en sus servicios de búsqueda SIAv2 ni de recortes, y **CDS (Estrasburgo) está caído** por un incidente de seguridad.

Pero el problema más grave no es de red, sino **astrofísico**. Si haces un *blink* (parpadeo) ingenuo mostrando las imágenes crudas una tras otra, la herramienta miente por **6 trampas científicas de SPHEREx** que nuestro pipeline (`spherex_ingest`) resuelve automáticamente antes de entregar el JSON al frontend:

### Las 6 trampas científicas y cómo las resuelve el backend

| # | Trampa en los datos crudos de SPHEREx | Analogía Web / Astrofoto | Cómo la resuelve `spherex_ingest` |
|---|---|---|---|
| **1** | **Rotación de 180° entre pasadas (`SPS_EPA`)**: cada 6 meses el telescopio observa la misma zona con orientación opuesta (~0° vs ~180°). | Como intentar hacer un GIF animado donde los fotogramas pares están de cabeza y descentrados. | Reproyecta todos los recortes con interpolación WCS exacta (`reproject_interp`) a una **cuadrícula celeste común Norte-arriba, Este-izquierda (`ICRS TAN`)** donde cada píxel `[y][x]` corresponde exactamente al mismo punto del cielo en todas las épocas. |
| **2** | **Filtro variable lineal (`WCS-WAVE`)**: SPHEREx no tiene filtros fijos; el color ($\lambda$) cambia de un borde al otro del detector. Dos fotos del mismo objeto tienen distinta longitud de onda. | Comparar una foto en H-alfa con otra en banda V y creer que la estrella varió su brillo. | Evalúa el WCS espectral tabular (`WCS-WAVE`) en la coordenada exacta del objetivo para etiquetar cada foto con su `wavelength_um` y `bandwidth_um`, y agrupa las series por **banda espectral (`frames_by_band`)** para comparar manzanas con manzanas. |
| **3** | **Brillo del polvo interplanetario (`ZODI`)**: en el infrarrojo cercano/medio, el cielo brilla intensamente por la luz solar dispersada por polvo del Sistema Solar, que cambia según la fecha. | Contaminación lumínica (Bortle 8) que cambia de gradiente en cada toma nocturna. | Resta el modelo oficial de luz zodiacal (`IMAGE - ZODI`) antes de reproyectar y medir fotometría. |
| **4** | **Saturación en estrellas brillantes (`FLAGS` + núcleo `NaN`)**: la Estrella de Barnard y R Draconis saturan el detector; el centro viene con valores `NaN` (un agujero negro en la estrella) y la bandera `OVERFLOW` (bit 1). | Quemar el núcleo de M42 en una toma larga y que el sensor devuelva píxeles muertos en el centro. | Detecta los bits `OVERFLOW` y `NaN` en el núcleo (`is_saturated_core: true`), calcula el centroide usando el **halo no saturado de la PSF** y reconstruye suavemente la visualización (`png_base64` y `matrix_mjy_sr`) para que el usuario vea una estrella real mientras conserva la máscara exacta en `saturation_mask`. |
| **5** | **Movimiento subpíxel y paralaje (Gaia DR3)**: el píxel de SPHEREx es enorme (6.15″). Barnard se mueve ~0.84 px cada 6 meses y su paralaje anual desplaza la estrella hasta 1.09″. | Querer medir un desplazamiento de menos de 1 píxel sin sub-muestreo ni referencia astrométrica. | Propaga rigurosamente la coordenada de catálogo (Gaia DR3 época J2016.0) con movimiento propio + paralaje a la fecha exacta (`MJD-AVG`) de cada foto (`predicted_pixel_x`, `predicted_pixel_y`) y mide el centroide real subpíxel (`measured_centroid_x`, `measured_centroid_y`) y el desplazamiento en segundos de arco (`centroid_offset_arcsec`). |
| **6** | **WISE 0855−0714 (enana Y ultrafría a 250 K)**: las coordenadas del reto son de ~2010; hoy está ~20 píxeles al oeste (`RA ≈ 133.760°, Dec ≈ -7.2422°`), sólo brilla a $\lambda > 3.9\ \mu\text{m}$ (Bandas 5 y 6) y hay una estrella fija a 29″ de la posición vieja. | Buscar un cometa con coordenadas de hace 15 años y confundirlo con una estrella de fondo. | Usa las coordenadas propagadas a 2025.5, alerta automáticamente en `scientific_warnings` sobre la fuente fija impostora y destaca las Bandas 5 y 6 donde WISE 0855 es realmente detectable. |

---

## 2. Cómo levantar el servidor o pre-generar los paquetes JSON

Desde la raíz del repositorio (con `uv` instalado):

### Opción A: Levantar el servidor API REST con CORS habilitado (Recomendado para desarrollo Frontend)

```bash
uv run spherex-ingest serve --host 0.0.0.0 --port 8000
```

- **Documentación interactiva Swagger UI:** `http://localhost:8000/docs`
- **Health check:** `http://localhost:8000/api/v1/health`
- **CORS:** Totalmente abierto (`Access-Control-Allow-Origin: *`), listo para conectarse desde Vite, Next.js o Astro en cualquier puerto local o desde Vercel.

### Opción B: Pre-generar los paquetes estáticos en `output/<target_id>/bundle.json`

Si quieren servir los 5 objetos de prueba del reto de forma instantánea (< 50 ms o directamente como archivos estáticos en `public/` del frontend):

```bash
# Generar un objeto de prueba específico
uv run spherex-ingest ingest --target barnards_star --output-dir output

# Generar los 5 objetos oficiales del reto de NASA Space Apps
uv run spherex-ingest ingest --all-benchmarks --output-dir output

# Generar cualquier coordenada personalizada
uv run spherex-ingest ingest --ra 269.45208 --dec 4.69336 --name "Barnard Custom" --output-dir output
```

Cada carpeta `output/<target_id>/` contendrá:
- `bundle.json`: El paquete completo (`BlinkBundleDTO`) con metadatos, matrices numéricas e imágenes en Base64 listas para `<img src="data:image/png;base64,..." />` o un `<canvas>`.
- Imágenes PNG individuales por fotograma y mapas de diferencia ($\Delta I = I_{t_2} - I_{t_1}$).

---

## 3. Endpoints de la API REST

### 3.1 `GET /api/v1/benchmarks`
Devuelve la lista de los **5 objetos oficiales de prueba del reto** con sus coordenadas precisas (Gaia DR3 / época 2025.5 para WISE 0855), movimiento propio, paralaje y notas científicas:
- `barnards_star` (Estrella de Barnard — estrella de mayor movimiento propio, núcleo saturado)
- `epsilon_indi_b` (Epsilon Indi B — enana marrón binaria T1+T6, el objetivo más limpio sin saturación)
- `wise_0855_0714` (WISE J085510.83-071442.5 — enana marrón Y más fría conocida, detectable en Bandas 5 y 6)
- `rw_aurigae` (RW Aurigae — estrella variable T Tauri clásica)
- `r_draconis` (R Draconis — variable tipo Mira en el campo profundo del Polo Norte Eclíptico)

### 3.2 `GET /api/v1/blink/{target_id}`
Ejemplo: `GET /api/v1/blink/barnards_star` o `GET /api/v1/blink/epsilon_indi_b`.
- Si ya existe `output/{target_id}/bundle.json` en disco, lo devuelve en **menos de 50 ms**.
- Si no existe en disco, ejecuta el pipeline en vivo y devuelve el `BlinkBundleDTO`.
- Parámetros query opcionales: `size_arcsec` (por defecto `180.0`), `max_frames` (por defecto `24`), `force_refresh` (`false`).

### 3.3 `GET /api/v1/blink`
Permite buscar cualquier punto del cielo por coordenadas (`ra`, `dec` en grados decimales) o por nombre de objeto (`query`, resuelto vía espejo de Harvard/Sesame o catálogo local):
- `GET /api/v1/blink?ra=331.07645&dec=-56.79382&size_arcsec=180&max_frames=18`
- `GET /api/v1/blink?query=Barnard%27s%20Star`

---

## 4. Contrato del JSON (`BlinkBundleDTO`) para el Frontend

Cuando el frontend llama a `/api/v1/blink/{target_id}` o carga `bundle.json`, recibe un objeto con la siguiente estructura (tipado en TypeScript para que puedan copiarlo directamente a su proyecto web):

```typescript
export interface TargetSpec {
  target_id: string;
  name: string;
  category: "high_proper_motion" | "brown_dwarf" | "variable_star" | "custom";
  ra_deg: number;
  dec_deg: number;
  ref_epoch_jyear: number;
  pm_ra_cosdec_mas_yr: number;
  pm_dec_mas_yr: number;
  parallax_mas: number;
  radial_velocity_km_s: number;
  cutout_size_arcsec: number;
  collections: string[];
  notes: string;
}

export interface CommonGridSpecDTO {
  center_ra_deg: number;
  center_dec_deg: number;
  pixel_scale_arcsec: number; // ~6.15 arcsec/px en SPHEREx
  width_px: number;
  height_px: number;
  orientation: string; // "North-up, East-left (ICRS TAN)"
}

export interface FrameMetadataDTO {
  frame_id: string;
  collection: string;          // "spherex_dr1", "spherex_qr3", etc.
  detector_band: number;       // 1 a 6 (Bandas espectrales de SPHEREx)
  mjd_avg: number;             // Fecha juliana modificada exacta de la toma
  obs_time_iso: string;        // Fecha ISO-8601 (ej. "2025-05-14T08:23:11.200")
  sps_epa_deg: number;         // Ángulo original de la nave (ya corregido en la imagen)
  wavelength_um: number;       // Longitud de onda exacta en el objetivo (micras)
  bandwidth_um: number;        // Ancho de banda del filtro LVF en ese píxel (micras)
  predicted_ra_deg: number;    // RA predicha por Gaia DR3 en la fecha mjd_avg
  predicted_dec_deg: number;   // Dec predicha por Gaia DR3 en la fecha mjd_avg
  predicted_pixel_x: number;   // Coordenada X en la cuadrícula común (0-indexed)
  predicted_pixel_y: number;   // Coordenada Y en la cuadrícula común (0-indexed)
  measured_centroid_x: number | null; // Centroide medido en la imagen (px)
  measured_centroid_y: number | null; // Centroide medido en la imagen (px)
  measured_ra_deg: number | null;
  measured_dec_deg: number | null;
  centroid_offset_arcsec: number | null; // Diferencia entre posición medida y predicha (")
  aperture_flux_ujy: number | null;      // Flujo medido en microJanskys (uJy)
  aperture_flux_err_ujy: number | null;  // Incertidumbre del flujo (uJy)
  snr: number | null;                    // Relación señal/ruido
  is_saturated_core: boolean;            // true en Barnard y R Draconis
  saturated_pixel_count: number;
  bad_artifact_pixel_count: number;
  valid_pixel_fraction: number;
  matrix_mjy_sr: (number | null)[][];    // Matriz 2D [y][x] en MJy/sr (sin luz zodiacal)
  saturation_mask: boolean[][];          // true donde el píxel original saturó
  bad_pixel_mask: boolean[][];           // true donde hubo rayos cósmicos / píxeles malos
  png_base64: string | null;             // Data URI ("data:image/png;base64,...") estirada con asinh lista para <img>
  source_url: string;
}

export interface DifferenceMapDTO {
  detector_band: number;
  frame_id_early: string;
  frame_id_late: string;
  mjd_early: number;
  mjd_late: number;
  baseline_days: number;                 // Días transcurridos entre t1 y t2
  mean_wavelength_um: number;
  diff_matrix_mjy_sr: (number | null)[][]; // I(t2) - I(t1) en MJy/sr
  png_base64: string | null;               // Data URI ("data:image/png;base64,...") divergente (azul = antes, naranja = después)
}

export interface BlinkBundleDTO {
  schema_version: string;
  target: TargetSpec;
  propagated_current_ra_deg: number;
  propagated_current_dec_deg: number;
  grid: CommonGridSpecDTO;
  total_frames: number;
  available_bands: number[];                         // ej. [1, 2, 3, 4, 5, 6]
  frames_chronological: FrameMetadataDTO[];          // Todos los frames ordenados por fecha
  frames_by_band: Record<string, FrameMetadataDTO[]>;// Agrupados por banda ("1", "2", ..., "6")
  difference_maps: DifferenceMapDTO[];               // Pares dipolo (movimiento) / cambio de flujo
  scientific_warnings: string[];                     // Avisos clave para mostrar en UI
  citations: string[];                               // Citas obligatorias de NASA / Gaia DR3
}
```

---

## 5. Recetas rápidas para la Interfaz de Usuario (UI)

### 1. Cómo animar el *Blink* correctamente (¡Agrupar por banda!)
- **Modo recomendado por defecto:** Iterar sobre `bundle.frames_by_band[selectedBand]`. Como todas las fotos de una misma banda tienen longitudes de onda cercanas y ya están reproyectadas al Norte arriba con el fondo zodiacal restado, el parpadeo entre épocas es **limpio y científicamente válido**.
- **Para mostrar la imagen al instante (`png_base64` ya incluye el prefijo `data:image/png;base64,`):**
  ```tsx
  <img
    src={frame.png_base64 ?? ""}
    alt={`${bundle.target.name} - ${frame.obs_time_iso} (${frame.wavelength_um.toFixed(2)} µm)`}
    style={{ imageRendering: "pixelated" }}
  />
  ```
  *(Usar `image-rendering: pixelated` en CSS permite apreciar los píxeles reales de 6.15″ de SPHEREx o bien desactivarlo para interpolación suave).*

### 2. Cómo superponer el marcador de movimiento propio (Gaia DR3 vs Centroide SPHEREx)
Cada fotograma trae coordenadas en píxeles (`0` a `grid.width_px - 1` en X, y `0` a `grid.height_px - 1` en Y):
- **Cruz / círculo de predicción astrométrica (Gaia DR3):** `(frame.predicted_pixel_x, frame.predicted_pixel_y)`
- **Centroide medido en la imagen de SPHEREx:** `(frame.measured_centroid_x, frame.measured_centroid_y)`
- Dibujar ambos en un `<svg>` o `<canvas>` superpuesto demuestra visualmente al jurado que la estrella se mueve exactamente lo que predice Gaia DR3 (criterio de **Validity** del jurado).

### 3. Cómo mostrar el «Dipolo de Movimiento» (`difference_maps`)
En objetos que se mueven (Barnard, Epsilon Indi B, WISE 0855), la resta entre la última época y la primera época de la misma banda ($\Delta I = I_{t_2} - I_{t_1}$) produce una **firma dipolar clásica**: una mancha negativa (donde estaba la estrella en $t_1$) pegada a una mancha positiva (donde está la estrella en $t_2$).
- Pueden renderizar directamente `diffMap.png_base64` o graficar `diffMap.diff_matrix_mjy_sr` en un canvas interactivo al pasar el cursor.

### 4. Mostrar siempre `scientific_warnings` y `citations`
El objeto `bundle.scientific_warnings` incluye explicaciones automáticas generadas para cada objetivo (por ejemplo, si el núcleo de Barnard o R Draconis saturó y fue reparado con el halo de la PSF, o por qué WISE 0855 debe mirarse en las Bandas 5 y 6). Mostrar estos avisos en un panel o *tooltip* de la interfaz suma puntos directos en **Validity**, **Relevance** y **Presentation**.
