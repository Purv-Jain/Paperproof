import reflex as rx

from app.citation_audit import AuditIssue, ReferenceAudit
from app.states.paper_data import AnswerEvidence, Paper, Passage, Reference
from app.states.workspace_state import WorkspaceState


def header() -> rx.Component:
    return rx.el.header(
        rx.el.div(
            rx.el.a(
                rx.el.span(
                    rx.icon(
                        "book-open-check", class_name="h-6 w-6 text-[#215b56]"
                    ),
                    class_name="flex h-10 w-10 items-center justify-center rounded-xl bg-[#e8efea]",
                ),
                rx.el.span(
                    "paperproof",
                    class_name="font-['Lora'] text-2xl font-semibold tracking-tight text-[#202e3b]",
                ),
                href="/",
                aria_label="Paperproof home",
                class_name="flex items-center gap-3",
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
                "Try a teaching sample, or upload a PDF or DOCX. Scanned PDFs are read with OCR automatically.",
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
        rx.el.p(
            rx.icon("lock-keyhole", class_name="mt-0.5 h-3 w-3 shrink-0"),
            "Your file stays in this session only. Citation-audit bibliography entries are sent to Crossref; claim excerpts are not sent to OpenRouter by this audit. Asking a question sends relevant excerpts to OpenRouter. Scanned PDFs use English OCR.",
            class_name="mt-3 flex gap-2 text-[11px] leading-relaxed text-[#7b847b]",
        ),
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


def reference_row(reference: Reference) -> rx.Component:
    return rx.el.li(
        rx.icon("bookmark", class_name="mt-1 h-4 w-4 shrink-0 text-[#80917e]"),
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
                "Paper text",
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
                "References",
                on_click=WorkspaceState.show_references,
                aria_pressed=WorkspaceState.reader_tab == "references",
                class_name=rx.cond(
                    WorkspaceState.reader_tab == "references",
                    "flex items-center gap-2 border-b-2 border-[#215b56] bg-transparent px-1 py-3 text-xs font-semibold text-[#215b56]",
                    "flex items-center gap-2 border-b-2 border-transparent bg-transparent px-1 py-3 text-xs text-[#7e887e] hover:text-[#215b56]",
                ),
            ),
            class_name="flex gap-7 border-y border-[#e9ebdf] px-5 md:px-7",
        ),
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
                    class_name="flex max-h-80 w-full shrink-0 flex-col gap-1 overflow-y-auto border-b border-[#eceede] bg-[#fafbf5] p-3 md:max-h-[430px] md:w-44 md:border-r md:border-b-0 md:py-5",
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
                                WorkspaceState.selected_audit[
                                    "references"
                                ].length()
                                > 0,
                                "Parsed references & Crossref status",
                                "References as supplied",
                            ),
                            class_name="font-['Lora'] text-xl text-[#263a3d]",
                        ),
                        rx.el.p(
                            rx.cond(
                                WorkspaceState.selected_audit[
                                    "references"
                                ].length()
                                > 0,
                                "Parsed entries and verification results from the latest citation audit. Crossref results are not proof that a source does or does not exist.",
                                "Reference entries as supplied. Run the citation audit below to compare in-text citations and check available Crossref metadata.",
                            ),
                            class_name="mt-2 text-xs leading-relaxed text-[#7d887c]",
                        ),
                        rx.cond(
                            WorkspaceState.selected_audit["references"].length()
                            > 0,
                            rx.el.ul(
                                rx.foreach(
                                    WorkspaceState.selected_audit["references"],
                                    verification_row,
                                ),
                                class_name="mt-2 divide-y divide-[#e8e7dc]",
                            ),
                            rx.el.ul(
                                rx.foreach(
                                    WorkspaceState.selected_paper["references"],
                                    reference_row,
                                ),
                                class_name="mt-2",
                            ),
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
            rx.el.span(
                issue["category"],
                class_name="w-fit rounded-full bg-[#f7e9e3] px-2.5 py-1 text-[10px] font-semibold text-[#9d6257]",
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


def verification_row(reference: ReferenceAudit) -> rx.Component:
    return rx.el.li(
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    rx.match(
                        reference["status"],
                        ("confirmed", "Metadata match"),
                        ("ambiguous", "Manual review"),
                        ("not_found_in_crossref", "No Crossref match"),
                        ("lookup_error", "Lookup unavailable"),
                        ("not_checked_limit", "Not checked · audit limit"),
                        "Pending check",
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
                    rx.el.div(
                        rx.el.h3(
                            "Crossref reference checks",
                            class_name="font-['Lora'] text-lg font-medium text-[#263a3d]",
                        ),
                        rx.el.p(
                            "A confirmed match means the available metadata aligned; ambiguous, missing, and lookup-error results require manual checking.",
                            class_name="mt-1 text-[11px] leading-relaxed text-[#788275]",
                        ),
                        rx.el.ul(
                            rx.foreach(
                                WorkspaceState.selected_audit["references"],
                                verification_row,
                            ),
                            class_name="mt-3 divide-y divide-[#e8e7dc] rounded-xl border border-[#e6e4d8] bg-[#fffefa] px-4",
                        ),
                        class_name="mt-5",
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
    return rx.el.button(
        rx.el.div(
            rx.icon(
                "quote", class_name="mt-0.5 h-4 w-4 shrink-0 text-[#bc7567]"
            ),
            rx.el.div(
                rx.el.p(
                    evidence["text"],
                    class_name="whitespace-pre-wrap break-words text-xs leading-relaxed text-[#46564f]",
                ),
                rx.el.p(
                    rx.cond(
                        evidence["page"] > 0,
                        f"{evidence['section']} · page {evidence['page']}",
                        f"{evidence['section']} · page unavailable",
                    ),
                    class_name="mt-2 text-[10px] font-semibold tracking-wide text-[#718078]",
                ),
            ),
            class_name="flex gap-3 text-left",
        ),
        on_click=WorkspaceState.select_passage(evidence["passage_id"]),
        aria_label="Open this quoted passage in the paper reader",
        class_name="w-full rounded-xl border border-[#e2e7dc] bg-[#fffefa] p-4 text-left transition-colors hover:border-[#9eafa0] hover:bg-[#f8faf5] focus-visible:outline-2 focus-visible:outline-[#215b56]",
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
            "Ask about this paper and get a concise answer with passages you can verify in the reader.",
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
                rx.cond(
                    WorkspaceState.answer_evidence.length() > 0,
                    rx.el.div(
                        rx.el.p(
                            "SUPPORTING PASSAGES · CLICK TO OPEN IN THE READER",
                            class_name="mb-2 text-[9px] font-semibold tracking-[0.12em] text-[#889184]",
                        ),
                        rx.el.div(
                            rx.foreach(
                                WorkspaceState.answer_evidence, evidence_card
                            ),
                            class_name="flex flex-col gap-2",
                        ),
                        class_name="mt-5 border-t border-[#e6e9df] pt-4",
                    ),
                    rx.el.p(
                        "The available paper text does not establish this. No supporting evidence is shown.",
                        class_name="mt-3 text-xs leading-relaxed text-[#7c8579]",
                    ),
                ),
                class_name="mt-4 rounded-xl border border-[#dfe5d7] bg-[#f8faf5] p-4 md:p-5",
            ),
        ),
        answer_settings(),
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
                rx.el.span(
                    "Made for curious minds, not just experts.",
                    class_name="font-['Lora'] text-xs italic text-[#8b9180]",
                ),
                rx.el.span(
                    "Session-only workspace · No account needed",
                    class_name="text-[10px] text-[#929887]",
                ),
                class_name="mt-8 flex flex-wrap justify-between gap-3 border-t border-[#e3e5d9] py-5",
            ),
            class_name="mx-auto w-full max-w-[1440px] px-5 pb-4 md:px-10",
        ),
        class_name="min-h-dvh bg-[#f8f8f1] font-['Inter'] text-[#24333b] selection:bg-[#dcebdc]",
    )
