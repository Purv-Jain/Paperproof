import reflex as rx

from app.citation_audit import AuditIssue, ReferenceAudit
from app.image_extraction import (
    UPLOAD_URL_PREFIX,
    ExtractionWarning,
    PaperImage,
)
from app.model_config import CapabilityCheck
from app.search_provenance import SearchSource
from app.states.paper_data import AnswerEvidence, Paper, Passage, Reference
from app.states.workspace_state import WorkspaceState, reference_number


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.el.a(
                rx.el.img(
                    src="/brand/icon-book-check.webp",
                    alt="",
                    width=40,
                    height=38,
                    class_name="h-9 w-auto shrink-0 sm:h-10",
                ),
                rx.el.img(
                    src="/brand/logo-text.webp",
                    alt="PaperProof",
                    width=148,
                    height=31,
                    class_name="h-[24px] w-auto shrink-0 sm:h-[30px]",
                ),
                href="/",
                aria_label="PaperProof home",
                class_name="flex items-center gap-2.5",
            ),
            rx.el.span(
                rx.el.span(class_name="h-1.5 w-1.5 rounded-full bg-[#bc7567]"),
                "A calmer way to read research",
                class_name="hidden items-center gap-2 text-xs font-medium text-[#68716f] sm:flex",
            ),
            class_name="mx-auto flex w-full max-w-[1440px] items-center justify-between px-5 py-5 md:px-10",
        ),
        class_name="border-b border-[#e5e3da] bg-[#faf9f4]",
    )


def guide() -> rx.Component:
    return rx.el.details(
        rx.el.summary(
            rx.el.span(
                rx.icon("compass", class_name="h-4 w-4 text-[#215b56]"),
                "New to research papers? Start here.",
                class_name="flex items-center gap-2 text-sm font-medium text-[#202e3b]",
            ),
            rx.icon(
                "chevron-down",
                class_name="h-4 w-4 text-[#7c8580] transition-transform group-open:rotate-180",
            ),
            class_name="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-5 py-4 hover:bg-[#edf1eb] focus-visible:outline-2 focus-visible:outline-[#215b56]",
        ),
        rx.el.div(
            guide_step(
                "01",
                "Choose a paper",
                "Try a teaching sample, or upload a PDF or DOCX. Scanned PDFs "
                "are read with OCR automatically. If a document does not look "
                "like a research paper, Paperproof asks before opening it.",
            ),
            guide_step(
                "02",
                "Read a little at a time",
                "Start with the abstract. Methods explain how; limitations explain what to be careful about.",
            ),
            guide_step(
                "03",
                "Check the citations",
                "Run an audit to compare in-text citations with the reference list, review possible claim mismatches, and check Crossref metadata.",
            ),
            class_name="grid gap-5 border-t border-[#dde5dc] px-5 py-5 md:grid-cols-3",
        ),
        class_name="group mb-7 rounded-xl border border-[#dde5dc] bg-[#f0f3ed]",
    )


def guide_step(number: str, title: str, description: str) -> rx.Component:
    return rx.el.div(
        rx.el.span(
            number, class_name="pt-0.5 text-xs font-semibold text-[#bc7567]"
        ),
        rx.el.div(
            rx.el.h3(
                title, class_name="mb-1 text-sm font-semibold text-[#202e3b]"
            ),
            rx.el.p(
                description, class_name="text-xs leading-relaxed text-[#69736e]"
            ),
        ),
        class_name="flex gap-3",
    )


def paper_choice(paper: Paper) -> rx.Component:
    return rx.el.button(
        rx.el.div(
            rx.el.span(
                paper["topic"],
                class_name="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#708079]",
            ),
            rx.cond(
                WorkspaceState.selected_id == paper["id"],
                rx.icon(
                    "circle-check", class_name="h-4 w-4 shrink-0 text-[#215b56]"
                ),
                rx.icon(
                    "arrow-up-right",
                    class_name="h-4 w-4 shrink-0 text-[#9aaba4]",
                ),
            ),
            class_name="mb-1.5 flex items-center justify-between gap-2",
        ),
        rx.el.p(
            paper["title"],
            class_name="text-sm font-medium leading-relaxed text-[#273a42]",
        ),
        rx.el.p(
            rx.cond(
                paper["source"] == "sample",
                f"Teaching sample · {paper['page_count']} pages",
                "Uploaded · session only",
            ),
            class_name="mt-2 text-[11px] text-[#78847d]",
        ),
        on_click=WorkspaceState.select_paper(paper["id"]),
        disabled=WorkspaceState.uploading,
        aria_pressed=WorkspaceState.selected_id == paper["id"],
        class_name=rx.cond(
            WorkspaceState.selected_id == paper["id"],
            "w-full rounded-xl border border-[#48756a] bg-[#edf3ed] p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-[#215b56] disabled:opacity-60",
            "w-full rounded-xl border border-[#e6e7df] bg-[#fffefa] p-4 text-left transition-colors hover:border-[#95aca1] hover:bg-[#f5f7f1] focus-visible:outline-2 focus-visible:outline-[#215b56] disabled:opacity-60",
        ),
    )


def classification_note() -> rx.Component:
    """Non-blocking note for a paper that opened with structural warnings."""
    return rx.cond(
        WorkspaceState.selected_paper["research_classification"]["outcome"]
        == "accepted_with_warnings",
        rx.el.div(
            rx.el.div(
                rx.icon(
                    "triangle-alert",
                    class_name="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#bc7567]",
                ),
                rx.el.p(
                    WorkspaceState.selected_paper["research_classification"][
                        "message"
                    ],
                    class_name="text-[11px] leading-relaxed text-[#5f6c64]",
                ),
                class_name="flex gap-2.5",
            ),
            rx.el.p(
                "Paperproof could not recognise every usual section. Papers "
                "differ in layout, so this is a reading hint, not a "
                "judgement about the quality of the work.",
                class_name="mt-2 text-[10px] leading-relaxed text-[#87917f]",
            ),
            class_name="border-t border-[#ece8da] bg-[#fdf6f1] px-5 py-3 md:px-7",
        ),
    )


def pending_upload_panel() -> rx.Component:
    """Confirmation step for a document Paperproof would not open silently."""
    return rx.cond(
        (WorkspaceState.pending_upload != None)
        & (WorkspaceState.pending_classification != None),
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "Is this a research paper?",
                    class_name="text-sm font-semibold text-[#202e3b]",
                ),
                rx.el.p(
                    WorkspaceState.pending_upload["filename"],
                    class_name="mt-1 text-xs text-[#6f7c75]",
                ),
                class_name="mb-3",
            ),
            rx.el.p(
                WorkspaceState.pending_classification["message"],
                role="alert",
                class_name="text-xs leading-relaxed text-[#43524d]",
            ),
            rx.el.div(
                rx.el.p(
                    "WHAT PAPERPROOF FOUND",
                    class_name="mb-1 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                ),
                rx.el.ul(
                    rx.foreach(
                        WorkspaceState.pending_classification["signals"],
                        lambda signal: rx.el.li(
                            signal,
                            class_name="text-[11px] leading-relaxed text-[#69766e]",
                        ),
                    ),
                    class_name="flex flex-col gap-0.5",
                ),
                rx.el.p(
                    "NOT FOUND OR UNRECOGNISED",
                    class_name="mt-3 mb-1 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                ),
                rx.el.ul(
                    rx.foreach(
                        WorkspaceState.pending_classification[
                            "missing_signals"
                        ],
                        lambda signal: rx.el.li(
                            signal,
                            class_name="text-[11px] leading-relaxed text-[#8a8073]",
                        ),
                    ),
                    class_name="flex flex-col gap-0.5",
                ),
                class_name="mt-3 rounded-lg bg-[#fafbf5] p-3",
            ),
            rx.el.p(
                "Nothing has been added to your session yet. If you recognise "
                "this as a paper, open it. Paperproof never edits or "
                "rejects the file itself.",
                class_name="mt-3 text-[11px] leading-relaxed text-[#7c8579]",
            ),
            rx.el.div(
                rx.el.button(
                    rx.icon("book-open-check", class_name="h-3.5 w-3.5"),
                    "Yes, open this paper",
                    on_click=WorkspaceState.confirm_pending_upload,
                    disabled=WorkspaceState.uploading,
                    class_name="flex items-center gap-2 rounded-lg bg-[#215b56] px-4 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-[#174842] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#215b56] disabled:opacity-60",
                ),
                rx.el.button(
                    rx.icon("trash-2", class_name="h-3.5 w-3.5"),
                    "Discard it",
                    on_click=WorkspaceState.discard_pending_upload,
                    disabled=WorkspaceState.uploading,
                    class_name="flex items-center gap-2 rounded-lg border border-[#dce2d4] bg-[#fffefa] px-4 py-2.5 text-xs font-semibold text-[#5f7268] transition-colors hover:bg-[#f0f4ed] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#215b56] disabled:opacity-60",
                ),
                class_name="mt-4 flex flex-wrap gap-3",
            ),
            class_name="mt-4 rounded-xl border border-[#e3d6b4] bg-[#fbf6e8] p-4",
        ),
    )


