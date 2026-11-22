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
