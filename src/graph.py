"""Build the directed weighted origin–destination edge list (brief §4.1, notes/graph-and-sbm.md G1–G3).

w_ij is the number of trips in ``trips_clean`` from station i to station j,
on the merged station ids (R9). Round trips stay in the list as self-loops
(i = j) and are flagged; the SBM stage decides whether to use them (G3).

    python src/graph.py

Reads ``data/interim/trips_clean.parquet``. Writes ``data/interim/edges.csv``
(``source``, ``target``, ``weight``, ``is_self_loop``; one row per pair with
at least one trip, sorted by source then target) and, in
``output/runs/graph/<UTC>/``: ``run.json``; a row in ``logs/runs.csv``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INTERIM, Run, rel, sha256_file, write_csv  # noqa: E402

CLEAN = INTERIM / "trips_clean.parquet"
EDGES = INTERIM / "edges.csv"


def edge_list(trips: pd.DataFrame) -> pd.DataFrame:
    """One row per (start, end) station pair with its number of trips."""
    e = (trips.groupby(["start_station_id", "end_station_id"], sort=False).size()
         .rename("weight").reset_index()
         .rename(columns={"start_station_id": "source", "end_station_id": "target"}))
    e["source"] = e["source"].astype(str)
    e["target"] = e["target"].astype(str)
    e["weight"] = e["weight"].astype("int64")
    e["is_self_loop"] = e["source"] == e["target"]
    return e.sort_values(["source", "target"]).reset_index(drop=True)


def summary(e: pd.DataFrame) -> dict:
    loops = e[e["is_self_loop"]]
    others = e[~e["is_self_loop"]]
    stations = set(e["source"]) | set(e["target"])
    linked = set(others["source"]) | set(others["target"])
    return {
        "stations": len(stations),
        "station_pairs": len(e),
        "station_pairs_without_self_loops": len(others),
        "self_loops": len(loops),
        "trips": int(e["weight"].sum()),
        "trips_on_self_loops": int(loops["weight"].sum()),
        "stations_with_only_self_loops": len(stations - linked),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args(argv)
    run = Run("graph")
    trips = pd.read_parquet(CLEAN, columns=["start_station_id", "end_station_id"])
    e = edge_list(trips)
    out = write_csv(EDGES, e)
    s = summary(e)
    if s["trips"] != len(trips):
        raise SystemExit(f"edge weights sum to {s['trips']}, trips_clean has {len(trips)} rows")
    for k, v in s.items():
        print(f"{k}: {v}")
    run.finish({**s, "input": rel(CLEAN), "input_sha256": sha256_file(CLEAN),
                "edges": rel(out), "edges_sha256": sha256_file(out)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
