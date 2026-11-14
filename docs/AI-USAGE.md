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
| 2026-11-14 15:05 | Claude Code (Anthropic), Claude Opus 5.5 | Wrote `DESIGN.md` by adapting Miguel's prior design system (Noir Cósmico v2, Bortle Cero) to a data viewer: tokens, type, spacing, components, accessibility and content rules. Interface design only; no code and no choice of features or of how to solve the challenge. | Miguel decided to reuse that design system and asked for the document; the team reviews it. | `DESIGN.md`, `AGENTS.md`, `docs/SOURCES.md`, `docs/AI-USAGE.md` |
| 2026-11-14 15:20 | Claude Code (Anthropic), Claude Opus 5.5 | Added `.gitattributes` so line endings stay LF for a team on Windows and Linux, wrote the cross-platform and branch-per-person rules into the agent instructions, pushed the design-system branch and opened its pull request. | Miguel asked for it and set the branch workflow; the team reviews the pull request. | `.gitattributes`, `AGENTS.md`, `docs/AI-USAGE.md` |
| 2026-11-14 15:40 | Claude Code (Anthropic), Claude Opus 5.5 | Created the public team wiki [bortlecero-spherex-wiki](https://github.com/vse-elbuenmai/bortlecero-spherex-wiki): 22 pages in Spanish on SPHEREx, its data and access services, the five test objects, known pitfalls, related missions, citations and a glossary, rewritten from the team's pre-hackathon study notes with a source and date on every fact. Reference material only: no project code and no solution design. Linked it from the agent instructions. Then added a searchable web version (<https://vse-elbuenmai.github.io/bortlecero-spherex-wiki/>): one Docsify `index.html` with a sidebar and full-text search, styled with the colors and font of `DESIGN.md`, published with GitHub Pages. | Miguel asked for a shared wiki and chose a separate public repository in Spanish; the team reviews it. | wiki repository; here `AGENTS.md`, `docs/AI-USAGE.md` |
