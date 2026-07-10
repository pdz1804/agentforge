"""env_loader: fills missing env vars from a .env file without clobbering ones
that are already set explicitly (setdefault semantics)."""
import os

from app.env_loader import load_env_files


def test_sets_missing_strips_quotes_and_preserves_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        '# a comment\n\nENVLOADER_NEW=bar\nexport ENVLOADER_Q="quoted val"\n'
        "ENVLOADER_EXISTING=fromfile\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ENVLOADER_NEW", raising=False)
    monkeypatch.delenv("ENVLOADER_Q", raising=False)
    monkeypatch.setenv("ENVLOADER_EXISTING", "fromenv")
    try:
        loaded = load_env_files(env)
        assert os.environ["ENVLOADER_NEW"] == "bar"
        assert os.environ["ENVLOADER_Q"] == "quoted val"  # export + quotes stripped
        assert os.environ["ENVLOADER_EXISTING"] == "fromenv"  # explicit env wins
        assert "ENVLOADER_EXISTING" not in loaded
        assert set(loaded) == {"ENVLOADER_NEW", "ENVLOADER_Q"}
    finally:
        os.environ.pop("ENVLOADER_NEW", None)
        os.environ.pop("ENVLOADER_Q", None)


def test_missing_file_is_a_noop(tmp_path):
    assert load_env_files(tmp_path / "does-not-exist.env") == {}
