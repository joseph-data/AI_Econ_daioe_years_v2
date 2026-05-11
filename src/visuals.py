import faicons as fa
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from shiny import ui

SCB_SOURCE_MD = (
    "Source: [Swedish Occupational Register, SCB]"
    "(https://www.scb.se/en/finding-statistics/statistics-by-subject-area/"
    "labour-market/labour-force-supply/"
    "the-swedish-occupational-register-with-statistics/)"
)

DAIOE_SOURCE_MD = "Source: [DAIOEs](https://www.ai-econlab.com/ai-exposure-daioe)"

# Brand colours from _brand.yml
_C_BG = "rgba(0,0,0,0)"
_C_GRID = "#E5E5E5"
_C_TEXT = "#1C2826"  # black
_C_TITLE = "#0C0A3E"  # primary / blue

_FONT_BASE = "Nunito Sans"
_FONT_HEAD = "Montserrat"

_BASE_LAYOUT = {
    "paper_bgcolor": _C_BG,
    "plot_bgcolor": _C_BG,
    "font": {"family": _FONT_BASE, "color": _C_TEXT, "size": 13},
    "title_font": {"family": _FONT_HEAD, "color": _C_TITLE, "size": 15},
    "hoverlabel": {"font": {"family": _FONT_BASE, "size": 12}},
    "margin": {"l": 20, "r": 20, "t": 45, "b": 20},
}


def build_value_boxes(summary: dict, occupation: str) -> ui.Tag:
    """
    Build the employment summary value boxes for a given occupation.

    Returns a div containing a heading, four value boxes (employment, 1/3/5-yr
    change), and a markdown source note.
    """

    def _arrow(v):
        return "▼" if v < 0 else "▲"

    def _theme(v):
        return "danger" if v < 0 else "success"

    def _fmt_pct(v):
        return f"{_arrow(v)} {v:.0f}%" if v is not None else "N/A"

    def _fmt_theme(v):
        return _theme(v) if v is not None else "secondary"

    emp = summary["employment"]
    pct1 = summary["pct_1y"]
    pct3 = summary["pct_3y"]
    pct5 = summary["pct_5y"]
    year = summary["year"]

    return ui.div(
        ui.h6(f"National Employment of {occupation}", class_="mt-3 mb-2 fw-semibold"),
        ui.layout_columns(
            ui.value_box(
                title="Employment",
                showcase=fa.icon_svg("users"),
                value=f"{emp:,.0f}",
                theme="primary",
            ),
            ui.value_box(
                title="1-yr change",
                value=_fmt_pct(pct1),
                showcase=fa.icon_svg("arrow-trend-up" if pct1 is None or pct1 >= 0 else "arrow-trend-down"),
                theme=_fmt_theme(pct1),
            ),
            ui.value_box(
                title="3-yr change",
                value=_fmt_pct(pct3),
                showcase=fa.icon_svg("arrow-trend-up" if pct3 is None or pct3 >= 0 else "arrow-trend-down"),
                theme=_fmt_theme(pct3),
            ),
            ui.value_box(
                title="5-yr change",
                value=_fmt_pct(pct5),
                showcase=fa.icon_svg("arrow-trend-up" if pct5 is None or pct5 >= 0 else "arrow-trend-down"),
                theme=_fmt_theme(pct5),
            ),
            col_widths=[3, 3, 3, 3],
        ),
        ui.markdown(f"Data as at **{year}**.\n\n{SCB_SOURCE_MD}"),
    )


