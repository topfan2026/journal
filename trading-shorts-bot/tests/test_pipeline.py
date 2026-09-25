import json

from agents import Orchestrator
from job import claim, discover
from stitch import probe


def test_six_clips_end_to_end_dry_run(settings, make_clip):
    job_dir = settings.ready / "strategy-1"
    job_dir.mkdir()
    for i in range(1, 7):
        make_clip(job_dir / f"clip{i}.mp4", seconds=1.0, audio=(i != 3))  # clip 3 has no audio track
    (job_dir / "caption.txt").write_text("Mark the opening range.\nTrade the break.")
    (job_dir / "meta.json").write_text(json.dumps({"subject": "Opening range breakout", "hashtags": ["trading"]}))

    [cand] = discover(settings.ready)
    folder = claim(cand, settings.processing)
    assert Orchestrator(settings).process(folder) is True

    done = settings.done / "strategy-1"
    state = json.loads((done / "job.json").read_text())
    assert state["result"] == "ok"
    assert {p["state"] for p in state["platforms"].values()} == {"dry_run"}
    info = probe(done / "_out" / "final.mp4")
    assert (info.width, info.height) == (270, 480)
    assert 5.5 <= info.duration <= 6.5
    assert (done / "_out" / "thumbnail.jpg").exists()


def test_bad_meta_goes_to_failed(settings, make_clip):
    job_dir = settings.ready / "broken"
    job_dir.mkdir()
    make_clip(job_dir / "v.mp4")
    (job_dir / "meta.json").write_text("{not json")
    [cand] = discover(settings.ready)
    assert Orchestrator(settings).process(claim(cand, settings.processing)) is False
    assert (settings.failed / "broken" / "error.txt").exists()


def test_retry_skips_platforms_already_posted(settings, make_clip, monkeypatch):
    import dataclasses

    import agents
    from common import UploadResult
    from watcher import retry

    job_dir = settings.ready / "retry-me"
    job_dir.mkdir()
    make_clip(job_dir / "v.mp4", size="270x480")
    (job_dir / "caption.txt").write_text("hello")
    live = dataclasses.replace(settings, dry_run=False)
    calls = []

    def fake_run(self, post):
        calls.append(self.platform)
        if self.platform == "tiktok" and calls.count("tiktok") == 1:
            raise RuntimeError("boom")
        return UploadResult(id=f"id-{self.platform}")

    monkeypatch.setattr(agents.UploadAgent, "run", fake_run)
    [cand] = discover(live.ready)
    assert Orchestrator(live).process(claim(cand, live.processing)) is False
    retry(live, [], fresh=False)
    [cand] = discover(live.ready)
    assert Orchestrator(live).process(claim(cand, live.processing)) is True
    assert sorted(calls) == ["instagram", "tiktok", "tiktok", "youtube"]
    state = json.loads((live.done / "retry-me" / "job.json").read_text())
    assert state["platforms"]["tiktok"]["attempts"] == 2
