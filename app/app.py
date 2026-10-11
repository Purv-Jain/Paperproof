import reflex as rx

from app.components.workspace import workspace


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
)
