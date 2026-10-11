# Paperproof

**A calmer way to read research.** A little more clarity.

Paperproof is a welcoming, session-only research-paper workspace. Read a fictional teaching sample or upload your own PDF/DOCX, ask grounded questions about it, inspect the exact passages behind each answer, and run a citation-and-reference audit that compares in-text citations with the bibliography and checks available metadata against [Crossref](https://www.crossref.org/).

There is no sign-in and no database. Uploaded documents live only in the current session.

---

## Features

### 📄 Read papers
- Three fictional teaching samples that demonstrate intentionally mixed citation issues — no specialist knowledge required.
- Upload a **PDF** or **DOCX** (up to **10 MB**, **120 pages**, ~300k characters).
- Scanned/image-only PDFs are read automatically with **English OCR** (bounded to 20 pages / 90 seconds per file).
- Headings are detected as reader sections, and bibliography entries are separated from the paper body — including nonstandard heading layouts.

### 💬 Grounded Q&A
- Ask about the selected paper and get a concise, composed **2–4 sentence** answer.
- Relevant passages are retrieved locally (section-aware ranking), then sent to **OpenRouter** for synthesis.
- Every claim must cite supplied passage IDs. Answers with missing or unknown citations fall back to an honest "this paper does not establish an answer" message rather than guessing.
- Supporting passages are shown as clickable evidence cards that open the source passage in the reader.

### 🔍 Citation & reference audit
- Compares author–year in-text citations against the parsed reference list.
- Flags:
  - Citations missing from the reference list
  - Uncited references
  - Possible duplicate references
  - Conflicting publication years
  - Incomplete reference formatting
  - Broad/absolute claims placed near a citation that needs manual review
  - Bibliography extraction gaps
- Verifies up to **15** references per audit against the Crossref public API (by DOI when present, otherwise by bibliographic search), matching title, first author, and year.
- Generates a copyable **correction prompt** for an external model, grounded in the findings and explicitly warned against inventing bibliographic details.

### 🔒 Privacy notes
- Files stay in your session; there is no persistence.
- Reference entries are sent to the Crossref public API during an audit.
- Relevant paper excerpts and your question are sent to OpenRouter to answer a question. The citation audit does **not** send claim excerpts to OpenRouter.
- Crossref results are metadata support only — a gap does not prove a work is nonexistent.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Framework | [Reflex](https://reflex.dev/) 0.9.12 (Python full-stack, React under the hood) |
| Styling | Tailwind CSS v4 (via Reflex plugin), Lora + Inter fonts |
| PDF text | `pypdf` |
| PDF rendering / OCR | `pymupdf` + `pytesseract` (Tesseract) |
| DOCX | `python-docx` |
| Sample data | `faker` |
| HTTP | `requests` |
| LLM answers | [OpenRouter](https://openrouter.ai/) |

---

## Getting started

### 1. Prerequisites
- Python **3.13** (recommended) or 3.11+. This project is developed and verified on 3.13. Python 3.10 has known incompatibilities with Reflex 0.9.12 and with this codebase.
- [uv](https://docs.astral.sh/uv/) (recommended) — it can create the venv with a managed Python 3.13 even if your system Python is older.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed and available on your `PATH` (required only for scanned PDFs). On Debian/Ubuntu: `tesseract-ocr` (see `apt-packages.txt`).
- **Node.js ≥ 22.22 or no system Node at all.** The frontend (React Router 8.4) requires Node ≥ 22.22. `run.ps1`, `reflex`, and the `/.env` setting `REFLEX_USE_NPM=1` use a **project-local portable Node** in `/.node/` (auto-downloaded on first run), so an outdated or missing system Node is not a problem on Windows.

### 2. Install
With uv (creates the venv with a known-good Python 3.13):

```bash
uv venv --python 3.13 .venv
uv pip install -r requirements.txt
```

With plain `venv` (requires a 3.13 interpreter already installed):

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Activate the venv before running anything below:

```powershell
# Windows (PowerShell)
.venv\Scripts\activate
```

```bash
# macOS/Linux
source .venv/bin/activate
```

### 3. Configure
Configuration lives in a **`.env`** file at the project root (Reflex loads it automatically via `env_file=".env"` in `rxconfig.py`). Create it from the template:

```bash
# macOS/Linux
cp .env.example .env

# Windows (PowerShell)
Copy-Item .env.example .env
```

Then edit `.env` and set your OpenRouter key:

```dotenv
OPENROUTER_API_KEY=your-key-here
```

The `.env` file is git-ignored; `.env.example` is the committed template. You can also edit the pre-created `.env` directly.

Without a key the app still runs; asking a question returns a friendly "answer service is not configured" message. The citation audit works independently of OpenRouter.

> A real environment variable (for example one set in your shell or CI) still works and is overridden by `.env` when both are present.

### 4. Run

**Windows (recommended)** — one command; uses the project venv and portable Node:

```powershell
.\run.ps1
```

(The first run auto-downloads a portable Node.js into `/.node/`; that folder is git-ignored. Use `.\run.ps1 -Mode prod` for production mode.)

**Any OS (manual)**:

```bash
reflex run
```

Then open the app at `http://localhost:3000`. (The first run downloads the JS toolchain and builds the frontend, so it can take a few minutes.)

> **Keep `REFLEX_USE_NPM=1` in `.env`.** Without it, Reflex launches the frontend with its bundled Bun, which mis-applies the `development` condition and crashes React Router's dev CLI with `restartWithMergedOptions() was called, but the process has already been restarted.` With npm, the React Router CLI picks up `--conditions=development` from `NODE_OPTIONS` and starts cleanly.

> **Troubleshooting:** If `reflex run` fails with `TypeError: ForwardRef.__init__() got an unexpected keyword argument 'is_class'` or `ImportError: cannot import name 'UTC' from 'datetime'`, your venv is on Python 3.10. Recreate it on 3.13 with `uv venv --clear --python 3.13 .venv` and reinstall requirements.

> **Troubleshooting:** If the browser shows **"Cannot connect to server: websocket error"**, another Reflex instance is almost certainly already running and sharing this project's `.web/` build folder. Two instances fight over ports (frontend on `3000`/`3001`, backend on `8000`/`8001`) and the most recently started one overwrites `.web/env.json` with its own port numbers — so the frontend ends up pointing at a backend port nobody is listening on. **Run only one instance at a time.** Close the second terminal, stop the extra processes, and relaunch `.\run.ps1` once; then hard-refresh the browser (`Ctrl+Shift+R`).

---

## Deployment

The production topology is: **Render runs the whole app** (frontend + backend + OCR) and **Vercel optionally serves a CDN copy of the static frontend** in front of it.

```
                     ┌──────────────────────────┐
  browser  ────────► │  Vercel (optional)       │   static React Router bundle
                     │  *.vercel.app            │   ──(Socket.IO ws + HTTP)──┐
                     └──────────────────────────┘                             │
                     ┌──────────────────────────┐                             │
  browser  ────────► │  Render  Caddy  :$PORT   │ ◄───────────────────────────┘
                     │  reflex backend :8000    │   Python, OCR, OpenRouter, Crossref
                     └──────────────────────────┘
```

Why the split: Reflex 0.9 processes every UI event on the backend over a **persistent Socket.IO WebSocket**. A CDN-served static frontend is just a set of files and needs no long-lived connection of its own, so it sits in front without fighting the backend's WebSocket.

### Files

| File | Purpose |
| --- | --- |
| `render.yaml` | Render Blueprint: one Docker web service, `OPENROUTER_API_KEY` prompted, health check on `/_health`. |
| `Dockerfile` | Two stages. Builder = Python 3.13 + Node 22 + uv, runs `reflex export`. Runtime = Python 3.13 + `tesseract-ocr-eng` + Caddy, **no Node**. |
| `Caddyfile` | Serves the exported bundle from `/srv`, proxies `/_event`, `/ping`, `/_upload`, `/_all_routes`, `/_health` to the backend. |
| `.dockerignore` | Keeps the build context small and stops host-generated state leaking into the image. |
| `vercel.json` | Builds the static frontend on Vercel and publishes `.web/build/client`. |
| `.vercelignore` | Excludes local toolchains from CLI deploys. |

### Why Docker on Render

Render's native Python runtime has no `root`, so `apt-get install tesseract-ocr` from `apt-packages.txt` is impossible there — scanned PDFs would silently fail to OCR. The Docker runtime installs it explicitly. Docker also pins Python 3.13 and Node 22 exactly.

`apt-packages.txt` still applies to local Debian/Ubuntu development and is not used by the container (the Dockerfile installs the package directly).

### Deploy to Render

1. Push these files to GitHub.
2. In Render: **New → Blueprint**, select the repo. Render reads `render.yaml`.
3. When prompted, paste an `OPENROUTER_API_KEY` (<https://openrouter.ai/keys>). Skipping it is fine — the citation audit still works and Q&A returns a "not configured" message.
4. Deploy. First build compiles the frontend (~2–5 min).

That alone gives you the full app at `https://paperproof.onrender.com`. Stop here if you don't need a CDN.

### Add the Vercel frontend (optional)

1. Deploy to Render first and note the URL, e.g. `https://paperproof.onrender.com`.
2. In the Render dashboard, add `REFLEX_CORS_ALLOWED_ORIGINS` to the service and redeploy, with the value set to your future Vercel origin (e.g. `https://paperproof.vercel.app`). Reflex reads this natively; `rxconfig.py` needs no change.
3. In Vercel: **Add New → Project**, select the same repo.
4. Add these as Vercel **environment variables** (available to the build):
   - `REFLEX_API_URL` = `https://paperproof.onrender.com`
   - `REFLEX_USE_NPM` = `1`
5. Deploy. `vercel.json` runs `reflex export --frontend-only --no-zip` and publishes `.web/build/client`.

`REFLEX_API_URL` has to be set at **build** time, not runtime: Reflex compiles the backend address into the JavaScript bundle. Without it the bundle points at `localhost`, and the frontend then tries to talk to the visitor's own machine.

If you later change the Vercel project name, update both `REFLEX_API_URL` (unchanged) and `REFLEX_CORS_ALLOWED_ORIGINS` on Render, then redeploy Render.

### Local Docker run

```bash
docker build -t paperproof .
docker run --rm -p 8080:8080 -e PORT=8080 -e OPENROUTER_API_KEY=sk-or-v1-... paperproof
```

Then open <http://localhost:8080>.

### Production notes

- **Sessions are ephemeral by design.** Reflex's disk state manager writes to `.states/` inside the container, which is wiped on every deploy and on every free-tier spin-down. `uploaded_files/` behaves the same way. This matches the app's session-only promise — no database, no sign-in — but a redeploy does drop in-flight sessions. To survive redeploys, attach a Render persistent disk and set the Reflex state path onto it.
- **`plan: free` is 0.1 CPU / 512 MB.** Fine for reading, asking questions, and auditing. OCR of a scanned PDF is CPU-bound; the code already caps it at 20 pages / 90 s per file. If uploads feel slow, change `plan` to `starter` in `render.yaml` — nothing else needs to change.
- **A single backend worker runs.** No Redis is configured, so Reflex stays single-process. Do not scale `numInstances` above 1 without adding Redis first: with the disk state manager, separate instances would not see each other's sessions.
- **Health checks.** `/_health` is proxied to the backend, so a backend crash fails the check and Render restarts the service.

---

## Tests

Tests live in `scripts/` and are plain `unittest` suites. Run them from the repository root so the `app` package is importable:

```bash
# from the repository root, with the venv active
python -m unittest scripts.test_paper_data scripts.test_citation_audit
```

Or run a single suite:

```bash
python -m unittest scripts.test_citation_audit
```

Not activated, or on PowerShell? Call the venv's interpreter directly:

```powershell
.venv\Scripts\python.exe -m unittest scripts.test_citation_audit
```

Some suites include inline regression tests that run when executed directly (for example `python -m app.states.workspace_state`).

---

## Project layout

```
PaperProof/
├── app/
│   ├── app.py                  # Reflex app entrypoint, theme, fonts, metadata
│   ├── citation_audit.py       # Citation/reference audit + Crossref verification
│   ├── components/
│   │   └── workspace.py        # All UI components (header, reader, Q&A, audit panel)
│   └── states/
│       ├── paper_data.py       # Sample papers + PDF/DOCX extraction, OCR, bibliography parsing
│       └── workspace_state.py  # Reactive state + retrieval and grounded-answer flow
├── scripts/
│   ├── test_paper_data.py      # Extraction and sample-data tests
│   └── test_citation_audit.py  # Audit logic tests
├── assets/                     # favicon and placeholder image
├── apt-packages.txt            # System dependency (tesseract-ocr), for local dev
├── Caddyfile                   # Static frontend + backend reverse proxy (production)
├── Dockerfile                  # Two-stage production image (build + runtime)
├── render.yaml                 # Render Blueprint
├── vercel.json                 # Vercel static-frontend config
├── .dockerignore               # Docker build context exclusions
├── .vercelignore               # Vercel CLI deploy exclusions
├── .env.example                # Template for local configuration (copy to .env)
├── .python-version             # Pin for uv: Python 3.13
├── run.ps1                     # Windows launcher (venv + portable Node + reflex run)
├── requirements.txt            # Python dependencies
├── rxconfig.py                 # Reflex configuration (Tailwind v4, env_file, sitemap)
├── wireframe.json              # Original product wireframe/spec
└── plan.md                     # Build plan / completed milestones
```

> Git-ignored and generated locally: `.env` (secrets), `.venv/` (Python env), `.node/` (portable Node), `.web/` (frontend build), `uploaded_files/` (session uploads), `.states/` (session state). `reflex.lock/` keeps the npm lockfile (`package-lock.json`); this project is npm-managed (`REFLEX_USE_NPM=1`), not Bun.

### How a question is answered
1. `workspace_state.save_question` validates the question.
2. `_retrieve_passages` splits passages into overlapping chunks, ranks them by section intent and term relevance, and excludes reference sections.
3. `_call_openrouter` sends only those passages to OpenRouter and requests a structured `{answer, cited_ids}` response.
4. `_ground_answer` verifies every cited ID exists and, for abstract questions, that an actual abstract passage is cited. Unsupported answers are replaced with an honest fallback.
5. Verified evidence is rendered as clickable cards in the reader.

### How the audit works
1. `run_citation_audit` partitions body text from bibliography entries.
2. `_build_issues` extracts author–year citations, cross-checks them against references, and flags duplicates, missing entries, uncited references, year conflicts, and formatting gaps.
3. `_verify_reference` queries Crossref by DOI or bibliographic search (with retry/backoff and a capped request rate) and records confirmed/ambiguous/not-found/lookup-error status.
4. A correction prompt summarizing the findings is generated for external use.

---

## Limitations

- Extraction is heuristic: equations, complex tables, footnotes, and text boxes may not be preserved.
- Crossref verification is capped at 15 references per audit to keep public API requests bounded.
- Confirmed metadata is supporting evidence only and does not prove a citation's claim is correct.
- The audit does not prove a work exists or does not exist; unresolved results require manual review.

---

## License

No license file is included in this repository. Contact the repository owner before reuse.
