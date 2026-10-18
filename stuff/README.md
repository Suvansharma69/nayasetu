# Project material

Everything written for people to read lives here, apart from the code. Nothing in this folder is needed to run Pramana, with one exception noted below.

| Folder | Contents |
|---|---|
| [`presentation/`](presentation/) | the animated slide deck: open `index.html` in Chrome or Edge (F full screen, P presenter view); `Pramana_presentation.pdf` is the static backup. See [`presentation/README.md`](presentation/README.md). |
| [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) | the complete project guide (also `.pdf`) |
| [`docs/paper/`](docs/paper/) | research paper, IEEE format |
| [`docs/synopsis/`](docs/synopsis/) | project synopsis, Word and PDF |
| [`docs/`](docs/) | evaluation reports and the per-case run records behind every number (indexed in [`docs/README.md`](docs/README.md)) |

**The exception:** the evaluation scripts write their run records to `docs/`, and the web interface's System view (`GET /stats`) reads some of them. Keep those files at these paths.
