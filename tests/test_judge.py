import json

import pytest

from callqa import judge

BUNDLE = {"execution_id": "e1", "progression": {"transcript": [
    {"kind": "message", "role": "agent", "text": "Your EMI is due", "interrupted": True},
    {"kind": "message", "role": "user", "text": "Mera account freeze hai"},
    {"kind": "function_call", "tool_name": "send_link", "status": "success"},
    {"kind": "event", "label": "hangup"}]}}


def test_transcript_text_marks_interruptions_and_tools():
    t = judge.transcript_text(BUNDLE)
    assert "[0] agent: Your EMI is due [interrupted]" in t
    assert "[2] tool send_link -> success" in t and "[3] event: hangup" in t


def test_judge_call_parses_json_inside_prose():
    seen = {}

    def chat(messages):
        seen["messages"] = messages
        body = {k: {"verdict": k == "language_mismatch", "reason": "r"} for k in judge.RUBRIC}
        return "Sure, here you go:\n" + json.dumps(body)

    out = judge.judge_call(BUNDLE, chat)
    assert out["language_mismatch"]["verdict"] is True and out["ignored_question"]["verdict"] is False
    assert "Mera account freeze hai" in seen["messages"][1]["content"]


def test_missing_item_or_no_json_raises():
    with pytest.raises(ValueError):
        judge.parse_verdicts('{"language_mismatch": true}')
    with pytest.raises(ValueError):
        judge.parse_verdicts("I cannot grade this call.")
