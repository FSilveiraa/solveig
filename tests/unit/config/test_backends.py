import anyconfig
import pytest


@pytest.mark.parametrize("ext", ["json", "yaml", "toml"])
def test_anyconfig_roundtrip_on_disk(tmp_path, ext):
    p = tmp_path / f"c.{ext}"
    data = {"api": {"url": "http://x", "temperature": 0.5}}
    anyconfig.dump(data, str(p))            # writes by file extension
    assert anyconfig.load(str(p)) == data   # reads by file extension


def test_anyconfig_multi_file_merge_later_wins(tmp_path):
    base = tmp_path / "base.toml"
    over = tmp_path / "over.json"
    anyconfig.dump({"api": {"url": "BASE", "model": "m"}}, str(base))
    anyconfig.dump({"api": {"url": "OVER"}}, str(over))
    merged = anyconfig.load([str(base), str(over)], ac_merge=anyconfig.MS_DICTS)
    assert merged["api"]["url"] == "OVER"    # later file wins
    assert merged["api"]["model"] == "m"     # deep-merged, base contributes
