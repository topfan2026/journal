import os
import time
from pathlib import Path

from connector_update import app_path_from, is_new_connector, pick_download

ARGS = '"C:\\Users\\f2far\\Documents\\Codex\\2026-08-23\\chec\\work\\tradeledger-deploy\\services\\ibkr_connector\\app.py" C:\\x\\pythonw.exe'


def test_finds_the_connector_path_in_the_task_arguments():
    p = app_path_from(ARGS)
    assert p is not None and str(p).endswith("ibkr_connector\\app.py") and "tradeledger-deploy" in str(p)
    assert app_path_from("") is None and app_path_from("python something.py") is None


def test_only_the_new_connector_is_taken_from_downloads(tmp_path: Path):
    (tmp_path / "app.py").write_text("old connector")
    assert pick_download(tmp_path) is None
    new = tmp_path / "app (1).py"
    new.write_text('@app.post("/market-data/order-flow")')
    other = tmp_path / "app_backup.py"
    other.write_text('/market-data/order-flow')
    assert pick_download(tmp_path) == new  # app_backup.py is not an app.py download
    newer = tmp_path / "app.py"
    newer.write_text('/market-data/order-flow')
    os.utime(new, (time.time() - 100, time.time() - 100))
    assert pick_download(tmp_path) == newer
    assert is_new_connector(newer) and not is_new_connector(tmp_path / "missing.py")


def test_an_explicit_path_must_still_be_the_new_connector(tmp_path: Path):
    f = tmp_path / "x.py"
    f.write_text("nothing")
    assert pick_download(tmp_path, str(f)) is None