def build_age_chart(df: pd.DataFrame, occupation: str) -> go.Figure:
    """
    Build a Plotly line chart of 1-yr employment % change by age group over time.

    Absolute employment count is shown on hover. Returns an empty figure if df is empty.
    """
    if df.empty:
        return go.Figure()

    fig = px.line(
        df,
        x="year",
        y="pct_chg_1y",
        color="age_group",
        markers=True,
        custom_data=["count"],
        labels={
            "year": "Year",
            "pct_chg_1y": "Employment change (%)",
            "age_group": "Age Group",
        },
    )
    fig.update_traces(
        hovertemplate=(
            "<b>%{fullData.name}</b><br>"
            "Year: %{x}<br>"
            "Change: %{y:.1f}%<br>"
            "Employment: %{customdata[0]:,}<extra></extra>"
        ),
    )
    fig.add_hline(y=0, line_color="grey", line_width=1)
    fig.update_layout(
        **_BASE_LAYOUT,
        title={
            "text": f"Annual Employment Change of {occupation} in Sweden",
            "x": 0.01,
            "xanchor": "left",
        },
        legend={"title": None},
        yaxis={"ticksuffix": "%"},
    )
    fig.update_xaxes(gridcolor=_C_GRID, zeroline=False, dtick=1)
    fig.update_yaxes(gridcolor=_C_GRID, zeroline=False)
    return fig


def build_comparison_employment_plot(df: pd.DataFrame) -> go.Figure:
    """Build a line chart comparing employment trends across selected occupations."""
    if df.empty:
        return go.Figure()

    fig = px.line(
        df,
        x="year",
        y="count",
        color="occupation",
        markers=True,
        labels={"count": "Total Employment", "year": "Year"},
    )
    fig.update_layout(
        **_BASE_LAYOUT,
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25, "xanchor": "center", "x": 0.5, "title": None},
    )
    fig.update_xaxes(gridcolor=_C_GRID, zeroline=False, dtick=1)
    fig.update_yaxes(gridcolor=_C_GRID, zeroline=False)
    return fig


def build_comp_radar_plot(df: pd.DataFrame, metrics: dict[str, str]) -> go.Figure:
    """Build a radar chart comparing AI percentile scores across selected occupations."""
    if df.empty:
        return go.Figure()

    categories = list(metrics.values())
    fig = go.Figure()

    for _, row in df.iterrows():
        r_values = [row[f"pctl_{k}_wavg"] for k in metrics]
        r_values_closed = [*r_values, r_values[0]]
        categories_closed = [*categories, categories[0]]

        fig.add_trace(go.Scatterpolar(
            r=r_values_closed,
            theta=categories_closed,
            fill="toself",
            name=row["occupation"],
            hovertemplate="%{theta}: %{r:.1f}%<extra></extra>",
        ))

    fig.update_layout(
        **_BASE_LAYOUT,
        polar={"radialaxis": {"visible": True, "range": [0, 100]}},
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25, "xanchor": "center", "x": 0.5},
    )
    return fig


def build_ai_exposure_bar(df: pd.DataFrame, occupation: str, year: int) -> go.Figure:
    """
    Build a vertical bar chart of AI exposure level per sub-domain.

    X-axis: AI sub-domains with emoji labels.
    Y-axis: exposure level (1=Low, 2=Medium, 3=High).
    Bar colour intensity driven by the weighted average score.
    Hover shows exposure level label, index score, and percentile rank.
    """
    if df.empty:
        return go.Figure()

    fig = go.Figure(
        go.Bar(
            x=df["percentile"],
            y=df["domain"],
            orientation="h",
            marker={
                "color": df["percentile"],
                "colorscale": "Blues",
                "colorbar": {"title": "Percentile Rank"},
                "showscale": True,
                "cmin": 0,
                "cmax": 100,
            },
            customdata=list(
                zip(df["level_label"], df["level"], df["score"], strict=False)
            ),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Percentile Rank: %{x:.0f}<br>"
                "Exposure Level: %{customdata[0]} (%{customdata[1]}/5)<br>"
                "Index Score: %{customdata[2]:.3f}<extra></extra>"
            ),
        ),
    )
    fig.update_layout(
        **_BASE_LAYOUT,
        title={
            "text": f"{occupation} Level of AI Exposure ({year})",
            "x": 0.01,
            "xanchor": "left",
        },
        xaxis={"title": "Percentile Rank", "range": [0, 100]},
        yaxis={"title": None},
    )
    fig.update_xaxes(gridcolor=_C_GRID, zeroline=False)
    fig.update_yaxes(gridcolor=_C_GRID, zeroline=False)
    return fig
