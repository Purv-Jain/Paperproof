# Upgrade roadmap

What Paperproof should improve, why each item matters, and how to verify it is
actually done. Ordered by impact ÷ effort, not by date.

Every item is written so it can be checked: each one names the success
criterion and the test that should catch a regression. Anything without a
verifiable outcome belongs in a backlog, not here.

**Legend** — `[effort: S|M|L]`, `[status: done | todo]`

---

## Shipped in this session

### `[done]` Grounded answers actually reach the model

`save_question` read a name it never assigned, raising `NameError` on every
question, which a broad `except` turned into *"We couldn't generate a grounded
answer."* OpenRouter was never contacted. One identifier, fixed.

- **Verified by** `test_save_question_reads_only_names_it_binds` (symbol-table
  check that every name the handler reads is bound) and
  `test_asking_a_question_reaches_the_model_and_grounds_the_answer` (drives the
  real handler against a stubbed provider).

### `[done]` IEEE-style reference titles parse correctly

`_reference_title` only understood APA `(2025). Title.`. On an IEEE entry it
found the year, took the remainder, and split at the first `.` — which lands
inside the trailing DOI — so it returned `"doi: 10"` as the title for
**every** reference. Title similarity then scored ~0 and nothing could ever be
confirmed. On the sample paper: **0 → 13 confirmed**, titles **0/28 → 27/28**.

- **Verified by** `scripts/test_crossref_lookup.py::ReferenceTitleParsingTests`
  (reintroducing the bug fails 5 tests).

### `[done]` Model fallback actually exists

`FALLBACK_MODELS` was defined and referenced nowhere: a withdrawn free model
ended every request until someone edited the environment. `effective_model()`
now rolls to the first backup the OpenRouter index can confirm.

Two rules keep it honest: it **refuses to switch on an empty index** (a failed
lookup is not evidence), and it **keeps the configured model when no backup
qualifies** so the request fails with OpenRouter's real error rather than a
confusing wrong-model one. Web-search fallbacks are filtered to models that
advertise tools, so a text-only backup cannot silently break search.

- **Verified by** `scripts/test_model_and_search.py::ModelConfigTests` (8 tests).

### `[done]` Crossref web path has test coverage

The existing audit suite stubbed `_verify_reference` out entirely, so the code
that actually talks to Crossref had zero tests. Now covered: DOI extraction,
exact/404/mismatched-DOI, bibliographic fallback, retry with bounded
`Retry-After`, network errors, and audit-survives-a-bad-lookup.

- **Verified by** `scripts/test_crossref_lookup.py` (23 tests, 2 live opt-in
  via `PAPERPROOF_LIVE_CROSSREF=1`).

### `[done]` Reference list scrolls, answers cite entry numbers

A 28-entry bibliography pushed the reader ~3,600px down. The list is now
capped at `max-h-[420px]` / `md:max-h-[520px]` with `overflow-y-auto`. Answers
cite `[n]` derived from **real list position**, so a number always points at
the row the reader can go and look at.

### `[done]` Page-background images are not shown as figures

Measured on a real IEEE template: the same 22 image objects were composited onto
every page — 132 embedded images across 6 pages. The extractor reported all 22
as "figures", burying any real ones and leaving the reader with a wall of
meaningless artwork.

Now counted per page first: an object drawn on more than **2** pages is page
furniture and is skipped, with an `info` warning naming how many were left out.
Because OCR runs in a later pass over extracted images only, skipped chrome also
saves that many tesseract calls — which matters on a 0.1-CPU instance where
tesseract *is* installed.

**Known limit:** this only catches *repeated* chrome. A single-page logo or a
one-off decorative graphic still appears. An aspect-ratio signal would catch
more but risks dropping genuine wide figures such as architecture diagrams.

### `[done]` Empty figures section says "no figures" instead of showing clutter

A paper with no figures rendered a tall empty bordered box plus an extraction
notes panel that repeated the same sentence. The minimum height is now
conditional, the section states the absence and its reason in one line, and the
two duplicate notes are suppressed **only when there are no images**. Warnings
about anything else (OCR failures, oversized figures) are always kept.

---

## Tier 1 — honesty fixes

> These matter more than features. Paperproof is a research tool, and the one
> failure mode it must never have is looking more certain than it is.

