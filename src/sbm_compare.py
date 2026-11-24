"""Compare SBM fits at every level (notes/graph-and-sbm.md, D25 amendment to G3, G6 and G8).

Reads one main run of ``src/sbm.py`` and the fits it saved, and measures:
- the spread across seeds: each fit against the kept fit of its fit set, at
  each level both have;
- the self-loop comparison: the kept main fit against the kept fit with
  self-loops, at each level both have.
Levels are numbered as in ``blocks.csv``. Scores are NMI and ARI
(``partitions.py``). Before comparing, the kept fits read from the saved
files are checked against the run's ``blocks.csv``.

    python src/sbm_compare.py --run output/runs/sbm/<UTC>

Writes in ``output/runs/sbm_compare/<UTC>/``: ``spread_by_level.csv``,
``self_loops_by_level.csv``, ``run.json``; a row in ``logs/runs.csv``.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, Run, rel, sha256_file, write_rows_csv  # noqa: E402
from partitions import ari, nmi  # noqa: E402

SPREAD_FIELDS = ["fit", "seed", "level", "blocks", "kept_blocks", "nmi_to_kept", "ari_to_kept"]
LOOP_FIELDS = ["level", "main_blocks", "self_loops_blocks", "nmi", "ari"]


def load_levels(path: Path) -> list[np.ndarray]:
    return [np.asarray(b, dtype=np.int64) for b in json.loads(path.read_text())["levels"]]


def blocks_from_csv(path: Path) -> dict[str, list[np.ndarray]]:
    """Levels of each kept fit in ``blocks.csv``, stations in the file's order."""
    by_fit: dict[str, dict[int, list[int]]] = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            by_fit.setdefault(r["fit"], {}).setdefault(int(r["level"]), []).append(int(r["block"]))
    return {fit: [np.asarray(lv[k], dtype=np.int64) for k in sorted(lv)] for fit, lv in by_fit.items()}


def nblocks(b: np.ndarray) -> int:
    return int(b.max()) + 1


def spread_rows(fit: str, levels_by_seed: dict[int, list[np.ndarray]], kept_seed: int) -> list[dict]:
    kept = levels_by_seed[kept_seed]
    rows = []
    for seed, levels in sorted(levels_by_seed.items()):
        for lvl in range(min(len(levels), len(kept))):
            a, b = levels[lvl], kept[lvl]
            rows.append({"fit": fit, "seed": seed, "level": lvl, "blocks": nblocks(a), "kept_blocks": nblocks(b),
                         "nmi_to_kept": repr(nmi(a, b)), "ari_to_kept": repr(ari(a, b))})
    return rows


def loop_rows(main: list[np.ndarray], loops: list[np.ndarray]) -> list[dict]:
    return [{"level": lvl, "main_blocks": nblocks(main[lvl]), "self_loops_blocks": nblocks(loops[lvl]),
             "nmi": repr(nmi(main[lvl], loops[lvl])), "ari": repr(ari(main[lvl], loops[lvl]))}
            for lvl in range(min(len(main), len(loops)))]


def compare(run_dir: Path, saved_dir: Path) -> tuple[list[dict], list[dict], dict]:
    summary = json.loads((run_dir / "run.json").read_text())["summary"]
    if summary.get("mode") != "main":
        raise SystemExit(f"{rel(run_dir)} is not a main SBM run")
    kept = summary["kept"]
    main_model = summary["main_model"]
    loop_fit = f"self_loops_{main_model}"
    in_csv = blocks_from_csv(run_dir / "blocks.csv")
    spread, levels_of = [], {}
    for fit in kept:
        by_seed = {s: load_levels(saved_dir / f"{fit}_seed{s}.json") for s in summary["seeds"]}
        k = by_seed[kept[fit]["seed"]]
        if len(k) != len(in_csv[fit]) or not all(np.array_equal(a, b) for a, b in zip(k, in_csv[fit])):
            raise SystemExit(f"saved fit {fit} seed {kept[fit]['seed']} differs from {rel(run_dir / 'blocks.csv')}")
        spread += spread_rows(fit, by_seed, kept[fit]["seed"])
        levels_of[fit] = k
    loops = loop_rows(levels_of[main_model], levels_of[loop_fit])
    return spread, loops, {"main_model": main_model, "self_loops_fit": loop_fit}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="a main run folder of src/sbm.py")
    args = ap.parse_args(argv)
    run_dir = args.run.resolve()
    summary = json.loads((run_dir / "run.json").read_text())["summary"]
    saved_dir = Path(summary["saved_fits"])
    saved_dir = saved_dir if saved_dir.is_absolute() else ROOT / saved_dir
    run = Run("sbm_compare")
    spread, loops, info = compare(run_dir, saved_dir)
    write_rows_csv(run.dir / "spread_by_level.csv", spread, SPREAD_FIELDS)
    write_rows_csv(run.dir / "self_loops_by_level.csv", loops, LOOP_FIELDS)
    for r in loops:
        print(f"self-loops, level {r['level']}: {r['main_blocks']} vs {r['self_loops_blocks']} blocks, "
              f"NMI {float(r['nmi']):.3f}, ARI {float(r['ari']):.3f}")
    run.finish({**info, "sbm_run": rel(run_dir), "saved_fits": rel(saved_dir),
                "blocks_csv_sha256": sha256_file(run_dir / "blocks.csv")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
