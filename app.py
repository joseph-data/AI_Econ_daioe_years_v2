from pathlib import Path

import polars as pl
from shiny import reactive, req
from shiny.express import app_opts, input, render, ui
from shinywidgets import render_plotly

from src import calcs, visuals
from src.setup import (
    AGES,
    INTRO_MD,
    LEVELS,
    METRICS,
    SEXES,
    YEAR_MAX,
    YEAR_MIN,
    YEARS,
    as_great_table_html,
    build_choices_by_level,
    download_extension,
    download_media_type,
    export_filtered_data,
    lf,
)

app_opts(static_assets={"/logos": Path(__file__).parent / "logos"})

LEVEL_LABELS = {
    "SSYK1": "SSYK 1 - Major groups",
    "SSYK2": "SSYK 2 - Minor groups",
    "SSYK3": "SSYK 3 - Unit groups",
    "SSYK4": "SSYK 4 - Detailed units",
}
OCCUPATION_CHOICES = build_choices_by_level(lf, LEVELS)
DEFAULT_LEVEL = "SSYK4" if "SSYK4" in LEVELS else LEVELS[0]
DEFAULT_OCCUPATION = next(iter(OCCUPATION_CHOICES[DEFAULT_LEVEL]))

ui.page_opts(
    title=ui.tags.span(
        ui.tags.img(
            src="logos/lab.svg",
            height="32px",
            style="margin-right:10px;vertical-align:middle;",
        ),
        "Yearly DAIOE Explorer of Swedish Occupations",
    ),
    theme=ui.Theme.from_brand(__file__),
    fillable=True,
    lang="en",
    full_width=True,
)


@reactive.calc
def _download_frame():
    """Collect filtered rows for the download tab."""
    occupations = (
        list(input.download_occupation()) if input.download_occupation() else None
    )
    years = input.download_years()
    age = input.download_age()
    sexes = list(input.download_sex())

    data = lf.filter(
        (pl.col("level") == input.download_level())
        & pl.col("year").is_between(int(years[0]), int(years[1])),
    )
    if sexes:
        data = data.filter(pl.col("sex").is_in(sexes))
    if age != "All":
        data = data.filter(pl.col("age_group") == age)
    if occupations:
        data = data.filter(pl.col("occupation").is_in(occupations))
    return data.collect()


@reactive.calc
def occ_summary():
    """Reactive wrapper: returns summary dict for the selected occupation and year."""
    return calcs.get_occ_summary(lf, input.occupation(), int(input.occ_year()))


@reactive.calc
def comparison_data():
    """Return total employment per year/occupation for the comparison view."""
    occs = list(input.comp_occs())
    ages = list(input.comp_age())
    req(occs, ages)
    return calcs.get_comparison_employment(lf, occs, ages)


@reactive.calc
def comp_radar_data():
    """Return mean AI percentile scores per occupation for the radar chart."""
    occs = list(input.comp_occs())
    req(occs)
    return calcs.get_comp_radar(lf, occs, int(input.comp_year()))


@reactive.calc
def occ_employment_by_age():
    """Reactive wrapper: returns long-format employment by age group for the line chart."""
    return calcs.get_occ_employment_by_age(
        lf,
        input.occupation(),
        (int(input.chart_year_range()[0]), int(input.chart_year_range()[1])),
        list(input.chart_age_groups()),
    )


