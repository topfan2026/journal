import io
import json
import zipfile

import pytest

import update


def repo_zip(files: dict[str, bytes], top="journal-abc123") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{top}/README.md", b"repo readme")                    # outside brain-break-live: ignored
        z.writestr(f"{top}/trading-shorts-bot/live.py", b"x")
        for rel, data in files.items():
            z.writestr(f"{top}/brain-break-live/{rel}", data)
    return buf.getvalue()


def test_files_in_zip_keeps_only_the_app_folder():
    files = update.files_in_zip(repo_zip({"main.py": b"m", "overlay/a.js": b"a", "../evil.py": b"no"}))
    assert files == {"main.py": b"m", "overlay/a.js": b"a"}


def test_apply_first_install_and_user_files(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "stats.json").write_text("{}")
    remote = {"main.py": b"v1", ".env": b"REMOTE", "data/stats.json": b"remote", "music/README.md": b"r",
              "music/song.mp3": b"remote song", "start.bat": b"bat v1", "requirements.txt": b"x"}
    report = update.apply(remote, tmp_path, {}, "a" * 40)
    assert (tmp_path / "main.py").read_bytes() == b"v1"
    assert (tmp_path / ".env").read_text() == "SECRET=1"                 # never touched
    assert (tmp_path / "data" / "stats.json").read_text() == "{}"
    assert not (tmp_path / "music" / "song.mp3").exists()                 # music/backgrounds are the user's
    assert (tmp_path / "music" / "README.md").exists()
    assert (tmp_path / "start.bat").read_bytes() == b"bat v1"            # new file: written
    assert report["requirements"]
    manifest = json.loads((tmp_path / ".update.json").read_text())
    assert manifest["sha"] == "a" * 40 and "main.py" in manifest["files"] and ".env" not in manifest["files"]


def test_apply_update_keeps_user_edits_and_bats(tmp_path):
    update.apply({"main.py": b"v1", "profiles/study.json": b"p1", "old.py": b"o", "gone.py": b"g",
                  "start.bat": b"bat v1"}, tmp_path, {}, "a" * 40)
    manifest = json.loads((tmp_path / ".update.json").read_text())
    (tmp_path / "profiles" / "study.json").write_bytes(b"my edit")        # user edited a profile
    (tmp_path / "gone.py").write_bytes(b"edited, keep me")
    report = update.apply({"main.py": b"v2", "profiles/study.json": b"p2", "start.bat": b"bat v2"},
                          tmp_path, manifest, "b" * 40)
    assert (tmp_path / "main.py").read_bytes() == b"v2"
    assert (tmp_path / "profiles" / "study.json").read_bytes() == b"my edit"
    assert (tmp_path / "profiles" / "study.json.new").read_bytes() == b"p2"
    assert (tmp_path / "start.bat").read_bytes() == b"bat v1"            # running launcher not replaced
    assert (tmp_path / "start.bat.new").read_bytes() == b"bat v2"
    assert not (tmp_path / "old.py").exists()                             # removed upstream, unchanged here
    assert (tmp_path / "gone.py").exists()                                # removed upstream, but you edited it
    assert set(report["kept"]) == {"profiles/study.json", "start.bat"} and report["removed"] == ["old.py"]


def test_update_skips_when_current(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "MANIFEST", tmp_path / ".update.json")
    (tmp_path / ".update.json").write_text(json.dumps({"sha": "c" * 40, "files": {}}))
    monkeypatch.setattr(update, "remote_sha", lambda *a, **k: "c" * 40)
    monkeypatch.setattr(update, "download", lambda *a, **k: pytest.fail("should not download"))
    assert update.update(quiet=True)["changed"] is False


def test_update_restart_needs_launcher(monkeypatch, settings, profiles, bank, clock):
    from app import App, ControlError
    from chat import DemoChat
    app = App(settings, profiles, DemoChat(settings, clock=clock, rate=0), bank, clock=clock)
    monkeypatch.delenv("BBL_LAUNCHER", raising=False)
    with pytest.raises(ControlError):
        app.control("update_restart")
    monkeypatch.setenv("BBL_LAUNCHER", "1")
    app.control("update_restart")
    assert app.restart_requested and app.snapshot()["can_update"]
