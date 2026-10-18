# Pramana — presentation

An animated slide deck: 15 slides, about 11–13 minutes that runs offline in a browser. It has no internet dependency: the fonts are bundled (SIL Open Font License), there are no external libraries, and every figure comes from the project's own data and evaluation files.

## Before the talk

1. **Check the `[[VERIFY: …]]` tags.** Amber dashed tags mark every detail that comes from outside the project (roll number, the guide's designation, paper details, competitor tools, the references). Confirm each one, then delete the tag in `index.html` (search for `[[VERIFY`).
2. **Drop in the media.** See `media/README.txt`: the four screenshots are in place; the screen recording (`media/demo.mp4`) is optional. Without it the demo slide shows a frame reading "Switching to the browser".
3. **Re-export the PDF backup** after adding media (command below).
4. Open `index.html` in Chrome once and step through every slide on the machine you will present from.

## Presenting

Open `index.html` in **Chrome or Edge** (double-click, or drag it into the browser). Press **F** for full screen.

| Key | Action |
|---|---|
| → · Space · PageDown · click | next build / next slide (presentation clickers work) |
| ← · PageUp | back |
| **N** | speaker notes along the bottom of this screen |
| **P** | presenter window: notes, timer, current and next slide (drag it to your laptop screen when projecting with an extended display) |
| **F** | full screen |
| **T** | switch between the dark "ink" theme and a light "paper" theme (use paper if the room is bright or the projector washes out dark slides) |
| **B** or **.** | black screen |
| number + Enter | jump to slide (e.g. `10` Enter for the multi-agent pipeline) |
| Home / End | first / last slide |
| ? | key help |

Slides build step by step: a press reveals the next part before moving on. The notes mark each press as `[click]`.

The address bar keeps the slide number (`index.html#12`), so a refresh returns to the same slide.

## The live demo (slide 15)

Start the app beforehand: `run_web.bat` in the project root, then `http://127.0.0.1:8000`. Paste the motorcycle facts shown on the slide. A live run takes about a minute. If anything misbehaves live, open the saved **Motorcycle theft** sample in the app; it replays instantly and is labelled as a replay.

## Structure

| # | Section | Slide |
|---|---|---|
| 1 | Title | |
| 2–4 | 01 The problem | research done by hand; renumbering; invented citations + the problem statement |
| 5 | 02 What exists | research, existing tools, the gap |
| 6–7 | 03 Our solution | facts in, checked memo out; how we do it in four steps |
| 8–9 | 04 How it works | architecture, retrieval |
| 10–13 | 05 Multi-agent pipeline | six agents on one shared state; identify + verify; applicability + defence; precedents + outcomes |
| 14 | 06 Technology | the stack and why each piece |
| 15 | 07 Demo | live run; "Thank you" on the last click |

Results, the IL-TUR benchmark and the references are in `stuff/docs/` (the guide and the paper) for questions.

## PDF backup

`Pramana_presentation.pdf` contains every slide in its final state, one per 16:9 page, for a machine that only has a PDF viewer or PowerPoint's PDF import. To regenerate it after editing the deck or adding screenshots (from the project root, in Git Bash):

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless=new --disable-gpu \
  --no-pdf-header-footer --virtual-time-budget=5000 \
  --print-to-pdf="D:/nayasetu/stuff/presentation/Pramana_presentation.pdf" \
  "file:///D:/nayasetu/stuff/presentation/index.html?print"
```

Add `&theme=paper` after `?print` for a light-background PDF suitable for printing handouts.

## Where the numbers come from

Every figure on the slides was checked against the project's records, not typed from memory:

- Corpus counts (2,699 judgments: 918 SC + 1,781 HC; 87,036 passages): `data/processed/build_report.json`; the outcome threshold of 5 judgments is `MIN_JUDGMENTS` in `src/pipeline/analytics.py`.

- Corpus and graph counts (933 sections, 2,699 judgments, 16,493 citation edges, 539 IPC→BNS bridges, 87,036 judgment passages): the built citation graph and `data/processed/build_report.json`.
- The citation-graph pictures (slides 11 and 13) draw a **real** subgraph: `tools/export_subgraph.py` writes `data/subgraph.js` from the built graph (41 judgments citing IPC 378, 379 and 411). Re-run it if the graph is rebuilt.
- The motorcycle example (candidates, precedents, similarities, appeal outcomes, the counter-argument): `app/samples/motorcycle_theft.json`.
- Embedder bake-off: `stuff/docs/embedding_bakeoff.md`. Retry loop: `stuff/docs/phase4_pipeline.md`. Catch rate, court orders and benchmark: `stuff/docs/evaluation_results.md` and `stuff/docs/iltur_lsi_test_100_summary.json`. Rules and laptop figures: `CLAUDE.md`.

## Files

```
stuff/presentation/
├── index.html              the deck: slides and speaker notes
├── assets/deck.css         stage, motion vocabulary, notes/presenter/print styles
├── assets/slides.css       per-slide layout and animation
├── assets/flow.css         layout of the problem, solution and backup slides
├── assets/motion.css       title seal, four-step track, agents diagram, applicability, technology wall
├── assets/deck.js          navigation, builds, counters, graph layout, media loading, presenter view
├── data/subgraph.js        real citation-graph neighbourhood (generated)
├── tools/export_subgraph.py
├── fonts/                  Spectral, IBM Plex Sans, IBM Plex Mono (SIL OFL 1.1)
├── media/                  drop the recording and screenshots here (see media/README.txt)
└── Pramana_presentation.pdf  static backup
```
