import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import sbm  # noqa: E402


def test_read_edges_keeps_ids_as_text(tmp_path):
    p = tmp_path / "edges.csv"
    p.write_text("source,target,weight,is_self_loop\n001,001,4,True\n001,002,3,False\n003,001,1,False\n")
    stations, rows = sbm.read_edges(p)
    assert stations == ["001", "002", "003"]
    assert rows == [("001", "001", 4), ("001", "002", 3), ("003", "001", 1)]
    assert sbm.edges_for(rows, self_loops=False) == [("001", "002", 3), ("003", "001", 1)]
    assert sbm.edges_for(rows, self_loops=True) == rows


def test_block_rows_are_long_format():
    import numpy as np
    rows = sbm.block_rows("m", ["a", "b"], [np.array([0, 1]), np.array([0, 0])])
    assert rows[1] == {"fit": "m", "station_id": "b", "level": 0, "block": 1}
    assert len(rows) == 4


def test_saved_fit_reads_back_exactly(tmp_path):
    import numpy as np
    fit = {"seed": 42, "dl": 7368.658403621379, "seconds": 3.2,
           "levels": [np.array([0, 1, 1, 2]), np.array([0, 0, 0, 1])]}
    path = tmp_path / "standard_seed42.json"
    sbm.save_fit(path, fit)
    back = sbm.load_fit(path)
    assert back["dl"] == fit["dl"] and back["seed"] == 42 and back["saved"]
    assert [b.tolist() for b in back["levels"]] == [b.tolist() for b in fit["levels"]]


def test_store_key_changes_with_any_part():
    parts = {"edges_sha256": "a", "sweeps": 100}
    assert sbm.store_key(parts) == sbm.store_key(dict(parts))
    assert sbm.store_key(parts) != sbm.store_key({**parts, "sweeps": 99})
