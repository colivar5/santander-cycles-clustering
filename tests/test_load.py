import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import load  # noqa: E402

STANDARD = ['"Number"', '"Start date"', '"Start station number"', '"Start station"', '"End date"',
            '"End station number"', '"End station"', '"Bike number"', '"Bike model"',
            '"Total duration"', '"Total duration (ms)"']
ROW = {"Number": "1", "Start date": "2025-01-14 23:59", "Start station number": "001043",
       "Start station": "Museum of London, Barbican", "End date": "2025-01-15 00:13",
       "End station number": "200149", "End station": "Watney Street, Shadwell", "Bike number": "55223",
       "Bike model": "CLASSIC", "Total duration": "14m 30s", "Total duration (ms)": "870468"}


def write(tmp_path, order, rows, name="411JourneyDataExtract01Jan2025-14Jan2025.csv"):
    p = tmp_path / name
    lines = [",".join(f'"{c}"' for c in order)]
    lines += [",".join(f'"{r[c]}"' for c in order) for r in rows]
    p.write_text("\n".join(lines) + "\n")
    return p


def test_columns_mapped_by_name_whatever_the_order(tmp_path):
    order = [h.strip('"') for h in STANDARD]
    swapped = order[:3] + order[4:7] + [order[3]] + order[7:]
    a = load.read_text_table(write(tmp_path, order, [ROW], "a.csv"))
    b = load.read_text_table(write(tmp_path, swapped, [ROW], "b.csv"))
    pd.testing.assert_frame_equal(a, b)
    assert list(a.columns) == list(load.COLUMNS.values())


def test_leading_zeros_and_commas_kept(tmp_path):
    t = load.read_text_table(write(tmp_path, list(ROW), [ROW]))
    assert t.loc[0, "start_station_id"] == "001043"
    assert t.loc[0, "start_station_name"] == "Museum of London, Barbican"


def test_unexpected_header_refused(tmp_path):
    order = list(ROW)
    p = tmp_path / "x.csv"
    p.write_text(",".join(f'"{c}"' for c in order[:-1] + ["Duration"]) + "\n")
    with pytest.raises(ValueError):
        load.read_text_table(p)


def test_types_and_failures_counted(tmp_path):
    bad = {**ROW, "Number": "2", "End date": "not a time", "Total duration (ms)": ""}
    text = load.read_text_table(write(tmp_path, list(ROW), [ROW, bad]))
    typed, failures, counts = load.type_frame(text, 411)
    assert typed["trip_id"].tolist() == [1, 2]
    assert typed.loc[0, "start_time"] == pd.Timestamp("2025-01-14 23:59")
    assert pd.isna(typed.loc[1, "end_time"])
    assert counts["unparsed_end_time"] == 1
    assert counts["empty_duration_ms"] == 1 and counts["unparsed_duration_ms"] == 0
    assert failures["trip_id"].tolist() == ["2"]
    assert failures.loc[failures.index[0], "end_time"] == "not a time"


def test_missing_trip_id_stops(tmp_path):
    text = load.read_text_table(write(tmp_path, list(ROW), [{**ROW, "Number": ""}]))
    with pytest.raises(ValueError):
        load.type_frame(text, 411)


def test_data_line_count(tmp_path):
    p = write(tmp_path, list(ROW), [ROW, ROW, ROW])
    assert load.count_data_lines(p) == 3
    p.write_bytes(p.read_bytes().rstrip(b"\n"))
    assert load.count_data_lines(p) == 3