def upload_panel() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.span("01", class_name="text-xs font-semibold text-[#bc7567]"),
            rx.el.h2(
                "Bring your paper",
                class_name="text-base font-semibold text-[#202e3b]",
            ),
            class_name="mb-4 flex items-center gap-2.5",
        ),
        rx.upload.root(
            rx.el.div(
                rx.el.span(
                    rx.icon("upload", class_name="h-5 w-5 text-[#215b56]"),
                    class_name="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-[#edf2eb]",
                ),
                rx.el.p(
                    "Drop a paper here",
                    class_name="text-sm font-semibold text-[#273a42]",
                ),
                rx.el.p(
                    "or click to choose a file",
                    class_name="mt-1 text-xs text-[#6f7c75]",
                ),
                rx.el.p(
                    "PDF or DOCX · up to 10 MB",
                    class_name="mt-3 text-[11px] text-[#8a9087]",
                ),
                class_name="flex flex-col items-center px-4 py-6 text-center",
            ),
            id="paper-upload",
            multiple=False,
            max_files=1,
            disabled=WorkspaceState.uploading,
            accept={
                "application/pdf": [".pdf"],
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
                    ".docx"
                ],
            },
            class_name="w-full cursor-pointer rounded-xl border border-dashed border-[#a9b7ac] bg-[#fffefa] transition-colors hover:border-[#215b56] hover:bg-[#f3f6ef]",
        ),
        rx.cond(
            rx.selected_files("paper-upload").length() > 0,
            rx.el.div(
                rx.foreach(
                    rx.selected_files("paper-upload"),
                    lambda name: rx.el.span(
                        name,
                        class_name="min-w-0 flex-1 truncate text-xs text-[#455b53]",
                    ),
                ),
                rx.el.button(
                    rx.icon("x", class_name="h-3.5 w-3.5"),
                    on_click=rx.clear_selected_files("paper-upload"),
                    disabled=WorkspaceState.uploading,
                    aria_label="Clear selected file",
                    class_name="rounded-md p-1 text-[#6c7b72] hover:bg-[#e8eee4] disabled:opacity-50",
                ),
                class_name="mt-3 flex items-center gap-2 rounded-lg bg-[#f0f4ed] px-3 py-2",
            ),
        ),
        rx.el.button(
            rx.cond(
                WorkspaceState.uploading,
                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                rx.icon("file-up", class_name="h-4 w-4"),
            ),
            rx.cond(
                WorkspaceState.uploading,
                "Extracting text…",
                "Upload & open paper",
            ),
            on_click=WorkspaceState.handle_upload(
                rx.upload_files(upload_id="paper-upload")
            ),
            disabled=WorkspaceState.uploading
            | (rx.selected_files("paper-upload").length() == 0),
            class_name="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-[#215b56] px-4 py-3 text-xs font-semibold text-white transition-colors hover:bg-[#174842] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#215b56] disabled:cursor-not-allowed disabled:bg-[#dfe6dd] disabled:text-[#7e8d80]",
        ),
        rx.cond(
            WorkspaceState.upload_error != "",
            rx.el.p(
                WorkspaceState.upload_error,
                role="alert",
                class_name="mt-3 rounded-lg bg-red-50 p-3 text-xs leading-relaxed text-red-700",
            ),
        ),
        rx.cond(
            WorkspaceState.upload_success != "",
            rx.el.p(
                WorkspaceState.upload_success,
                role="status",
                class_name="mt-3 rounded-lg bg-[#eef4ea] p-3 text-xs leading-relaxed text-[#215b56]",
            ),
        ),
        rx.cond(
            ~WorkspaceState.ocr_status["available"],
            rx.el.div(
                rx.el.p(
                    WorkspaceState.ocr_status["detail"],
                    class_name="text-[11px] leading-relaxed text-[#8a5f2b]",
                ),
                class_name="mt-3 rounded-lg border border-[#e8d9b8] bg-[#fdf6e7] p-3",
            ),
        ),
        rx.el.p(
            rx.icon("lock-keyhole", class_name="mt-0.5 h-3 w-3 shrink-0"),
            "Your file stays in this session only. Figures are extracted and "
            "read on this server: image pixels are never sent to an external "
            "model. Citation-audit bibliography entries are sent to Crossref; "
            "claim excerpts are not sent to OpenRouter by this audit. Asking a "
            "question sends relevant text excerpts to OpenRouter. Scanned PDFs "
            "and figures use English OCR when this machine provides it.",
            class_name="mt-3 flex gap-2 text-[11px] leading-relaxed text-[#7b847b]",
        ),
        pending_upload_panel(),
        class_name="rounded-2xl border border-[#e3e4da] bg-[#fffefa] p-5",
    )


def library_panel() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.h2(
                "Or explore a sample",
                class_name="text-sm font-semibold text-[#202e3b]",
            ),
            rx.el.span(
                "3 PAPERS",
                class_name="text-[10px] font-medium tracking-wider text-[#879083]",
            ),
            class_name="mb-3 flex items-center justify-between",
        ),
        rx.el.p(
            "Fictional papers made for learning. No specialist knowledge needed.",
            class_name="mb-4 text-xs leading-relaxed text-[#798076]",
        ),
        rx.el.div(
            rx.foreach(WorkspaceState.samples, paper_choice),
            class_name="flex flex-col gap-3",
        ),
        rx.cond(
            WorkspaceState.uploads.length() > 0,
            rx.el.div(
                rx.el.h2(
                    "Your session papers",
                    class_name="mb-3 text-sm font-semibold text-[#202e3b]",
                ),
                rx.el.div(
                    rx.foreach(WorkspaceState.uploads, paper_choice),
                    class_name="flex flex-col gap-3",
                ),
                class_name="mt-6",
            ),
        ),
        class_name="px-1 py-5",
    )


def passage_choice(passage: Passage) -> rx.Component:
    return rx.el.button(
        rx.el.span(passage["section"], class_name="truncate"),
        rx.cond(
            passage["page"] > 0,
            rx.el.span(
                f"p. {passage['page']}",
                class_name="shrink-0 text-[10px] opacity-65",
            ),
        ),
        on_click=WorkspaceState.select_passage(passage["id"]),
        aria_pressed=WorkspaceState.selected_passage_id == passage["id"],
        class_name=rx.cond(
            WorkspaceState.selected_passage_id == passage["id"],
            "flex w-full items-center justify-between gap-2 rounded-lg bg-[#e7eee6] px-3 py-2.5 text-left text-xs font-semibold text-[#215b56] focus-visible:outline-2 focus-visible:outline-[#215b56]",
            "flex w-full items-center justify-between gap-2 rounded-lg bg-transparent px-3 py-2.5 text-left text-xs text-[#748073] transition-colors hover:bg-[#f0f3eb] focus-visible:outline-2 focus-visible:outline-[#215b56]",
        ),
    )


def entry_number_badge(reference_id: str) -> rx.Component:
    """The `[n]` an answer cites, shown on the bibliography row itself.

    Answers cite entries by their position in this list, and an evidence card
    tells the reader it is "the same row shown in the References tab". Without
    the number on the row that instruction cannot be followed: the reader is
    left counting rows by hand, and on a 28-entry list that guess is easy to
    get wrong. The number comes from the entry's real position, so it cannot
    drift from the order on screen.
    """
    number = WorkspaceState.reference_numbers[reference_id]
    return rx.cond(
        number.to_string() != "",
        rx.el.span(
            "[" + number + "]",
            class_name="mt-0.5 w-fit shrink-0 rounded-md bg-[#eef1e6] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#5f7268]",
        ),
    )


def reference_row(reference: Reference) -> rx.Component:
    return rx.el.li(
        rx.icon("bookmark", class_name="mt-1 h-4 w-4 shrink-0 text-[#80917e]"),
        entry_number_badge(reference["id"]),
        rx.el.div(
            rx.el.p(
                reference["text"], class_name="text-sm leading-7 text-[#43524d]"
            ),
            rx.el.span(
                "As supplied · run audit to check",
                class_name="mt-2 block w-fit rounded-md bg-[#f1f1e8] px-2 py-1 text-[10px] text-[#7d8477]",
            ),
        ),
        class_name="flex gap-3 border-b border-[#eeeede] py-5 last:border-0",
    )


def image_src(paper_id, filename) -> str:
    """Stored URL for one figure.

    Both parts were generated and validated by the extractor when written to
    disk (see `media_dir`), so this only formats a path for the browser. The
    paper id is a uuid4 that is never published outside the session, which
    makes this a capability URL rather than an enumerable listing.
    """
    return f"{UPLOAD_URL_PREFIX}/{paper_id}/{filename}"


