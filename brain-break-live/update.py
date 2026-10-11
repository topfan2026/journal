"""Self-update from GitHub: fetch the latest brain-break-live/ folder and install it in place.

    python update.py           update now (also run automatically by launcher.py on every start)
    python update.py --check   only say whether an update is available

Your own files are never touched: .env, data/, and what you put in music/ and backgrounds/.
A file you edited yourself (e.g. a profile) is kept; the new version is saved next to it as
<name>.new so you can compare. The .bat launchers are never replaced while they may be running:
if they change, the new one is saved as <name>.bat.new.

Standard library only, so it works before anything else is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / ".update.json"
REPO = os.environ.get("UPDATE_REPO", "topfan2026/journal")
BRANCH = os.environ.get("UPDATE_BRANCH", "claude/friendly-meitner-act04s")
SUBDIR = "brain-break-live"
TIMEOUT = 20


class UpdateError(Exception):
    pass


def _env_from_dotenv() -> None:
    """UPDATE_BRANCH / UPDATE_REPO / AUTO_UPDATE may be set in .env (read without python-dotenv)."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if sep and key in ("UPDATE_BRANCH", "UPDATE_REPO", "AUTO_UPDATE") and value:
            os.environ.setdefault(key, value)


def protected(rel: str) -> bool:
    """Files that belong to the user and are never written by the updater."""
    if rel == ".env" or rel == MANIFEST.name or rel.startswith("data/") or rel.startswith(".venv/"):
        return True
    for folder in ("music/", "backgrounds/"):
        if rel.startswith(folder) and not rel.endswith("README.md"):
            return True
    return False


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _get(url: str, accept: str | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "brain-break-live-updater",
                                               **({"Accept": accept} if accept else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def remote_sha(repo: str | None = None, branch: str | None = None) -> str:
    repo, branch = repo or os.environ.get("UPDATE_REPO", REPO), branch or os.environ.get("UPDATE_BRANCH", BRANCH)
    try:
        sha = _get(f"https://api.github.com/repos/{repo}/commits/{branch}", "application/vnd.github.sha").decode().strip()
    except Exception as e:
        raise UpdateError(f"can't reach GitHub ({e})") from e
    if len(sha) != 40:
        raise UpdateError(f"unexpected answer from GitHub: {sha[:80]!r}")
    return sha


def update_available() -> bool:
    try:
        return remote_sha() != read_manifest().get("sha")
    except UpdateError:
        return False


def download(sha: str, repo: str | None = None) -> bytes:
    repo = repo or os.environ.get("UPDATE_REPO", REPO)
    try:
        return _get(f"https://codeload.github.com/{repo}/zip/{sha}")
    except Exception as e:
        raise UpdateError(f"download failed ({e})") from e


def files_in_zip(zip_bytes: bytes) -> dict[str, bytes]:
    """{path inside brain-break-live/: content} from a GitHub repository zip."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/", 2)       # <repo>-<sha>/brain-break-live/<rel>
            if len(parts) < 3 or parts[1] != SUBDIR:
                continue
            rel = posixpath.normpath(parts[2])
            if rel.startswith("../") or rel.startswith("/") or rel == ".." or "\\" in rel:
                continue
            out[rel] = z.read(info)
    if not out:
        raise UpdateError(f"no {SUBDIR}/ folder in the download")
    return out


def apply(remote: dict[str, bytes], root: Path, manifest: dict, sha: str) -> dict:
    """Install `remote` into `root`. Returns a report; writes the new manifest."""
    old = manifest.get("files", {})
    report = {"updated": [], "added": [], "removed": [], "kept": [], "requirements": False}
    new_hashes = {}
    for rel, data in sorted(remote.items()):
        if protected(rel):
            continue
        new_hash = new_hashes[rel] = sha256(data)
        path = root / rel
        if path.exists():
            local_hash = sha256(path.read_bytes())
            if local_hash == new_hash:
                continue
            edited = rel in old and local_hash != old[rel]
            if rel.endswith(".bat") or edited:
                side = path.with_name(path.name + ".new")
                side.write_bytes(data)
                report["kept"].append(rel)
                continue
            report["updated"].append(rel)
        else:
            report["added"].append(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp-update")
        tmp.write_bytes(data)
        tmp.replace(path)
        if rel == "requirements.txt":
            report["requirements"] = True
    for rel, h in old.items():
        if rel in remote or protected(rel):
            continue
        path = root / rel
        if path.exists() and sha256(path.read_bytes()) == h:   # only delete files you didn't change
            path.unlink()
            report["removed"].append(rel)
    tmp = root / (MANIFEST.name + ".tmp")
    tmp.write_text(json.dumps({"sha": sha, "branch": os.environ.get("UPDATE_BRANCH", BRANCH), "files": new_hashes},
                              indent=1), encoding="utf-8")
    tmp.replace(root / MANIFEST.name)
    return report


def update(quiet: bool = False) -> dict:
    """Check GitHub and install a newer version. Raises UpdateError when GitHub can't be reached."""
    manifest = read_manifest()
    sha = remote_sha()
    if sha == manifest.get("sha"):
        if not quiet:
            print(f"Brain Break Live is up to date ({sha[:7]}).")
        return {"changed": False, "requirements": False, "sha": sha}
    print(f"Updating Brain Break Live to {sha[:7]}...")
    report = apply(files_in_zip(download(sha)), ROOT, manifest, sha)
    changes = len(report["updated"]) + len(report["added"]) + len(report["removed"])
    print(f"  {changes} file(s) updated." if changes else "  Nothing to change.")
    for rel in report["kept"]:
        print(f"  Kept your version of {rel}; the new one is saved as {rel}.new")
    return {"changed": bool(changes), "requirements": report["requirements"], "sha": sha, "report": report}


def main() -> int:
    _env_from_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report whether an update is available")
    args = ap.parse_args()
    try:
        if args.check:
            sha = remote_sha()
            current = read_manifest().get("sha")
            print("up to date" if sha == current else f"update available: {(current or 'unknown')[:7]} -> {sha[:7]}")
            return 0
        update()
        return 0
    except UpdateError as e:
        print(f"Update skipped: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
