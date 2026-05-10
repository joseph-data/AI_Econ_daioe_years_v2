from shiny.express import input, render, ui

ui.page_opts(
    title="Yearly DAIOE Explorer of Swedish Occupations",
    theme=ui.Theme.from_brand(__file__),
    fillable=True,
    lang="en",
    full_width=True,
)


with ui.navset_pill_list(id="tab", well=False, widths=(2, 10)):
    with ui.nav_panel(title="Occupation View"):
        "Panel A content"

    with ui.nav_panel(title="Comparison View"):
        "Panel B content"

    with ui.nav_panel(title="Download"):
        "Panel C content"
