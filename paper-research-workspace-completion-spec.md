# PaperProof: Research-Paper Workspace Completion Specification

**Status:** Proposed implementation specification  
**Scope:** Corrections and additions required to make PaperProof a complete research-paper analysis workspace  
**Source baseline:** Current PaperProof architecture as inspected at revision `e9dbb80`  

---

## 1. Purpose

PaperProof should accept a research paper in **PDF or DOCX format**, understand its complete structure, expose the structure clearly to the user, answer questions using grounded evidence, interpret figures and other images, check references with external metadata/search support, and produce a careful citation audit with an explainable review and a safe correction prompt.

The system must prioritize:

- **Grounded answers instead of unsupported generation**
- **Self-explanation instead of copying source passages**
- **Traceability from every answer to its source material**
- **Separate handling of paper text, references, and images**
- **Clear uncertainty and review status**
- **No invented bibliographic details or claims**
- **Session-only privacy unless persistent storage is deliberately added later**

This document is an implementation specification, not a claim that all of the functionality already exists.

---

## 2. Current system baseline

The existing application already provides:

- A Reflex single-page workspace
- Three fictional sample papers
- PDF and DOCX upload
- PDF text extraction with `pypdf`
- DOCX extraction with `python-docx`
- PyMuPDF and Tesseract OCR support for scanned PDFs
- Heading detection and passage segmentation
- Bibliography extraction
- Local section-aware retrieval
- OpenRouter-based grounded Q&A
- Citation/reference auditing
- Crossref verification
- Session-only state and uploads

The main current implementation files are:

```text
app/app.py                         Reflex app entry point
app/components/workspace.py       UI components
app/states/paper_data.py           file extraction and paper model
app/states/workspace_state.py      session state, retrieval, Q&A, events
app/citation_audit.py              audit and Crossref logic
```

The current system should be extended rather than replaced. Existing behavior that already satisfies a requirement should be preserved unless this specification explicitly changes it.

---

## 3. Product requirements

### 3.1 Accepted input

The upload workflow must accept only:

- `.pdf`
- `.docx`

The existing file safety limits remain the default unless changed by configuration:

- Maximum file size: 10 MB
- Maximum PDF pages: 120
- Maximum extracted text: approximately 300,000 characters
- Maximum session uploads: 5

The system must reject:

- Unsupported extensions
- Empty files
- Corrupt files
- Password-protected PDFs
- Files exceeding configured limits
- Documents that contain no readable or recoverable content

### 3.2 Research-paper-only requirement

The application must check whether the uploaded document is plausibly a **research paper** before opening it as a normal paper workspace.

This check should be treated as a classifier and warning system, not as an absolute truth detector. A document can be valid research while using an unusual structure.

The system should inspect available signals such as:

- Title or heading structure
- Abstract, summary, or introduction
- Methods, methodology, study design, or procedure
- Results, findings, analysis, or discussion
- Conclusion or limitations
- References, bibliography, or works cited
- Academic citation patterns
- Author and affiliation-like lines
- Figure/table captions
- Research language such as participants, dataset, experiment, sample, analysis, or results

Recommended outcomes:

| Outcome | Meaning | UI behavior |
|---|---|---|
| `accepted` | Strong evidence that the document is a research paper | Open normally |
| `accepted_with_warnings` | Likely research paper but missing expected structure | Open and show warnings |
| `needs_review` | Ambiguous document type | Ask the user to confirm or continue |
| `rejected` | Clearly unrelated document or unsupported content | Do not add it to the session |

The classifier must never claim that a paper is invalid solely because it lacks one conventional section.

### 3.3 Privacy and external processing disclosure

Before processing, the interface must explain:

- The uploaded file remains session-only under the current architecture.
- Relevant extracted text may be sent to the selected OpenRouter model for Q&A.
- Image content may be sent to the selected vision-capable model when image analysis is requested or required.
- Bibliographic metadata may be sent to Crossref or another configured reference-search service.
- The citation audit does not send full claim excerpts to a language model unless a separately enabled feature explicitly does so.

The UI must distinguish **local processing** from **external processing**.

---

## 4. Paper representation and extraction model

The current `Paper` structure should be expanded so that text, references, and images are first-class objects.

### 4.1 Recommended paper model

