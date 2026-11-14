# Bortle Cero · NASA Space Apps 2026 — Planet X and SPHEREx

Repo del proyecto del equipo **Bortle Cero** (sede presencial de Guadalajara) para el reto
[Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/)
del NASA Space Apps Challenge 2026 (14–15 nov 2026). **El repo es público:** lo leen el equipo, el
jurado y cualquiera. No escribas aquí datos personales, contactos ni secretos.

**Qué pide el reto:** una herramienta web pública donde alguien escribe RA/Dec y ve la serie de
imágenes de SPHEREx de ese trozo de cielo como un parpadeo, para notar lo que se mueve o cambia de
brillo. Objetos de prueba: Estrella de Barnard, Epsilon Indi B, WISE 0855−0714, RW Aurigae y
R Draconis.

## Estado (sáb 14 nov 2026, pipeline de ingesta implementada)

- **Pipeline de Ingesta de Datos (`src/spherex_ingest/`):** implementada en Python 3.12+ (gestionada con Astral `uv`) siguiendo principios **SOLID** e inspirada en la arquitectura de tareas desacopladas de SPHEREx SSDC (`pipeline.pdf`).
  - **Modo Híbrido (CLI + API FastAPI):** permite tanto pre-generar paquetes estáticos (`JSON` + matrices numéricas reproyectadas + imágenes `PNG` en base64 + mapas de diferencia $\Delta I$) para los 5 objetos de prueba, como consultar cualquier coordenada $(\text{RA}, \text{Dec})$ en vivo vía FastAPI con CORS habilitado y caché local de FITS en `.cache/fits/`.
  - **Guía técnica en español para el equipo de Frontend:** ver [docs/GUIA-EQUIPO-INGESTA.md](docs/GUIA-EQUIPO-INGESTA.md).
- **Comandos del Pipeline de Ingesta (`uv`):**
  ```bash
  # 1. Crear entorno e instalar dependencias
  uv venv --python 3.14 .venv
  uv sync --extra dev

  # 2. Correr pruebas automatizadas y linter
  uv run pytest
  uv run ruff check src/ tests/

  # 3. Listar o descargar/procesar objetos de prueba de IRSA
  uv run spherex-ingest list-benchmarks
  uv run spherex-ingest ingest --target epsilon_indi_b --max-frames 12

  # 4. Levantar servidor FastAPI (puerto 8000, docs en /docs)
  uv run spherex-ingest serve --host 0.0.0.0 --port 8000
  ```
- Prioridad acordada: **una demo desplegada que funcione antes que más funciones.**

## Reloj (hora de Guadalajara)

| Cuándo | Qué |
|---|---|
| Sáb 14, ~14:00 | se congela el alcance: después sólo se termina lo empezado (Miguel lo confirma) |
| Sáb 14 y dom 15, 20:00 | cierra la sede; se sigue desde fuera |
| Dom 15, ~21:00 | objetivo para enviar la entrega, con 3–4 horas reservadas para armarla |
| Dom 15, 23:59 | límite en la plataforma; cuenta la última versión enviada |

## Reglas del hackatón que obligan en cada sesión

Romperlas puede costar la nominación o el premio. Detalle y enlaces oficiales en
[docs/SOURCES.md](docs/SOURCES.md).

1. **Bitácora de IA.** Cada sesión de un agente añade una entrada a
   [docs/AI-USAGE.md](docs/AI-USAGE.md) antes de su último commit: qué herramienta, qué hizo, qué
   archivos tocó. La entrega tiene que describir el uso de IA y sale de ahí.
2. **Lo generado con IA se declara.** Código, datos y audio: en la bitácora y en los metadatos (el
   trailer `Co-Authored-By` del commit). Imágenes y videos generados llevan **marca de agua
   visible**. Nada generado usa ni modifica logos, banderas o identificadores de misión de la NASA.
3. **La idea de la solución es del equipo.** La guía de entrega dice: «SI should not be used to come
   up with your idea of how to solve the challenge». El agente explica, compara opciones cuando se
   las piden e implementa lo decidido; no elige el enfoque por su cuenta.
4. **Toda fuente se cita**, aunque sea abierta: datos, código, librerías, textos, imágenes. Se añade
   a [docs/SOURCES.md](docs/SOURCES.md) **en el mismo commit** que la introduce.