### 1. The audit silently skips references

`[todo]` `[effort: S]`

`MAX_VERIFIED_REFERENCES = 15` (upstream constant, not a Paperproof setting).
On the sample paper that meant **13 of 28 references were labelled
`not_checked_limit`** — a status a reader can easily misread as "all clear".
The summary cards reported "Externally checked: 15" with no denominator.

The UI is currently more confident than the audit actually is.

**Do:** surface `checked / total` everywhere the count appears; add an
explicit *"N of M references were not checked"* line to `limits` and the
summary cards; make the cap configurable by environment variable.

**Success:** no screen shows a checked count without the total beside it.

**Caution:** raising the cap multiplies Crossref load. A DOI cache (item 4)
should land *first* if the cap goes up.

### 2. A 34-second audit with no progress feedback

`[todo]` `[effort: M]`

15 lookups at ≥1s spacing plus network is ~34s locally, single-threaded. On
Render **free (0.1 CPU / 512 MB)** this will be materially worse, and the free
tier spins down after 15 minutes idle — long enough for a restart mid-audit.

**Do:** stream per-reference progress; make the audit resumable per reference;
ensure a restart never loses completed lookups.

**Success:** closing the tab and reopening does not repeat finished lookups.

### 3. Missing tesseract degrades silently

`[todo]` `[effort: S]`

Local runs logged *"Could not OCR extracted image"* for every figure and
continued. Tesseract **is** installed in the Docker image, so production is
fine — but a local run quietly loses figure OCR text with no UI signal.

**Do:** detect once at startup; surface a banner in the upload panel that
figures will be read from captions and nearby text only.

**Success:** a user with no tesseract is told, before they upload, not after.

### 4. Cache verified DOIs

`[todo]` `[effort: M]`

Re-auditing the same paper re-queries Crossref and OpenAlex for everything.
This makes repeat audits slow, spends the public APIs' rate limits on
duplicates, and risks an IP-level throttle under load.

**Do:** persistent `DOI → (status, matched metadata, checked_at)` cache. Cache
positives longer than negatives — a 404 can change when a work is finally
registered, but a confirmed DOI does not un-confirm.

**Success:** second audit of an unchanged paper issues no network requests.

**Precondition:** this should land **before** the item 1 cap is raised.

### 5. Resume a single failed reference

`[todo]` `[effort: S]`

One `ReadTimeout` cost a reference its check for the whole run, with no way to
retry just that entry.

**Do:** per-reference "re-check" action.

---

## Tier 2 — detection quality

### 6. A second resolver (OpenAlex) — **done**

`[done]`

Crossref indexes **DOI-registered works only**, so a preprint, book, thesis, or
report returns "not found" there and becomes indistinguishable from a fabricated
reference. Measured against a real case: `10.48550/arXiv.1706.03762` (*Attention
Is All You Need*, a DataCite DOI) returns **404 from Crossref** and **200 from
OpenAlex** with correct title, year, and first author. Before this change that
landmark paper was reported as unverifiable.

OpenAlex requires **no key and no billing**, so the fallback costs nothing.

Implemented as: Crossref first, OpenAlex on a 404/empty result *and* on a
Crossref outage. OpenAlex records are normalized into the Crossref shape so the
existing comparison logic is shared unchanged rather than duplicated.

**Honesty rules enforced:** "not found" now names both registries and keeps its
"this does not prove the work does not exist" caveat; a resolver **outage** is
never laundered into "not found"; and a confirmation obtained while Crossref was
down discloses that in the message and uncertainty.

- **Verified by** `scripts/test_crossref_lookup.py::OpenAlexFallbackTests`
  (8 tests; reintroducing the bug fails 4).

### 7. Fabricated reference pointing at a real, unrelated DOI

`[todo]` `[effort: L]`

**This is the important gap in fake-reference detection today.** A fabricated
entry carrying a *genuine but unrelated* DOI resolves successfully. The title,
first-author, and year comparison catches it — but only as `ambiguous`, which
reads as a soft warning next to metadata drift.

**Do:** escalate. A DOI that resolves while the title disagrees well beyond
formatting noise is strong evidence of a mismatched citation and should be
`high` severity, not `medium`.

