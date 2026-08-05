import anyconfig
import pytest

from solveig.config import sources


def test_load_paths_highest_first_wins(tmp_path):
    hi = tmp_path / "hi.json"
    lo = tmp_path / "lo.toml"
    anyconfig.dump({"api": {"url": "HI"}}, str(hi))
    anyconfig.dump({"api": {"url": "LO", "model": "m"}}, str(lo))
    merged = sources.load_paths([str(hi), str(lo)])  # hi first => hi wins
    assert merged["api"]["url"] == "HI"
    assert merged["api"]["model"] == "m"  # deep-merged from lo


def test_load_paths_legacy_hard_breaks(tmp_path):
    p = tmp_path / "old.json"
    anyconfig.dump({"http_timeout": 5, "api_key": "x"}, str(p))
    with pytest.raises(ValueError, match="tools.http.timeout"):
        sources.load_paths([str(p)])


def test_resolve_uses_search_and_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "DEFAULT_CONFIG_SEARCH", [str(tmp_path / "config")])
    anyconfig.dump({"api": {"url": "u"}}, str(tmp_path / "config.yaml"))
    # No explicit --config → the search runs (basename × every extension).
    assert sources.resolve_config_files([]) == [str(tmp_path / "config.yaml")]

    # An explicit --config short-circuits the search entirely.
    explicit = tmp_path / "e.json"
    anyconfig.dump({"api": {"url": "u"}}, str(explicit))
    assert sources.resolve_config_files([str(explicit)]) == [str(explicit)]

    # A non-existent explicit path is dropped (the record lives in argv).
    assert sources.resolve_config_files(["/x/y.json"]) == []


def test_plugin_paths_union_across_files(tmp_path):
    # plugins.paths UNIONS across layers (order-preserving dedupe), unlike other
    # lists which the highest-precedence file replaces.
    hi = tmp_path / "hi.json"
    lo = tmp_path / "lo.json"
    anyconfig.dump({"plugins": {"paths": ["./local", "./shared"]}}, str(hi))
    anyconfig.dump({"plugins": {"paths": ["./global", "./shared"]}}, str(lo))
    merged = sources.load_paths([str(hi), str(lo)])
    assert merged["plugins"]["paths"] == ["./global", "./shared", "./local"]


def test_save_creates_dirs_and_roundtrips(tmp_path):
    p = str(tmp_path / "sub" / "out.toml")
    sources.save_config({"api": {"url": "u"}}, p)
    assert anyconfig.load(p) == {"api": {"url": "u"}}
