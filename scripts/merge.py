"""
Combine multiple SSYK12 parquet extracts into one cleaned dataset.

Logic
-----
- Read all data/raw/ssyk12*.parquet (newest first)
- Add provenance: source_file + source_rank (0 = newest)
- Detect duplicates and count conflicts by identity columns
- Resolve duplicates: keep newest row per identity (source_rank lowest)
- Drop provenance columns and write data/processed/ssyk12_combined_cleaned.parquet
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

# =========================
# Config
# =========================
ID_CANDIDATES = ["code", "occupation", "age", "year", "sex"]
LOG_PREVIEW_LIMIT = 10
PROVENANCE_COLS = ["source_file", "source_rank"]
REQUIRED_COLS = {"count"}  # identity cols are discovered from candidates


@dataclass(frozen=True)
class Config:
    root: Path
    raw_dir: Path
    out_dir: Path
    out_file: Path


def default_config() -> Config:
    root = Path.cwd().resolve()
    raw_dir = root / "data" / "raw"
    out_dir = root / "data" / "processed"

    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        root=root,
        raw_dir=raw_dir,
        out_dir=out_dir,
        out_file=out_dir / "ssyk12_combined_cleaned.parquet",
    )


# =========================
# Logging
# =========================
def log(msg: str) -> None:
    print(f"[{datetime.now(tz=UTC).isoformat(timespec='seconds')}] {msg}")


# =========================
# Helpers
# =========================
def get_id_cols(columns: list[str]) -> list[str]:
    return [c for c in ID_CANDIDATES if c in columns]


def list_files_newest_first(raw_dir: Path) -> list[Path]:
    # Uses filename sorting (works well if filenames embed dates / year ranges).
    # If you want filesystem modified-time instead, replace sorting key with p.stat().st_mtime.
    return sorted(raw_dir.glob("ssyk12*.parquet"), reverse=True)


def lazy_union(files: list[Path]) -> pl.LazyFrame:
    return pl.concat(
        [
            pl.scan_parquet(p).with_columns(
                pl.lit(p.name).alias("source_file"),
                pl.lit(rank).cast(pl.Int64).alias("source_rank"),  # rank 0 = newest
            )
            for rank, p in enumerate(files)
        ],
        how="vertical",
    )


def lf_rowcount(lf: pl.LazyFrame) -> int:
    return lf.select(pl.len()).collect().item()


# =========================
# Pipeline
# =========================
def main() -> None:
    cfg = default_config()

    files = list_files_newest_first(cfg.raw_dir)
    log(f"[1] Files found: {len(files)}")
    if not files:
        log("[1] No files found -> exiting.")
        return

    log("[1] Files (newest first):")
    for i, p in enumerate(files[:LOG_PREVIEW_LIMIT]):
        log(f"     {i:02d}: {p.name}")
    if len(files) > LOG_PREVIEW_LIMIT:
        log(f"     ... +{len(files) - LOG_PREVIEW_LIMIT} more")

    # Get schema/columns cheaply from first file
    first_cols = pl.read_parquet(files[0], n_rows=1).columns
    id_cols = get_id_cols(first_cols)
    log(f"[2] Identity columns: {id_cols}")
    if not id_cols:
        log("[2] Missing identity columns -> exiting.")
        return

    missing_required = REQUIRED_COLS - set(first_cols)
    if missing_required:
        log(f"[2] Missing required columns: {sorted(missing_required)} -> exiting.")
        return

    combined_lf = lazy_union(files)
    combined_rows = lf_rowcount(combined_lf)
    log(f"[1] Combined rows (lazy count): {combined_rows}")
    log(f"[1] Columns (from first file): {first_cols}")

    # ---- Duplicate stats
    dup_rows = (
        combined_lf
        .with_columns(pl.len().over(id_cols).alias("_n"))
        .filter(pl.col("_n") > 1)
        .select(pl.len())
        .collect()
        .item()
    )

    dup_groups = (
        combined_lf
        .group_by(id_cols)
        .agg(pl.len().alias("n"))
        .filter(pl.col("n") > 1)
        .select(pl.len())
        .collect()
        .item()
    )

    log(f"[3] Duplicate rows flagged: {dup_rows}")
    log(f"[3] Duplicate identity groups: {dup_groups}")

    # ---- Conflict groups (same identity, different counts)
    conflict_groups = (
        combined_lf
        .group_by(id_cols)
        .agg(pl.col("count").n_unique().alias("n_unique_count"))
        .filter(pl.col("n_unique_count") > 1)
        .select(pl.len())
        .collect()
        .item()
    )

    log(f"[4] Conflicting count groups: {conflict_groups}")

    # ---- Resolve newest wins (rank 0 = newest)
    df_resolved = (
        combined_lf
        .sort("source_rank")                    # 0 first
        .unique(subset=id_cols, keep="first")   # keep newest
        .collect()
    )

    log(f"[5] Final rows after keep-newest: {df_resolved.height}")
    log(f"[5] Conflicts resolved by newest: {conflict_groups}")

    # ---- Drop provenance cols
    cols_to_drop = [c for c in PROVENANCE_COLS if c in df_resolved.columns]
    df_final = df_resolved.drop(cols_to_drop) if cols_to_drop else df_resolved

    df_final.write_parquet(cfg.out_file)
    log(f"[6] Saved cleaned dataset: {cfg.out_file}")

    # ---- Sanity checks
    if "year" in df_final.columns and not df_final.is_empty():
        year_min = df_final.select(pl.col("year").min()).item()
        year_max = df_final.select(pl.col("year").max()).item()
        log(f"[S] Year range: {year_min} - {year_max}")

        by_year = df_final.group_by("year").agg(pl.len().alias("rows")).sort("year")
        log("[S] Rows per year:")
        for y, n in by_year.iter_rows():
            log(f"[S]   Year {y}: {n} rows")

    log("[S] Final schema:")
    for col, dtype in df_final.schema.items():
        log(f"[S]   {col}: {dtype}")


if __name__ == "__main__":
    main()
