import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import sbm_compare  # noqa: E402

STATIONS = ["001", "002", "003", "004"]
FITS = {  # fit -> seed -> levels
    "standard": {42: [[0, 1, 2, 2], [0, 0, 1, 1]], 43: [[0, 1, 1, 2], [0, 0, 0, 1]]},
    "degree_corrected": {42: [[0, 0, 1, 2], [0, 0, 1, 1]], 43: [[0, 1, 2, 3]]},
    "self_loops_standard": {42: [[0, 1, 2, 2], [0, 0, 1, 1]], 43: [[0, 0, 1, 2], [0, 0, 0, 1]]},
}
KEPT = {"standard": 42, "degree_corrected": 42, "self_loops_standard": 43}


def make_run(tmp_path, blocks_override=None):
    run, saved = tmp_path / "run", tmp_path / "saved"
    run.mkdir(), saved.mkdir()
    for fit, by_seed in FITS.items():
        for seed, levels in by_seed.items():
            (saved / f"{fit}_seed{seed}.json").write_text(json.dumps({"seed": seed, "levels": levels}))
    lines = ["fit,station_id,level,block"]
    for fit, seed in KEPT.items():
        levels = (blocks_override or {}).get(fit, FITS[fit][seed])
        lines += [f"{fit},{s},{lvl},{b}" for lvl, bs in enumerate(levels) for s, b in zip(STATIONS, bs)]
    (run / "blocks.csv").write_text("\n".join(lines) + "\n")
    summary = {"mode": "main", "main_model": "standard", "seeds": [42, 43],
               "kept": {f: {"seed": s} for f, s in KEPT.items()}, "saved_fits": str(saved)}
    (run / "run.json").write_text(json.dumps({"summary": summary}))
    return run, saved


def test_compares_every_shared_level(tmp_path):
    spread, loops, info = sbm_compare.compare(*make_run(tmp_path))
    std = [r for r in spread if r["fit"] == "standard"]
    assert [(r["seed"], r["level"]) for r in std] == [(42, 0), (42, 1), (43, 0), (43, 1)]
    assert float(std[0]["nmi_to_kept"]) == 1.0 and float(std[0]["ari_to_kept"]) == 1.0
    dc = [r for r in spread if r["fit"] == "degree_corrected"]
    assert [(r["seed"], r["level"]) for r in dc] == [(42, 0), (42, 1), (43, 0)]
    assert [(r["level"], r["main_blocks"], r["self_loops_blocks"]) for r in loops] == [(0, 3, 3), (1, 2, 2)]
    assert info == {"main_model": "standard", "self_loops_fit": "self_loops_standard"}


def test_stops_when_saved_fit_differs_from_blocks_csv(tmp_path):
    run, saved = make_run(tmp_path, {"standard": [[0, 0, 0, 0], [0, 0, 1, 1]]})
    with pytest.raises(SystemExit):
        sbm_compare.compare(run, saved)
