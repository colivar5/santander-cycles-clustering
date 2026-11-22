import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import clean  # noqa: E402


def trip(i, start="2025-06-01 10:00", end="2025-06-01 10:10", s="001", e="002", ms=600_000, bike="b1",
         sname=None, ename=None):
    return {"trip_id": i, "start_time": pd.Timestamp(start), "start_station_id": s,
            "start_station_name": sname or f"Station {s}", "end_time": pd.Timestamp(end) if end else pd.NaT,
            "end_station_id": e, "end_station_name": ename or (f"Station {e}" if e else ""),
            "bike_id": bike, "bike_model": "CLASSIC", "duration_text": "10m", "duration_ms": ms,
            "source_file": 422}


def frame(rows):
    df = pd.DataFrame(rows)
    df["duration_ms"] = df["duration_ms"].astype("Int64")
    return df


def test_rules_in_order_and_waterfall():
    df = frame([
        trip(1),
        trip(2, start="2024-12-31 23:59", end="2025-01-01 00:09"),
        trip(3, start="2025-12-31 23:59", end="2026-01-01 00:09"),
        trip(4, e="", end=None, ms=pd.NA),
        trip(5, ms=0),
        trip(6, ms=-5),
        trip(7, s="003", e="003"),
        trip(8),
        trip(9, bike="b2"),
    ])
    kept, excluded, wf, _ = clean.apply_rules(df, frozenset(), frozenset())
    assert kept["trip_id"].tolist() == [1, 3, 7, 9]
    assert dict(zip(excluded["trip_id"], excluded["rule"])) == {
        2: "R1_start_not_in_2025", 4: "R2_missing_station", 5: "R3_duration_not_positive",
        6: "R3_duration_not_positive", 8: "R7_duplicate_of_lower_trip_id"}
    assert wf["rows_removed"].tolist() == [0, 1, 1, 2, 1, 0, 0]
    assert wf["rows_left"].iloc[-1] == 4
    assert kept.set_index("trip_id")["is_round_trip"].to_dict() == {1: False, 3: False, 7: True, 9: False}


def test_duplicate_keeps_lower_trip_id_whatever_the_row_order():
    kept, excluded, _, _ = clean.apply_rules(frame([trip(20), trip(10)]), frozenset(), frozenset())
    assert kept["trip_id"].tolist() == [10]
    assert excluded["trip_id"].tolist() == [20]


def test_long_trips_are_kept():
    kept, _, _, _ = clean.apply_rules(frame([trip(1, end="2025-06-03 10:00", ms=2 * 86_400_000)]), frozenset(), frozenset())
    assert kept["trip_id"].tolist() == [1]


def test_duration_gaps_and_clock_change():
    df = frame([
        trip(1),
        trip(2, end="2025-06-01 10:13"),
        trip(3, start="2025-03-30 00:50", end="2025-03-30 02:10", ms=1_200_000),
        trip(4, start="2025-10-26 01:50", end="2025-10-26 01:10", ms=1_200_000),
        trip(5, start="2025-03-20 10:00", end="2025-04-02 11:00", ms=(13 * 86_400) * 1000),
        trip(6, start="2025-03-30 03:00", end="2025-03-30 05:00", ms=3_600_000),
    ])
    g = clean.duration_gaps(df).set_index("trip_id")
    assert g["kind"].to_dict() == {2: "other", 3: "across_clock_change", 4: "across_clock_change",
                                   5: "across_clock_change", 6: "other"}
    assert g["gap_s"].to_dict() == {2: -180.0, 3: -3600.0, 4: 3600.0, 5: -3600.0, 6: -3600.0}


def test_station_names_label_and_conflicts():
    df = frame([
        trip(1, s="001", sname="A", e="002", ename="B"),
        trip(2, s="001", sname="A", e="002", ename="B"),
        trip(3, s="001", sname="A_OLD", e="003", ename="B"),
    ])
    t = clean.station_names(df)
    a = t[t["station_id"] == "001"].set_index("station_name")
    assert a["departures"].to_dict() == {"A": 2, "A_OLD": 1}
    assert set(a["label"]) == {"A"} and a["names_for_id"].tolist() == [2, 2]
    b = t[t["station_name"] == "B"]
    assert sorted(b["station_id"]) == ["002", "003"] and b["ids_for_name"].tolist() == [2, 2]


def test_r9_merges_old_ids_and_r10_removes_workshops():
    df = frame([
        trip(1, s="123456", sname="Elm Road", e="999999", ename="Oak Street"),
        trip(2, s="123456", sname="Elm Road", e="999999", ename="Oak Street", bike="b2"),
        trip(3, s="123456444", sname="Elm Road_OLD", e="999999", ename="Oak Street"),
        trip(4, s="123456444", sname="Elm Road_OLD", e="123456", ename="Elm Road"),
        trip(5, s="5555554444", sname="Not Its Label_OLD", e="999999", ename="Oak Street"),
        trip(6, s="010626", sname="Mechanical Workshop Penton", e="999999", ename="Oak Street"),
        trip(7, s="999999", sname="Oak Street", e="010626", ename="Mechanical Workshop Penton"),
        trip(8, s="555555", sname="Ash Lane", e="999999", ename="Oak Street"),
    ])
    kept, excluded, wf, merges = clean.apply_rules(df, frozenset({"123456444"}), frozenset({"010626"}))
    k = kept.set_index("trip_id")
    assert k.loc[3, "start_station_id"] == "123456" and k.loc[3, "start_station_id_published"] == "123456444"
    assert k.loc[5, "start_station_id"] == "5555554444"
    assert bool(k.loc[4, "is_round_trip"]) and not bool(k.loc[3, "is_round_trip"])
    assert merges.to_dict("records") == [{"published_id": "123456444", "merged_into": "123456",
                                          "departures": 2, "arrivals": 0}]
    assert dict(zip(excluded["trip_id"], excluded["rule"])) == {6: "R10_workshop", 7: "R10_workshop"}
    assert wf.set_index("step")["rows_removed"].to_dict()["R9_merge_old_ids"] == 0
    assert wf.set_index("step")["rows_removed"].to_dict()["R10_workshop"] == 2


def test_r9_and_r10_stop_when_the_ids_found_differ():
    df = frame([trip(1, s="123456", sname="Elm Road"), trip(2, s="123456444", sname="Elm Road_OLD"),
                trip(3, s="010626", sname="Mechanical Workshop Penton")])
    with pytest.raises(SystemExit):
        clean.apply_rules(df, frozenset(), frozenset({"010626"}))
    with pytest.raises(SystemExit):
        clean.apply_rules(df, frozenset({"123456444"}), frozenset())
