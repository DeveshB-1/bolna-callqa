import json
from pathlib import Path

import pytest

from callqa import signals

CALLS = Path(__file__).parent.parent / "fixtures" / "calls"


def load(prefix):
    return json.loads(next(CALLS.glob(f"{prefix}*.json")).read_text())


def kinds(prefix, **kw):
    return sorted((s.kind, s.index) for s in signals.analyze(load(prefix), signals.Thresholds(**kw)).signals)


def test_real_barge_in_is_info():
    rep = signals.analyze(load("a1c04e2b"))
    assert [(s.kind, s.severity) for s in rep.signals] == [("barge_in", "info")]


def test_backchannel_repeat_and_slow_tool():
    assert kinds("b2d19a7e") == [("agent_repeat", 2), ("backchannel_cutoff", 0), ("slow_tool", 4), ("slow_turn", 2)]


def test_tool_failure_and_unanswered_hangup():
    got = {s.kind: s for s in signals.analyze(load("c3e88b10")).signals}
    assert got["tool_failure"].severity == "high"
    assert "http=500" in got["tool_failure"].detail
    assert got["unanswered_hangup"].index == 4


def test_dropped_speech_keeps_estimated_time_flag():
    got = {s.kind: s for s in signals.analyze(load("d4f2c7a9")).signals}
    assert got["dropped_user_speech"].estimated is True
    assert "endpointing" in got["slow_turn"].detail


def test_clean_call_has_no_signals():
    assert signals.analyze(load("f6b3e9c2")).signals == []


def test_thresholds_are_respected():
    assert ("slow_turn", 2) not in kinds("b2d19a7e", slow_turn_ms=5000)
    assert ("slow_tool", 4) not in kinds("b2d19a7e", slow_tool_ms=5000)


@pytest.mark.parametrize("text,expected", [
    ("haan", True), ("ok ok", True), ("haan ji", True), ("हाँ जी", True), ("Hmm.", True),
    ("haan bolo kab aayega", False), ("ruko", False), ("", False),
])
def test_backchannel(text, expected):
    assert signals.is_backchannel(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("Theek hai, bye", True), ("Ok ji, dhanyavaad", True), ("bye? hello?", False), ("Kya hua?", False),
])
def test_closing(text, expected):
    assert signals.is_closing(text) is expected


def test_response_ms_sums_stages_and_names_worst():
    total, worst = signals.response_ms({"asr_end_to_user_end_ms": 300, "llm_start_to_asr_end_ms": 100,
                                        "tts_start_to_llm_start_ms": 1200, "agent_speech_to_tts_start_ms": 200})
    assert (total, worst) == (1800, "llm_to_tts")
    assert signals.response_ms({"llm_duration_ms": 900}) is None


def test_missing_progression_is_reported_not_crashed():
    rep = signals.analyze({"execution_id": "x", "unavailable": {"progression": "not_available"},
                           "progression": None})
    assert rep.signals == [] and rep.unavailable == {"progression": "not_available"}
    assert rep.latency_summary()["p50_ms"] is None


def test_latency_summary():
    rep = signals.analyze(load("b2d19a7e"))
    s = rep.latency_summary()
    assert s["turns"] == 3 and s["max_ms"] == 3600 and s["p50_ms"] == 1050
