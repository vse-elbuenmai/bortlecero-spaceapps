# AI usage log

NASA Space Apps requires every team to describe how AI tools were used. This log is the record that
description is written from. Every AI-assisted work session adds one row before its last commit.

- Times are local to Guadalajara, Mexico (UTC−6).
- AI-assisted commits also carry a `Co-Authored-By` trailer in their metadata.
- AI-generated images or video, if any, carry a visible watermark and are listed here.
- The idea of how to solve the challenge comes from the team. AI tools explain, compare options when
  asked, and implement what the team decided.

| When | Tool and model | What it did | Human role | Files |
|---|---|---|---|---|
| 2026-11-14 11:10 | Claude Code (Anthropic), Claude Fable 5.2 | Wrote the agent instructions for this repository from the team's pre-hackathon study notes, started this log and the source list, and created the GitHub repository. No project code and no solution design. | Miguel requested it and reviews the result. | `AGENTS.md`, `CLAUDE.md`, `docs/AI-USAGE.md`, `docs/SOURCES.md` |
| 2026-11-14 15:56 | Google Antigravity, Gemini 4 Argon (Medium) | Analyzed the three SPHEREx mission/pipeline/simulator papers, explained the astrophysics-to-ML mapping and architectural options, and implemented the SOLID data ingestion pipeline (`spherex_ingest` managed with Astral `uv`), FastAPI CORS proxy, CLI, automated pytest suite, and Spanish team guide after user selection of the hybrid architecture. | Leo defined the scope (data ingestion pipeline in Python with Astral `uv` and SOLID principles), selected the hybrid CLI + FastAPI architecture, and reviewed the implementation. | `.gitignore`, `pyproject.toml`, `uv.lock`, `requirements.txt`, `README.md`, `AGENTS.md`, `docs/SOURCES.md`, `docs/AI-USAGE.md`, `docs/GUIA-EQUIPO-INGESTA.md`, `src/spherex_ingest/**`, `tests/**` |