def figure_card(paper_id, image: PaperImage) -> rx.Component:
    source = image_src(paper_id, image["filename"])
    return rx.el.li(
        rx.el.img(
            src=source,
            alt=rx.cond(
                image["caption"] != "",
                image["caption"],
                f"Figure {image['order'] + 1} from this paper",
            ),
            loading="lazy",
            class_name="w-full rounded-lg border border-[#e4e7db] bg-white object-contain",
        ),
        rx.el.p(
            rx.cond(
                image["caption"] != "",
                image["caption"],
                "No caption was found near this figure.",
            ),
            class_name="mt-2 text-xs leading-relaxed text-[#43524d]",
        ),
        rx.el.div(
            rx.el.span(
                rx.icon("layers", class_name="h-3 w-3"),
                rx.cond(
                    image["page"] > 0,
                    f"Page {image['page']}",
                    "Page unavailable (DOCX)",
                ),
                class_name="flex items-center gap-1.5",
            ),
            rx.el.span(
                rx.icon("tag", class_name="h-3 w-3"),
                f"Type: {image['image_kind']}",
                class_name="flex items-center gap-1.5",
            ),
            rx.cond(
                image["section"] != "",
                rx.el.span(
                    rx.icon("heading", class_name="h-3 w-3"),
                    image["section"],
                    class_name="flex items-center gap-1.5",
                ),
            ),
            class_name="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-[#7a877b]",
        ),
        rx.cond(
            image["ocr_text"] != "",
            rx.el.div(
                rx.el.p(
                    "TEXT FOUND INSIDE THIS FIGURE",
                    class_name="mb-1 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                ),
                rx.el.p(
                    image["ocr_text"],
                    class_name="whitespace-pre-wrap text-[11px] leading-relaxed text-[#5f6c64]",
                ),
                class_name="mt-2 rounded-md bg-[#f4f7ee] p-2",
            ),
        ),
        rx.cond(
            image["surrounding_text"] != "",
            rx.el.p(
                rx.el.span(
                    "Nearby text: ",
                    class_name="font-semibold text-[#5f7268]",
                ),
                image["surrounding_text"],
                class_name="mt-2 text-[11px] leading-relaxed text-[#69766e]",
            ),
        ),
        class_name="rounded-xl border border-[#e6e4d8] bg-[#fffefa] p-4",
    )


def figures_panel() -> rx.Component:
    """Figures tab. Always renders, so an extraction failure stays visible."""
    return rx.el.div(
        rx.cond(
            WorkspaceState.selected_images.length() > 0,
            rx.el.div(
                rx.el.h3(
                    f"Figures & images · {WorkspaceState.selected_images.length()} item(s)",
                    class_name="font-['Lora'] text-xl text-[#263a3d]",
                ),
                rx.el.p(
                    "Figures are read locally from the document. Text inside a "
                    "figure is recovered with OCR, and the caption and nearby "
                    "paper text are shown for context. Paperproof does not "
                    "interpret what a figure looks like, so no claim is made "
                    "about a chart's shape or trend.",
                    class_name="mt-2 max-w-2xl text-xs leading-relaxed text-[#7d887c]",
                ),
                rx.el.ul(
                    rx.foreach(
                        WorkspaceState.selected_images,
                        lambda image: figure_card(
                            WorkspaceState.selected_paper["id"], image
                        ),
                    ),
                    class_name="mt-4 flex flex-col gap-3",
                ),
            ),
            rx.el.div(
                rx.icon("image-off", class_name="mb-3 h-6 w-6 text-[#9aa597]"),
                rx.el.h3(
                    "No figures in this paper",
                    class_name="font-['Lora'] text-lg text-[#263a3d]",
                ),
                rx.el.p(
                    rx.cond(
                        WorkspaceState.skipped_page_furniture > 0,
                        f"Paperproof skipped {WorkspaceState.skipped_page_furniture} repeating background or template image(s) that were drawn on most pages. Those are page artwork, not figures, so nothing is left to show here.",
                        "This paper has no embedded images Paperproof could read. Figures drawn as vector shapes, or a scanned paper whose pages are one large image, often cannot be separated this way.",
                    ),
                    class_name="mt-2 max-w-2xl text-xs leading-relaxed text-[#7d887c]",
                ),
                rx.el.p(
                    "The paper text, grounded answers, and the citation audit all work normally. Any figures remain visible in the source file.",
                    class_name="mt-2 max-w-2xl text-xs leading-relaxed text-[#9aa597]",
                ),
                class_name="py-2",
            ),
        ),
        # The tall minimum height exists so a short figure list does not make
        # the card jump when navigating tabs. With nothing to show it just
        # leaves an empty box, so the empty state is allowed to be compact.
        class_name=rx.cond(
            WorkspaceState.selected_images.length() > 0,
            "min-h-[330px] px-5 py-6 md:px-7",
            "px-5 py-6 md:px-7",
        ),
    )


def extraction_warning_row(item: ExtractionWarning) -> rx.Component:
    tones = {
        "error": "border-[#e6b4a8] bg-[#fdf1ed] text-[#9d6257]",
        "warning": "border-[#e3d6b4] bg-[#fbf6e8] text-[#8a7338]",
        "info": "border-[#dfe3d6] bg-[#f7f9f3] text-[#69766e]",
    }
    return rx.el.li(
        rx.el.p(
            item["message"],
            class_name="text-[11px] leading-relaxed text-[#5f6c64]",
        ),
        rx.el.p(
            rx.el.span(
                "Next step: ", class_name="font-semibold text-[#315e54]"
            ),
            item["recommended_action"],
            class_name="mt-1 text-[11px] leading-relaxed text-[#315e54]",
        ),
        class_name=rx.match(
            item["severity"],
            ("error", tones["error"]),
            ("warning", tones["warning"]),
            tones["info"],
        ),
    )


def extraction_warnings_panel() -> rx.Component:
    """Extraction warnings, kept visible under the reader."""
    return rx.cond(
        WorkspaceState.selected_extraction_warnings.length() > 0,
        rx.el.div(
            rx.el.p(
                "Extraction notes",
                class_name="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#889184]",
            ),
            rx.el.ul(
                rx.foreach(
                    WorkspaceState.selected_extraction_warnings,
                    extraction_warning_row,
                ),
                class_name="mt-2 flex flex-col gap-2",
            ),
            class_name="border-t border-[#ece8da] bg-[#fbf7ed] px-5 py-4 md:px-7",
        ),
    )


def paper_reader() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    rx.icon("file-text", class_name="h-3 w-3"),
                    rx.cond(
                        WorkspaceState.selected_paper["source"] == "sample",
                        "TEACHING SAMPLE",
                        "SESSION UPLOAD",
                    ),
                    class_name="flex w-fit items-center gap-1.5 rounded-md bg-[#eaf0e6] px-2.5 py-1.5 text-[10px] font-semibold tracking-wider text-[#55755d]",
                ),
                rx.cond(
                    WorkspaceState.selected_paper["source"] == "upload",
                    rx.el.button(
                        rx.icon("trash-2", class_name="h-3.5 w-3.5"),
                        "Remove",
                        on_click=WorkspaceState.remove_upload,
                        disabled=WorkspaceState.uploading
                        | WorkspaceState.audit_running,
                        class_name="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-[#a8675a] hover:bg-[#fbefea] disabled:opacity-50",
                    ),
                ),
                class_name="mb-4 flex items-center justify-between",
            ),
            rx.el.h2(
                WorkspaceState.selected_paper["title"],
                class_name="max-w-[650px] font-['Lora'] text-2xl font-medium leading-snug tracking-tight text-[#24333b] md:text-[29px]",
            ),
            rx.el.p(
                WorkspaceState.selected_paper["authors"],
                rx.cond(
                    WorkspaceState.selected_paper["year"] != "",
                    f" · {WorkspaceState.selected_paper['year']}",
                    "",
                ),
                class_name="mt-3 text-xs text-[#7d857b]",
            ),
            rx.el.div(
                rx.el.span(
                    rx.icon("layers", class_name="h-3.5 w-3.5"),
                    rx.cond(
                        WorkspaceState.selected_paper["page_count"] > 0,
                        f"{WorkspaceState.selected_paper['page_count']} pages",
                        "Pages unavailable",
                    ),
                    class_name="flex items-center gap-1.5",
                ),
                rx.el.span(
                    rx.icon("align-left", class_name="h-3.5 w-3.5"),
                    f"{WorkspaceState.selected_paper['word_count']:,} words",
                    class_name="flex items-center gap-1.5",
                ),
                rx.el.span(
                    "Text ready to explore", class_name="text-[#65836b]"
                ),
                class_name="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-[#7a877b]",
            ),
            class_name="px-5 pt-6 pb-5 md:px-7",
        ),
        rx.el.div(
            rx.el.button(
                rx.icon("book-open", class_name="h-3.5 w-3.5"),
                rx.el.span(
                    "Paper text",
                    rx.el.span(
                        f" · {WorkspaceState.selected_section_count} sections",
                        class_name="font-normal opacity-70",
                    ),
                ),
                on_click=WorkspaceState.show_body,
                aria_pressed=WorkspaceState.reader_tab == "body",
                class_name=rx.cond(
                    WorkspaceState.reader_tab == "body",
                    "flex items-center gap-2 border-b-2 border-[#215b56] bg-transparent px-1 py-3 text-xs font-semibold text-[#215b56]",
                    "flex items-center gap-2 border-b-2 border-transparent bg-transparent px-1 py-3 text-xs text-[#7e887e] hover:text-[#215b56]",
                ),
            ),
            rx.el.button(
                rx.icon("quote", class_name="h-3.5 w-3.5"),
                rx.el.span(
                    "References",
                    rx.el.span(
                        f" · {WorkspaceState.selected_paper['references'].length()} entries",
                        class_name="font-normal opacity-70",
                    ),
                ),
                on_click=WorkspaceState.show_references,
                aria_pressed=WorkspaceState.reader_tab == "references",
                class_name=rx.cond(
                    WorkspaceState.reader_tab == "references",
                    "flex items-center gap-2 border-b-2 border-[#215b56] bg-transparent px-1 py-3 text-xs font-semibold text-[#215b56]",
                    "flex items-center gap-2 border-b-2 border-transparent bg-transparent px-1 py-3 text-xs text-[#7e887e] hover:text-[#215b56]",
                ),
            ),
            rx.el.button(
                rx.icon("image", class_name="h-3.5 w-3.5"),
                rx.el.span(
                    "Figures & images",
                    rx.el.span(
                        f" · {WorkspaceState.selected_images.length()} items",
                        class_name="font-normal opacity-70",
                    ),
                ),
                on_click=WorkspaceState.show_figures,
                aria_pressed=WorkspaceState.reader_tab == "figures",
                class_name=rx.cond(
                    WorkspaceState.reader_tab == "figures",
                    "flex items-center gap-2 border-b-2 border-[#215b56] bg-transparent px-1 py-3 text-xs font-semibold text-[#215b56]",
                    "flex items-center gap-2 border-b-2 border-transparent bg-transparent px-1 py-3 text-xs text-[#7e887e] hover:text-[#215b56]",
                ),
            ),
            class_name="flex flex-wrap gap-x-7 gap-y-1 border-y border-[#e9ebdf] px-5 md:px-7",
        ),
        rx.cond(
            WorkspaceState.reader_tab == "figures",
            figures_panel(),
            rx.cond(
                WorkspaceState.reader_tab == "body",
            rx.el.div(
                rx.el.nav(
                    rx.el.p(
                        "IN THIS PAPER",
                        class_name="mb-3 px-3 text-[9px] font-semibold tracking-[0.15em] text-[#8b9585]",
                    ),
                    rx.foreach(
                        WorkspaceState.selected_paper["passages"],
                        passage_choice,
                    ),
                    aria_label="Paper passages",
                    role="region",
                    tab_index=0,
                    class_name="flex max-h-80 w-full shrink-0 flex-col gap-1 overflow-y-auto border-b border-[#eceede] bg-[#fafbf5] p-3 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#215b56] md:max-h-[430px] md:w-44 md:border-r md:border-b-0 md:py-5",
                ),
                rx.el.article(
                    rx.el.div(
                        rx.el.h3(
                            WorkspaceState.selected_passage["section"],
                            class_name="font-['Lora'] text-xl text-[#263a3d]",
                        ),
                        rx.el.span(
                            rx.cond(
                                WorkspaceState.selected_passage["page"] > 0,
                                f"PAGE {WorkspaceState.selected_passage['page']}",
                                "DOCX SECTION",
                            ),
                            class_name="shrink-0 text-[9px] font-medium tracking-wider text-[#8c988b]",
                        ),
                        class_name="mb-5 flex flex-wrap items-center justify-between gap-2",
                    ),
                    rx.el.p(
                        WorkspaceState.selected_passage["text"],
                        class_name="whitespace-pre-wrap break-words font-['Lora'] text-[14px] leading-[1.95] text-[#4a5752]",
                    ),
                    class_name="min-w-0 flex-1 px-5 py-6 md:px-7",
                ),
                class_name="flex min-h-[330px] flex-col md:flex-row",
            ),
            rx.el.div(
                rx.cond(
                    (WorkspaceState.selected_paper["references"].length() > 0)
                    | (
                        WorkspaceState.selected_audit["references"].length() > 0
                    ),
                    rx.el.div(
                        rx.el.h3(
                            rx.cond(
                                WorkspaceState.selected_audit["references"].length()
                                > 0,
                                "Parsed references & Crossref status",
                                "References as supplied",
                            ),
                            class_name="font-['Lora'] text-xl text-[#263a3d]",
                        ),
                        rx.el.p(
                            rx.cond(
                                WorkspaceState.selected_audit["references"].length()
                                > 0,
                                "Parsed entries and verification results from the latest citation audit. Crossref results are not proof that a source does or does not exist.",
                                "Reference entries as supplied. Run the citation audit below to compare in-text citations and check available Crossref metadata.",
                            ),
                            class_name="mt-2 text-xs leading-relaxed text-[#7d887c]",
                        ),
                        rx.el.div(
                            rx.cond(
                                WorkspaceState.selected_audit["references"].length()
                                > 0,
                                rx.el.ul(
                                    rx.foreach(
                                        WorkspaceState.selected_audit["references"],
                                        verification_row,
                                    ),
                                    class_name="divide-y divide-[#e8e7dc]",
                                ),
                                rx.el.ul(
                                    rx.foreach(
                                        WorkspaceState.selected_paper["references"],
                                        reference_row,
                                    ),
                                ),
                            ),
                            # A paper can carry hundreds of entries. Scoping the
                            # scroll to this list keeps the tabs and the reader
                            # reachable instead of pushing them off-screen.
                            # `tab_index` and `role` are what make the scroll
                            # reachable: an overflow container is not in the tab
                            # order on its own, so without them the list is
                            # mouse-only.
                            role="region",
                            tab_index=0,
                            aria_label=rx.cond(
                                WorkspaceState.selected_audit["references"].length()
                                > 0,
                                "Parsed references and verification status",
                                "References as supplied",
                            ),
                            class_name="mt-2 max-h-[420px] overflow-y-auto "
                            "overscroll-contain rounded-xl border border-[#eeede0] "
                            "bg-[#fffefa] pr-1 focus-visible:outline-2 "
                            "focus-visible:outline-offset-2 "
                            "focus-visible:outline-[#215b56] md:max-h-[520px]",
                        ),
                    ),
                    rx.el.div(
                        rx.icon(
                            "list", class_name="mb-4 h-7 w-7 text-[#79917b]"
                        ),
                        rx.el.h3(
                            "No reference entries extracted",
                            class_name="font-['Lora'] text-xl text-[#263a3d]",
                        ),
                        rx.el.p(
                            "Reference entries are separated when you upload a paper. None could be extracted confidently here. Check the bibliography heading and entry layout in the original file, or try a clearer searchable copy. The audit can explain extraction gaps but cannot invent missing references.",
                            class_name="mt-3 max-w-lg text-sm leading-relaxed text-[#7d887c]",
                        ),
                        class_name="py-8",
                    ),
                ),
                class_name="min-h-[330px] px-5 py-6 md:px-7",
            ),
        ),
        ),
        extraction_warnings_panel(),
        classification_note(),
        rx.el.div(
            rx.icon(
                "info", class_name="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#b98170]"
            ),
            rx.el.p(
                WorkspaceState.selected_paper["note"],
                class_name="text-[11px] leading-relaxed text-[#8a8073]",
            ),
            class_name="flex gap-2.5 border-t border-[#ece8da] bg-[#fbf7ed] px-5 py-3 md:px-7",
        ),
        class_name="overflow-hidden rounded-2xl border border-[#e0e3d7] bg-[#fffefa]",
    )


