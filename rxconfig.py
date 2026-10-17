import reflex as rx

config = rx.Config(
    app_name="app",
    env_file=".env",
    # Keep all client state (including uploaded paper text) in process memory
    # only. The disk manager would pickle session state to `.states/*.pkl`,
    # which contradicts the "session only" promise shown in the upload panel.
    state_manager_mode="memory",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ],
)
