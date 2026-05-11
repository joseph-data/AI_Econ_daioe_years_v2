import importlib.util
import io
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import polars as pl
from great_tables import GT
from shiny import ui

# ---------------------------------------------------
# Mardown Files
# ------------

BASE_DIR = Path(__file__).resolve().parent.parent

INTRO_MD = (BASE_DIR / "md_files" / "intro.md").read_text(encoding="utf-8")


# ---------------------------------------------------
# Data Preliminaries
# ---------------------------------------------------

DATA_PATH = BASE_DIR / "data" / "daioe_scb_years_processed.parquet"

lf = pl.scan_parquet(DATA_PATH)

lf.collect_schema()


# ---------------------------------------------------
# Defining Input Values
# ---------------------------------------------------

# 1. SSYK12 Levels

LEVELS = lf.select(pl.col("level").unique().sort()).collect().to_series().to_list()


def build_choices_by_level(
    lf: pl.LazyFrame,
    levels: list[str],
) -> dict[str, dict[str, str]]:
    out = {}
    for lvl in levels:
        occs = (
            lf.filter(pl.col("level") == lvl)
            .select(pl.col("occupation").unique().sort())
            .collect()
            .to_series()
            .to_list()
        )
        out[lvl] = {o: o for o in occs}
    return out


# 2. Men and Women

SEXES = lf.select(pl.col("sex").unique().sort()).collect().to_series().to_list()

# 3. Age groupings

AGE_ORDER = [
    "Early Career 1 (16-24)",
    "Early Career 2 (25-29)",
    "Developing (30-34)",
    "Mid-Career 1 (35-39)",
    "Mid-Career 1 (40-44)",
    "Mid-Career 2 (45-49)",
    "Senior (50+)",
]

present = lf.select(pl.col("age_group").unique()).collect().to_series().to_list()

AGES = [x for x in AGE_ORDER if x in present]


YEARS = lf.select(pl.col("year").unique().sort()).collect().to_series().to_list()

# 4. Years from the dataset

YEAR_MIN, YEAR_MAX = min(YEARS), max(YEARS)

# 5. AI Sub-Indexes

METRICS: dict[str, str] = {
    "daioe_genai": "🧠 Generative AI",
    "daioe_allapps": "📚 All Applications",
    "daioe_stratgames": "♟️ Strategy Games",
    "daioe_videogames": "🎮 Video Games (Real-Time)",
    "daioe_imgrec": "🖼️🔎 Image Recognition",
    "daioe_imgcompr": "🧩🖼️ Image Comprehension",
    "daioe_imggen": "🖌️🖼️ Image Generation",
    "daioe_readcompr": "📖 Reading Comprehension",
    "daioe_lngmod": "✍️🤖 Language Modeling",
    "daioe_translat": "🌐🔤 Translation",
    "daioe_speechrec": "🗣️🎙️ Speech Recognition",
}


first_cols = [
    "level",
    "ssyk_code",
    "occupation",
    "year",
    "sex",
    "age",
    "age_group",
    "count",
    "weight_sum",
    "chg_1y",
    "chg_3y",
    "chg_5y",
    "pct_chg_1y",
    "pct_chg_3y",
    "pct_chg_5y",
]