```python
class Paper(TypedDict):
    id: str
    title: str
    authors: str
    year: str
    topic: str
    source: str
    filename: str
    page_count: int
    word_count: int
    note: str
    passages: list[Passage]
    references: list[Reference]
    images: list[PaperImage]
    extraction_warnings: list[ExtractionWarning]
    research_classification: ResearchClassification
    bibliography_parsed: bool
    bibliography_detected: bool
```

### 4.2 Passage model

The current `Passage` model should remain compatible, but should include enough location data to support accurate navigation:

```python
class Passage(TypedDict):
    id: str
    section: str
    section_id: str
    page: int
    order: int
    text: str
    source_kind: Literal["body", "caption", "table", "reference_note"]
```

`section_id` should be stable within the uploaded document. `order` should preserve document order.

### 4.3 Reference model

```python
class Reference(TypedDict):
    id: str
    order: int
    text: str
    raw_text: str
    authors: list[str]
    first_author: str
    year: str
    title: str
    doi: str
    url: str
    parse_status: str
    parse_warnings: list[str]
```

Parsing must preserve the original reference text. Normalized fields are derived data and must never overwrite the supplied source entry.

### 4.4 Image model

Images must be extracted or registered separately from normal text passages:

```python
class PaperImage(TypedDict):
    id: str
    page: int
    order: int
    filename: str
    local_path: str
    mime_type: str
    width: int
    height: int
    caption: str
    surrounding_text: str
    section: str
    image_kind: str
    ocr_text: str
    extraction_status: str
    analysis_status: str
    analysis_summary: str
    analysis_warnings: list[str]
```

The `local_path` should be session-scoped and must not be exposed as a permanent public path without an explicit security decision.

### 4.5 Extraction warnings

```python
class ExtractionWarning(TypedDict):
    code: str
    location: str
    severity: Literal["info", "warning", "error"]
    message: str
    recommended_action: str
```

Examples:

- Image-only page partially recovered by OCR
- Figure extracted but caption was not found
- DOCX text box or footnote may be missing
- Bibliography heading found but entries could not be separated
- Table structure may not be preserved
- Image analysis was not run

---

## 5. Required three-section workspace

After successful extraction, the reader must display three top-level sections:

1. **Paper text**
2. **References**
3. **Figures and images**

The current two-tab reader should become a three-tab reader. The audit panel remains a separate workflow below or beside the reader.

### 5.1 Paper text section

The Paper text section must:

- Show all detected sections in document order.
- Show a navigable section list.
- Preserve page numbers for PDFs.
- Clearly state when page numbers are unavailable for DOCX.
- Display tables as separate navigable content where possible.
- Display captions in document order or link them to their image.
- Allow evidence cards from Q&A to open the relevant passage.
- Show extraction warnings at the relevant location when possible.

### 5.2 References section

The References section must:

- Show references exactly as supplied.
- Show parsed metadata separately from raw text.
- Show whether each reference is cited in the body.
- Show audit status after an audit is run.
- Show Crossref/search status without presenting it as proof of existence or nonexistence.
- Link a reference to its detected in-text citation locations when available.
- Clearly mark references that could not be parsed confidently.

### 5.3 Figures and images section

The Figures and images section must:

- List extracted images in paper order.
- Show page and section location.
- Show the image itself where extraction succeeded.
- Show the associated caption.
- Show surrounding text that provides context.
- Show OCR text if available.
- Provide an action such as **Analyze this image**.
- Provide a question input scoped to the selected image.
- Display image-analysis answers separately from ordinary text-only answers.
- Make clear whether the answer used:
  - the image pixels,
  - the caption,
  - nearby paper text,
  - OCR output,
  - or a combination.

If image extraction fails, the tab must remain visible and explain the failure rather than silently omitting the section.

---

## 6. PDF and DOCX image extraction

### 6.1 PDF images

For PDFs, use PyMuPDF to inspect each page and extract embedded images where available. For each image:

1. Assign a stable image ID.
2. Save the image to a session-scoped location.
3. Record page number and document order.
4. Search nearby extracted text for figure/table captions.
5. Associate the image with the closest plausible caption.
6. Record extraction warnings where association is uncertain.

A rendered page crop may be used as a fallback when a figure is not available as a clean embedded image.

### 6.2 DOCX images

For DOCX files, inspect the document package and document order to identify embedded images. Preserve the order relative to paragraphs and tables as far as the format allows.

