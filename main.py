"""
DAIOE Processing Pipeline.

Reads the SCB aggregated parquet already available in data/processed/,
loads the DAIOE exposure index, derives SSYK hierarchy levels, computes
employment-weighted aggregates and percentile ranks, builds 1/3/5-year
employment changes, and writes the final processed parquet.

Run
---
    uv run python main.py
"""

from datetime import UTC, datetime
from pathlib import Path

import polars as pl

# =========================
# Constants
# =========================
DAIOE_SOURCE: str = (
    "https://raw.githubusercontent.com/joseph-data/07_translate_ssyk/main/"
    "03_translated_files/daioe_ssyk2012_translated.csv"
)
SCB_SOURCE: str = (
    "https://raw.githubusercontent.com/joseph-data/AI_Econ_daioe_years/daioe_pull/"
    "data/processed/ssyk12_aggregated_ssyk4_to_ssyk1.parquet"
)
SSYK12_MIN_YEAR: int = 2014
SSYK4_CODE_LEN: int = 4
QUINTILE_BOUNDS: tuple[int, int, int, int] = (20, 40, 60, 80)

AGE_MAP: dict[str, str] = {
    "16-24": "Early Career 1 (16-24)",
    "25-29": "Early Career 2 (25-29)",
    "30-34": "Developing (30-34)",
    "35-39": "Mid-Career 1 (35-39)",
    "40-44": "Mid-Career 1 (40-44)",
    "45-49": "Mid-Career 2 (45-49)",
    "50-54": "Senior (50+)",
    "55-59": "Senior (50+)",
    "60-64": "Senior (50+)",
    "065-69": "Senior (50+)",
}


# =========================
# Logging
# =========================
def log(msg: str) -> None:
    print(f"[{datetime.now(tz=UTC).isoformat(timespec='seconds')}] {msg}")


