"""
Fetch + clean SCB occupational tables (SSYK) into Parquet.

Outputs
-------
- data/raw/<tab_id>.parquet

Notes
-----
- Uses ThreadPoolExecutor because SCB calls are I/O bound.
- Keeps transformation inside Polars where possible.

"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from pyscbwrapper import SCB

# =========================
# Configuration
# =========================
TableSpec = tuple[str, str, str, str, str]


@dataclass(frozen=True)
class Config:
    root: Path
    out_dir: Path
    tables: dict[str, TableSpec]
    max_workers: int = 8


def default_config() -> Config:
    root = Path.cwd().resolve()
    out_dir = root / "data" / "raw"

    out_dir.mkdir(parents=True, exist_ok=True)

    tables: dict[str, TableSpec] = {
        "ssyk96_05_to_13": ("en", "AM", "AM0208", "AM0208E", "Yreg34"),
        "ssyk12_14_to_18": ("en", "AM", "AM0208", "AM0208E", "YREG51"),
        "ssyk12_19_to_21": ("en", "AM", "AM0208", "AM0208E", "YREG51N"),
        "ssyk12_20_to_24": ("en", "AM", "AM0208", "AM0208E", "YREG51BAS"),
    }

    return Config(root=root, out_dir=out_dir, tables=tables)


# =========================
# Utilities
# =========================
def log(msg: str) -> None:
    print(f"[{datetime.now(tz=UTC).isoformat(timespec='seconds')}] {msg}")


def find_key(var_dict: dict[str, Any], needle: str) -> str:
    """Return the first SCB variable key containing `needle` (case-insensitive)."""
    needle = needle.lower()
    for k in var_dict:
        if needle in k.lower():
            return k
    msg = f"Could not find a variable containing '{needle}'. Keys: {list(var_dict.keys())[:10]} ..."
    raise KeyError(msg)


def build_maps(scb: SCB, vars_info: dict[str, Any], occ_k: str, sex_k: str) -> tuple[dict, dict]:
    """Build code->label maps from query + variables."""
    query = scb.get_query()["query"]

    # Convention from your current query setup:
    # 0: occupation, 1: year, 2: sex, 3: age
    occ_codes = query[0]["selection"]["values"]
    sex_codes = query[2]["selection"]["values"]

    occ_map = dict(zip(occ_codes, vars_info[occ_k], strict=True))
    sex_map = dict(zip(sex_codes, vars_info[sex_k], strict=True))
    return occ_map, sex_map


# =========================
# Core pipeline
# =========================
def fetch_raw(scb: SCB) -> tuple[dict[str, Any], list[dict]]:
    """Fetch variables + data payload from SCB."""
    vars_info = scb.get_variables()
    raw_data = scb.get_data()["data"]
    return vars_info, raw_data


def set_full_query(scb: SCB, vars_info: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Discover variable keys and set SCB query to fetch the full cube."""
    occ_k = find_key(vars_info, "occupation")
    year_k = find_key(vars_info, "year")
    sex_k = find_key(vars_info, "sex")
    age_k = find_key(vars_info, "age")
    obs_k = find_key(vars_info, "observations")

    # pyscbwrapper sometimes needs stripped key
    occ_k_clean = occ_k.strip().replace(" ", "")

    scb.set_query(
        **{
            occ_k_clean: vars_info[occ_k],
            year_k: vars_info[year_k],
            sex_k: vars_info[sex_k],
            age_k: vars_info[age_k],
            obs_k: vars_info[obs_k][0],
        },
    )

    return occ_k, year_k, sex_k, age_k, obs_k


def transform(raw_data: list[dict], occ_map: dict, sex_map: dict) -> pl.DataFrame:
    """Transform SCB payload -> clean Polars DataFrame."""
    df = pl.from_dicts(raw_data)

    df = (
        df.with_columns(
            code=pl.col("key").list.get(0),
            age=pl.col("key").list.get(1),
            sex=pl.col("key").list.get(2),
            year=pl.col("key").list.get(3),
            count=pl.col("values").list.get(0),
        )
        .with_columns(
            occupation=pl.col("code").replace_strict(occ_map, default=pl.col("code")),
            sex=pl.col("sex").replace_strict(sex_map, default=pl.col("sex")),
        )
        .select(["code", "occupation", "age", "sex", "year", "count"])
        # filter before casting
        .filter(
            ~pl.col("code").str.ends_with("0002"),
        )
        .with_columns(
            pl.col("code").cast(pl.Utf8),
            pl.col("occupation").cast(pl.Utf8),
            pl.col("age").cast(pl.Categorical),
            pl.col("sex").cast(pl.Categorical),
            pl.col("year").cast(pl.Int64),
            pl.col("count").cast(pl.Int64),
        )
    )
    return df


def fetch_clean_write(cfg: Config, tab_id: str, spec: TableSpec) -> bool:
    """Full per-table pipeline."""
    try:
        log(f"Processing: {tab_id}")

        scb = SCB(*spec)

        # 1) variables -> set query -> data
        vars_info = scb.get_variables()
        occ_k, _, sex_k, _, _ = set_full_query(scb, vars_info)
        raw_data = scb.get_data()["data"]

        # 2) mapping
        occ_map, sex_map = build_maps(scb, vars_info, occ_k=occ_k, sex_k=sex_k)

        # 3) transform
        df = transform(raw_data, occ_map=occ_map, sex_map=sex_map)

        # 4) write + log
        out_path = cfg.out_dir / f"{tab_id}.parquet"
        df.write_parquet(out_path)
        log(f"Saved: {out_path} ({df.height} rows)")

    except Exception as e:  # noqa: BLE001
        log(f"FAILED: {tab_id} -> {type(e).__name__}: {e}")
        return False
    else:
        return True


# =========================
# Main
# =========================
def main() -> None:
    cfg = default_config()
    start = datetime.now(tz=UTC)

    log(f"ROOT: {cfg.root}")
    log(f"OUT_DIR: {cfg.out_dir}")
    log(f"Tables: {list(cfg.tables.keys())}")

    workers = min(len(cfg.tables), cfg.max_workers)
    results: dict[str, bool] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_clean_write, cfg, tab_id, spec): tab_id for tab_id, spec in cfg.tables.items()}
        for fut in as_completed(futures):
            tab_id = futures[fut]
            results[tab_id] = bool(fut.result())

    duration = datetime.now(tz=UTC) - start
    ok = sum(results.values())
    total = len(results)

    log(f"Done in: {duration}")
    log(f"Success: {ok}/{total}")
    log(f"Summary: {results}")


if __name__ == "__main__":
    main()