The implementation should attempt to associate images with:

- immediately preceding or following captions
- paragraphs containing `Figure`, `Fig.`, `Table`, or numbered caption patterns
- surrounding section headings

DOCX images may not have reliable page numbers. In that case, show `DOCX location unavailable` rather than inventing a page.

### 6.3 Image classification

The system may classify images into:

- figure
- chart
- plot
- diagram
- photograph
- scanned page fragment
- table image
- equation image
- unknown

Classification should be marked as inferred unless it comes from explicit document metadata or a successful model analysis.

---

## 7. Question-answering requirements

### 7.1 Answer style

The answer must be a **self-contained explanation**, not a copied passage.

The model should:

- Answer the user’s actual question directly.
- Explain the result in its own words.
- Use the supplied passages as evidence, not as text to repeat.
- Preserve qualifiers, limitations, population, scope, and uncertainty.
- Distinguish association from causation.
- Say when the paper does not establish an answer.
- Avoid invented facts, citations, quotations, page numbers, and references.
- Mention the relevant method or result when needed to make the answer understandable.

The UI should show the explanation first, followed by expandable evidence cards.

### 7.2 Retrieval context

The Q&A context should be assembled from:

- relevant body passages
- relevant captions
- relevant table text
- relevant image analysis results, when the question concerns an image
- relevant reference entries only when the question explicitly asks about references or citations

References must not be included in ordinary scientific-content retrieval by default.

### 7.3 Question routing

Questions should be routed by intent:

| Question intent | Primary context | Model capability |
|---|---|---|
| Paper content | Body passages, tables, captions | Grounded text model |
| Method/results/limitations | Section-filtered passages | Grounded text model |
| Reference details | Parsed references and external metadata | Reference-check model/search |
| Figure/chart/diagram interpretation | Image plus caption and nearby text | Vision model |
| Mixed question | Relevant combination of the above | Orchestrated multi-source answer |

The router must not rely solely on keywords. It should combine deterministic rules with a small structured intent classifier where necessary.

### 7.4 Text-answer model contract

The text-answer model should receive a strict structured prompt and return:

```json
{
  "answer": "A self-contained explanation in 2-6 sentences.",
  "evidence_ids": ["p3-c01", "p5"],
  "confidence": "high|medium|low",
  "limitations": ["..."],
  "unsupported_parts": ["..."]
}
```

The application must validate:

- `answer` is non-empty.
- Every evidence ID exists in the supplied context.
- The answer does not claim unsupported facts.
- `confidence` is one of the allowed values.
- `limitations` and `unsupported_parts` are arrays of strings.

If validation fails, show a safe fallback rather than the raw model output.

### 7.5 OpenRouter model selection

Model selection must be configuration-driven, not hard-coded into the UI logic.

Recommended configuration categories:

```dotenv
OPENROUTER_TEXT_MODEL=...
OPENROUTER_REFERENCE_MODEL=...
OPENROUTER_VISION_MODEL=...
OPENROUTER_WEB_SEARCH_MODEL=...
```

The selected models must be checked against the live provider capability before use where possible.

**Assumption:** OpenRouter model availability and web-search support vary by model/provider. The implementation must verify the currently configured model and fail clearly when a required capability is unavailable.

---

## 8. Web-search and external-knowledge behavior

The requested system includes a model that can answer using web search and logic. This must be implemented carefully so that external knowledge does not silently replace the paper.

### 8.1 Default policy

For questions about what the paper says:

- The paper remains the primary authority.
- Web search must not be used to fill gaps silently.
- If web search is used, the answer must label external context separately.

For questions about a cited reference:

- Search may be used to locate metadata or the referenced work.
- The result must distinguish supplied bibliography text from externally found metadata.

For questions such as “Is this claim supported by current evidence?”:

- The system may use web search if the user explicitly requests an external-evidence comparison.
- The answer must have separate sections such as **According to the paper** and **External context**.

### 8.2 Search provenance

Every external search result used in an answer must carry:

- URL
- title
- publisher/domain
- retrieval timestamp
- excerpt or metadata used
- reason it was included

The answer must not present search snippets alone as verified facts. The system should fetch and inspect the source page where possible.

### 8.3 Search failure behavior

If web search is unavailable:

