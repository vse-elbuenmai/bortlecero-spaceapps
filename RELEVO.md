# Relevo

Trabajo que se deja a medias para retomarlo después, en otra sesión o con otro agente. El otro sólo
ve git: cada relevo es **una rama pusheada más una entrada aquí**, la más nueva arriba.

- **Al entrar:** `git fetch --all --prune`, leer la entrada de arriba y
  `git branch -a | grep wip/` por si hay una rama a medias.
- **Al dejar algo:** rama `wip/<tema>`, commit aunque esté a medias, `git push -u origin wip/<tema>`,
  y una entrada aquí con **Cómo retomar**.
- **Al terminar:** commits con sentido, pull request a `main` con `--no-ff`, borrar la rama y marcar
  la entrada `(cerrada)`.

---

## 2026-11-14 · `wip/clic-en-el-cielo` · idea aparcada, sin código

Idea del equipo: tocar o hacer clic en cualquier punto del cielo del mockup y abrir solo el modal del
parpadeo con las coordenadas y las fotos de SPHEREx de ese punto, quizá dividiendo el mapa en cuadros.
Se apuntó con su análisis de factibilidad y se aparcó para no tocar el alcance antes del congelamiento
de las 20:00.

**Cómo retomar:** leer [docs/IDEA-CLIC-EN-EL-CIELO.md](docs/IDEA-CLIC-EN-EL-CIELO.md). Lo primero es
que el equipo conteste las cuatro preguntas de "Lo que decide el equipo"; sin eso no se programa.
Después se empieza por clic → RA/Dec y toque contra arrastre en `mockup/sky.js`, y se mide cuánto
tarda la API (`GET /api/v1/blink?ra=…&dec=…`) con una coordenada al azar.
