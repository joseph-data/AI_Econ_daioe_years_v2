from pathlib import Path

import faicons as fa
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
from shiny import reactive
from shiny.express import input, render, ui
from shinywidgets import render_plotly

# ── Data ───────────────────────────────────────────────────────────────────────
DATA_PATH = Path(__file__).parent / "data" / "daioe_scb_years_processed.parquet"
df_full = pl.read_parquet(DATA_PATH)

YEARS = sorted(df_full["year"].unique().to_list())
LEVELS = ["SSYK1", "SSYK2", "SSYK3", "SSYK4"]
AGE_GROUPS = sorted(df_full["age_group"].unique().to_list())

AI_CAPS = {
    "All Applications":     "daioe_allapps_avg",
    "Generative AI":        "daioe_genai_avg",
    "Language Models":      "daioe_lngmod_avg",
    "Translation":          "daioe_translat_avg",
    "Reading Comprehension":"daioe_readcompr_avg",
    "Speech Recognition":   "daioe_speechrec_avg",
    "Image Recognition":    "daioe_imgrec_avg",
    "Image Comprehension":  "daioe_imgcompr_avg",
    "Image Generation":     "daioe_imggen_avg",
    "Video Games":          "daioe_videogames_avg",
    "Strategic Games":      "daioe_stratgames_avg",
}

SEX_COLORS = {"men": "#4C72B0", "women": "#DD8452"}

