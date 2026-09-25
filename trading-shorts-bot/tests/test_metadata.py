from pathlib import Path

from job import Job
from metadata import generate, truncate, utf16_len
from upload_tiktok import chunk_plan


def _job(meta, caption="Line one\nLine two"):
    return Job(Path("/tmp/x"), [Path("/tmp/x/a.mp4")], caption, meta, meta.get("subject", "ORB strategy"), None)


def test_meta_json_wins_and_limits_apply(settings):
    meta = {"title": "T" * 120, "description": "Desc <b>", "tags": ["orb", "day trading"],
            "hashtags": ["#trading", "stocks"], "thumbnail_text": "ORB", "tiktok": {"caption": "Short!"}}
    md = generate(_job(meta), settings)
    assert md["source"] == "meta.json"
    assert len(md["youtube"]["title"]) <= 100
    assert "<" not in md["youtube"]["description"]
    assert "#Shorts" in md["youtube"]["description"]
    assert md["youtube"]["tags"][:2] == ["orb", "day trading"]
    assert md["instagram"]["caption"].endswith("#trading #stocks")
    assert md["tiktok"]["caption"].startswith("Short!")


def test_shorts_tag_added_to_title(settings):
    md = generate(_job({"title": "Opening range breakout", "description": "d", "tags": ["a"],
                        "hashtags": ["b"], "thumbnail_text": "x"}), settings)
    assert md["youtube"]["title"] == "Opening range breakout #Shorts"


def test_template_fallback_without_claude(settings):
    md = generate(_job({"subject": "Opening range breakout strategy"}), settings)
    assert md["source"] == "template"
    assert md["youtube"]["title"].startswith("Opening range breakout strategy")


def test_truncate_utf16():
    s = "😀" * 2000
    assert utf16_len(truncate(s, 2200, measure=utf16_len)) <= 2200


def test_tiktok_chunk_plan():
    mb = 1024 * 1024
    assert chunk_plan(30 * mb) == (30 * mb, 1)
    size, count = chunk_plan(95 * mb)
    assert size == 10 * mb and count == 9  # last chunk carries the 5 MB remainder


def test_claude_request_and_merge(settings, monkeypatch):
    import dataclasses
    import json as _json
    from types import SimpleNamespace

    import anthropic

    captured = {}

    class FakeMessages:
        def create(self, **kw):
            captured.update(kw)
            out = {"title": "Claude title", "description": "Claude desc", "tags": ["x"], "hashtags": ["y"],
                   "instagram_caption": "IG", "tiktok_caption": "TT", "thumbnail_text": "HOOK"}
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=_json.dumps(out))])

    class FakeClient:
        def __init__(self, **kw):
            self.beta = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    s = dataclasses.replace(settings, metadata_mode="fill")
    md = generate(_job({"subject": "ORB", "title": "My own title"}), s, duration=60)
    assert captured["model"] == "claude-opus-5"
    assert captured["fallbacks"] == "default"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert md["source"].startswith("claude")
    assert md["youtube"]["title"] == "My own title #Shorts"   # meta.json beats Claude
    assert md["thumbnail_text"] == "HOOK"
