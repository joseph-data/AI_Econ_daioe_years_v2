"""
Aggregate SSYK4 -> SSYK3/2/1 (keeping age/sex/year) and map codes to occupation names.

Inputs
------
- data/processed/ssyk12_combined_cleaned.parquet
- structure_ssyk12.csv  (columns: code, name)

Output
------
- data/processed/ssyk12_aggregated_ssyk4_to_ssyk1.parquet
"""


from dataclasses import dataclass
from pathlib import Path

import polars as pl

YEAR_CHECK = 2022


# -------------------------
# Config
# -------------------------
@dataclass(frozen=True)
class Paths:
    root: Path
    in_file: Path
    map_file: Path
    out_file: Path


def default_paths(root: Path | None = None) -> Paths:
    root = (root or Path.cwd()).resolve()
    data_dir = root / "data"
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    return Paths(
        root=root,
        in_file=processed / "ssyk12_combined_cleaned.parquet",
        map_file=root / "structure_ssyk12.csv",
        out_file=processed / "ssyk12_aggregated_ssyk4_to_ssyk1.parquet",
    )


# -------------------------
# Core functions
# -------------------------
def ensure_inputs(paths: Paths) -> None:
    if not paths.in_file.exists():
        msg = f"Input parquet not found: {paths.in_file}"
        raise FileNotFoundError(msg)
    if not paths.map_file.exists():
        msg = f"Mapping file not found: {paths.map_file}"
        raise FileNotFoundError(msg)


def load_ssyk4(paths: Paths) -> pl.DataFrame:
    df = pl.read_parquet(paths.in_file)

    required_cols = {"code", "age", "sex", "year", "count"}
    missing = required_cols - set(df.columns)
    if missing:
        msg = f"Missing required columns: {sorted(missing)}"
        raise ValueError(msg)

    # Normalize dtypes a bit (safe + helps with slicing/grouping)
    df = df.with_columns(
        pl.col("code").cast(pl.Utf8),
        pl.col("age").cast(pl.Utf8),
        pl.col("sex").cast(pl.Utf8),
        pl.col("year").cast(pl.Int64),
        pl.col("count").cast(pl.Int64),
    )

    return df


def add_ssyk_levels(df: pl.DataFrame) -> pl.LazyFrame:
    """Add SSYK4/3/2/1 code columns and drop 'occupation' if present."""
    return (
        df.lazy()
        .with_columns(
            ssyk4=pl.col("code"),
            ssyk3=pl.col("code").str.slice(0, 3),
            ssyk2=pl.col("code").str.slice(0, 2),
            ssyk1=pl.col("code").str.slice(0, 1),
        )
        .drop([c for c in ["occupation"] if c in df.columns])
    )


def agg_level(lf: pl.LazyFrame, level_col: str, level_name: str) -> pl.LazyFrame:
    return (
        lf.group_by([level_col, "age", "sex", "year"])
        .agg(pl.col("count").sum().alias("count"))
        .with_columns(pl.lit(level_name).alias("level"))
        .rename({level_col: "ssyk_code"})
        .select(["level", "ssyk_code", "age", "sex", "year", "count"])
    )


def aggregate_all_levels(lf: pl.LazyFrame) -> pl.DataFrame:
    lf_ssyk4 = agg_level(lf, "ssyk4", "SSYK4")
    lf_ssyk3 = agg_level(lf, "ssyk3", "SSYK3")
    lf_ssyk2 = agg_level(lf, "ssyk2", "SSYK2")
    lf_ssyk1 = agg_level(lf, "ssyk1", "SSYK1")

    return pl.concat([lf_ssyk4, lf_ssyk3, lf_ssyk2, lf_ssyk1], how="vertical").collect()


def load_name_map(paths: Paths) -> pl.DataFrame:
    return (
        pl.read_csv(
            paths.map_file,
            schema_overrides={"code": pl.Utf8, "name": pl.Utf8},
        )
        .with_columns(
            pl.col("code").cast(pl.Utf8).str.strip_chars(),
            pl.col("name").cast(pl.Utf8),
        )
        .select(["code", "name"])
        .unique(subset=["code"], keep="first")
    )


def map_occupation_names(df_all: pl.DataFrame, df_name_maps: pl.DataFrame) -> pl.DataFrame:
    return (
        df_all.join(df_name_maps, left_on="ssyk_code", right_on="code", how="left")
        .rename({"name": "occupation"})
    )


def diagnostics(df_join: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    diag = df_join.select(
        pl.col("occupation").is_null().sum().alias("unmapped_rows"),
        pl.col("ssyk_code").n_unique().alias("unique_ssyk_codes"),
    )

    unmapped = (
        df_join.filter(pl.col("occupation").is_null())
        .select(["level", "ssyk_code"])
        .unique()
        .sort(["level", "ssyk_code"])
    )
    return diag, unmapped


def write_output(df: pl.DataFrame, paths: Paths) -> None:
    df.write_parquet(paths.out_file)


# -------------------------
# Main
# -------------------------
def main() -> None:
    paths = default_paths()
    print("ROOT:", paths.root)
    print("IN_FILE:", paths.in_file)
    print("MAP_FILE:", paths.map_file)
    print("OUT_FILE:", paths.out_file)

    ensure_inputs(paths)

    df = load_ssyk4(paths)
    print("\nInput schema:", df.schema)

    lf = add_ssyk_levels(df)
    df_all = aggregate_all_levels(lf)

    print("\nRows per level:")
    print(df_all.group_by("level").agg(pl.len().alias("rows")).sort("level"))

    # Optional quick check (kept from your notebook)
    check = df_all.filter(
        (pl.col("age") == "35-39") & (pl.col("year") == YEAR_CHECK) & (pl.col("ssyk_code") == "217"),
    )
    print(f"\nRandom check (age=35-39, year={YEAR_CHECK}, ssyk_code=217):")
    print(check)

    df_name_maps = load_name_map(paths)
    df_join = map_occupation_names(df_all, df_name_maps)

    diag, unmapped = diagnostics(df_join)
    print("\nMapping diagnostics:")
    print(diag)

    if unmapped.height > 0:
        print("\nUnmapped SSYK codes (unique):")
        print(unmapped)

    write_output(df_join, paths)
    print(f"\n✅ Saved: {paths.out_file}")


if __name__ == "__main__":
    main()