- Continue with paper-only analysis when possible.
- State that external verification was unavailable.
- Never pretend that a search was completed.

---

## 9. Image reading and image-question answering

### 9.1 Image model behavior

When a user asks about a figure, chart, diagram, equation image, or photograph, the image model should receive:

- The image
- Caption
- Nearby paper text
- Section name
- User question
- Any available OCR text

The model must answer in its own words and should explain:

- What the image appears to show
- Which visual elements support the answer
- What the caption says
- Any uncertainty caused by low resolution, missing legend, cropped axes, or unreadable labels

### 9.2 Image-answer contract

```json
{
  "answer": "Self-contained image explanation.",
  "image_id": "img-03",
  "evidence": [
    {
      "kind": "image|caption|nearby_text|ocr",
      "id": "...",
      "description": "..."
    }
  ],
  "limitations": ["The axis labels are too small to read."],
  "confidence": "high|medium|low"
}
```

The UI must not describe an image-derived conclusion as certain when the model reports low confidence or unreadable visual elements.

### 9.3 Image analysis caching

Image analysis can be expensive. Cache results per:

```text
paper_id + image_id + normalized_question + model_id
```

The cache must be session-scoped and invalidated when the source image or model changes.

---

## 10. Reference checking and audit

The reference workflow should be divided into two related but distinct activities:

1. **Structural citation audit** — deterministic analysis of the uploaded paper.
2. **External reference verification** — Crossref/search-supported metadata checking.

### 10.1 Structural audit requirements

The audit must check:

- In-text citations missing from the reference list
- References never cited in the body
- Author–year inconsistencies
- Conflicting years
- Duplicate or probable duplicate entries
- Incomplete formatting
- Bibliography extraction gaps
- Citation style inconsistencies where detectable
- Strong or absolute claims near citations requiring manual review
- References appearing to be cited only inside the bibliography
- Numeric citations when the current author–year parser cannot reliably interpret them

Numeric-style citations must not be falsely reported as missing merely because the author–year parser cannot read them. Instead, report:

> Citation style not fully supported; manual review required.

### 10.2 External verification requirements

For each checked reference, store:

- Original raw entry
- Parsed author/title/year/DOI
- Lookup method: DOI or bibliographic search
- External source and URL
- Match status
- Matching fields
- Conflicting fields
- Uncertainty explanation
- Timestamp

Suggested statuses:

```text
confirmed
partial_match
ambiguous
not_found
lookup_error
not_checked_limit
not_enough_metadata
```

“Not found” must never be displayed as “the source does not exist.”

### 10.3 Audit result explanation

The audit UI must explain the review in plain language:

1. **What was checked**
2. **What was found**
3. **What appears reliable**
4. **What needs manual review**
5. **What could not be checked**
6. **What the user should do next**

A report should distinguish:

- Verified match
- Possible issue
- Extraction limitation
- External lookup limitation
- Unsupported citation style
- Manual review recommendation

### 10.4 Audit completion status

Recommended statuses:

| Status | Meaning |
|---|---|
| `complete` | All supported checks ran without material limitations |
| `partial` | Some checks ran but extraction, lookup, or style limits remain |
| `error` | The audit could not complete |
| `not_run` | No audit has been run |

The existing `incomplete` status may be retained for compatibility, but the UI should explain the reason explicitly.

---

## 11. Correction-prompt generation

The generated correction prompt must be safe and review-oriented.

It must include:

- Paper title and authors when available
- Audit scope and limitations
- Each finding with location and excerpt
- Original reference text
- External verification status
- Suggested action
- Clear instructions not to invent details
- A requirement to preserve the selected citation style
- A requirement to mark unresolved fields rather than guessing

The prompt must say that audit findings are **leads for review**, not automatic proof of error.

Recommended output structure:

```text
Paper under review
Audit scope
Important limitations
Findings grouped by severity
Reference verification notes
Requested correction format
Safety rules
```

The prompt should be copyable, but PaperProof must not automatically rewrite the user’s paper or publish corrections.

---

## 12. Orchestration flow for a mixed question

For a question that involves text, references, and images, use an explicit orchestrator:

