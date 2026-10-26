import reflex as rx

config = rx.Config(
    app_name="app",
    env_file=".env",
    # Hide the sticky "Built with Reflex" badge that production builds add to
    # every page. Reflex only omits it automatically when deploying through its
    # own cloud on a paid tier; self-hosted deployments opt out here.
    show_built_with_reflex=False,
    # Keep all client state (including uploaded paper text) in process memory
    # only. The disk manager would pickle session state to `.states/*.pkl`,
    # which contradicts the "session only" promise shown in the upload panel.
    state_manager_mode="memory",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ],
)
