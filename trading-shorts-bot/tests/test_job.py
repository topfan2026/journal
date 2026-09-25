import json

from job import StabilityTracker, claim, discover, load_job


def test_discovers_folder_and_loose_jobs(tmp_path):
    ready = tmp_path / "Ready"
    (ready / "a").mkdir(parents=True)
    (ready / "a" / "clip1.mp4").write_bytes(b"x")
    (ready / "a" / "meta.json").write_text("{}")
    (ready / "b").mkdir()
    (ready / "b" / "clip.mp4").write_bytes(b"x")  # no text file -> not a job yet
    (ready / "c").mkdir()
    (ready / "c" / "clip.mp4.crdownload").write_bytes(b"x")  # still downloading
    (ready / "c" / "caption.txt").write_text("hi")
    (ready / "video.mp4").write_bytes(b"x")
    (ready / "caption.txt").write_text("hello")
    names = sorted(c.name for c in discover(ready))
    assert names == ["a", "video"]


def test_stability_tracker(tmp_path):
    ready = tmp_path / "Ready"
    (ready / "a").mkdir(parents=True)
    (ready / "a" / "v.mp4").write_bytes(b"x")
    (ready / "a" / "caption.txt").write_text("hi")
    t = StabilityTracker(10)
    [cand] = discover(ready)
    assert not t.is_stable(cand, now=0)
    assert not t.is_stable(cand, now=5)
    assert t.is_stable(cand, now=11)
    (ready / "a" / "v.mp4").write_bytes(b"xx")  # file grew -> timer restarts
    [cand] = discover(ready)
    assert not t.is_stable(cand, now=12)


def test_claim_loose_and_load(tmp_path):
    ready, proc = tmp_path / "Ready", tmp_path / "Processing"
    ready.mkdir()
    proc.mkdir()
    for n in ("clip10.mp4", "clip2.mp4"):
        (ready / n).write_bytes(b"x")
    (ready / "meta.json").write_text(json.dumps({"subject": "VWAP bounce"}))
    [cand] = discover(ready)
    folder = claim(cand, proc)
    assert not list(ready.iterdir())
    job = load_job(folder)
    assert [c.name for c in job.clips] == ["clip2.mp4", "clip10.mp4"]
    assert job.subject == "VWAP bounce"
    assert job.target_platforms(("youtube", "tiktok")) == ["youtube", "tiktok"]