5. **Datos de la NASA en el centro.** Para los premios globales hay que usar al menos una fuente de
   la pestaña Resources del reto (IRSA/SPHEREx, tutoriales de IRSA, WiseView, Gaia DR3), y que sea
   la base de la herramienta, no un adorno.
6. **Sólo librerías de código abierto.** El proyecto se publica abierto (Apache 2.0, la licencia por
   defecto de Space Apps).
7. **Código propio anterior:** no copiar de los sitios de Bortle Cero mientras el GO Team no conteste
   la pregunta [#1924](https://github.com/nasa/spaceapps/discussions/1924). Si Miguel decide
   reutilizar algo, que sea poco y vaya citado como trabajo previo. **Decidido el 14 nov:** se
   reutilizan los valores y reglas del design system Noir Cósmico v2, adaptados en
   [DESIGN.md](DESIGN.md) y citados en `docs/SOURCES.md`. El código de esos sitios sigue sin copiarse.
8. **No abrir ni copiar repos de otros equipos** del reto (hay varios «spherex-blink» en GitHub,
   algunos empezados antes del hackatón).
9. **Todo lo que ve el público va en inglés:** interfaz, README, página del proyecto, slides. Nada
   que muestre a menores de 18 años.
10. **Demo:** video de 30 s como máximo (subtítulos en inglés si se habla español) o hasta 7 slides.
    Pasarse del límite deja al proyecto fuera del juicio global.
11. **Diseño:** toda interfaz sigue [DESIGN.md](DESIGN.md). Lo que no esté ahí se decide en equipo y
    se añade ahí en el mismo commit.

El jurado puntúa de 1 a 5: Impact, Creativity, Validity, Relevance y Presentation.

## Lo que ya se sabe de los datos

Foto al 13 nov 2026, salida del estudio previo. El estado de los servicios caduca: compruébalo en
vivo antes de apoyarte en él.

- **Dónde viven:** IRSA (NASA/IPAC). Búsqueda por posición con SIA en las colecciones `spherex_dr1`
  y `spherex_qr3` (más `spherex_dr1_deep` y `spherex_qr3_deep` para R Draconis). **No usar QR2:**
  DR1 lo reprocesa y está hecha para usarse junto con QR3. Hay servicio de recortes y copia en AWS S3
  (`nasa-irsa-spherex`, sin firma).
- **Un archivo = una foto** de un detector (3.5° de lado, ~62–72 MB, píxel de 6.15″) con seis hojas:
  IMAGE, FLAGS, VARIANCE, ZODI, EPSF y WCS-WAVE. Un recorte pesa ~4 MB aunque los píxeles útiles
  sean pocos, porque arrastra la tabla EPSF.
- **CORS:** el SIA, los recortes y el TAP de IRSA no lo mandan, y el archivo de Gaia de la ESA
  tampoco. Sí lo mandan S3 (con pedidos por rango), los HiPS de IRSA y los espejos de SIMBAD y
  Sesame en Harvard. S3 se lista por semana, no por posición.
- **CDS (Estrasburgo) está caído** por un incidente de seguridad: SIMBAD, VizieR, Sesame, sus HiPS y
  `aladin.js` desde su servidor. Usar los espejos (`simbad.harvard.edu`, `vizier.cfa.harvard.edu`),
  los HiPS de IRSA o de la ESA, y Aladin Lite desde npm.
- **Trampas que rompen un parpadeo ingenuo:**
  1. Entre pasadas la nave ve la zona **girada 180°** (`SPS_EPA` en el encabezado): sin reproyectar
     a una cuadrícula común, la estrella brinca.
  2. **Cada foto ve otro color**, porque la estrella cae en otra franja del filtro: un cambio de
     brillo entre dos fotos no prueba que la estrella varíe.
  3. **Saturación:** Barnard y R Draconis saturan (núcleo en NaN, halo con bandera), RW Aurigae cae
     en zona no lineal. Epsilon Indi B es la única limpia.
  4. **El movimiento es subpíxel:** Barnard ≈0.8 px por pasada y ≈1.9 px en toda la serie.
  5. **La coordenada de catálogo no es la de hoy:** hay que propagarla con movimiento propio a la
     fecha de cada foto, y el paralaje pesa (hasta 1.09″ en Barnard, más que el error de 0.3″).
  6. **WISE 0855 no está donde dice el enunciado** (coordenadas de ~2010; hoy ≈ 133.760, −7.2422,
     unos 20 px al oeste), sólo se detecta por encima de 3.9 µm (bandas 5 y 6) y tiene una fuente
     fija igual de brillante a 29″ de la coordenada del enunciado.
- **Pasadas por objeto:** Barnard 3, Epsilon Indi B 4, WISE 0855 3 (sólo en DR1), RW Aurigae 3,
  R Draconis casi continuo (campo profundo).

## Entorno

- **Python:** entorno compartido fuera del repo, en la laptop de Miguel:
  `D:\dev\lab\.venvs\astro` (Python 3.14 con uv; astropy, pyvo, astroquery, reproject, photutils,
  matplotlib, s3fs, ipyaladin). Prueba:
  `D:\dev\lab\.venvs\astro\Scripts\python -c "import astropy; print(astropy.__version__)"`.
- Para repetirlo en otra máquina (los mismos comandos en PowerShell y en bash; en Linux el
  intérprete queda en `.venv/bin/python`, en Windows en `.venv\Scripts\python`):

  ```sh
  uv python install 3.14
  uv venv .venv --python 3.14 --managed-python
  uv pip install --python .venv -r requirements.txt
  ```

  `requirements.txt` todavía no existe: se crea con el primer código de Python y lista **sólo lo que
  el proyecto usa de verdad**.
- **Datos pesados fuera de git:** ningún FITS ni descarga de IRSA se commitea. En la laptop de Miguel
  hay archivos de estudio en `D:\dev\lab\datos-spherex\`.
- Node, git, `gh` y Vercel CLI están instalados; `gh` y Vercel tienen sesión como `vse-elbuenmai`.

## Cómo se trabaja aquí

- **Idioma:** con Miguel, español y lenguaje simple. Es desarrollador web y astrofotógrafo, no
  físico ni programador de Python: tiene que entender lo que se construye para defenderlo ante el
  jurado. Explica la ciencia con analogías de desarrollo web o de astrofotografía.
- **Ramas:** `main` siempre funciona y está pusheado; nadie commitea directo a `main`. Cada persona
  trabaja en su rama (`<nombre>/<tema>`; los agentes en `claude/<tema>`, `codex/<tema>` o
  `wip/<tema>`) y entra a `main` por pull request, fusionando con `--no-ff`.
- **Windows y Linux:** el equipo usa los dos. Todo comando que se documente aquí tiene que correr en
  ambos (o venir en sus dos versiones); en el código, rutas relativas con `/` o `pathlib`, nunca
  rutas absolutas de una máquina. `.gitattributes` guarda el texto con finales LF; no cambies
  `core.autocrlf` para saltártelo.
- **Relevo entre Claude Code y Codex:** por git, con el protocolo de `~/.agent-shared/relevo.md`.
  `RELEVO.md` se crea en la raíz en el primer relevo; si existe, léelo al entrar.
- **Validez científica:** lo que la herramienta muestre se comprueba contra una medida conocida
  (Gaia DR3, SIMBAD). Si Barnard no se mueve lo que dice Gaia, hay un error.
- **El estado externo se verifica en vivo** (enunciado, reglas, IRSA, versiones de librerías), no
  desde notas.
- **Wiki del equipo (público):** [bortlecero-spherex-wiki](https://github.com/vse-elbuenmai/bortlecero-spherex-wiki):
  la misión, los datos, los cinco objetos, las trampas, las citas y un glosario, con fuente y fecha en
  cada dato. Es la primera parada para dudas de SPHEREx. No decide la solución, y lo que caduca se
  verifica en vivo. En la entrega se cita la fuente original, no el wiki.
- **Material de consulta, local y privado, en la laptop de Miguel:**
  `D:\dev\lab\bortlecero-preparacion-space-apps\` (su `CLAUDE.md`, `SPHEREX.md` y `biblioteca/`: las
  citas listas para pegar están en `biblioteca/00-arranque-sabado.md` §6 y
  `biblioteca/06-bibliografia-y-citas.md`) y los tutoriales oficiales de IRSA clonados en
  `D:\dev\lab\referencias\irsa-tutorials\`. Lo que se saque de ahí se cita.
