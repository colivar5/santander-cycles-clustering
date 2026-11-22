import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import graph  # noqa: E402


def trips():
    return pd.DataFrame({"start_station_id": ["002", "001", "001", "001", "003"],
                         "end_station_id": ["001", "002", "002", "001", "003"]})


def test_edge_list_counts_trips_per_ordered_pair():
    e = graph.edge_list(trips())
    assert e[["source", "target", "weight"]].values.tolist() == [
        ["001", "001", 1], ["001", "002", 2], ["002", "001", 1], ["003", "003", 1]]
    assert e["is_self_loop"].tolist() == [True, False, False, True]


def test_summary_counts_stations_with_only_self_loops():
    s = graph.summary(graph.edge_list(trips()))
    assert s == {"stations": 3, "station_pairs": 4, "station_pairs_without_self_loops": 2, "self_loops": 2,
                 "trips": 5, "trips_on_self_loops": 2, "stations_with_only_self_loops": 1}