def audit_issue(issue: AuditIssue) -> rx.Component:
    return rx.el.article(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    issue["category"],
                    class_name="w-fit rounded-full bg-[#f7e9e3] px-2.5 py-1 text-[10px] font-semibold text-[#9d6257]",
                ),
                severity_badge(issue["severity"]),
                class_name="flex flex-wrap items-center gap-2",
            ),
            rx.el.span(
                issue["location"],
                class_name="text-[10px] font-medium text-[#7d887c]",
            ),
            class_name="flex flex-wrap items-center justify-between gap-2",
        ),
        rx.el.blockquote(
            issue["excerpt"],
            class_name="mt-3 border-l-2 border-[#d6a18f] pl-3 font-['Lora'] text-sm leading-relaxed text-[#43524d]",
        ),
        rx.el.p(
            issue["explanation"],
            class_name="mt-3 text-xs leading-relaxed text-[#5f6c64]",
        ),
        rx.el.p(
            rx.icon(
                "arrow-right",
                class_name="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#215b56]",
            ),
            issue["action"],
            class_name="mt-2 flex gap-2 text-xs font-medium leading-relaxed text-[#315e54]",
        ),
        class_name="rounded-xl border border-[#e6e4d8] bg-[#fffefa] p-4",
    )


VERIFICATION_LABEL = {
    "confirmed": "Metadata match",
    "partial_match": "Partial match · review",
    "ambiguous": "Manual review",
    "not_found_in_crossref": "No Crossref match",
    "not_enough_metadata": "Not enough metadata",
    "lookup_error": "Lookup unavailable",
    "not_checked_limit": "Not checked · audit limit",
    "pending": "Pending check",
}