# =========================
# DAIOE Processing
# =========================
def load_sources(
    daioe_url: str, scb_url: str,
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """
    Load the DAIOE exposure CSV and the SCB aggregated parquet as LazyFrames.

    Parameters
    ----------
    daioe_url : str
        URL of the translated DAIOE SSYK2012 CSV file.
    scb_url : str
        URL of the aggregated SCB parquet on the daioe_pull branch.

    Returns
    -------
    tuple[pl.LazyFrame, pl.LazyFrame]
        ``(daioe_lf, scb_lf)`` — both as lazy frames for deferred execution.

    """
    return pl.scan_csv(daioe_url), pl.scan_parquet(scb_url)


def remove_military(
    daioe_lf: pl.LazyFrame, scb_lf: pl.LazyFrame,
) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    """
    Remove military occupation rows (codes starting with "0") from both sources.

    Military occupations carry null DAIOE exposure values and are excluded from
    all analyses. The filter is applied lazily and does not trigger execution.

    Parameters
    ----------
    daioe_lf : pl.LazyFrame
        DAIOE source frame with a ``ssyk2012_4`` column.
    scb_lf : pl.LazyFrame
        SCB source frame with a ``ssyk_code`` column.

    Returns
    -------
    tuple[pl.LazyFrame, pl.LazyFrame]
        Filtered ``(daioe_lf, scb_lf)``.

    """
    daioe_lf = daioe_lf.filter(pl.col("ssyk2012_4").str.starts_with("0").not_())
    scb_lf = scb_lf.filter(pl.col("ssyk_code").str.starts_with("0").not_())
    return daioe_lf, scb_lf


def derive_ssyk_levels(daioe_lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Derive SSYK1-4 prefix columns from the 4-digit SSYK code and filter to SSYK12 era.

    Slices the ``ssyk2012_4`` column at 1, 2, 3, and 4 characters to produce
    ``code_1`` through ``code_4``, then drops the original ``ssyk2012_*`` columns
    and filters to years from ``SSYK12_MIN_YEAR`` onward.

    Parameters
    ----------
    daioe_lf : pl.LazyFrame
        DAIOE source frame containing ``ssyk2012_4`` and ``year``.

    Returns
    -------
    pl.LazyFrame
        Frame with ``code_1``-``code_4`` columns, filtered to the SSYK12 era.

    """
    return (
        daioe_lf
        .with_columns(
            pl.col("ssyk2012_4").str.slice(0, 1).alias("code_1"),
            pl.col("ssyk2012_4").str.slice(0, 2).alias("code_2"),
            pl.col("ssyk2012_4").str.slice(0, 3).alias("code_3"),
            pl.col("ssyk2012_4").str.slice(0, 4).alias("code_4"),
        )
        .drop(pl.col("^ssyk2012.*$"))
        .filter(pl.col("year") >= SSYK12_MIN_YEAR)
    )


def extend_daioe_years(
    daioe_lf: pl.LazyFrame, scb_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Extend DAIOE forward to match the latest SCB year by repeating the last year's values.

    SCB is updated annually and typically has more recent years than DAIOE.
    Rather than dropping those years from the final dataset, we carry the last
    observed DAIOE values forward so the SCB employment counts can still be joined.

    Parameters
    ----------
    daioe_lf : pl.LazyFrame
        DAIOE frame already filtered to the SSYK12 era.
    scb_lf : pl.LazyFrame
        SCB frame used only to determine the latest available year.

    Returns
    -------
    pl.LazyFrame
        DAIOE frame extended through the SCB max year, if needed.

    """
    daioe_max = daioe_lf.select(pl.max("year")).collect().item()
    scb_max = scb_lf.select(pl.max("year")).collect().item()
    missing = list(range(daioe_max + 1, scb_max + 1))

    if not missing:
        return daioe_lf

    log(f"Extend DAIOE: carrying {daioe_max} values forward to cover {missing}")
    extension = (
        daioe_lf
        .filter(pl.col("year") == daioe_max)
        .drop("year")
        .join(pl.LazyFrame({"year": missing}), how="cross")
        .select(daioe_lf.collect_schema().names())
    )
    return pl.concat([daioe_lf, extension], how="vertical")


def build_scb_ssyk4(scb_lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Aggregate SCB employment counts to the year x SSYK4 level.

    Filters to rows where ``ssyk_code`` is exactly 4 characters, then sums
    ``count`` across age and sex within each (year, ssyk_code) group.

    Parameters
    ----------
    scb_lf : pl.LazyFrame
        Full SCB frame containing ``level``, ``ssyk_code``, ``year``, and ``count``.

    Returns
    -------
    pl.LazyFrame
        Frame with columns ``year``, ``ssyk_code``, ``total_count``.

    """
    return (
        scb_lf
        .filter(pl.col("ssyk_code").str.len_chars() == SSYK4_CODE_LEN)
        .group_by(["year", "ssyk_code"])
        .agg(pl.col("count").sum().alias("total_count"))
    )


def merge_daioe_scb(
    daioe_lf: pl.LazyFrame, scb_lf_level4: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Join DAIOE exposure scores with SCB SSYK4 employment totals.

    Left-joins on (year, code_4 = ssyk_code) so all DAIOE rows are retained.
    Rows without a matching SCB count will have null ``total_count``.

    Parameters
    ----------
    daioe_lf : pl.LazyFrame
        DAIOE frame with ``code_4`` and ``year`` columns.
    scb_lf_level4 : pl.LazyFrame
        SCB SSYK4 frame with ``ssyk_code``, ``year``, and ``total_count``.

    Returns
    -------
    pl.LazyFrame
        Joined frame with DAIOE metrics and SCB employment weights.

    """
    return daioe_lf.join(
        scb_lf_level4,
        left_on=["year", "code_4"],
        right_on=["year", "ssyk_code"],
        how="left",
    )


def aggregate_daioe_level(  # noqa: PLR0913
    lf: pl.LazyFrame,
    code_col: str,
    level_label: str,
    *,
    weight_col: str = "total_count",
    prefix: str = "daioe_",
    add_percentiles: bool = True,
    pct_scale: int = 100,
    descending: bool = False,
) -> pl.LazyFrame:
    """
    Aggregate DAIOE exposure scores to one SSYK level with optional within-year percentile ranks.

    For each (year, ssyk_code) group, computes both a simple mean and an
    employment-weighted mean for every DAIOE metric column. When
    ``add_percentiles=True``, appends within-year percentile ranks (0-100)
    for every avg and wavg column.

    Parameters
    ----------
    lf : pl.LazyFrame
        Input frame containing DAIOE metric columns, a weight column, and ``year``.
    code_col : str
        Column to group by as the SSYK code (e.g. ``"code_4"``).
    level_label : str
        Value written to the ``level`` column (e.g. ``"SSYK4"``).
    weight_col : str
        Column used as the employment weight. Defaults to ``"total_count"``.
    prefix : str
        Column name prefix used to identify DAIOE metric columns.
    add_percentiles : bool
        Whether to append within-year percentile rank columns.
    pct_scale : int
        Scale factor for percentile output (100 -> 0-100 range).
    descending : bool
        If True, higher raw values receive lower percentile ranks.

    Returns
    -------
    pl.LazyFrame
        Aggregated frame with ``level``, ``ssyk_code``, ``year``, ``weight_sum``,
        ``*_avg``, ``*_wavg``, and optionally ``pctl_*`` columns.

    """
    daioe_cols = [c for c in lf.collect_schema().names() if c.startswith(prefix)]
    w = pl.col(weight_col)

    out = (
        lf
        .group_by(["year", code_col])
        .agg(
            w.sum().alias("weight_sum"),
            pl.col(daioe_cols).mean().name.suffix("_avg"),
            ((pl.col(daioe_cols) * w).sum() / w.sum()).name.suffix("_wavg"),
        )
        .with_columns(pl.lit(level_label).alias("level"))
        .rename({code_col: "ssyk_code"})
    )

    if not add_percentiles:
        return out

    group_keys = ["year", "level"]
    rank_expr = (
        pl.col(f"^{prefix}.*_(avg|wavg)$")
        .rank(method="average", descending=descending)
        .over(group_keys)
    )
    n_expr = pl.len().over(group_keys)

    return out.with_columns(
        (
            pl.when(n_expr > 1)
            .then((rank_expr - 1) / (n_expr - 1))
            .otherwise(0.0)
            * pct_scale
        ).name.prefix("pctl_"),
    )


def build_all_levels(daioe_scb_years: pl.LazyFrame) -> pl.LazyFrame:
    """
    Aggregate DAIOE + SCB data across all four SSYK levels and stack vertically.

    Calls ``aggregate_daioe_level`` for SSYK4/3/2/1 and concatenates the
    results into a single long-format frame sorted by level, year, and code.

    Parameters
    ----------
    daioe_scb_years : pl.LazyFrame
        Joined DAIOE + SCB SSYK4 frame containing ``code_1``-``code_4``.

    Returns
    -------
    pl.LazyFrame
        Long-format frame with a ``level`` column covering all four SSYK levels.

    """
    levels = {
        "code_4": "SSYK4",
        "code_3": "SSYK3",
        "code_2": "SSYK2",
        "code_1": "SSYK1",
    }
    return (
        pl.concat(
            [aggregate_daioe_level(daioe_scb_years, col, label) for col, label in levels.items()],
            how="diagonal",
        )
        .sort(["level", "year", "ssyk_code"])
    )


def add_exposure_levels(daioe_all_levels: pl.LazyFrame) -> pl.LazyFrame:
    """
    Convert weighted percentile ranks (0-100) to 1-5 Level Exposure bins.

    Uses ``QUINTILE_BOUNDS = (20, 40, 60, 80)`` to assign each ``pctl_*_wavg``
    column to a discrete 1-5 bin:

        1 = ≤20th percentile (lowest exposure)
        2 = >20 and ≤40th
        3 = >40 and ≤60th
        4 = >60 and ≤80th
        5 = >80th percentile (highest exposure)

    Null percentile values produce null exposure levels.

    Parameters
    ----------
    daioe_all_levels : pl.LazyFrame
        Frame produced by ``build_all_levels`` containing ``pctl_daioe_*_wavg`` columns.

    Returns
    -------
    pl.LazyFrame
        Input frame with additional ``daioe_*_Level_Exposure`` Int8 columns appended.

    """
    pct_cols = [
        c for c in daioe_all_levels.collect_schema().names()
        if c.startswith("pctl_daioe_") and c.endswith("_wavg")
    ]
    _q1, _q2, _q3, _q4 = QUINTILE_BOUNDS

    exposure_exprs = []
    for col_name in pct_cols:
        metric = col_name[len("pctl_daioe_"):-len("_wavg")]
        out_col = f"daioe_{metric}_Level_Exposure"
        p = pl.col(col_name)
        exposure_exprs.append(
            pl.when(p.is_null()).then(None)
            .when(p <= _q1).then(1)
            .when(p <= _q2).then(2)
            .when(p <= _q3).then(3)
            .when(p <= _q4).then(4)
            .otherwise(5)
            .cast(pl.Int8)
            .alias(out_col),
        )
    return daioe_all_levels.with_columns(exposure_exprs)


def add_age_groups(scb_lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Map raw SCB age bands to career-stage labels and append as ``age_group``.

    Parameters
    ----------
    scb_lf : pl.LazyFrame
        SCB frame containing an ``age`` column with raw band strings (e.g. ``"25-29"``).

    Returns
    -------
    pl.LazyFrame
        Input frame with an additional ``age_group`` string column.

    """
    return scb_lf.with_columns(pl.col("age").replace(AGE_MAP).alias("age_group"))


def build_final_merge(
    scb_lf: pl.LazyFrame, daioe_all_levels: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Join DAIOE aggregates onto the full SCB base table.

    Left-joins on (year, ssyk_code, level) so every SCB row is retained.
    Rows for SSYK codes not present in the DAIOE data will have null exposure columns.

    Parameters
    ----------
    scb_lf : pl.LazyFrame
        Full SCB frame (with age_group already added).
    daioe_all_levels : pl.LazyFrame
        DAIOE aggregates covering all four SSYK levels.

    Returns
    -------
    pl.LazyFrame
        Full merged frame with SCB counts and DAIOE exposure metrics.

    """
    return scb_lf.join(daioe_all_levels, on=["year", "ssyk_code", "level"], how="left")


def compute_changes(final_lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Compute 1, 3, and 5-year absolute and percent employment changes.

    Groups by (level, ssyk_code, age, sex) and uses window shifts over the
    sorted year series to derive changes relative to prior years.

    Zero prior-year counts are replaced with null before dividing to avoid
    ``inf`` in the percent change columns — a group going from 0 → N has no
    meaningful percentage baseline, so null is more honest than infinity, which
    would otherwise propagate silently into downstream aggregations and plots.

    Parameters
    ----------
    final_lf : pl.LazyFrame
        The fully merged SCB + DAIOE frame containing ``count``, ``level``,
        ``ssyk_code``, ``age``, ``sex``, and ``year``.

    Returns
    -------
    pl.LazyFrame
        Frame keyed by (level, ssyk_code, age, sex, year) with columns
        ``chg_1y``, ``chg_3y``, ``chg_5y``, ``pct_chg_1y``, ``pct_chg_3y``,
        ``pct_chg_5y``.

    """
    keys = ["level", "ssyk_code", "age", "sex"]
    return (
        final_lf
        .group_by([*keys, "year"])
        .agg(pl.col("count").sum().alias("emp_count"))
        .sort([*keys, "year"])
        .with_columns(
            # Guard: replace zero prior-year counts with null before dividing.
            pl.col("emp_count").shift(1).over(keys).replace(0, None).alias("_prev1"),
            pl.col("emp_count").shift(3).over(keys).replace(0, None).alias("_prev3"),
            pl.col("emp_count").shift(5).over(keys).replace(0, None).alias("_prev5"),
        )
        .with_columns(
            (pl.col("emp_count") - pl.col("_prev1")).alias("chg_1y"),
            (pl.col("emp_count") - pl.col("_prev3")).alias("chg_3y"),
            (pl.col("emp_count") - pl.col("_prev5")).alias("chg_5y"),
            ((pl.col("emp_count") / pl.col("_prev1") - 1) * 100).alias("pct_chg_1y"),
            ((pl.col("emp_count") / pl.col("_prev3") - 1) * 100).alias("pct_chg_3y"),
            ((pl.col("emp_count") / pl.col("_prev5") - 1) * 100).alias("pct_chg_5y"),
        )
        .drop("emp_count", "_prev1", "_prev3", "_prev5")
    )


def build_processed(
    final_lf: pl.LazyFrame, changes_lf: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Join change metrics onto the full dataset and bring key columns to the front.

    Performs a left join so all original rows are preserved regardless of
    whether a change could be computed (e.g. first 1/3/5 years will be null).
    Columns are reordered so identity and analytical columns appear first,
    followed by all remaining DAIOE metric columns.

    Parameters
    ----------
    final_lf : pl.LazyFrame
        The fully merged SCB + DAIOE frame.
    changes_lf : pl.LazyFrame
        Employment change frame produced by ``compute_changes``.

    Returns
    -------
    pl.LazyFrame
        Final processed frame sorted descending by (year, level, ssyk_code, age, sex).

    """
    join_cols = ["year", "level", "ssyk_code", "age", "sex"]
    processed = final_lf.join(changes_lf, on=join_cols, how="left")

    first_cols = [
        "year", "level", "ssyk_code", "occupation",
        "sex", "age", "age_group",
        "count", "weight_sum",
        "chg_1y", "chg_3y", "chg_5y",
        "pct_chg_1y", "pct_chg_3y", "pct_chg_5y",
    ]
    schema_cols = list(processed.collect_schema())
    other_cols = [c for c in schema_cols if c not in first_cols]

    return (
        processed
        .select(first_cols + other_cols)
        .sort(join_cols, descending=True, nulls_last=True)
    )


# =========================
# Main
# =========================
def main() -> None:
    start = datetime.now(tz=UTC)
    out_path = Path.cwd().resolve() / "data" / "daioe_scb_years_processed.parquet"

    log("=== DAIOE Processing Pipeline ===")

    daioe_lf, scb_lf = load_sources(DAIOE_SOURCE, SCB_SOURCE)
    log("Sources loaded.")

    daioe_lf, scb_lf = remove_military(daioe_lf, scb_lf)

    daioe_lf = derive_ssyk_levels(daioe_lf)
    daioe_lf = extend_daioe_years(daioe_lf, scb_lf)
    log("DAIOE prepared.")

    scb_lf_level4 = build_scb_ssyk4(scb_lf)
    daioe_scb_years = merge_daioe_scb(daioe_lf, scb_lf_level4)

    daioe_all_levels = build_all_levels(daioe_scb_years)
    daioe_all_levels = add_exposure_levels(daioe_all_levels)
    log("DAIOE aggregated across all SSYK levels.")

    scb_lf = add_age_groups(scb_lf)
    final_lf = build_final_merge(scb_lf, daioe_all_levels)

    changes_lf = compute_changes(final_lf)
    processed_lf = build_processed(final_lf, changes_lf)
    log("Changes computed and columns ordered.")

    processed_lf.sink_parquet(out_path)
    log(f"Saved: {out_path}")

    duration = datetime.now(tz=UTC) - start
    log(f"Pipeline complete in {duration}")


if __name__ == "__main__":
    main()
