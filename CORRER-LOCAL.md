# Cómo correr el proyecto en tu compu

Guía interna del equipo. Explica qué cambió con la guía del cielo (la pestaña
«02 / Don't know where to start?», el chat con el personaje) y qué hay que hacer para correrlo.

## Lo corto

- **Para ver la página no cambia nada.** Se corre igual que antes.
- **No hay dependencias nuevas.** El chat usa `httpx`, que el proyecto ya tenía.
- **Sólo es nuevo si quieres probar el chat en tu compu:** necesitas tu propia clave de Gemini en
  un archivo `.env` y levantar la API local.
- **Para enseñar el proyecto no hace falta correr nada:** usa la página pública,
  <https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html>. Se actualiza sola
  cuando un pull request entra a `main`.

## 0. Bajar los cambios (una vez)

```shell
git pull
```

Si todavía no tienes el entorno de Python, créalo como dice `AGENTS.md` (los mismos comandos en
PowerShell y en bash):

```shell
uv venv --python 3.14 .venv
uv sync --extra dev
```

## 1. Ver la página (igual que antes)

Desde la raíz del repo:

```shell
uv run python -m http.server 8765 --directory mockup
```

Abre <http://localhost:8765>. El buscador y el visor de parpadeo usan la API pública de Cloud Run,
igual que antes.

La pestaña del chat también sale. Mientras el servidor público no tenga clave de Gemini, el
personaje contesta «I'm not set up on this server yet». **Es normal, no es un error tuyo.**

## 2. Probar el chat en tu compu (nuevo, opcional)

Sólo hace falta si vas a probar o cambiar el chat antes de que esté desplegado.

### 2.1 Saca tu clave de Gemini

Entra a <https://aistudio.google.com/apikey> con tu cuenta de Google y crea una clave. No pide
tarjeta: es el plan gratuito y **no cobra**. Si se acaba la cuota, Gemini deja de contestar un rato
y el personaje dice «try again later».

### 2.2 Crea tu `.env`

Copia la plantilla en la raíz del repo:

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
```

```bash
# Linux / macOS
cp .env.example .env
```

Abre `.env` y pega tu clave después del `=`, sin espacios ni comillas:

```text
GEMINI_API_KEY=tu-clave-aqui
```

> **`.env` nunca se sube a GitHub** (está en `.gitignore`). No pegues la clave en ningún otro
> archivo, ni en el chat del equipo, ni en un issue. Si se filtra, bórrala en AI Studio y crea otra.

### 2.3 Levanta la API y la página (dos terminales, ambas en la raíz del repo)

```shell
# Terminal 1: la API, que lee tu .env al arrancar
uv run spherex-ingest serve --host 127.0.0.1 --port 8000
```

```shell
# Terminal 2: la página
uv run python -m http.server 8765 --directory mockup
```

### 2.4 Abre la página apuntando a tu API

<http://localhost:8765/?api=http://localhost:8000>

El `?api=...` sólo cambia a dónde pregunta **el chat**. El buscador y el visor siguen usando la API
pública. Ese parámetro sólo funciona en `localhost`.

## Si algo falla

| Lo que ves | Qué pasa | Qué hacer |
|---|---|---|
| «I'm not set up on this server yet» con `?api=` | Tu API no encontró la clave | Revisa que `.env` esté en la raíz, que la línea sea `GEMINI_API_KEY=...` y que arrancaste la API **desde la raíz**. Reinicia la API después de editar `.env` |
| «I couldn't reach my notes» | La API no está corriendo, o la clave o el modelo fallan | Mira la Terminal 1: ahí sale el error de Gemini |
| «Give me a minute and try again» | Límite por minuto, o se acabó la cuota gratuita | Espera un minuto |
| «Come back tomorrow!» | Se llegó al tope diario (200 preguntas) | Se reinicia a medianoche, hora del Pacífico |
| `uv` no se reconoce | No tienes `uv` instalado | Instálalo (<https://docs.astral.sh/uv/>) o usa el Python del entorno: `.venv\Scripts\python` en Windows, `.venv/bin/python` en Linux y macOS |

## Opcional: cambiar el modelo o los límites

Están comentados en `.env.example`. Quita el `#` y cambia el valor en tu `.env`:

```text
GEMINI_MODEL=gemini-3.5-flash-lite
ASSISTANT_PER_CLIENT_PER_MINUTE=4
ASSISTANT_GLOBAL_PER_MINUTE=10
ASSISTANT_DAILY_LIMIT=200
```

Los límites exactos de tu cuenta están en <https://aistudio.google.com/rate-limit>.

## Para quien despliega

La clave del sitio público no va en `.env`, va en Secret Manager de Google Cloud. Los pasos están en
[docs/CLOUD-RUN.md](docs/CLOUD-RUN.md), en la sección «Sky guide».