def verification_row(reference: ReferenceAudit) -> rx.Component:
    return rx.el.li(
        rx.el.div(
            rx.el.div(
                entry_number_badge(reference["id"]),
                rx.el.span(
                    rx.match(
                        reference["status"],
                        ("confirmed", VERIFICATION_LABEL["confirmed"]),
                        ("partial_match", VERIFICATION_LABEL["partial_match"]),
                        ("ambiguous", VERIFICATION_LABEL["ambiguous"]),
                        (
                            "not_found_in_crossref",
                            VERIFICATION_LABEL["not_found_in_crossref"],
                        ),
                        (
                            "not_enough_metadata",
                            VERIFICATION_LABEL["not_enough_metadata"],
                        ),
                        ("lookup_error", VERIFICATION_LABEL["lookup_error"]),
                        (
                            "not_checked_limit",
                            VERIFICATION_LABEL["not_checked_limit"],
                        ),
                        VERIFICATION_LABEL["pending"],
                    ),
                    class_name=rx.cond(
                        reference["status"] == "confirmed",
                        "w-fit rounded-md bg-green-100 px-2 py-1 text-[10px] font-semibold text-green-700",
                        rx.cond(
                            reference["status"] == "ambiguous",
                            "w-fit rounded-md bg-yellow-100 px-2 py-1 text-[10px] font-semibold text-yellow-700",
                            rx.cond(
                                reference["status"] == "not_found_in_crossref",
                                "w-fit rounded-md bg-[#f7e9e3] px-2 py-1 text-[10px] font-semibold text-[#9d6257]",
                                "w-fit rounded-md bg-gray-100 px-2 py-1 text-[10px] font-semibold text-gray-600",
                            ),
                        ),
                    ),
                ),
                rx.el.span(
                    reference["location"],
                    class_name="text-[10px] font-medium text-[#7d887c]",
                ),
                class_name="flex flex-wrap items-center justify-between gap-2",
            ),
            rx.el.p(
                reference["text"],
                class_name="mt-2 text-xs leading-relaxed text-[#43524d]",
            ),
            rx.el.p(
                reference["message"],
                class_name="mt-2 text-[11px] leading-relaxed text-[#69766e]",
            ),
            rx.cond(
                reference["lookup_method"] != "",
                rx.el.p(
                    f"Lookup method: {reference['lookup_method']} · checked {reference['checked_at']}",
                    class_name="mt-1 text-[10px] text-[#87917f]",
                ),
            ),
            rx.cond(
                reference["conflicting_fields"].length() > 0,
                rx.el.div(
                    rx.el.span(
                        "Fields in conflict",
                        class_name="mr-1.5 text-[10px] text-[#9d6257]",
                    ),
                    rx.el.span(
                        rx.foreach(
                            reference["conflicting_fields"],
                            lambda field: rx.el.span(
                                field,
                                class_name="mr-1 rounded bg-[#f7e9e3] px-1.5 py-0.5 text-[10px] font-medium text-[#9d6257]",
                            ),
                        ),
                    ),
                    class_name="mt-1 flex flex-wrap items-center",
                ),
            ),
            rx.cond(
                reference["uncertainty"] != "",
                rx.el.p(
                    reference["uncertainty"],
                    class_name="mt-1 text-[10px] italic leading-relaxed text-[#87917f]",
                ),
            ),
            rx.cond(
                reference["url"] != "",
                rx.el.a(
                    rx.icon("external-link", class_name="h-3 w-3"),
                    "Open DOI record",
                    href=reference["url"],
                    target="_blank",
                    rel="noreferrer",
                    class_name="mt-2 flex w-fit items-center gap-1.5 text-[11px] font-semibold text-[#215b56] underline-offset-2 hover:underline",
                ),
            ),
            class_name="py-3 first:pt-0 last:pb-0",
        ),
        class_name="border-b border-[#e8e7dc] last:border-0",
    )


SEVERITY_STYLE = {
    "high": "border-l-[#b9563f] bg-[#fdf1ed] text-[#8f4632]",
    "medium": "border-l-[#c9a227] bg-[#fbf6e8] text-[#7d6a1f]",
    "low": "border-l-[#9aab9f] bg-[#f7f9f4] text-[#5f7268]",
}
SEVERITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}


def severity_badge(severity: str) -> rx.Component:
    return rx.el.span(
        SEVERITY_LABEL.get(severity, severity),
        class_name=(
            "ml-2 w-fit rounded-md border-l-2 px-2 py-0.5 text-[10px] "
            "font-semibold " + SEVERITY_STYLE.get(severity, SEVERITY_STYLE["low"])
        ),
    )


def summary_cards() -> rx.Component:
    counts = WorkspaceState.selected_audit["counts"]
    cards = [
        ("Citations found", "citations_found"),
        ("References parsed", "references_parsed"),
        ("Externally checked", "references_checked"),
        ("Confirmed matches", "confirmed"),
        ("Needing review", "needing_review"),
        ("Extraction warnings", "extraction_warnings"),
    ]
    return rx.el.div(
        rx.foreach(
            cards,
            lambda card: rx.el.div(
                rx.el.p(
                    card[1],
                    class_name="text-[9px] font-semibold uppercase tracking-[0.1em] text-[#87917f]",
                ),
                rx.el.p(
                    counts[card[1]].to_string(),
                    class_name="mt-1 font-['Lora'] text-2xl text-[#263a3d]",
                ),
                class_name="rounded-lg border border-[#e6e4d8] bg-[#fffefa] p-3",
            ),
        ),
        class_name="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3",
    )


def audit_explanation() -> rx.Component:
    return rx.cond(
        WorkspaceState.selected_audit["explanation"].length() > 0,
        rx.el.div(
            rx.el.h3(
                "What this audit did",
                class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
            ),
            rx.el.div(
                rx.foreach(
                    WorkspaceState.selected_audit["explanation"],
                    lambda note: rx.el.div(
                        rx.el.p(
                            note["heading"],
                            class_name="text-[11px] font-semibold text-[#5f7268]",
                        ),
                        rx.el.p(
                            note["body"],
                            class_name="mt-1 text-[11px] leading-relaxed text-[#69766e]",
                        ),
                        class_name="border-l-2 border-[#e0e5d8] py-1.5 pl-3",
                    ),
                ),
                class_name="mt-3 flex flex-col gap-1",
            ),
            class_name="mt-4 rounded-xl border border-[#e6e4d8] bg-[#fffefa] p-4",
        ),
    )