# ---------------------------------------------------
# Shared UI Helpers
# ---------------------------------------------------
def apply_plot_style(fig: go.Figure, brand: dict[str, str]) -> go.Figure:
    """Apply a consistent visual style to Plotly charts."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Nunito Sans", "color": brand["text"]},
        hoverlabel={"bgcolor": "white", "font_size": 12},
        margin={"l": 20, "r": 20, "t": 40, "b": 20},
    )
    fig.update_xaxes(gridcolor="#E5E5E5", zeroline=False)
    fig.update_yaxes(gridcolor="#E5E5E5", zeroline=False)
    return fig


def empty_figure(message: str, brand: dict[str, str]) -> go.Figure:
    """Create a styled empty Plotly figure with a centered message."""
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font_size=16)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_plot_style(fig, brand)


# ---------------------------------------------------
# Shared Table/Label Helpers
# ---------------------------------------------------
def metric_display_name(metric_key: str, metrics: dict[str, str]) -> str:
    """Return a clean human-readable metric label without leading icons."""
    label = metrics.get(metric_key, metric_key.replace("_", " ").title())
    return re.sub(r"^[^A-Za-z0-9]+\s*", "", label).strip()


def readable_column_name(col: str, metrics: dict[str, str]) -> str:
    """Convert raw dataset column names into readable table headers."""
    exact = {
        "ssyk_code": "SSYK Code",
        "age_group": "Age Group",
        "count": "Employees",
        "year": "Year",
        "sex": "Sex",
        "level": "SSYK Level",
        "occupation": "Occupation",
        "chg_1y": "1-year Change",
        "chg_3y": "3-year Change",
        "chg_5y": "5-year Change",
    }
    if col in exact:
        return exact[col]

    col_l = col.lower()
    if col_l.startswith("pctl_") and col_l.endswith("_wavg"):
        metric_key = col[5:-5]
        return f"{metric_display_name(metric_key, metrics)} Percentile (Weighted Avg)"
    if col_l.endswith("_wavg"):
        metric_key = col[:-5]
        return f"{metric_display_name(metric_key, metrics)} (Weighted Avg)"
    if col_l.endswith("_avg"):
        metric_key = col[:-4]
        return f"{metric_display_name(metric_key, metrics)} (Average)"
    if col_l.endswith("_level_exposure"):
        metric_key = col[: -len("_level_exposure")]
        return f"{metric_display_name(metric_key, metrics)} Exposure Level"

    fallback = col.replace("_", " ").title()
    return (
        fallback.replace("Ssyk", "SSYK").replace("Ai", "AI").replace("Daioe", "DAIOE")
    )


def as_great_table_html(df, metrics: dict[str, str]) -> ui.TagChild:
    """Render a pandas DataFrame as Great Tables HTML with readable headers."""
    if df.empty:
        return ui.p("No data available for the selected filters.")

    df_display = df.rename(
        columns={c: readable_column_name(c, metrics) for c in df.columns},
    )

    float_cols = [
        c
        for c in df_display.columns
        if c != "Year" and pd.api.types.is_float_dtype(df_display[c])
    ]

    gt = (
        GT(df_display)
        .opt_row_striping()
        .tab_options(table_font_names=["Nunito Sans", "Arial", "sans-serif"])
        .opt_stylize(style=2, color="blue")
    )

    if float_cols:
        gt = gt.fmt_number(columns=float_cols, decimals=2)

    return ui.HTML(gt.as_raw_html())


# ---------------------------------------------------
# Shared Download Helpers
# ---------------------------------------------------
def download_extension(fmt: str) -> str:
    """Map selected download format to its file extension."""
    return {"csv": "csv", "parquet": "parquet", "excel": "xlsx"}.get(fmt, "csv")


def download_media_type(fmt: str) -> str:
    """Return browser media type for each supported download format."""
    if fmt == "parquet":
        return "application/octet-stream"
    if fmt == "excel":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return "text/csv"


def export_filtered_data(df, fmt: str) -> str | bytes:
    """Export a pandas DataFrame to csv/parquet/excel payload for Shiny download."""
    if fmt == "parquet":
        return df.to_parquet(index=False)

    if fmt == "excel":
        engine = None
        if importlib.util.find_spec("openpyxl") is not None:
            engine = "openpyxl"
        elif importlib.util.find_spec("xlsxwriter") is not None:
            engine = "xlsxwriter"
        else:
            raise RuntimeError("Excel export requires openpyxl or xlsxwriter.")

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine=engine)
        return buffer.getvalue()

    return df.to_csv(index=False)