**Success:** the severity of a resolved-but-contradicted DOI is `high`, and the
explanation says the work exists but does not match this entry.

### 8. Orphan continuation lines

`[todo]` `[effort: M]`

A wrapped reference got split, producing a fragment entry
(`Environment, Development and Sustainability, 2025, doi: ...`) that is not a
reference at all. Reference **boundary detection** is the defect — not title
parsing. 1 of 28 on the sample paper.

**Do:** require an entry to start with a plausible author/index pattern before
accepting it; merge a line into the previous entry when it does not.

**Success:** entries that begin mid-sentence are never emitted alone.

### 9. Claim-level checking — **not built, by design**

`[todo]` `[effort: L]` `[decision needed]`

Current verification proves **the work exists and the metadata matches**. It
says nothing about whether the *claim* drawn from it is accurate. A real paper
can be cited for something it does not say.

The upstream code anticipates this and explicitly refuses to blur it:
*"This audit does not send claim excerpts to OpenRouter; only bounded relevant
excerpts would be sent if a separate claim-analysis feature uses it."*

If built, it must be a **separate, labelled pass** — never folded into the
existence check, and never presented as proof a claim is wrong. It would send
claim text to an external provider, which is a privacy decision, not a coding
one.

**Decide before building:** is this in scope for this product at all?

---

## Tier 3 — product quality

### 10. Export and share the audit

`[todo]` `[effort: M]`

The highest-leverage missing feature for this audience. A user who just found a
fabricated reference in their paper currently has no way to show anyone.

**Do:** copyable Markdown (the correction prompt already exists and is
well-structured) and a printable HTML/PDF report.

### 11. Per-paper audit in the References tab

`[todo]` `[effort: S]`

Audit results currently live in a separate panel from the reference list, so a
reader must hold two mental models. Put verification badges inline with each
entry, and make the `[n]` number a visible badge so the link between an answer's
citation and the reference row is immediate.

### 12. Cache passage chunking

`[todo]` `[effort: S]`

`_chunk_passages` and `_retrieve_passages` re-chunk and re-tokenize the whole
document on **every** question. Memoize chunks per paper — pure win, no
behaviour change.

### 13. Keyboard and screen-reader support for the scroll region

`[todo]` `[effort: S]`

The new scrollable list needs `tabindex="0"`, `role="region"`, and an
`aria-label`, or it is unreachable by keyboard.

### 14. End-to-end browser test

`[todo]` `[effort: L]`

Every test today is Python-level. Nothing exercises the **rendered** UI — which
is exactly where the unbounded reference list and the extension-induced
hydration warning live. A single Playwright test covering upload → audit →
answer would close a real gap.

### 15. Auth and rate limiting

`[todo]` `[effort: M]` — deferred

No auth, no rate limiting. Anyone with the URL can burn the operator's
OpenRouter quota, and — because Gemini free tier usually cannot do Search
grounding and `_call_search` falls through to the paid OpenRouter web plugin —
can spend real money. This is the one thing standing between this and a safe
public deploy.

---

## Known operational limits

Not upgrade items — facts a deployment must plan around.

| Limit | Consequence |
|---|---|
| `plan: free` (0.1 CPU / 512 MB, 15-min idle spin-down) | 30–60s cold start; a long audit risks a restart mid-run |
| `state_manager_mode="memory"` | Every deploy, restart, or spin-down drops all sessions and figures |
| Single backend worker, no Redis | `numInstances` must stay at 1; instances cannot see each other's sessions |
| `:free` OpenRouter models | Heavy 429s under real traffic — now mitigated by `effective_model()`, but a paid model is the real fix |
| Gemini free tier lacks Search grounding | Web search silently falls through to the **paid** OpenRouter web plugin |
| Outbound Crossref / OpenAlex calls | Risk of IP-level throttling under load — a reason to build item 4 early |

---

## Definition of done

An upgrade is done when:

1. It has a test that **fails without it** (reintroduce the bug and watch it go red).
2. The full suite passes offline and deterministically.
3. Any new status carries an honest `uncertainty` string, and nothing is ever
   reported as proven without a source.
4. Claims in the README about what the audit covers stay true — if a capability
   is added or removed, this file and `README.md` change together.