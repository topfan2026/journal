"""The agent pipeline that turns one dropped job into three published posts.

    Orchestrator
      1. EditorAgent      clips -> 9:16 1080x1920 final.mp4, <= MAX_DURATION   (stitch.py)
      2. CopywriterAgent  subject + caption -> title/description/tags/captions  (metadata.py, Claude)
      3. ThumbnailAgent   frame + hook text -> thumbnail.jpg, cover time        (thumbnail.py)
      4. UploadAgents     youtube | instagram | tiktok, in parallel             (upload_*.py)

Each agent's result is checkpointed in the job's job.json, so a job moved
from Failed/ back to Ready/ resumes where it stopped. It keeps the same
metadata and never re-posts a platform that already succeeded.
"""
from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import metadata
import stitch
import thumbnail
from common import Post, UploadResult
from config import Settings
from job import Job, JobError, load_job, move, now_iso

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- agents

class Agent:
    name = "agent"

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, job: Job, ctx: dict) -> dict:
        """Do the work (or reuse the checkpoint) and return this stage's result."""
        cached = job.stage(self.name)
        if cached and self.reusable(job, cached):
            log.info("[%s] %s: reusing previous result", self.name, job.name)
            return cached
        log.info("[%s] %s: working", self.name, job.name)
        result = self.work(job, ctx)
        job.set_stage(self.name, result)
        return result

    def reusable(self, job: Job, cached: dict) -> bool:
        return True

    def work(self, job: Job, ctx: dict) -> dict:
        raise NotImplementedError


class EditorAgent(Agent):
    name = "editor"

    def reusable(self, job, cached):
        return bool(cached.get("video")) and (job.folder / cached["video"]).exists()

    def work(self, job, ctx):
        s = self.settings
        out = job.out_dir / "final.mp4"
        fit = str(job.meta.get("fit") or "pad")
        if job.meta.get("edit") is False and len(job.clips) == 1:
            info = stitch.probe(job.clips[0])
            video = job.clips[0]
        else:
            info = stitch.stitch(job.clips, out, width=s.width, height=s.height,
                                 max_duration=s.max_duration, fit=fit)
            video = out
        if not info.vertical:
            raise JobError(f"video is {info.width}x{info.height}; not vertical")
        if info.duration > s.max_duration + 0.5:
            raise JobError(f"video is {info.duration:.1f}s; limit is {s.max_duration:.0f}s")
        return {"video": str(video.relative_to(job.folder)), "duration": info.duration, "width": info.width,
                "height": info.height, "clips": [c.name for c in job.clips]}


class CopywriterAgent(Agent):
    name = "copywriter"

    def work(self, job, ctx):
        return metadata.generate(job, self.settings, duration=ctx["editor"]["duration"])


class ThumbnailAgent(Agent):
    name = "thumbnail"

    def reusable(self, job, cached):
        return bool(cached.get("path")) and (job.folder / cached["path"]).exists()

    def work(self, job, ctx):
        at = float(job.meta.get("thumbnail_time", 1.5))
        return thumbnail.make_thumbnail(
            job.folder / ctx["editor"]["video"], job.out_dir,
            text=ctx["copywriter"].get("thumbnail_text", ""), custom=job.custom_thumbnail,
            at_seconds=at, duration=ctx["editor"]["duration"], base=job.folder)


def _uploader(platform: str):
    if platform == "youtube":
        import upload_youtube as mod
    elif platform == "instagram":
        import upload_instagram as mod
    elif platform == "tiktok":
        import upload_tiktok as mod
    else:
        raise ValueError(platform)
    return mod


class UploadAgent:
    def __init__(self, platform: str, settings: Settings):
        self.platform = platform
        self.settings = settings

    def run(self, post: Post) -> UploadResult:
        if self.settings.dry_run:
            md = post.metadata.get(self.platform, {})
            log.info("[%s] DRY RUN %s -> %s", self.platform, post.video.name,
                     {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v) for k, v in md.items()})
            return UploadResult(id=f"dry-run-{self.platform}", status="dry_run")
        return _uploader(self.platform).upload(post)

    def check(self) -> str:
        return _uploader(self.platform).check()


# --------------------------------------------------------------------------- orchestrator

class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.stages: list[Agent] = [EditorAgent(settings), CopywriterAgent(settings), ThumbnailAgent(settings)]

    def process(self, folder: Path) -> bool:
        """Run a claimed job (in Processing/) through every agent, then file it in Done/ or Failed/."""
        s = self.settings
        try:
            job = load_job(folder)
        except Exception as e:
            return self._finish_failed(folder, {}, f"cannot read job: {e}")

        job.state.setdefault("name", job.name)
        job.state.setdefault("created", now_iso())
        job.state["subject"] = job.subject
        job.state.pop("error", None)
        log.info("=== job %s | subject: %s", job.name, job.subject)

        ctx: dict = {}
        try:
            for agent in self.stages:
                ctx[agent.name] = agent.run(job, ctx)
            targets = job.target_platforms(s.platforms)
        except Exception as e:
            log.error("job %s failed during preparation: %s", job.name, e)
            log.debug(traceback.format_exc())
            job.state["error"] = str(e)
            job.save_state()
            return self._finish(job, ok=False)

        pending = [p for p in targets if job.platform_state(p).get("state") != "done"]
        for p in set(targets) - set(pending):
            log.info("[%s] %s: already posted - skipping", p, job.name)

        def post_for(platform: str) -> Post:
            thumb = ctx["thumbnail"].get("path")
            return Post(name=job.name, video=job.folder / ctx["editor"]["video"],
                        duration=ctx["editor"]["duration"], metadata=ctx["copywriter"],
                        thumbnail=job.folder / thumb if thumb else None,
                        cover_time_ms=int(ctx["thumbnail"].get("cover_time_ms", 0)),
                        opts=job.opts(platform), settings=s)

        def run_one(platform: str) -> tuple[str, UploadResult | Exception]:
            try:
                return platform, UploadAgent(platform, s).run(post_for(platform))
            except Exception as e:  # each platform fails independently
                log.debug(traceback.format_exc())
                return platform, e

        ok = True
        if pending:
            with ThreadPoolExecutor(max_workers=len(pending)) as pool:
                results = list(pool.map(run_one, pending))
            for platform, res in results:
                prev_attempts = int(job.platform_state(platform).get("attempts", 0))
                if isinstance(res, Exception):
                    ok = False
                    log.error("[%s] %s: FAILED: %s", platform, job.name, res)
                    job.set_platform_state(platform, {"state": "failed", "error": str(res)[:2000],
                                                      "attempts": prev_attempts + 1})
                else:
                    state = "dry_run" if res.status == "dry_run" else "done"
                    log.info("[%s] %s: %s %s", platform, job.name, res.status, res.url or res.id)
                    job.set_platform_state(platform, {"state": state, "id": res.id, "url": res.url,
                                                      "status": res.status, **res.extra,
                                                      "attempts": prev_attempts + 1})
        return self._finish(job, ok)

    def _finish(self, job: Job, ok: bool) -> bool:
        job.state["finished"] = now_iso()
        job.state["result"] = "ok" if ok else "failed"
        job.save_state()
        dest = move(job.folder, self.settings.done if ok else self.settings.failed)
        log.info("=== job %s %s -> %s", job.name, "DONE" if ok else "FAILED", dest)
        return ok

    def _finish_failed(self, folder: Path, state: dict, error: str) -> bool:
        log.error("job %s: %s", folder.name, error)
        dest = move(folder, self.settings.failed)
        (dest / "error.txt").write_text(error + "\n", encoding="utf-8")
        return False
