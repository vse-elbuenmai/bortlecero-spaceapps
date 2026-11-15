# Idea: tocar el cielo y ver el parpadeo de ese punto

**Estado:** aparcada, sin código. Se apuntó el sáb 14 nov 2026 para retomarla con calma. Vive en la
rama `wip/clic-en-el-cielo` hasta que el equipo la desarrolle.

## La idea (del equipo)

En la vista del cielo del mockup ([mockup/sky.js](../mockup/sky.js)), el usuario toca o hace clic
en **cualquier punto** del mapa. Se abre sola la ventana del parpadeo con las coordenadas de ese
punto y la serie de fotos de SPHEREx de ese trozo de cielo. Una variante es dividir el mapa en
**cuadros**: tocar un cuadro abre el de ese cuadro.

Hoy al modal sólo se llega con el buscador o con los botones de los cinco objetos de prueba.

## Qué ya existe

- **La cuenta de "punto de la pantalla → RA/Dec"** ya la hace el shader para cada píxel
  ([sky.js:92-96](../mockup/sky.js#L92-L96)): proyección estereográfica inversa. La cuenta contraria,
  de "RA/Dec → punto de la pantalla", está en `project()` ([sky.js:64](../mockup/sky.js#L64)).
- **El modal acepta cualquier posición**: `openModal(target)` ([sky.js:373](../mockup/sky.js#L373)).
  Fuera de Barnard hoy muestra las coordenadas y el aviso de que no hay datos.
- **La API de ingesta acepta cualquier coordenada**: `GET /api/v1/blink?ra=…&dec=…`
  ([api.py:184](../src/spherex_ingest/api.py#L184)). El recorte mide 180″ (3′) por defecto, como
  máximo 1800″ (30′).

## Las piezas

1. **Clic → RA/Dec.** Repetir en JavaScript la cuenta del shader para el punto del clic. Es poco
   trabajo.
2. **Separar un toque de un arrastre.** Hoy arrastrar gira el cielo
   ([sky.js:478](../mockup/sky.js#L478)). Un toque corto, que casi no se mueve, abriría el modal;
   un arrastre seguiría girando. Tiene que funcionar con mouse, dedo y teclado.
3. **Cuadrícula (opcional).** Dos maneras:
   - **Sin cuadrícula visible:** el clic da el punto exacto.
   - **Con cuadrícula visible:** el clic se ajusta al centro del cuadro. Una cuadrícula de RA/Dec
     en cuadros iguales se aplasta cerca de los polos, como los meridianos de un globo. La malla
     estándar en astronomía, con celdas de igual área, es HEALPix; si se usa, se cita en
     `docs/SOURCES.md`.
4. **La imagen real del punto.** Fuera de Barnard no hay fotos preparadas: hay que pedirlas a la API
   en vivo. El navegador no puede ir directo a IRSA porque IRSA no manda CORS.

## Trampas que ya se ven

- **La escala no coincide.** El mapa nunca baja de unos 30° de ancho, y el recorte mide de 3′ a 30′.
  Un cuadro que se pueda tocar mediría grados, y el modal mostraría un pedazo pequeño de su centro.
  Es como tocar una ciudad en un mapamundi y recibir la foto de una cuadra.
- **La API tiene que estar desplegada** en un servidor público. El despliegue todavía no se decide.
  Sin ella, el clic sólo puede mostrar las coordenadas.
- **Espera.** Cada recorte de IRSA pesa ~4 MB y por posición son varios. Se calcula que tardará de
  segundos a decenas de segundos por clic, **pero no está medido**. El modal necesita un estado de
  "cargando".
- **Un punto al azar casi nunca muestra algo que se mueva.** En la mayor parte del cielo, el
  parpadeo son estrellas quietas. Algunos puntos pueden traer pocas pasadas. El modal tiene que saber
  decir "aquí no hay nada que parpadear".

## Lo que decide el equipo antes de programar

1. ¿Cuadrícula visible (y de qué tamaño) o clic libre?
2. ¿Basta con coordenadas más el aviso, o se conecta a la API desplegada?
3. Si se conecta: ¿de qué tamaño es el recorte, cuántas fotos se piden y qué ve el usuario mientras
   espera?
4. ¿Cómo se distingue en la interfaz tocar para girar de tocar para abrir?

## Para retomarla

```sh
git fetch --all --prune
git checkout wip/clic-en-el-cielo
uv run python -m http.server 8765 --directory mockup   # http://127.0.0.1:8765/
uv run spherex-ingest serve --port 8000                # API local, docs en /docs
```

Sin las respuestas a las preguntas de arriba no se programa nada. Con ellas, se empieza por las
piezas 1 y 2 en `mockup/sky.js`, y se mide la espera real de la API con una coordenada al azar antes
de diseñar el estado de "cargando".