# ── Page ───────────────────────────────────────────────────────────────────────
ui.page_opts(
    title="DAIOE — AI Occupational Exposure Dashboard",
    fillable=True,
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with ui.sidebar(width=270):
    ui.h6("Filters", class_="fw-bold mt-1")

    ui.input_select(
        "level", "Hierarchy Level",
        choices={"SSYK1": "SSYK 1 — Major groups",
                 "SSYK2": "SSYK 2 — Minor groups",
                 "SSYK3": "SSYK 3 — Unit groups",
                 "SSYK4": "SSYK 4 — Detailed units"},
        selected="SSYK2",
    )
    ui.input_slider(
        "year_range", "Year Range",
        min=min(YEARS), max=max(YEARS),
        value=[min(YEARS), max(YEARS)],
        step=1, sep="",
    )
    ui.input_select(
        "year_snap", "Snapshot Year",
        choices={str(y): str(y) for y in YEARS},
        selected=str(max(YEARS)),
    )
    ui.input_checkbox_group(
        "sex", "Sex",
        choices={"men": "Men", "women": "Women"},
        selected=["men", "women"],
    )
    ui.input_select(
        "age_group", "Age Group",
        choices={"All": "All ages"} | {a: a for a in AGE_GROUPS},
        selected="All",
    )
    ui.hr()
    ui.input_select(
        "ai_cap", "AI Capability",
        choices=list(AI_CAPS.keys()),
        selected="Generative AI",
    )
    ui.input_numeric("top_n", "Top N Occupations", value=15, min=5, max=50, step=5)


# ── Reactive data ──────────────────────────────────────────────────────────────
@reactive.calc
def filtered():
    """Time-series slice respecting all sidebar filters."""
    sexes = list(input.sex())
    d = df_full.filter(
        pl.col("level") == input.level(),
        pl.col("year").is_between(input.year_range()[0], input.year_range()[1]),
    )
    if sexes:
        d = d.filter(pl.col("sex").is_in(sexes))
    if input.age_group() != "All":
        d = d.filter(pl.col("age_group") == input.age_group())
    return d


@reactive.calc
def snapshot():
    """Cross-sectional slice for the snapshot year, aggregated over sex/age."""
    cap_col = AI_CAPS[input.ai_cap()]
    sexes = list(input.sex())
    d = df_full.filter(
        pl.col("level") == input.level(),
        pl.col("year") == int(input.year_snap()),
    )
    if sexes:
        d = d.filter(pl.col("sex").is_in(sexes))
    if input.age_group() != "All":
        d = d.filter(pl.col("age_group") == input.age_group())
    return (
        d.group_by("ssyk_code", "occupation")
        .agg(
            pl.col("count").sum(),
            pl.col(cap_col).mean().alias("ai_score"),
            pl.col("pct_chg_1y").mean(),
            pl.col("pct_chg_3y").mean(),
            pl.col("pct_chg_5y").mean(),
        )
        .sort("ai_score", descending=True)
    )


# ── Tabs ───────────────────────────────────────────────────────────────────────
with ui.navset_tab():

    # ── Overview ───────────────────────────────────────────────────────────────
    with ui.nav_panel("Overview"):

        with ui.layout_columns(col_widths=[3, 3, 3, 3], class_="mb-3"):

            with ui.value_box(showcase=fa.icon_svg("users"), theme="primary"):
                "Total Employment"
                @render.text
                def kpi_total():
                    return f"{filtered()['count'].sum():,.0f}"

            with ui.value_box(showcase=fa.icon_svg("robot"), theme="info"):
                "Avg GenAI Exposure"
                @render.text
                def kpi_genai():
                    return f"{filtered()['daioe_genai_avg'].mean():.3f}"

            with ui.value_box(showcase=fa.icon_svg("arrow-trend-up"), theme="success"):
                "Avg 1-Year Emp. Change"
                @render.text
                def kpi_chg():
                    val = filtered().drop_nulls("pct_chg_1y")["pct_chg_1y"].mean()
                    return f"{val:+.1f}%"

            with ui.value_box(showcase=fa.icon_svg("briefcase"), theme="secondary"):
                "Occupations in View"
                @render.text
                def kpi_occ():
                    return f"{filtered()['occupation'].n_unique():,}"

        with ui.layout_columns(col_widths=[7, 5]):

            with ui.card(full_screen=True):
                ui.card_header("Total Employment Over Time by Sex")
                @render_plotly
                def plot_emp_trend():
                    d = (
                        filtered()
                        .group_by("year", "sex")
                        .agg(pl.col("count").sum())
                        .sort("year")
                        .to_pandas()
                    )
                    fig = px.line(
                        d, x="year", y="count", color="sex",
                        color_discrete_map=SEX_COLORS,
                        markers=True, template="plotly_white",
                        labels={"count": "Employed Persons", "year": "Year", "sex": "Sex"},
                    )
                    fig.update_xaxes(tickformat="d")
                    fig.update_layout(legend_title="", margin=dict(t=10, b=30))
                    return fig

            with ui.card(full_screen=True):
                ui.card_header("Employment Share by AI Exposure Level (Snapshot Year)")
                @render_plotly
                def plot_exp_dist():
                    cap_col = AI_CAPS[input.ai_cap()]
                    level_col = cap_col.replace("_avg", "_Level_Exposure")
                    sexes = list(input.sex())
                    d = df_full.filter(
                        pl.col("level") == input.level(),
                        pl.col("year") == int(input.year_snap()),
                    )
                    if sexes:
                        d = d.filter(pl.col("sex").is_in(sexes))
                    d = (
                        d.drop_nulls(level_col)
                        .group_by(level_col)
                        .agg(pl.col("count").sum())
                        .sort(level_col)
                        .to_pandas()
                    )
                    d[level_col] = d[level_col].astype(str)
                    fig = px.bar(
                        d, x=level_col, y="count",
                        color=level_col,
                        color_discrete_sequence=["#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850"],
                        template="plotly_white",
                        labels={level_col: "Exposure Level (1 = Low → 5 = High)",
                                "count": "Employed Persons"},
                    )
                    fig.update_layout(showlegend=False, margin=dict(t=10, b=30))
                    return fig

    # ── AI Exposure Rankings ───────────────────────────────────────────────────
    with ui.nav_panel("AI Exposure Rankings"):

        with ui.layout_columns(col_widths=[6, 6]):

            with ui.card(full_screen=True):
                ui.card_header("Highest-Exposed Occupations")
                @render_plotly
                def plot_top():
                    d = snapshot().head(input.top_n()).to_pandas().sort_values("ai_score")
                    fig = px.bar(
                        d, x="ai_score", y="occupation", orientation="h",
                        color="ai_score", color_continuous_scale="RdYlGn",
                        template="plotly_white",
                        labels={"ai_score": input.ai_cap(), "occupation": ""},
                        hover_data={"count": True},
                    )
                    fig.update_layout(coloraxis_showscale=False, margin=dict(t=10, l=10, b=30))
                    return fig

            with ui.card(full_screen=True):
                ui.card_header("Lowest-Exposed Occupations")
                @render_plotly
                def plot_bot():
                    d = snapshot().tail(input.top_n()).to_pandas().sort_values("ai_score", ascending=False)
                    fig = px.bar(
                        d, x="ai_score", y="occupation", orientation="h",
                        color="ai_score", color_continuous_scale="RdYlGn",
                        template="plotly_white",
                        labels={"ai_score": input.ai_cap(), "occupation": ""},
                        hover_data={"count": True},
                    )
                    fig.update_layout(coloraxis_showscale=False, margin=dict(t=10, l=10, b=30))
                    return fig

        with ui.card(full_screen=True):
            ui.card_header("AI Capability Radar — Average Across Filtered Selection")
            @render_plotly
            def plot_radar():
                d = filtered()
                labels = list(AI_CAPS.keys())
                cols = list(AI_CAPS.values())
                means = [round(float(d[c].mean()), 3) for c in cols]
                fig = go.Figure(go.Scatterpolar(
                    r=means + [means[0]],
                    theta=labels + [labels[0]],
                    fill="toself",
                    fillcolor="rgba(76, 114, 176, 0.3)",
                    line=dict(color="#4C72B0", width=2),
                ))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, showticklabels=True)),
                    showlegend=False,
                    template="plotly_white",
                    margin=dict(t=30, b=30, l=60, r=60),
                )
                return fig

    # ── Employment vs AI ───────────────────────────────────────────────────────
    with ui.nav_panel("Employment vs AI"):

        with ui.card(full_screen=True):
            ui.card_header("AI Exposure vs 1-Year Employment Change (bubble size = employment)")
            @render_plotly
            def plot_scatter():
                d = snapshot().drop_nulls(["ai_score", "pct_chg_1y"]).to_pandas()
                fig = px.scatter(
                    d, x="ai_score", y="pct_chg_1y",
                    size="count", size_max=50,
                    hover_name="occupation",
                    hover_data={"count": ":,", "ai_score": ":.3f", "pct_chg_1y": ":.1f%"},
                    color="pct_chg_1y",
                    color_continuous_scale="RdYlGn",
                    color_continuous_midpoint=0,
                    template="plotly_white",
                    labels={
                        "ai_score": f"{input.ai_cap()} Score",
                        "pct_chg_1y": "1-Year Employment Change (%)",
                        "count": "Employed",
                    },
                )
                fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
                fig.update_layout(coloraxis_showscale=False, margin=dict(t=10, b=30))
                return fig

        with ui.layout_columns(col_widths=[6, 6]):

            with ui.card(full_screen=True):
                ui.card_header("3-Year Employment Change Distribution by Exposure Level")
                @render_plotly
                def plot_box():
                    cap_col = AI_CAPS[input.ai_cap()]
                    level_col = cap_col.replace("_avg", "_Level_Exposure")
                    d = filtered().drop_nulls([level_col, "pct_chg_3y"]).to_pandas()
                    d[level_col] = d[level_col].astype(str)
                    fig = px.box(
                        d, x=level_col, y="pct_chg_3y",
                        color=level_col,
                        color_discrete_sequence=["#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850"],
                        template="plotly_white",
                        labels={level_col: "Exposure Level (1=Low → 5=High)",
                                "pct_chg_3y": "3-Year Emp. Change (%)"},
                    )
                    fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
                    fig.update_layout(showlegend=False, margin=dict(t=10, b=30))
                    return fig

            with ui.card(full_screen=True):
                ui.card_header("Avg 1-Year Employment Change by Age Group")
                @render_plotly
                def plot_age():
                    d = (
                        filtered()
                        .drop_nulls("pct_chg_1y")
                        .group_by("age_group")
                        .agg(pl.col("pct_chg_1y").mean())
                        .sort("age_group")
                        .to_pandas()
                    )
                    fig = px.bar(
                        d, x="age_group", y="pct_chg_1y",
                        color="pct_chg_1y",
                        color_continuous_scale="RdYlGn",
                        color_continuous_midpoint=0,
                        template="plotly_white",
                        labels={"age_group": "Age Group",
                                "pct_chg_1y": "Avg 1-Year Change (%)"},
                    )
                    fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.5)
                    fig.update_layout(
                        coloraxis_showscale=False,
                        margin=dict(t=10, b=60),
                        xaxis_tickangle=-30,
                    )
                    return fig

    # ── Time Trends ────────────────────────────────────────────────────────────
    with ui.nav_panel("Time Trends"):

        with ui.card(full_screen=True):
            ui.card_header("AI Exposure Over Time — SSYK1 Major Occupation Groups")
            @render_plotly
            def plot_cap_trend():
                cap_col = AI_CAPS[input.ai_cap()]
                sexes = list(input.sex())
                d = df_full.filter(
                    pl.col("level") == "SSYK1",
                    pl.col("year").is_between(input.year_range()[0], input.year_range()[1]),
                )
                if sexes:
                    d = d.filter(pl.col("sex").is_in(sexes))
                d = (
                    d.group_by("year", "occupation")
                    .agg(pl.col(cap_col).mean().alias("ai_score"))
                    .sort("year")
                    .to_pandas()
                )
                fig = px.line(
                    d, x="year", y="ai_score", color="occupation",
                    markers=True, template="plotly_white",
                    labels={"year": "Year", "ai_score": input.ai_cap(),
                            "occupation": "Major Group"},
                )
                fig.update_xaxes(tickformat="d")
                fig.update_layout(legend_title="", margin=dict(t=10, b=30))
                return fig

        with ui.layout_columns(col_widths=[6, 6]):

            with ui.card(full_screen=True):
                ui.card_header("Employment by Sex Over Time (Stacked Area)")
                @render_plotly
                def plot_area():
                    d = (
                        df_full.filter(
                            pl.col("level") == input.level(),
                            pl.col("year").is_between(input.year_range()[0], input.year_range()[1]),
                        )
                        .group_by("year", "sex")
                        .agg(pl.col("count").sum())
                        .sort("year")
                        .to_pandas()
                    )
                    fig = px.area(
                        d, x="year", y="count", color="sex",
                        color_discrete_map=SEX_COLORS,
                        template="plotly_white",
                        labels={"year": "Year", "count": "Employed Persons", "sex": "Sex"},
                    )
                    fig.update_xaxes(tickformat="d")
                    fig.update_layout(legend_title="", margin=dict(t=10, b=30))
                    return fig

            with ui.card(full_screen=True):
                ui.card_header("GenAI vs All-Apps Exposure Gap Over Time")
                @render_plotly
                def plot_gap():
                    sexes = list(input.sex())
                    d = df_full.filter(
                        pl.col("level") == input.level(),
                        pl.col("year").is_between(input.year_range()[0], input.year_range()[1]),
                    )
                    if sexes:
                        d = d.filter(pl.col("sex").is_in(sexes))
                    d = (
                        d.group_by("year")
                        .agg(
                            pl.col("daioe_genai_avg").mean().alias("GenAI"),
                            pl.col("daioe_allapps_avg").mean().alias("All Apps"),
                        )
                        .sort("year")
                        .to_pandas()
                    )
                    fig = px.line(
                        d.melt("year", var_name="Metric", value_name="Score"),
                        x="year", y="Score", color="Metric",
                        markers=True, template="plotly_white",
                        labels={"year": "Year"},
                    )
                    fig.update_xaxes(tickformat="d")
                    fig.update_layout(legend_title="", margin=dict(t=10, b=30))
                    return fig

    # ── Data Table ─────────────────────────────────────────────────────────────
    with ui.nav_panel("Data"), ui.card(full_screen=True):
        ui.card_header("Snapshot Data Table")
        @render.data_frame
        def data_table():
            cap_label = input.ai_cap()
            d = (
                snapshot()
                .rename({
                    "count":      "Employed",
                    "ai_score":   cap_label,
                    "pct_chg_1y": "Chg 1Y (%)",
                    "pct_chg_3y": "Chg 3Y (%)",
                    "pct_chg_5y": "Chg 5Y (%)",
                })
                .to_pandas()
            )
            return render.DataGrid(d, filters=True, height="600px", width="100%")