```text
User question
  ▼
Intent classification
  ├── paper text needed?
  ├── references needed?
  ├── images needed?
  └── external search explicitly requested?
  ▼
Retrieve relevant paper sections
  ▼
Retrieve relevant images/captions
  ▼
Parse or select relevant references
  ▼
Run only the required specialist calls
  ├── text model
  ├── vision model
  ├── reference/search model
  └── web search, when allowed
  ▼
Synthesis model or deterministic response composer
  ▼
Validate evidence and provenance
  ▼
Return self-contained answer plus expandable evidence/provenance
```

The orchestrator must avoid calling every model for every question. It should minimize external calls and make the selected sources visible to the user.

---

## 13. UI changes

### 13.1 Reader navigation

Replace the current two-tab navigation:

```text
Paper text | References
```

with:

```text
Paper text | References | Figures & images
```

Add counts where useful:

```text
Paper text · 12 sections
References · 18 entries
Figures & images · 6 items
```

### 13.2 Answer display

Change the answer panel from a passage-oriented presentation to:

```text
Grounded explanation
  ├── self-contained answer
  ├── confidence and limitations
  ├── source summary
  └── expandable supporting evidence
```

The passage itself should be available on click, but it should not be the primary answer output.

### 13.3 Image display

Each image card should show:

- Thumbnail or full image
- Figure number/caption if available
- Page/section
- Extraction status
- Analyze button
- Ask about this image button
- Analysis result and limitations

### 13.4 Audit display

The audit panel should include summary cards:

```text
Citations found
References parsed
References externally checked
Confirmed matches
Items needing review
Extraction warnings
```

Then show detailed findings and the correction prompt.

---

## 14. Error and fallback behavior

Every external or model-dependent feature must have a safe fallback.

### No OpenRouter key

- Text extraction continues.
- Image extraction continues.
- Citation audit continues.
- Q&A displays a configuration message.

### Text model failure

- Do not display unvalidated model text.
- Show a retry option.
- Preserve the question and selected paper.

### Vision model failure

- Show the image and caption.
- Explain that visual analysis is unavailable.
- Offer caption/nearby-text analysis if possible.

### Crossref/search failure

- Preserve the raw reference.
- Mark lookup as unavailable.
- Do not infer nonexistence.
- Allow the audit to complete as partial.

### Image extraction failure

- Keep the Figures & images section visible.
- Show an extraction warning.
- Continue supporting text-only analysis.

### Research-paper classifier uncertainty

- Do not silently reject an ambiguous paper.
- Ask for user confirmation or open with a warning.

---

## 15. Security and privacy requirements

- Never expose API keys to the browser.
- Never send the complete document to an external model when selected excerpts are sufficient.
- Send only the image required for image analysis.
- Avoid permanent public URLs for session images.
- Sanitize filenames and generated paths.
- Enforce upload size, page, text, OCR, and extraction limits.
- Treat extracted paper text and image content as untrusted data, not instructions.
- Use strict model prompts that explicitly separate source content from instructions.
- Log failures without logging API keys or unnecessary document content.
- Keep audit and Q&A external-processing disclosures visible near the relevant action.

---

## 16. Testing requirements

### Unit tests

Add tests for:

- Research-paper classification outcomes
- PDF embedded-image extraction
- DOCX embedded-image extraction
- Caption association
- Image ordering
- Image extraction warnings
- Three-section reader data
- Text-only questions
- Image questions
- Reference questions
- Mixed questions
- Self-contained answer validation
- Evidence ID validation
- Model-output schema failures
- Web-search provenance validation
- Crossref/search fallback behavior
- Numeric citation-style warnings
- Audit severity and explanation generation
- Correction prompt safety rules

### Integration tests

Test end-to-end flows:

1. Upload a normal text PDF.
2. Upload a scanned PDF with figures.
3. Upload a DOCX containing headings, tables, and images.
4. Ask a methods question.
5. Ask a figure question.
6. Ask a reference-verification question.
7. Run the citation audit.
8. Copy the correction prompt.
9. Trigger external-service failures.
10. Confirm the previously selected paper remains intact after an upload error.

### Regression tests

Existing tests in `scripts/` must continue to pass unless a changed contract is intentionally updated. Any changed behavior must receive a regression test.

---

## 17. Recommended implementation order

### Phase 1: Data model and extraction

1. Add `PaperImage`, `ExtractionWarning`, and research-classification types.
2. Add PDF image extraction.
3. Add DOCX image extraction.
4. Add caption and surrounding-text association.
5. Preserve current text/reference extraction behavior.

