# Paperproof

**A calmer way to read research.** A little more clarity.

Paperproof is a session-only research-paper workspace. Read a fictional teaching sample or upload your own PDF/DOCX, read the paper across three separate views, ask grounded questions that cite the exact evidence behind them, and run a citation audit that compares in-text citations with the bibliography and checks metadata against [Crossref](https://www.crossref.org/).

There is no sign-in and no database. Uploaded documents and their figures live only in the current session, and are deleted from disk when the session forgets them.

---

## Features

### 📄 Read papers
- Three fictional teaching samples that demonstrate intentionally mixed citation issues — no specialist knowledge required.
- Upload a **PDF** or **DOCX** (up to **10 MB**, **120 pages**, ~300k characters).
- Scanned/image-only pages are read automatically with **English OCR** (bounded to 20 pages / 90 seconds per file).
- Headings become reader sections, and bibliography entries are separated from the paper body — including nonstandard heading layouts.
- Every document is classified before it opens: **accepted**, **accepted with warnings**, **needs review**, or **rejected**. Only `rejected` refuses to open a file, and it requires the absence of every structural signal — never the absence of one section. A document that merely lacks an Abstract is never rejected.
- An unrecognised document is **held, not dropped**. It waits for you to confirm it is a paper or discard it; nothing disappears silently.

### 🖼 Three reader views
Every paper opens as exactly three areas:

| View | Contents |
| --- | --- |
| **Paper text** | All detected sections, navigable one by one. |
| **References** | Bibliography entries as supplied, kept separate from the body. |
| **Figures & images** | Every extracted image with its caption, OCR text, and nearby paper text. |

Figures are extracted from both PDF image objects and DOCX embedded images. Captions are associated by real geometry — the nearest caption-shaped line above or below the image — so a figure is never shown detached from what it was labelled.

### 💬 Grounded Q&A
- Ask about the selected paper and get a concise, composed **2–4 sentence** answer with a **confidence** level and any **limitations** that must travel with it.
- Relevant passages are retrieved locally (section-aware ranking), then only those excerpts and your question are sent to **OpenRouter**.
- The model must return a strict JSON contract (`answer`, `evidence_ids`, `confidence`, `limitations`, `unsupported_parts`) and every cited ID must resolve to something actually supplied. An answer citing IDs that were never provided is discarded as a contract violation.
- Three distinct honest outcomes, never a guess:
  - grounded, with clickable evidence cards that open the source passage;
  - the model cited nothing and explained why — shown as *"The available material did not contain evidence that could be verified"* with its stated reasons;
  - the passages do not support an answer at all — *"This paper does not establish an answer to that question."*
- Questions are **routed** first. A methods question gets body passages; a figure question gets figures; a reference question gets the bibliography *and* the body text it cites. An ordinary scientific question never receives the reference list at all.

### 🔍 External context (opt-in)
- **Off by default.** A checkbox enables it per question.
- When on, a clearly separate section adds what external sources say, with **provenance** for every source: publisher, retrieval time, what it agreed on, what it contradicted, and where the evidence is thin.
- Search runs through **Gemini's Google Search grounding** when a Gemini key is present, and falls back to **OpenRouter's web plugin**. With neither configured it says external context is unavailable rather than inventing sources.
- External text can never be merged into, or validated as, the paper's own evidence.

### 🔍 Citation & reference audit
- Compares author–year in-text citations against the parsed reference list, and flags every finding with a **severity** (high / medium / low).
- Flags:
  - Citations missing from the reference list — *high*
  - Broad or absolute claims placed near a citation that needs manual review — *high*
  - Bibliography extraction gaps — *high*
  - Uncited references, probable duplicates, conflicting years — *medium*
  - Citation numbers pointing past the end of the reference list — *medium*
  - Incomplete reference formatting — *low*
- Numeric citation styles are **detected, not mis-parsed**. Paperproof reports what it cannot check and withholds the checks it cannot support, rather than reporting invented uncited references.
- Verifies up to **15** references per audit against the Crossref public API — by DOI when present, otherwise by bibliographic search. Each result records the lookup method, which fields matched, which conflicted, the uncertainty, and a timestamp.
- Reports every reason an audit is partial, separately, instead of burying it in prose.
- Explains itself in plain language: what was checked, what was found, what appears reliable, what needs manual review, what could not be checked, and what to do next.
- Generates a copyable **correction prompt** in a fixed structure with findings grouped by severity, a reference-verification section, and explicit safety rules against inventing any bibliographic detail.

### 🔒 Privacy notes
- Files and figures stay in your session; there is no persistence and no sign-in.
- **Image pixels are never sent to any external provider.** There is no vision model. Figures are read locally from OCR, caption, and nearby text only.
- Reference entries are sent to the Crossref public API during an audit.
- Relevant paper excerpts and your question are sent to OpenRouter to answer a question. The citation audit does **not** send claim excerpts to OpenRouter.
- Crossref results are metadata support only — a gap does not prove a work is nonexistent.
- Every log line is scrubbed of API keys before any handler sees it, and failures are logged by operation and call path rather than by message, so provider responses and paper text cannot end up in a log file.

---

## Tech stack

| Layer | Technology |
| --- | --- |
| Framework | [Reflex](https://reflex.dev/) 0.9.12 (Python full-stack, React under the hood) |
| Styling | Tailwind CSS v4 (via Reflex plugin), Lora + Inter fonts |
| PDF text | `pypdf` |
| PDF rendering / OCR | `pymupdf` + `pytesseract` (Tesseract) |
| Image measurement | `pillow` |
| DOCX | `python-docx` |
| Sample data | `faker` |
| HTTP | `requests` |
| LLM answers | [OpenRouter](https://openrouter.ai/) — free models only |
| Web search | Google Search grounding via Gemini, or the OpenRouter web plugin |

---

## Getting started

### 1. Prerequisites
- Python **3.13** (recommended) or 3.11+. This project is developed and verified on 3.13. Python 3.10 has known incompatibilities with Reflex 0.9.12 and with this codebase.
- [uv](https://docs.astral.sh/uv/) (recommended) — it can create the venv with a managed Python 3.13 even if your system Python is older.
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed and available on your `PATH`. It is only needed for scanned PDFs, and Paperproof degrades gracefully with a visible warning if it is missing. On Debian/Ubuntu: `tesseract-ocr` (see `apt-packages.txt`).
- **Node.js ≥ 22.22 or no system Node at all.** The frontend (React Router 8.4) requires Node ≥ 22.22. `run.ps1`, `reflex`, and the `.env` setting `REFLEX_USE_NPM=1` use a **project-local portable Node** in `/.node/` (auto-downloaded on first run), so an outdated or missing system Node is not a problem on Windows.

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

Then edit `.env`. Only the keys are yours to fill in; the models are already chosen and verified:

```dotenv
OPENROUTER_API_KEY=your-key-here
GEMINI_API_KEY=            # optional; only for web search
```

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | for Q&A | Grounded answers and the fallback search path |
| `GEMINI_API_KEY` | no | Preferred web-search provider. Without it search falls back to OpenRouter |
| `OPENROUTER_TEXT_MODEL` | no | Override the default free model |
| `PAPERPROOF_MEDIA_DIR` | no | Where session figures are stored |

The `.env` file is git-ignored; `.env.example` is the committed template and never contains a secret.

Without an OpenRouter key the app still runs: extraction, the three reader views, figure extraction, and the citation audit all work. Asking a question returns a friendly "answer service is not configured" message.

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

> **Troubleshooting:** If the browser shows **"Cannot connect to server: websocket error"**, another Reflex instance is almost certainly already running and sharing this project's `.web/` build folder. Two instances fight over ports and the most recently started one overwrites `.web/env.json` with its own port numbers. **Run only one instance at a time**, then hard-refresh the browser (`Ctrl+Shift+R`).

> **Troubleshooting:** If a test fails with `OSError: [Errno 28] No space left on device`, your system temp directory is full. Point `TEMP` and `TMP` at a drive with space before running tests.

---

## Deployment

Everything runs on **Render** as a single Docker web service. Caddy serves the static frontend and proxies the Reflex backend on one origin, so there is no CORS setup and no second host to keep in sync.

```
  browser  ────────►  Render  Caddy  :$PORT   (TLS terminated at Render's edge)
                     │   /            → static bundle from /srv
                     │   /_event,     → reflex backend :8000 (Socket.IO websocket)
                     │   /ping, /_upload, /_all_routes, /_health
                     │
                     │   Python 3.13, Tesseract OCR, OpenRouter, Gemini, Crossref
```

One origin means the browser never applies its same-origin policy to any of these requests, so no `Access-Control-Allow-Origin` handling is needed anywhere.

### Files

| File | Purpose |
| --- | --- |
| `render.yaml` | Render Blueprint: one Docker web service, keys prompted, health check on `/_health`. |
| `Dockerfile` | Two stages. Builder = Python 3.13 + Node 22 + uv, runs `reflex export`. Runtime = Python 3.13 + `tesseract-ocr-eng` + Caddy, **no Node**. |
| `Caddyfile` | Serves the exported bundle from `/srv`, proxies `/_event`, `/ping`, `/_upload`, `/_all_routes`, `/_health` to the backend. |
| `.dockerignore` | Keeps the build context small and excludes `.env`, so no secret can be baked into an image. |

### Why Docker on Render

Render's native Python runtime has no `root`, so `apt-get install tesseract-ocr` from `apt-packages.txt` is impossible there — scanned PDFs would silently fail to OCR. The Docker runtime installs it explicitly. Docker also pins Python 3.13 and Node 22 exactly.

`apt-packages.txt` still applies to local Debian/Ubuntu development and is not used by the container (the Dockerfile installs the package directly).

### Deploy

1. Push these files to GitHub.
2. In Render: **New → Blueprint**, select the repo. Render reads `render.yaml`.
3. When prompted, paste an `OPENROUTER_API_KEY` (<https://openrouter.ai/keys>). Skipping it is fine — extraction, the reader, figures, and the citation audit all work and Q&A returns a "not configured" message.
4. Optionally paste a `GEMINI_API_KEY` (<https://aistudio.google.com/apikey>) to enable Google Search grounding.
5. Deploy. The first build compiles the frontend (~3–6 min); later builds reuse the cached dependency layer.

The app is then live at `https://<service-name>.onrender.com`.

No `REFLEX_API_URL` and no `REFLEX_CORS_ALLOWED_ORIGINS` are required. Reflex defaults `api_url` to a localhost address and the compiled frontend rewrites that to whichever origin served the page, upgrading it to `wss://`. That is what makes the single-origin setup work with no configuration.

### Local Docker run

```bash
docker build -t paperproof .
docker run --rm -p 8080:8080 -e PORT=8080 -e OPENROUTER_API_KEY=sk-or-v1-... paperproof
```

Then open <http://localhost:8080>.

### Production notes

- **Sessions are ephemeral by design.** `rxconfig.py` sets `state_manager_mode="memory"`, so no state is written to disk at all — a redeploy, restart, or spin-down drops in-flight sessions. `uploaded_files/` still exists because Reflex serves session figures from it, but a **sweep deletes every figure folder whose paper is not in the current session**, on page load, after each upload, and on removal. The result is that a paper's figures do not outlive the session that uploaded them, even across a restart.
- **`plan: free` is 0.1 CPU / 512 MB**, and free instances spin down after ~15 minutes idle; the first request after a wake-up takes 30–60 s. Fine for reading, asking questions, and auditing. OCR of a scanned PDF is CPU-bound; the code already caps it at 20 pages / 90 s per file. If uploads feel slow, change `plan` to `starter` in `render.yaml` — nothing else needs to change.
- **A single backend worker runs.** No Redis is configured, so Reflex stays single-process. Do not scale `numInstances` above 1 without adding Redis first: state is per-process, so separate instances would not see each other's sessions.
- **Health checks.** `/_health` is proxied to the backend, so a backend crash fails the check and Render restarts the service.
- **Caddy's file capability is stripped in the Dockerfile.** The official Caddy image sets `cap_net_bind_service=+ep` on its binary; the effective bit makes the kernel refuse to exec it under Render, which does not grant that capability. `RUN setcap -r` removes it. The build asserts the capability is gone, so this cannot regress silently.
- **Free OpenRouter models are rate-limited and can be withdrawn.** The default was chosen by probing every zero-cost model against a real key; only a subset actually worked. Paperproof checks the configured model against OpenRouter's live list at runtime and shows an actionable message rather than failing silently. Verified fallbacks are listed in `.env.example`.

---

## Tests

Tests are plain `unittest` suites. Run them from the repository root so the `app` package is importable:

```bash
# from the repository root, with the venv active
python -m unittest discover scripts -p "test_*.py"
```

Or name the suites explicitly:

```bash
python -m unittest scripts.test_paper_data scripts.test_citation_audit \
  scripts.test_image_extraction scripts.test_paper_classification \
  scripts.test_question_routing scripts.test_model_and_search \
  scripts.test_integration scripts.test_session_cleanup \
  scripts.test_logging_safety
```

Not activated, or on PowerShell? Call the venv's interpreter directly:

```powershell
.venv\Scripts\python.exe -m unittest discover scripts -p "test_*.py"
```

Some suites include inline regression tests that run when executed directly (for example `python -m app.states.workspace_state`).

### What each suite covers

| Suite | Covers |
| --- | --- |
| `test_paper_data` | Extraction, section detection, sample data, bibliography parsing |
| `test_image_extraction` | PDF and DOCX image extraction, caption association, ordering, warnings |
| `test_paper_classification` | All four classification outcomes and their signals |
| `test_question_routing` | Question intent detection |
| `test_model_and_search` | Model capability configuration, search provenance, fallback behaviour |
| `test_citation_audit` | Audit findings, severity, structured explanation, prompt safety |
| `test_integration` | The ten end-to-end flows from the spec, with only the network replaced |
| `test_session_cleanup` | Session figure sweeping, path-traversal safety, media isolation |
| `test_logging_safety` | Credential redaction and failure logging |
| `app.states.workspace_state` | Inline answer-grounding and retrieval regressions |
| `test_crossref_lookup.py` | The live web-reference path: DOI extraction, metadata agreement, retry/backoff, honest failure states. Two opt-in live tests (`PAPERPROOF_LIVE_CROSSREF=1`) |

`test_integration.py` drives the real pipeline in the order the application runs it — validate, classify, extract, route, retrieve, build context, call the model at the HTTP boundary, ground the answer, audit — and stubs only `requests`. A break anywhere between two steps fails a test.

---

## Project layout

```
PaperProof/
├── app/
│   ├── app.py                  # Reflex app entrypoint, theme, fonts, installs log redaction
│   ├── citation_audit.py       # Citation/reference audit + Crossref verification
│   ├── image_extraction.py     # PDF/DOCX figure extraction, captions, session media sweeping
│   ├── logging_safety.py       # Credential redaction + safe failure logging
│   ├── model_config.py         # Free-model configuration and capability checks
│   ├── paper_classification.py # Research-paper classifier
│   ├── question_routing.py     # Question intent routing
│   ├── search_provenance.py    # External source provenance parsing
│   ├── components/
│   │   └── workspace.py        # All UI components
│   └── states/
│       ├── paper_data.py       # Sample papers + PDF/DOCX extraction, OCR, bibliography parsing
│       └── workspace_state.py  # Reactive state, retrieval, grounding, model dispatch
├── scripts/                    # Test suites (see above)
├── assets/                     # favicon and placeholder image
├── apt-packages.txt            # System dependency (tesseract-ocr), for local dev
├── Caddyfile                   # Static frontend + backend reverse proxy (production)
├── Dockerfile                  # Two-stage production image (build + runtime)
├── render.yaml                 # Render Blueprint
├── .dockerignore               # Docker build context exclusions
├── .env.example                # Template for local configuration (copy to .env)
├── .python-version             # Pin for uv: Python 3.13
├── run.ps1                     # Windows launcher (venv + portable Node + reflex run)
├── requirements.txt            # Python dependencies
├── rxconfig.py                 # Reflex configuration (Tailwind v4, env_file, memory state)
└── wireframe.json              # Original product wireframe/spec
```

> Git-ignored and generated locally: `.env` (secrets), `.venv/` (Python env), `.node/` (portable Node), `.web/` (frontend build), `uploaded_files/` (session figures). `reflex.lock/` keeps the npm lockfile; this project is npm-managed (`REFLEX_USE_NPM=1`), not Bun.

### How a question is answered
1. `route_question` classifies the intent — body, references, figures, or external.
2. `_retrieve_passages` ranks passages locally by section intent and term relevance, excluding reference sections.
3. `build_answer_context` assembles only the evidence the question needs: body passages, plus the bibliography for a reference question, plus figure records for a figure question.
4. `_call_openrouter` sends those excerpts to OpenRouter with a strict JSON schema and an instruction to treat passage text as untrusted data, not instructions.
5. `_build_grounded_answer` resolves every cited ID against what was actually supplied. Unknown IDs discard the text as a contract violation; a contract-valid answer citing nothing becomes an honest "could not be verified" message; no supportable context becomes "this paper does not establish an answer".
6. Verified evidence renders as clickable cards in the reader.

### How an image is read
1. `extract_pdf_images` / `extract_docx_images` walk the embedded image objects, discarding anything under 80 px on a side as a glyph or logo fragment.
2. `_nearest_caption` searches for the closest caption-shaped line above or below the image's real bounding rectangle.
3. Tesseract reads text from the image **locally**. If it is unavailable, the paper still opens with a visible warning.
4. Only caption, OCR text, and nearby paper text are ever used. Image pixels are never transmitted.

### How the audit works
1. `run_citation_audit` partitions body text from bibliography entries.
2. `_build_issues` extracts author–year citations, cross-checks them against references, and flags duplicates, missing entries, uncited references, year conflicts, out-of-range citation numbers, and formatting gaps — each with a severity.
3. `_verify_reference` queries **Crossref** by DOI or bibliographic search, with retry, backoff, and a capped request rate. When Crossref has no record — or is unreachable — it falls back to **OpenAlex**, which needs no key and covers far more (preprints, books, theses) because Crossref indexes only DOI-registered works. Each resolver's records are normalized to one shape so both are judged by identical title/author/year rules. `lookup_method` names the resolver that answered, and one failed lookup can never abort the audit.
4. `limits` states every reason the audit is partial; `explanation` renders the result in plain language; `_correction_prompt` builds the copyable, severity-grouped prompt with explicit prohibitions on inventing detail.

Three honesty rules are enforced: "not found" names **both** registries and keeps its *"this does not prove the work does not exist"* caveat; a resolver **outage** is never reported as a missing reference; and a confirmation obtained while Crossref was down discloses that in the message.

This verifies that a **reference** is real and matches its metadata. It does **not** check whether a **claim** attributed to that reference is accurate — see `UPGRADE-ROADMAP.md` §9.

---

## Limitations

- Extraction is heuristic: equations, complex tables, footnotes, and text boxes may not be preserved.
- Bracketed numeric citation styles are detected and reported, not fully mapped. Paperproof says so and withholds the checks it cannot support rather than reporting invented uncited references.
- Crossref verification is capped at 15 references per audit to keep public API requests bounded.
- Confirmed metadata is supporting evidence only and does not prove a citation's claim is correct. The audit verifies that a **reference** is real and matches its metadata; it does not check that the **claim** drawn from it is accurate.
- The audit does not prove a work exists or does not exist; unresolved results require manual review.
- Figure reading is local. A figure whose meaning lives only in its pixels — a plotted curve with no caption or nearby explanation — cannot be interpreted, by design.

---

## License

No license file is included in this repository. Contact the repository owner before reuse.