with ui.navset_pill(id="tab"):
    with ui.nav_panel(title="1. Occupation View"):
        with ui.layout_columns(col_widths=[6, 6]):
            with ui.card(full_screen=True):
                ui.markdown(INTRO_MD)
                with ui.div(class_="d-flex gap-3 align-items-end"):
                    ui.input_select(
                        "occ_level",
                        "SSYK level",
                        choices={
                            level: LEVEL_LABELS.get(level, level) for level in LEVELS
                        },
                        selected=DEFAULT_LEVEL,
                        width="200px",
                    )
                    ui.input_selectize(
                        "occupation",
                        "Occupation",
                        choices=OCCUPATION_CHOICES[DEFAULT_LEVEL],
                        selected=DEFAULT_OCCUPATION,
                    )
                    ui.input_select(
                        "occ_year",
                        "Year",
                        choices={y: str(y) for y in YEARS},
                        selected=YEAR_MAX,
                        width="120px",
                    )

                @render.ui
                def occ_value_boxes():
                    """Render employment and % change value boxes for the selected occupation."""
                    req(input.occupation())
                    summary = occ_summary()
                    if summary is None:
                        return ui.p("No data available.")
                    return visuals.build_value_boxes(summary, input.occupation())

            with ui.card(full_screen=True):
                ui.card_header("AI Exposure by Sub-domain")

                @render_plotly
                def ai_exposure_bar():
                    """Render bar chart of AI exposure level per sub-domain, coloured by index score."""
                    req(input.occupation())
                    df = calcs.get_occ_ai_exposure(
                        lf, input.occupation(), int(input.occ_year())
                    )
                    return visuals.build_ai_exposure_bar(
                        df.to_pandas(), input.occupation(), int(input.occ_year())
                    )

                ui.markdown(visuals.DAIOE_SOURCE_MD)

            with ui.card(full_screen=True):
                ui.card_header("Employment by Age Group")
                with ui.layout_sidebar():
                    with ui.sidebar(width="220px", open="closed"):
                        ui.input_slider(
                            "chart_year_range",
                            "Year range",
                            min=min(YEARS),
                            max=max(YEARS),
                            value=(min(YEARS), max(YEARS)),
                            step=1,
                            sep="",
                        )
                        ui.input_selectize(
                            "chart_age_groups",
                            "Age groups",
                            choices=AGES,
                            selected=AGES[:2],
                            multiple=True,
                        )

                    @render_plotly
                    def occ_age_chart():
                        """Render a line chart of 1-yr employment % change per age group."""
                        req(input.occupation())
                        df = occ_employment_by_age()
                        return visuals.build_age_chart(
                            df.to_pandas(), input.occupation()
                        )

                    ui.markdown(visuals.SCB_SOURCE_MD)

            with ui.card():
                "Card 4"

    with ui.nav_panel(title="2. Comparison View"):
        with ui.layout_sidebar():
            with ui.sidebar(bg="#FFFFFF", width=250, title="Benchmarking"):
                ui.input_select(
                    "comp_level",
                    "SSYK Level",
                    choices=["All Levels", *LEVELS],
                    selected=DEFAULT_LEVEL,
                )
                ui.input_selectize(
                    "comp_occs", "Select Occupations", choices={}, multiple=True,
                    options={"placeholder": "Accountants ..."},
                )
                ui.hr()
                ui.input_selectize(
                    "comp_age",
                    "Age Group",
                    choices=AGES,
                    selected="Early Career 2 (25-29)",
                    multiple=True,
                )
                ui.hr()
                ui.input_select(
                    "comp_year",
                    "Comparison Year (Radar)",
                    choices=[str(y) for y in YEARS],
                    selected=str(YEAR_MAX),
                )

            with ui.card():
                ui.card_header("Occupations Summary")

                @render.ui
                def comparison_summary():
                    df = comparison_data()

                    latest_yr = df["year"].max()
                    summary_rows = []
                    for occ in df["occupation"].unique():
                        sub = df.filter(pl.col("occupation") == occ).sort("year")
                        curr_emp = sub.tail(1)["count"][0]

                        def _val(yr, _sub=sub):
                            s = _sub.filter(pl.col("year") == yr)["count"]
                            return f"{int(s[0]):,}" if not s.is_empty() else "---"

                        summary_rows.append(
                            ui.tags.tr(
                                ui.tags.td(occ, style="font-weight: bold;"),
                                ui.tags.td(_val(latest_yr - 5)),
                                ui.tags.td(_val(latest_yr - 3)),
                                ui.tags.td(_val(latest_yr - 1)),
                                ui.tags.td(
                                    f"{int(curr_emp):,}",
                                    style="background-color: #f8f9fa; font-weight: bold;",
                                ),
                            ),
                        )

                    return ui.tags.table(
                        ui.tags.thead(
                            ui.tags.tr(
                                ui.tags.th("Occupation"),
                                ui.tags.th(f"Emp ({latest_yr - 5})"),
                                ui.tags.th(f"Emp ({latest_yr - 3})"),
                                ui.tags.th(f"Emp ({latest_yr - 1})"),
                                ui.tags.th(f"Emp ({latest_yr})"),
                            ),
                        ),
                        ui.tags.tbody(*summary_rows),
                        class_="table table-sm table-hover",
                        style="font-size: 0.9rem;",
                    )

            with ui.layout_columns(col_widths=[6, 6], gap="1rem"):
                with ui.card(full_screen=True):
                    ui.card_header("Annual Employment Change (Selected Occupations)")

                    @render_plotly
                    def comparison_employment_plot():
                        return visuals.build_comparison_employment_plot(
                            comparison_data().to_pandas()
                        )

                with ui.card(full_screen=True):
                    ui.card_header("Radar Comparison (AI Exposure Percentiles)")

                    @render_plotly
                    def comp_radar_plot():
                        return visuals.build_comp_radar_plot(
                            comp_radar_data().to_pandas(), METRICS
                        )

    with ui.nav_panel(title="3. Download"):
        ui.p(
            "Export the filtered row-level dataset or inspect a compact preview before downloading.",
            class_="text-muted mb-3",
        )
        with ui.div(class_="d-flex gap-3 align-items-end flex-wrap mb-3"):
            ui.input_select(
                "download_level",
                "SSYK level",
                choices={level: LEVEL_LABELS.get(level, level) for level in LEVELS},
                selected=DEFAULT_LEVEL,
                width="200px",
            )
            ui.input_slider(
                "download_years",
                "Year range",
                min=YEAR_MIN,
                max=YEAR_MAX,
                value=(YEAR_MIN, YEAR_MAX),
                step=1,
                sep="",
                width="220px",
            )
            ui.input_checkbox_group(
                "download_sex",
                "Sex",
                choices={"men": "Men", "women": "Women"},
                selected=SEXES,
                inline=True,
            )
            ui.input_select(
                "download_age",
                "Age group",
                choices={"All": "All ages"} | {a: a for a in AGES},
                selected="All",
                width="200px",
            )
            ui.input_selectize(
                "download_occupation",
                "Occupations",
                choices=OCCUPATION_CHOICES[DEFAULT_LEVEL],
                multiple=True,
                options={"placeholder": "All occupations"},
            )
            ui.input_select(
                "download_format",
                "Format",
                choices={"csv": "CSV", "parquet": "Parquet", "excel": "Excel"},
                selected="csv",
                width="120px",
            )

        with ui.layout_columns(col_widths=[3, 9]):
            with ui.value_box(theme="primary"):
                "Rows"

                @render.text
                def download_rows_count():
                    """Show count of rows matching current download filters."""
                    return f"{_download_frame().height:,}"

            with ui.card():
                ui.card_header("Export")

                @render.download(
                    filename=lambda: (
                        "daioe_swedish_occupations_"
                        f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}."
                        f"{download_extension(input.download_format())}"
                    ),
                    media_type=lambda: download_media_type(input.download_format()),
                    label="Download filtered data",
                )
                def download_data():
                    """Export filtered data in the selected format."""
                    return export_filtered_data(
                        _download_frame().to_pandas(),
                        input.download_format(),
                    )

        with ui.card(full_screen=True):
            ui.card_header("Preview (first 50 rows)")

            @render.ui
            def download_preview():
                """Render a preview table of the filtered download data."""
                cols = [
                    "level",
                    "ssyk_code",
                    "occupation",
                    "year",
                    "sex",
                    "age_group",
                    "count",
                    "daioe_genai_wavg",
                    "daioe_allapps_wavg",
                    "pct_chg_1y",
                ]
                data = _download_frame().select(cols).head(50).to_pandas()
                return as_great_table_html(data, METRICS)


@reactive.effect
def _sync_occupation_choices():
    """Update the occupation selectize choices whenever the SSYK level changes."""
    level = input.occ_level()
    choices = OCCUPATION_CHOICES[level]
    ui.update_selectize("occupation", choices=choices, selected=next(iter(choices)))


@reactive.effect
def _sync_comp_occupation_choices():
    """Update comparison occupation choices when the SSYK level changes."""
    level = input.comp_level()
    if level == "All Levels":
        choices = {occ: occ for d in OCCUPATION_CHOICES.values() for occ in d}
    else:
        choices = OCCUPATION_CHOICES.get(level, {})
    ui.update_selectize("comp_occs", choices=choices, selected=[])


@reactive.effect
def _sync_download_occupation_choices():
    """Update the download occupation selectize when the download SSYK level changes."""
    level = input.download_level()
    ui.update_selectize(
        "download_occupation", choices=OCCUPATION_CHOICES[level], selected=[]
    )