def citation_audit_panel() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "03", class_name="text-xs font-semibold text-[#bc7567]"
                ),
                rx.el.h2(
                    "Citation & reference audit",
                    class_name="text-base font-semibold text-[#202e3b]",
                ),
                class_name="flex items-center gap-2.5",
            ),
            rx.el.span(
                "ON-DEMAND CHECK",
                class_name="text-[9px] font-semibold tracking-wider text-[#8a9585]",
            ),
            class_name="flex flex-wrap items-center justify-between gap-3",
        ),
        rx.el.p(
            "Compare author–year citations with the bibliography, flag possible duplicates and formatting gaps, and review citation placement against nearby claims.",
            class_name="mt-2 text-xs leading-relaxed text-[#788275]",
        ),
        rx.el.div(
            rx.icon(
                "info", class_name="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#bc7567]"
            ),
            rx.el.p(
                "To verify references, their bibliography text is sent to Crossref's public API. Crossref gaps do not mean a work is nonexistent. This audit does not send claim excerpts to OpenRouter; only bounded relevant excerpts would be sent if a separate claim-analysis feature uses it.",
                class_name="text-[11px] leading-relaxed text-[#7b756a]",
            ),
            class_name="mt-3 flex gap-2 rounded-lg border border-[#ece3d3] bg-[#fbf7ed] p-3",
        ),
        rx.el.button(
            rx.cond(
                WorkspaceState.is_auditing_selected,
                rx.icon("loader-circle", class_name="h-4 w-4 animate-spin"),
                rx.icon("scan-search", class_name="h-4 w-4"),
            ),
            rx.cond(
                WorkspaceState.is_auditing_selected,
                "Auditing citations…",
                rx.cond(
                    WorkspaceState.audit_running,
                    "Another audit is finishing…",
                    rx.cond(
                        WorkspaceState.selected_audit["status"] == "not_run",
                        "Run citation audit",
                        "Re-run citation audit",
                    ),
                ),
            ),
            on_click=WorkspaceState.run_citation_audit,
            disabled=WorkspaceState.audit_running,
            class_name="mt-4 flex items-center justify-center gap-2 rounded-lg bg-[#215b56] px-4 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-[#174842] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#215b56] disabled:cursor-wait disabled:opacity-60",
        ),
        rx.cond(
            WorkspaceState.selected_audit["status"] == "not_run",
            rx.el.div(
                rx.icon("list-checks", class_name="h-5 w-5 text-[#79917b]"),
                rx.el.p(
                    "The audit has not run for this paper yet. Results are kept with this paper for the current session.",
                    class_name="text-xs leading-relaxed text-[#788275]",
                ),
                class_name="mt-4 flex items-start gap-2 rounded-xl border border-dashed border-[#dfe3d6] bg-[#fffefa]/70 p-4",
            ),
            rx.el.div(
                rx.el.div(
                    rx.icon(
                        rx.cond(
                            WorkspaceState.selected_audit["status"] == "error",
                            "triangle-alert",
                            "clipboard-check",
                        ),
                        class_name="mt-0.5 h-4 w-4 text-[#215b56]",
                    ),
                    rx.el.p(
                        WorkspaceState.selected_audit["summary"],
                        class_name="text-xs leading-relaxed text-[#46564f]",
                    ),
                    class_name="flex items-start gap-2 rounded-xl border border-[#dfe5d7] bg-[#fffefa] p-4",
                ),
                rx.cond(
                    WorkspaceState.selected_audit["error"] != "",
                    rx.el.p(
                        WorkspaceState.selected_audit["error"],
                        role="alert",
                        class_name="mt-3 rounded-lg bg-red-50 p-3 text-xs leading-relaxed text-red-700",
                    ),
                ),
                summary_cards(),
                rx.cond(
                    WorkspaceState.selected_audit["limits"].length() > 0,
                    rx.el.div(
                        rx.el.p(
                            "Limits on this audit",
                            class_name="mb-1 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                        ),
                        rx.el.ul(
                            rx.foreach(
                                WorkspaceState.selected_audit["limits"],
                                lambda limit: rx.el.li(
                                    limit,
                                    class_name="text-[11px] leading-relaxed text-[#8a8073]",
                                ),
                            ),
                            class_name="flex flex-col gap-1",
                        ),
                        class_name="mt-4 rounded-lg border border-[#e3d6b4] bg-[#fbf6e8] p-3",
                    ),
                ),
                audit_explanation(),
                rx.cond(
                    WorkspaceState.selected_audit["issues"].length() > 0,
                    rx.el.div(
                        rx.el.h3(
                            "Findings & next steps",
                            class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
                        ),
                        rx.el.div(
                            rx.foreach(
                                WorkspaceState.selected_audit["issues"],
                                audit_issue,
                            ),
                            class_name="mt-3 flex flex-col gap-3",
                        ),
                        class_name="mt-5",
                    ),
                    rx.el.div(
                        rx.icon(
                            "circle-check", class_name="h-4 w-4 text-[#4f7b61]"
                        ),
                        rx.el.p(
                            "No citation-structure issues were detected by the available checks. This is not a guarantee that every claim is supported.",
                            class_name="text-xs leading-relaxed text-[#597362]",
                        ),
                        class_name="mt-4 flex items-start gap-2 rounded-lg bg-[#eef4ea] p-3",
                    ),
                ),
                rx.cond(
                    WorkspaceState.selected_audit["references"].length() > 0,
                    rx.el.p(
                        "Reference-by-reference results are in the reader's References tab.",
                        class_name="mt-5 text-[11px] leading-relaxed text-[#788275]",
                    ),
                ),
                rx.cond(
                    WorkspaceState.selected_audit["fix_prompt"] != "",
                    rx.el.div(
                        rx.el.div(
                            rx.el.h3(
                                "Correction prompt for an external model",
                                class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
                            ),
                            rx.el.button(
                                rx.icon("copy", class_name="h-3.5 w-3.5"),
                                "Copy prompt",
                                on_click=rx.set_clipboard(
                                    WorkspaceState.selected_audit["fix_prompt"]
                                ),
                                class_name="flex items-center gap-1.5 rounded-lg border border-[#dce4d7] bg-[#fffefa] px-3 py-2 text-[11px] font-semibold text-[#315e54] hover:bg-[#edf3e8] focus-visible:outline-2 focus-visible:outline-[#215b56]",
                            ),
                            class_name="flex flex-wrap items-center justify-between gap-3",
                        ),
                        rx.el.textarea(
                            default_value=WorkspaceState.selected_audit[
                                "fix_prompt"
                            ],
                            key=f"audit-prompt:{WorkspaceState.selected_id}:{WorkspaceState.selected_audit['status']}",
                            read_only=True,
                            rows=7,
                            aria_label="Generated citation correction prompt",
                            class_name="mt-3 w-full resize-y rounded-xl border border-[#dce2d4] bg-[#fafbf5] px-3 py-3 text-xs leading-relaxed text-[#46564f] focus:outline-hidden",
                        ),
                        rx.el.p(
                            "Verify every suggested change against the actual source; the prompt explicitly discourages invented replacements.",
                            class_name="mt-2 text-[10px] leading-relaxed text-[#87917f]",
                        ),
                        class_name="mt-5 border-t border-[#e6e9df] pt-4",
                    ),
                ),
            ),
        ),
        class_name="mt-5 rounded-2xl border border-[#dfe5d7] bg-[#f4f7ee] p-5 md:p-6",
    )


def starter(text: str) -> rx.Component:
    return rx.el.button(
        text,
        type="button",
        on_click=WorkspaceState.use_question(text),
        class_name="rounded-full border border-[#dce4d7] bg-[#fffefa] px-3 py-2 text-[11px] text-[#597362] transition-colors hover:border-[#769384] hover:bg-[#edf3e8] focus-visible:outline-2 focus-visible:outline-[#215b56]",
    )


def evidence_card(evidence: AnswerEvidence) -> rx.Component:
    location = rx.cond(
        evidence["page"] > 0,
        f"{evidence['section']} · page {evidence['page']}",
        f"{evidence['section']} · page unavailable",
    )
    body = rx.el.div(
        rx.el.p(
            evidence["text"],
            class_name="whitespace-pre-wrap break-words text-xs leading-relaxed text-[#46564f]",
        ),
        rx.el.p(
            location,
            class_name="mt-2 text-[10px] font-semibold tracking-wide text-[#718078]",
        ),
    )
    return rx.cond(
        evidence["passage_id"] != "",
        rx.el.button(
            rx.el.div(
                rx.icon(
                    rx.match(
                        evidence["kind"],
                        ("image", "image"),
                        ("reference", "quote"),
                        "quote",
                    ),
                    class_name="mt-0.5 h-4 w-4 shrink-0 text-[#bc7567]",
                ),
                body,
                class_name="flex gap-3 text-left",
            ),
            on_click=WorkspaceState.select_passage(evidence["passage_id"]),
            aria_label="Open this evidence in the paper reader",
            class_name="w-full rounded-xl border border-[#e2e7dc] bg-[#fffefa] p-4 text-left transition-colors hover:border-[#9eafa0] hover:bg-[#f8faf5] focus-visible:outline-2 focus-visible:outline-[#215b56]",
        ),
        rx.el.div(
            rx.el.p(
                evidence["detail"],
                class_name="mb-2 w-fit rounded-md bg-[#f1f1e8] px-2 py-1 text-[10px] text-[#7d8477]",
            ),
            body,
            class_name="w-full rounded-xl border border-[#e2e7dc] bg-[#fafbf5] p-4",
        ),
    )


def evidence_section() -> rx.Component:
    """Expandable evidence list shown under the composed answer."""
    return rx.cond(
        WorkspaceState.answer_evidence.length() > 0,
        rx.el.details(
            rx.el.summary(
                rx.el.div(
                    rx.icon(
                        "chevron-down",
                        class_name="h-3.5 w-3.5 text-[#7e887e] transition-transform group-open:rotate-180",
                    ),
                    rx.el.span(
                        "Show the supporting evidence",
                        class_name="text-xs font-semibold text-[#315e54]",
                    ),
                    rx.el.span(
                        f"({WorkspaceState.answer_evidence.length()} item(s))",
                        class_name="text-[11px] font-normal text-[#87917f]",
                    ),
                    class_name="flex cursor-pointer list-none items-center gap-2",
                ),
            ),
            rx.el.div(
                rx.foreach(WorkspaceState.answer_evidence, evidence_card),
                class_name="mt-3 flex flex-col gap-2",
            ),
            rx.el.p(
                "These are the exact excerpts the answer was checked against. "
                "Passage evidence opens in the reader; reference and figure "
                "evidence is shown as supplied.",
                class_name="mt-2 text-[10px] leading-relaxed text-[#87917f]",
            ),
            class_name="group mt-5 border-t border-[#e6e9df] pt-4",
        ),
        rx.el.p(
            "The available paper text does not establish this. No supporting evidence is shown.",
            class_name="mt-3 text-xs leading-relaxed text-[#7c8579]",
        ),
    )


def setting_control(
    label: str,
    hint: str,
    value: rx.Var,
    setter: rx.EventHandler,
    min_value: float,
    max_value: float,
    step: float,
) -> rx.Component:
    """A compact labelled numeric control for one answer-sampling parameter."""
    return rx.el.label(
        rx.el.span(
            label,
            class_name="text-[10px] font-semibold tracking-wide text-[#5f7268]",
        ),
        rx.el.input(
            type="number",
            value=value,
            on_change=setter,
            min=min_value,
            max=max_value,
            step=step,
            aria_label=f"{label} setting",
            class_name="mt-1 w-full rounded-lg border border-[#d9e0d3] bg-[#fffefa] px-2.5 py-1.5 text-xs tabular-nums text-[#273b3d] focus:border-[#467c69] focus:outline-hidden focus:ring-1 focus:ring-[#215b56]/10",
        ),
        rx.el.span(
            hint,
            class_name="mt-1 text-[9px] leading-snug text-[#89948a]",
        ),
        class_name="flex w-full min-w-[128px] max-w-[165px] flex-col",
    )


