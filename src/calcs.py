import polars as pl


def get_occ_summary(lf: pl.LazyFrame, occupation: str, year: int) -> dict | None:
    """
    Aggregate employment count and percentage changes for one occupation and year.

    Returns a dict with keys: employment, pct_1y, pct_3y, pct_5y, year.
    Returns None if no data matches the filters.
    """
    df = (
        lf.filter(
            (pl.col("occupation") == occupation) & (pl.col("year") == year),
        )
        .select(["count", "pct_chg_1y", "pct_chg_3y", "pct_chg_5y", "year"])
        .collect()
    )

    if df.is_empty():
        return None

    def _mean_or_none(col: str) -> float | None:
        val = df[col].mean()
        return None if val is None else float(val)

    return {
        "employment": df["count"].sum(),
        "pct_1y": _mean_or_none("pct_chg_1y"),
        "pct_3y": _mean_or_none("pct_chg_3y"),
        "pct_5y": _mean_or_none("pct_chg_5y"),
        "year": int(df["year"][0]),
    }


AI_WAVG_COLS = [
    "daioe_genai_wavg",
    "daioe_allapps_wavg",
    "daioe_stratgames_wavg",
    "daioe_videogames_wavg",
    "daioe_imgrec_wavg",
    "daioe_imgcompr_wavg",
    "daioe_imggen_wavg",
    "daioe_readcompr_wavg",
    "daioe_lngmod_wavg",
    "daioe_translat_wavg",
    "daioe_speechrec_wavg",
]

AI_LABELS = {
    "daioe_genai_wavg": "🧠 Generative AI",
    "daioe_allapps_wavg": "📚 All Applications",
    "daioe_stratgames_wavg": "♟️ Strategy Games",
    "daioe_videogames_wavg": "🎮 Video Games",
    "daioe_imgrec_wavg": "🖼️ Image Recognition",
    "daioe_imgcompr_wavg": "🧩 Image Comprehension",
    "daioe_imggen_wavg": "🎨 Image Generation",
    "daioe_readcompr_wavg": "📖 Reading Comprehension",
    "daioe_lngmod_wavg": "✍️ Language Modeling",
    "daioe_translat_wavg": "🌐 Translation",
    "daioe_speechrec_wavg": "🎙️ Speech Recognition",
}


AI_LEVEL_COLS = [c.replace("_wavg", "_Level_Exposure") for c in AI_WAVG_COLS]
AI_PCTL_COLS = [f"pctl_{c}" for c in AI_WAVG_COLS]

EXPOSURE_LABELS = {1: "Very Low", 2: "Low", 3: "Medium", 4: "High", 5: "Very High"}


def get_occ_ai_exposure(
    lf: pl.LazyFrame, occupation: str, year: int,
) -> pl.DataFrame:
    """
    Return mean weighted AI exposure scores, exposure levels, and percentile ranks per sub-domain.

    Returns a long-format DataFrame with columns: domain, score, level, level_label, percentile.
    Used to power the ranked horizontal bar chart in Card 2.
    """
    select_cols = AI_WAVG_COLS + AI_LEVEL_COLS + AI_PCTL_COLS
    df = (
        lf.filter(
            (pl.col("occupation") == occupation) & (pl.col("year") == year),
        )
        .select(select_cols)
        .collect()
    )

    rows = []
    for wavg_col, level_col, pctl_col in zip(AI_WAVG_COLS, AI_LEVEL_COLS, AI_PCTL_COLS, strict=False):
        raw_level = df[level_col].mean()
        level_val = round(raw_level) if raw_level is not None else None
        rows.append({
            "domain": AI_LABELS[wavg_col],
            "score": df[wavg_col].mean(),
            "level": level_val,
            "level_label": EXPOSURE_LABELS.get(level_val, "Unknown") if level_val else "Unknown",
            "percentile": df[pctl_col].mean(),
        })
    return pl.DataFrame(rows).sort("score")


def get_occ_ai_trend(
    lf: pl.LazyFrame, occupation: str, year_range: tuple[int, int],
) -> pl.DataFrame:
    """
    Return yearly mean weighted AI exposure (All Applications) for one occupation over a year range.

    Returns a DataFrame with columns: year, daioe_allapps_wavg.
    Used to power the trend line in Card 2.
    """
    year_min, year_max = year_range
    return (
        lf.filter(
            (pl.col("occupation") == occupation)
            & (pl.col("year") >= year_min)
            & (pl.col("year") <= year_max),
        )
        .group_by("year")
        .agg(pl.col("daioe_allapps_wavg").mean())
        .sort("year")
        .collect()
    )


def get_occ_employment_by_age(
    lf: pl.LazyFrame,
    occupation: str,
    year_range: tuple[int, int],
    age_groups: list[str],
) -> pl.DataFrame:
    """
    Return yearly employment counts per age group for a given occupation and year range.

    Used to power the employment change line chart in Card 3.
    Returns a long-format DataFrame with columns: year, age_group, count.
    """
    year_min, year_max = year_range
    return (
        lf.filter(
            (pl.col("occupation") == occupation)
            & (pl.col("year") >= year_min)
            & (pl.col("year") <= year_max)
            & (pl.col("age_group").is_in(age_groups)),
        )
        .group_by(["year", "age_group"])
        .agg([
            pl.col("count").sum(),
            pl.col("pct_chg_1y").mean(),
        ])
        .sort(["age_group", "year"])
        .collect()
    )
