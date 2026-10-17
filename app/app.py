import reflex as rx

from app.components.workspace import workspace
from app.logging_safety import install_redaction
from app.states.workspace_state import WorkspaceState

# Installed before anything can log, so no credential can reach a handler even
# if a future change logs one by mistake.
install_redaction()


def index() -> rx.Component:
    return workspace()


app = rx.App(
    theme=rx.theme(appearance="light"),
    head_components=[
        rx.el.link(rel="preconnect", href="https://fonts.googleapis.com"),
        rx.el.link(
            rel="preconnect",
            href="https://fonts.gstatic.com",
            cross_origin="",
        ),
        rx.el.link(
            href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Lora:ital,wght@0,400;0,500;0,600;1,400;1,500&display=swap",
            rel="stylesheet",
        ),
    ],
)
app.add_page(
    index,
    route="/",
    title="Paperproof — A little more clarity",
    description="A welcoming research-paper workspace. Read teaching samples or upload a PDF or DOCX, ask grounded questions, and inspect cited evidence.",
    # Reflex takes load events from add_page, not from a state method named
    # on_load. This clears figures left on disk by an earlier run of the app
    # before any paper is shown.
    on_load=WorkspaceState.sweep_session_media,
)
