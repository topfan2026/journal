import io
import json
import zipfile

from src import updater


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, data in files.items():
            z.writestr(f"journal-abc123/{path}", data)
    return buf.getvalue()


def test_update_replaces_code_and_keeps_user_files(tmp_path, monkeypatch):
    (tmp_path / "cycle.py").write_text("old code")
    (tmp_path / ".env").write_text("TOKEN=mine")
    (tmp_path / "rules.json").write_text('{"mine": 1}')
    (tmp_path / "trades.csv").write_text("my trades")
    (tmp_path / "requirements.txt").write_text("pandas\n")
    archive = make_zip({"ibkr-trading-bot/cycle.py": "new code", "ibkr-trading-bot/.env": "TOKEN=theirs",
                        "ibkr-trading-bot/rules.json": '{"default": 1}', "ibkr-trading-bot/src/new_module.py": "x = 1",
                        "ibkr-trading-bot/requirements.txt": "pandas\n", "other-project/file.py": "ignore me"})

    def fake_get(url, timeout=20):
        return archive if "codeload" in url else json.dumps({"sha": "abc123" + "0" * 34}).encode()

    monkeypatch.setattr(updater, "_get", fake_get)
    monkeypatch.setattr(updater, "PROJECT_DIR", tmp_path)
    monkeypatch.setattr(updater, "VERSION_PATH", tmp_path / ".version")
    log = updater.apply()
    assert (tmp_path / "cycle.py").read_text() == "new code"
    assert (tmp_path / "src" / "new_module.py").read_text() == "x = 1"
    assert (tmp_path / ".env").read_text() == "TOKEN=mine"
    assert (tmp_path / "rules.json").read_text() == '{"mine": 1}'
    assert (tmp_path / "trades.csv").read_text() == "my trades"
    assert not (tmp_path / "file.py").exists()
    assert (tmp_path / ".version").read_text().startswith("abc123")
    assert "Installing" not in log  # requirements unchanged -> no pip run


def test_check_reports_available(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "VERSION_PATH", tmp_path / ".version")
    commit = {"sha": "f" * 40, "commit": {"message": "New charts\n\ndetails", "committer": {"date": "2026-10-12T00:00:00Z"}}}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=20: json.dumps(commit).encode())
    info = updater.check(force=True)
    assert info["available"] and info["message"] == "New charts"
    (tmp_path / ".version").write_text("f" * 40)
    assert not updater.check(force=True)["available"]
