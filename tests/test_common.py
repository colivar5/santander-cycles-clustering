import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import common  # noqa: E402


def test_new_file_is_written(tmp_path):
    out = common.write_text(tmp_path / "a.txt", "one")
    assert out == tmp_path / "a.txt"
    assert out.read_text() == "one"


def test_identical_content_is_left_alone(tmp_path):
    p = common.write_text(tmp_path / "a.txt", "one")
    mtime = p.stat().st_mtime_ns
    out = common.write_text(tmp_path / "a.txt", "one")
    assert out == p
    assert p.stat().st_mtime_ns == mtime
    assert sorted(x.name for x in tmp_path.iterdir()) == ["a.txt"]


def test_different_content_goes_beside_with_note(tmp_path, capsys):
    p = common.write_text(tmp_path / "a.txt", "one")
    out = common.write_text(tmp_path / "a.txt", "two")
    assert out != p
    assert out.name.startswith("a.") and out.name.endswith("Z.txt")
    assert p.read_text() == "one"
    assert out.read_text() == "two"
    assert "NOTE" in capsys.readouterr().out
    out2 = common.write_text(tmp_path / "a.txt", "three")
    assert len({p, out, out2}) == 3
    assert p.read_text() == "one"


def test_no_temporary_files_left(tmp_path):
    common.write_text(tmp_path / "a.txt", "one")
    common.write_text(tmp_path / "a.txt", "two")
    assert not [x for x in tmp_path.iterdir() if x.name.startswith(".tmp-")]


def test_failed_writer_leaves_nothing(tmp_path):
    def boom(_):
        raise ValueError("boom")
    try:
        common.write_with(tmp_path / "a.txt", boom)
    except ValueError:
        pass
    assert list(tmp_path.iterdir()) == []


def test_json_is_deterministic(tmp_path):
    a = common.write_json(tmp_path / "a.json", {"b": 1, "a": [1, 2]})
    b = common.write_json(tmp_path / "a.json", {"a": [1, 2], "b": 1})
    assert a == b