def answer_settings() -> rx.Component:
    """Sampling hyperparameters for the grounded answer, laid out horizontally."""
    return rx.el.div(
        rx.el.div(
            rx.icon(
                "sliders-horizontal",
                class_name="h-3.5 w-3.5 shrink-0 text-[#215b56]",
            ),
            rx.el.span(
                "Answer settings",
                class_name="text-xs font-semibold text-[#31453c]",
            ),
            rx.el.span(
                "applied to the next question you ask",
                class_name="text-[10px] text-[#84907f]",
            ),
            class_name="flex flex-wrap items-center gap-2",
        ),
        rx.el.div(
            setting_control(
                "Temperature",
                "Lower = more focused, literal",
                WorkspaceState.temperature,
                WorkspaceState.update_temperature,
                0,
                2,
                0.1,
            ),
            setting_control(
                "Top-p",
                "Nucleus sampling cut-off",
                WorkspaceState.top_p,
                WorkspaceState.update_top_p,
                0,
                1,
                0.05,
            ),
            setting_control(
                "Top-k",
                "0 = model default (off)",
                WorkspaceState.top_k,
                WorkspaceState.update_top_k,
                0,
                100,
                1,
            ),
            setting_control(
                "Frequency penalty",
                "Penalise repeated text",
                WorkspaceState.frequency_penalty,
                WorkspaceState.update_frequency_penalty,
                -2,
                2,
                0.1,
            ),
            setting_control(
                "Presence penalty",
                "Encourage new topics",
                WorkspaceState.presence_penalty,
                WorkspaceState.update_presence_penalty,
                -2,
                2,
                0.1,
            ),
            class_name="mt-3 flex flex-wrap items-end gap-4",
        ),
        class_name="mt-5 border-t border-[#e4e8dc] pt-4",
    )


def answer_meta() -> rx.Component:
    """Confidence, limitations, and a source summary shown with an answer."""
    return rx.cond(
        WorkspaceState.answer_confidence != "",
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "CONFIDENCE",
                    class_name="text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                ),
                rx.el.span(
                    WorkspaceState.answer_confidence,
                    class_name=rx.cond(
                        WorkspaceState.answer_confidence == "high",
                        "w-fit rounded-md bg-[#e6f0e4] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#3f6b4c]",
                        rx.cond(
                            WorkspaceState.answer_confidence == "medium",
                            "w-fit rounded-md bg-[#f7e9e3] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#9d6257]",
                            "w-fit rounded-md bg-[#f1f1e8] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#7d8477]",
                        ),
                    ),
                ),
                rx.el.span(
                    f"From {WorkspaceState.answer_evidence.length()} supporting passage(s) in this paper",
                    class_name="text-[11px] text-[#7c8579]",
                ),
                class_name="flex flex-wrap items-center gap-3",
            ),
            rx.el.ul(
                rx.foreach(
                    WorkspaceState.answer_limitations,
                    lambda limitation: rx.el.li(
                        rx.el.span(
                            rx.icon(
                                "triangle-alert",
                                class_name="mt-0.5 h-3 w-3 shrink-0 text-[#bc7567]",
                            ),
                            limitation,
                            class_name="flex gap-2 text-[11px] leading-relaxed text-[#69766e]",
                        ),
                    ),
                ),
                class_name="mt-2.5 flex flex-col gap-1.5",
            ),
            rx.el.ul(
                rx.foreach(
                    WorkspaceState.answer_unsupported_parts,
                    lambda part: rx.el.li(
                        rx.el.span(
                            rx.icon(
                                "circle-alert",
                                class_name="mt-0.5 h-3 w-3 shrink-0 text-[#b98170]",
                            ),
                            f"Could not be grounded: {part}",
                            class_name="flex gap-2 text-[11px] leading-relaxed text-[#8a8073]",
                        ),
                    ),
                ),
                class_name="mt-2 flex flex-col gap-1.5",
            ),
            class_name="mt-4 rounded-lg border border-[#e6e9df] bg-[#fbfcf8] p-3",
        ),
    )


def source_row(source: SearchSource) -> rx.Component:
    return rx.el.li(
        rx.el.div(
            rx.el.a(
                source["title"],
                href=source["url"],
                target="_blank",
                rel="noreferrer",
                class_name="text-xs font-semibold text-[#315e54] underline-offset-2 hover:underline",
            ),
            rx.el.p(
                f"{source['publisher']} · retrieved {source['retrieved_at']}",
                class_name="mt-0.5 text-[10px] text-[#87917f]",
            ),
            rx.el.p(
                f"Why included: {source['reason']}",
                class_name="mt-1 text-[10px] leading-relaxed text-[#87917f]",
            ),
            rx.el.p(
                rx.cond(
                    source["excerpt"] != "",
                    source["excerpt"],
                    "No excerpt was returned for this source.",
                ),
                class_name="mt-1.5 rounded-md bg-[#fafbf5] p-2 text-[11px] leading-relaxed text-[#5f6c64]",
            ),
            rx.el.span(
                "Search excerpt, not a page Paperproof read",
                class_name="mt-1.5 inline-block rounded-md bg-[#f7e9e3] px-2 py-1 text-[10px] text-[#9d6257]",
            ),
            class_name="rounded-lg border border-[#e6e4d8] bg-[#fffefa] p-3",
        ),
        class_name="list-none",
    )


