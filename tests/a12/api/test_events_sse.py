"""SSE event stream: monotonic seq, revision, reconnect through ``Last-Event-ID``.

These tests drive the real ASGI app (see ``_sse_client``) because the pinned
starlette-1.7/httpx2 stack cannot read a stream that never finishes.
"""

from __future__ import annotations

import json
import time

from _sse_client import asgi_stream
from tests.a12.api.api_test_support import create_job, run_worker_once

PREFIX = "/api/synlab"


def _parse_sse(text: str, *, keep_stream_end: bool = False) -> list[dict]:
    """Parse SSE frames; ``stream_end`` is the transport sentinel, not a job event."""
    events: list[dict] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if line == "":
            if current.get("data"):
                events.append({"id": current.get("id"), "event": current.get("event"),
                               "data": json.loads(current["data"])})
            current = {}
            continue
        if line.startswith(":"):
            current.setdefault("comments", "")
            continue
        field, _, value = line.partition(":")
        current[field.strip()] = value.strip()
    if current.get("data"):
        events.append({"id": current.get("id"), "event": current.get("event"),
                       "data": json.loads(current["data"])})
    if not keep_stream_end:
        events = [event for event in events if event["event"] != "stream_end"]
    return events


def _app_of(client):
    return client.app


def _replay(app, run_id: str, **params) -> str:
    """Replay a non-following SSE response to completion and return the raw body."""
    query = "&".join(f"{key}={value}" for key, value in {"follow": "false", **params}.items())
    with asgi_stream(app, "GET", f"{PREFIX}/runs/{run_id}/events?{query}") as stream:
        assert stream.status_code == 200
        response = stream.read_to_end()
    assert response.finished, "follow=false must close the stream itself"
    return response.body


def test_events_of_one_run_are_never_diluted_by_other_runs(researcher):
    """A shared event log must not leak another run's events, nor cap a run's own stream.

    The store keeps one global ordered log, so this exercises the per-run filtering and the
    batch-draining path that a busy store hits and a single-run test cannot.
    """
    for index in range(4):
        create_job(researcher, stage="freeze_spec", key=f"sse-noise-{index}")
    target = create_job(researcher, stage="freeze_spec", key="sse-target").json()["run_id"]

    app = _app_of(researcher)
    events = _parse_sse(_replay(app, target))
    assert events, "the target run must have its own events"
    assert {event["data"]["run_id"] for event in events} == {target}
    seqs = [event["data"]["seq"] for event in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert {"run.created", "job.created", "run.accepted"}.issubset(
        {event["data"]["type"] for event in events})

    # a batch smaller than the run's own event count still drains every batch
    tiny = _parse_sse(_replay(app, target, limit=1))
    assert [event["data"]["seq"] for event in tiny] == seqs


def test_events_are_monotonic_and_reconnect_resumes_after_last_event_id(store_root, researcher,
                                                                       cube_asset):
    created = create_job(researcher, stage="freeze_spec", key="sse-1",
                         input_refs=[cube_asset]).json()
    run_id = created["run_id"]
    run_worker_once(store_root)

    app = _app_of(researcher)
    with asgi_stream(app, "GET", f"{PREFIX}/runs/{run_id}/events?follow=false&limit=500") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        response = stream.read_to_end()
    assert response.finished
    events = _parse_sse(response.body)
    assert events, "a committed job must have produced events"
    seqs = [event["data"]["seq"] for event in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "seq must be unique"
    types = {event["data"]["type"] for event in events}
    assert {"run.created", "job.created", "run.accepted"}.issubset(types)
    assert "job.committed" in types
    assert all(event["data"]["run_id"] == run_id for event in events)
    assert all("revision" in event["data"] for event in events)

    committed = [e for e in events if e["data"]["type"] == "job.committed"][0]["data"]
    assert committed["state"] == "COMMITTED"
    assert committed["metrics_ref"] and committed["metrics_ref"].startswith("metrics_")
    assert committed["progress"] is None or "done" in committed["progress"]

    midpoint = seqs[len(seqs) // 2]
    replayed = _parse_sse(_replay(app, run_id, after_seq=midpoint))
    assert [e["data"]["seq"] for e in replayed] == [s for s in seqs if s > midpoint]

    # reconnect purely from the SSE id, exactly as a browser EventSource does
    last_id = str(midpoint)
    with asgi_stream(app, "GET", f"{PREFIX}/runs/{run_id}/events?follow=false",
                     headers={"Last-Event-ID": last_id}) as stream:
        assert stream.status_code == 200
        resumed_response = stream.read_to_end()
    assert resumed_response.finished
    resumed_events = _parse_sse(resumed_response.body)
    assert [e["data"]["seq"] for e in resumed_events] == [s for s in seqs if s > midpoint]

    # a duplicate delivery of the same events is idempotent for the client: same seqs, no new state
    again = _parse_sse(_replay(app, run_id, after_seq=midpoint))
    assert [e["data"]["seq"] for e in again] == [e["data"]["seq"] for e in resumed_events]


def test_events_after_seq_is_the_final_word_and_unknown_run_is_404(store_root, researcher):
    created = create_job(researcher, stage="freeze_spec", key="sse-2").json()
    run_id = created["run_id"]
    run_worker_once(store_root)
    app = _app_of(researcher)

    full = _parse_sse(_replay(app, run_id))
    assert full, "the committed run must have events"
    tail = _parse_sse(_replay(app, run_id, after_seq=full[-1]["data"]["seq"]))
    assert tail == []

    with asgi_stream(app, "GET", f"{PREFIX}/runs/run_nope/events?follow=false") as stream:
        assert stream.status_code == 404
        body = stream.body_json()
    assert body["error"]["code"] == "NOT_FOUND"


def test_events_bad_last_event_id_is_rejected(store_root, researcher):
    created = create_job(researcher, stage="freeze_spec", key="sse-3").json()
    with asgi_stream(_app_of(researcher), "GET",
                     f"{PREFIX}/runs/{created['run_id']}/events?follow=false",
                     headers={"Last-Event-ID": "abc"}) as stream:
        assert stream.status_code == 400
        body = stream.body_json()
    assert body["error"]["code"] == "BAD_REQUEST"
    assert "Last-Event-ID" in body["error"]["message"]


def test_heartbeat_is_a_comment_not_a_fake_progress_event(store_root, researcher):
    created = create_job(researcher, stage="freeze_spec", key="sse-4").json()
    started = time.monotonic()
    with asgi_stream(_app_of(researcher), "GET",
                     f"{PREFIX}/runs/{created['run_id']}/events?follow=true&poll_ms=150") as stream:
        assert stream.status_code == 200
        # read a bounded window of an idle follow stream, then hang up like a browser would
        text = stream.read_for(1.5)
        elapsed = time.monotonic() - started
        hung_up = stream.close()
    lines = text.splitlines()
    assert lines, "the stream must open with a header comment"
    assert lines[0].startswith(": synlab events run=")
    heartbeats = [line for line in lines if line.startswith(": heartbeat")]
    assert heartbeats, "an idle stream emits comment heartbeats, not progress events"
    assert all("progress" not in line for line in heartbeats)
    # No fabricated progress is ever produced on an idle stream.  The envelope always carries
    # a ``progress`` key, so the honest check is that it stays null (and never a bare
    # percentage) while nothing has been counted.
    assert all(event["data"]["progress"] is None for event in _parse_sse(text))
    assert not any("%" in line for line in lines if line.startswith("data:"))
    # the idle stream keeps producing until the client itself hangs up
    assert elapsed >= 1.4, elapsed
    assert hung_up, "the stream must still be open when the client disconnects"
