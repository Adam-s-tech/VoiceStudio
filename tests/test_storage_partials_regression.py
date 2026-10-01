

def test_partial_managed_engines_remain_in_data_footprint(tmp_path):
    from services.storage_report import build_report
    data = tmp_path / "data"
    engines = data / "engines"
    installed = engines / "installed"
    (installed / ".venv").mkdir(parents=True)
    (installed / "weights.bin").write_bytes(b"i" * 70)
    partial = engines / "interrupted" / "checkpoints"
    partial.mkdir(parents=True)
    (partial / "weights.bin").write_bytes(b"p" * 110)
    (engines / "install.log").write_bytes(b"log")
    report = build_report(data_dir=str(data), engines_dir=str(engines),
                          hf_cache_dir=str(tmp_path / "hf"), temp_root=str(tmp_path / "tmp"))
    categories = {c["id"]: c for c in report["categories"]}
    assert categories["engine_venvs"]["bytes"] == 70
    other = next(c for c in categories["data"]["children"] if c["id"] == "other")
    assert other["bytes"] == 113
    assert sum(c["bytes"] for c in categories.values()) == 183
