import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sbm_coassign  # noqa: E402
from test_sbm_compare import make_run  # noqa: E402


def test_counts_pairs_sharing_a_block():
    stations = ["001", "002", "003"]
    counts = sbm_coassign.coassignment(stations, [np.array([0, 0, 1]), np.array([0, 0, 0]), np.array([0, 1, 2])])
    assert counts == {("001", "002"): 2, ("001", "003"): 1, ("002", "003"): 1}


def test_collect_uses_the_kept_model_and_level(tmp_path):
    stations, parts, info = sbm_coassign.collect(*make_run(tmp_path), level=1)
    assert stations == ["001", "002", "003", "004"]
    assert [p.tolist() for p in parts] == [[0, 0, 1, 1], [0, 0, 0, 1]]
    assert info["fit"] == "standard" and info["kept_seed"] == 42


def test_collect_stops_on_missing_level_or_mismatch(tmp_path):
    run, saved = make_run(tmp_path)
    with pytest.raises(SystemExit):
        sbm_coassign.collect(run, saved, level=2)
    (tmp_path / "b").mkdir()
    run2, saved2 = make_run(tmp_path / "b", {"standard": [[0, 0, 0, 0], [0, 0, 1, 1]]})
    with pytest.raises(SystemExit):
        sbm_coassign.collect(run2, saved2, level=1)