def external_section() -> rx.Component:
    """External context, kept strictly separate from the grounded answer."""
    return rx.cond(
        WorkspaceState.answer_search_status != "not_requested",
        rx.el.div(
            rx.el.div(
                rx.icon(
                    "globe", class_name="h-4 w-4 text-[#bc7567]"
                ),
                rx.el.h3(
                    "External context",
                    class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
                ),
                rx.el.span(
                    "NOT FROM THIS PAPER",
                    class_name="rounded-md bg-[#f7e9e3] px-2 py-1 text-[10px] font-semibold text-[#9d6257]",
                ),
                class_name="flex flex-wrap items-center gap-2",
            ),
            rx.el.p(
                "The answer above comes only from this paper. Anything below "
                "was found on the web and has not been checked against the "
                "paper.",
                class_name="mt-2 text-[11px] leading-relaxed text-[#7d887c]",
            ),
            rx.el.p(
                WorkspaceState.answer_external_context,
                class_name="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[#43524d]",
            ),
            rx.el.p(
                WorkspaceState.answer_search_note,
                role="status",
                class_name="mt-3 rounded-lg bg-[#fbf7ed] p-3 text-[11px] leading-relaxed text-[#7b756a]",
            ),
            rx.cond(
                WorkspaceState.answer_sources.length() > 0,
                rx.el.div(
                    rx.el.p(
                        "SOURCES",
                        class_name="mt-4 mb-2 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                    ),
                    rx.el.ul(
                        rx.foreach(WorkspaceState.answer_sources, source_row),
                        class_name="flex flex-col gap-2",
                    ),
                ),
            ),
            rx.el.p(
                "Search excerpts and metadata only. Open each source before "
                "relying on it.",
                class_name="mt-3 text-[10px] leading-relaxed text-[#87917f]",
            ),
            class_name="mt-5 border-t border-[#e6e9df] pt-4",
        ),
    )


def external_toggle() -> rx.Component:
    """Explicit opt-in, off by default, with the cost stated up front."""
    return rx.el.div(
        rx.el.label(
            rx.el.input(
                type="checkbox",
                checked=WorkspaceState.external_enabled,
                on_change=WorkspaceState.toggle_external,
                disabled=WorkspaceState.answer_loading,
                class_name="h-4 w-4 shrink-0 accent-[#215b56]",
            ),
            rx.el.div(
                rx.el.span(
                    "Include external context",
                    class_name="text-xs font-semibold text-[#31453c]",
                ),
                rx.el.p(
                    "Off by default. When on, your question and a short summary "
                    "of the paper's evidence are sent to an external search "
                    "provider, which may cost extra. Results are shown "
                    "separately and are never treated as what this paper says.",
                    class_name="mt-1 text-[10px] leading-relaxed text-[#87917f]",
                ),
                class_name="min-w-0",
            ),
            class_name="mt-3 flex cursor-pointer items-start gap-2.5 rounded-lg border border-[#e4e8dc] bg-[#fafbf5] p-3",
        ),
        class_name="mt-4",
    )


def capabilities_panel() -> rx.Component:
    """What the configured models can and cannot do right now."""
    return rx.el.details(
        rx.el.summary(
            rx.el.div(
                rx.icon(
                    "chevron-down",
                    class_name="h-3.5 w-3.5 text-[#7e887e] transition-transform group-open:rotate-180",
                ),
                rx.el.span(
                    "Model capabilities",
                    class_name="text-xs font-semibold text-[#31453c]",
                ),
                class_name="flex cursor-pointer list-none items-center gap-2",
            ),
        ),
        rx.el.ul(
            rx.foreach(
                WorkspaceState.capability_report,
                lambda check: rx.el.li(
                    rx.el.div(
                        rx.el.span(
                            check["capability"].replace("_", " "),
                            class_name="text-[11px] font-semibold text-[#5f7268]",
                        ),
                        rx.el.span(
                            rx.el.span(
                                rx.cond(
                                    check["model"] != "",
                                    check["model"],
                                    "not configured",
                                ),
                                class_name="text-[11px] text-[#43524d]",
                            ),
                            rx.el.span(
                                rx.cond(
                                    check["available"],
                                    "available",
                                    "unavailable",
                                ),
                                class_name=rx.cond(
                                    check["available"],
                                    "ml-2 rounded-md bg-[#e6f0e4] px-2 py-0.5 text-[10px] font-semibold text-[#3f6b4c]",
                                    "ml-2 rounded-md bg-[#f7e9e3] px-2 py-0.5 text-[10px] font-semibold text-[#9d6257]",
                                ),
                            ),
                            class_name="mt-1 flex flex-wrap items-center gap-1",
                        ),
                        rx.el.p(
                            check["detail"],
                            class_name="mt-1 text-[10px] leading-relaxed text-[#87917f]",
                        ),
                    ),
                    class_name="border-b border-[#e8e7dc] py-2 last:border-0",
                ),
            ),
            class_name="mt-2 flex flex-col",
        ),
        class_name="group mt-3 border-t border-[#e4e8dc] pt-3",
    )


def question_panel() -> rx.Component:
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "02", class_name="text-xs font-semibold text-[#bc7567]"
                ),
                rx.el.h2(
                    "What would you like to understand?",
                    class_name="text-base font-semibold text-[#202e3b]",
                ),
                class_name="flex items-center gap-2.5",
            ),
            rx.el.span(
                "GROUNDED Q&A",
                class_name="text-[9px] font-semibold tracking-wider text-[#8a9585]",
            ),
            class_name="flex flex-wrap items-center justify-between gap-3",
        ),
        rx.el.p(
            "Ask about this paper and get a concise answer you can verify. "
            "Questions about the paper's text, its figures, and its reference "
            "list are routed to the right evidence automatically.",
            class_name="mt-2 text-xs leading-relaxed text-[#788275]",
        ),
        rx.el.form(
            rx.el.label(
                "Your question", html_for="question", class_name="sr-only"
            ),
            rx.el.textarea(
                id="question",
                name="question",
                default_value=WorkspaceState.question,
                key=f"{WorkspaceState.selected_id}:{WorkspaceState.question}",
                placeholder="For example, what can this study actually tell us?",
                max_length=1000,
                rows=3,
                class_name="mt-5 w-full resize-y rounded-xl border border-[#dce2d4] bg-[#fffefa] px-4 py-3 text-sm leading-relaxed text-[#273b3d] placeholder:text-[#9aa493] focus:border-[#467c69] focus:outline-hidden focus:ring-2 focus:ring-[#215b56]/10",
            ),
            rx.el.div(
                rx.el.span(
                    "Relevant excerpts and your question are sent to OpenRouter to answer.",
                    class_name="max-w-sm text-[11px] leading-relaxed text-[#87917f]",
                ),
                rx.el.button(
                    rx.cond(
                        WorkspaceState.answer_loading,
                        rx.icon(
                            "loader-circle", class_name="h-4 w-4 animate-spin"
                        ),
                        rx.icon("arrow-right", class_name="h-4 w-4"),
                    ),
                    rx.cond(
                        WorkspaceState.answer_loading,
                        "Asking OpenRouter…",
                        "Ask about this paper",
                    ),
                    type="submit",
                    disabled=WorkspaceState.answer_loading,
                    class_name="flex shrink-0 items-center gap-2 rounded-lg bg-[#215b56] px-4 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-[#174842] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#215b56] disabled:cursor-wait disabled:opacity-70",
                ),
                class_name="mt-2 flex flex-wrap items-center justify-between gap-3",
            ),
            external_toggle(),
            on_submit=WorkspaceState.save_question,
        ),
        rx.el.div(
            rx.el.span(
                "TRY ASKING",
                class_name="text-[9px] font-semibold tracking-wider text-[#9b9e8a]",
            ),
            starter("What is the main finding?"),
            starter("How was the study designed?"),
            starter("What are the limitations?"),
            starter("Which references are never cited?"),
            class_name="mt-5 flex flex-wrap items-center gap-2",
        ),
        rx.cond(
            WorkspaceState.question_error,
            rx.el.p(
                WorkspaceState.question_message,
                role="alert",
                class_name="mt-3 rounded-lg bg-red-50 p-3 text-xs leading-relaxed text-red-700",
            ),
        ),
        rx.cond(
            WorkspaceState.answer_error_message != "",
            rx.el.p(
                rx.icon("triangle-alert", class_name="mt-0.5 h-4 w-4 shrink-0"),
                WorkspaceState.answer_error_message,
                role="alert",
                class_name="mt-4 flex gap-2 rounded-lg bg-red-50 p-3 text-xs leading-relaxed text-red-700",
            ),
        ),
        rx.cond(
            WorkspaceState.answer_loading,
            rx.el.div(
                rx.icon(
                    "loader-circle",
                    class_name="h-4 w-4 animate-spin text-[#215b56]",
                ),
                rx.el.p(
                    "Finding relevant passages and preparing a grounded answer…",
                    class_name="text-xs text-[#597362]",
                ),
                role="status",
                class_name="mt-4 flex items-center gap-2 rounded-xl border border-[#dfe5d7] bg-[#fffefa] p-4",
            ),
        ),
        rx.cond(
            WorkspaceState.answer != "",
            rx.el.div(
                rx.el.p(
                    f"“{WorkspaceState.saved_question}”",
                    class_name="mb-3 break-words text-xs font-medium text-[#718078]",
                ),
                rx.el.div(
                    rx.icon("sparkles", class_name="h-4 w-4 text-[#215b56]"),
                    rx.el.h3(
                        "A grounded answer",
                        class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
                    ),
                    class_name="mb-3 flex items-center gap-2",
                ),
                rx.el.p(
                    WorkspaceState.answer,
                    class_name="whitespace-pre-wrap text-sm leading-relaxed text-[#43524d]",
                ),
                answer_meta(),
                external_section(),
                evidence_section(),
                class_name="mt-4 rounded-xl border border-[#dfe5d7] bg-[#f8faf5] p-4 md:p-5",
            ),
        ),
        answer_settings(),
        capabilities_panel(),
        class_name="mt-5 rounded-2xl border border-[#dfe5d7] bg-[#f4f7ee] p-5 md:p-6",
    )


def workspace() -> rx.Component:
    return rx.el.div(
        header(),
        rx.el.main(
            rx.el.div(
                rx.el.div(
                    rx.el.span(class_name="h-px w-6 bg-[#bd7b69]"),
                    "RESEARCH, WITHOUT THE OVERWHELM",
                    class_name="mb-4 flex items-center gap-2 text-[10px] font-semibold tracking-[0.17em] text-[#ab7565]",
                ),
                rx.el.h1(
                    "Big ideas. ",
                    rx.el.span(
                        "A little more clarity.",
                        class_name="italic text-[#396e60]",
                    ),
                    class_name="font-['Lora'] text-3xl font-medium leading-tight tracking-tight text-[#24333b] sm:text-4xl lg:text-[43px]",
                ),
                rx.el.p(
                    "Your space to slow down, read a paper, and ask better questions.",
                    class_name="mt-4 text-sm leading-relaxed text-[#7c8579]",
                ),
                class_name="pt-9 pb-7 md:pt-10 md:pb-8",
            ),
            guide(),
            rx.el.div(
                rx.el.aside(
                    upload_panel(), library_panel(), class_name="w-full min-w-0"
                ),
                rx.el.div(
                    paper_reader(),
                    question_panel(),
                    class_name="w-full min-w-0",
                ),
                class_name="grid w-full grid-cols-1 items-start gap-7 lg:grid-cols-[320px_minmax(0,1fr)] xl:gap-9",
            ),
            citation_audit_panel(),
            rx.el.footer(
                rx.el.div(
                    rx.el.img(
                        src="/brand/icon-book-check.webp",
                        alt="",
                        width=22,
                        height=21,
                        class_name="h-[21px] w-auto shrink-0 opacity-75",
                    ),
                    rx.el.span(
                        "Made for curious minds, not just experts.",
                        class_name="font-['Lora'] text-xs italic text-[#8b9180]",
                    ),
                    class_name="flex items-center gap-2.5",
                ),
                rx.el.span(
                    "Session-only workspace · No account needed",
                    class_name="text-[10px] text-[#929887]",
                ),
                class_name="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-[#e3e5d9] py-5",
            ),
            class_name="mx-auto w-full max-w-[1440px] px-5 pb-4 md:px-10",
        ),
        class_name="min-h-dvh bg-[#f8f8f1] font-['Inter'] text-[#24333b] selection:bg-[#dcebdc]",
    )
