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
        rx.el.link(rel="icon", href="/favicon.ico", sizes="any"),
        rx.el.link(
            rel="icon",
            href="/brand/icon-book-check.webp",
            type="image/webp",
        ),
        rx.el.link(rel="apple-touch-icon", href="/apple-touch-icon.png"),
        rx.el.meta(name="theme-color", content="#f8f8f1"),
        rx.el.meta(property="og:type", content="website"),
        rx.el.meta(property="og:site_name", content="PaperProof"),
        rx.el.meta(property="og:title", content="PaperProof — A little more clarity"),
        rx.el.meta(
            property="og:description",
            content="Research, without the overwhelm. Read a paper, ask grounded questions, and check the citations.",
        ),
        rx.el.meta(property="og:image", content="/og-image.png"),
        rx.el.meta(name="twitter:card", content="summary_large_image"),
        rx.el.meta(name="twitter:image", content="/og-image.png"),
    ],
)
app.add_page(
    index,
    route="/",
    title="PaperProof — A little more clarity",
    description="A welcoming research-paper workspace. Read teaching samples or upload a PDF or DOCX, ask grounded questions, and inspect cited evidence.",
)