### Phase 2: Three-section reader

1. Add image state and selectors.
2. Change the reader to three tabs.
3. Build image cards and image detail view.
4. Add extraction-warning display.

### Phase 3: Research-paper classification

1. Implement deterministic structural signals.
2. Add a classification result to the upload pipeline.
3. Add warning/confirmation UI.
4. Keep ambiguous documents recoverable by explicit user choice.

### Phase 4: Q&A routing and self-contained answers

1. Add intent routing.
2. Preserve current local retrieval.
3. Add structured answer schema and validation.
4. Change the UI to emphasize explanation over passage text.
5. Add vision-question routing.
6. Add reference-question routing.

### Phase 5: External search and model configuration

1. Add model configuration by capability.
2. Add capability checks.
3. Add search provenance objects.
4. Add explicit external-context answer sections.
5. Add failure and unavailable-service states.

### Phase 6: Audit completion

1. Improve citation-style detection.
2. Add richer reference parsing.
3. Add severity and review explanations.
4. Add explicit partial-audit reasons.
5. Improve correction-prompt structure and safety wording.

### Phase 7: Testing, privacy, and deployment

1. Add unit and integration tests.
2. Add session-image cleanup behavior.
3. Review logging and external-processing disclosures.
4. Update Docker/runtime dependencies if image libraries require them.
5. Update README and deployment notes.

---

## 18. Acceptance criteria

The feature set is complete when all of the following are true:

- A PDF or DOCX can be uploaded and safely rejected if invalid or clearly unsupported.
- The system classifies the document as accepted, accepted with warnings, needs review, or rejected.
- A valid paper opens with exactly three reader areas: paper text, references, and figures/images.
- All detected text sections remain navigable.
- References are shown separately from the paper body.
- Embedded images are extracted or an explicit extraction warning is shown.
- Captions and nearby context are associated with images when possible.
- A normal paper question produces a self-contained explanation, not a pasted passage.
- The answer is backed by validated passage/image/reference evidence.
- Unsupported questions result in an honest limitation message.
- Image questions use a vision-capable model only when required.
- Reference questions use reference metadata and external verification when available.
- Web-search usage is explicit and provenance is shown.
- The citation audit explains both findings and limitations.
- Crossref/search failures are shown as lookup limitations, not proof of nonexistence.
- The correction prompt is copyable and explicitly prohibits invented details.
- Existing sample-paper, extraction, Q&A-grounding, and citation-audit regressions continue to pass.
- No API secret is exposed to the frontend.

---

## 19. Decisions that must be confirmed before implementation

The following details are not fully determined by the current repository and should be selected before coding:

1. **Exact OpenRouter models** for text, vision, reference checking, and search-capable reasoning.
2. Whether external web search is allowed by default or only after the user explicitly asks for it.
3. Whether image files may be temporarily uploaded to an external vision provider.
4. Whether “research paper only” should hard-reject unrelated documents or use a confirmation flow for ambiguous files.
5. Whether numeric citation styles must be fully supported in the first implementation or only warned about.
6. Whether users should be able to export the extracted paper, images, and audit report.
7. Whether session-only storage remains the long-term privacy model.
8. Whether the correction prompt should be generated only, or whether a later feature may propose structured edits without automatically applying them.

These are product decisions, not implementation facts. Until confirmed, use the safest reversible default: **warn rather than reject when classification is uncertain, keep the paper as the primary authority, make external search opt-in for claims, and never auto-apply corrections.**

---

## 20. Summary

The completed PaperProof system should become a structured research-paper workspace rather than only a text reader with a reference audit.

Its core pipeline should be:

```text
Upload PDF/DOCX
  ▼
Validate file and classify as research paper
  ▼
Extract text, sections, references, tables, captions, and images
  ▼
Open three-section reader:
  Paper text | References | Figures & images
  ▼
Route each question to the required evidence and specialist model
  ▼
Generate a self-contained explanation
  ▼
Validate evidence and show provenance
  ▼
Run structural citation audit and external reference checks
  ▼
Explain findings, limitations, and recommended review actions
  ▼
Generate a safe, copyable correction prompt
```

The essential design principle is:

> **Models may explain and compare supplied evidence, but they must not silently invent missing research content, bibliographic details, visual facts, or audit conclusions.**
