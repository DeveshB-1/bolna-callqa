"""Deterministic call-quality signals over a Bolna execution debug bundle.

Input is the JSON returned by ``GET /executions/{execution_id}/debug``
(sections ``execution``, ``progression`` and ``logs``). Only ``progression``
is required: its ``turns`` carry per-turn latency in ms and its ``transcript``
holds message, function_call and event rows in call order.

Every signal points at a row (transcript index) or a turn id, so a person
checking it in Label Studio or the dashboard can jump straight to the moment.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

# Short acknowledgements callers say while the agent is talking. When one of
# these is the only thing the caller said after the agent was cut off, the
# agent most likely stopped for a backchannel, not a real interruption.
BACKCHANNEL = {
    "haan", "haa", "han", "ha", "ji", "hmm", "hm", "hmmm", "ok", "okay", "okk",
    "achha", "acha", "accha", "theek", "thik", "hai", "yes", "yeah", "yep",
    "right", "uh", "huh", "sure", "bilkul", "sahi", "ho", "haanji", "hanji",
    "हाँ", "हां", "जी", "ठीक", "है", "अच्छा", "हम्म", "ओके",
}
# A last caller message holding one of these words is a goodbye, not a question left hanging.
CLOSERS = {"bye", "thanks", "thank", "dhanyavaad", "dhanyawad", "shukriya", "alvida", "बाय", "धन्यवाद"}
OK_TOOL_STATUS = {"success", "succeeded", "completed", "ok"}


@dataclass
class Thresholds:
    slow_turn_ms: float = 2000.0   # caller stops speaking -> agent starts speaking
    slow_tool_ms: float = 2500.0
    repeat_ratio: float = 0.85     # difflib ratio for "agent said this already"
    repeat_min_chars: int = 20


@dataclass
class Signal:
    execution_id: str
    kind: str
    index: int            # transcript row index, or turn_id for slow_turn
    severity: str         # high | medium | info
    detail: str
    ts_ms: float | None = None
    estimated: bool = False  # row time was estimated (ts_exact == false)

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.execution_id, self.kind, self.index)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CallReport:
    execution_id: str
    signals: list[Signal] = field(default_factory=list)
    response_ms: list[float] = field(default_factory=list)
    unavailable: dict = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.signals:
            out[s.kind] = out.get(s.kind, 0) + 1
        return out

    def latency_summary(self) -> dict[str, float | None]:
        r = sorted(self.response_ms)
        if not r:
            return {"turns": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
        p95 = r[min(len(r) - 1, round(0.95 * (len(r) - 1)))]
        return {"turns": len(r), "p50_ms": statistics.median(r), "p95_ms": p95, "max_ms": r[-1]}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^\wऀ-ॿ]+", (text or "").lower()) if w]


def is_backchannel(text: str) -> bool:
    w = _words(text)
    return 0 < len(w) <= 3 and all(x in BACKCHANNEL for x in w)


def is_closing(text: str) -> bool:
    return "?" not in (text or "") and any(x in CLOSERS for x in _words(text))


# The four measured gaps between "caller stopped" and "agent started speaking".
STAGES = [
    ("asr_end_to_user_end_ms", "endpointing"),
    ("llm_start_to_asr_end_ms", "llm_queue"),
    ("tts_start_to_llm_start_ms", "llm_to_tts"),
    ("agent_speech_to_tts_start_ms", "tts_to_audio"),
]


def response_ms(turn: dict) -> tuple[float, str] | None:
    """Perceived response time for one turn and the stage that took longest."""
    parts = {name: float(turn[k]) for k, name in STAGES if isinstance(turn.get(k), (int, float))}
    if not parts:
        return None
    total = sum(v for v in parts.values() if v > 0)
    worst = max(parts, key=parts.get)
    return total, worst


def analyze(bundle: dict, th: Thresholds | None = None) -> CallReport:
    th = th or Thresholds()
    eid = bundle.get("execution_id") or (bundle.get("execution") or {}).get("id") or "unknown"
    rep = CallReport(execution_id=eid, unavailable=dict(bundle.get("unavailable") or {}))
    prog = bundle.get("progression") or {}

    for turn in prog.get("turns") or []:
        r = response_ms(turn)
        if r is None:
            continue
        total, worst = r
        rep.response_ms.append(total)
        if total > th.slow_turn_ms:
            tid = turn.get("turn_id", turn.get("sequence_id", -1))
            rep.signals.append(Signal(eid, "slow_turn", int(tid), "medium",
                                      f"{total:.0f} ms to respond, worst stage {worst}"))

    rows = prog.get("transcript") or []
    agent_said: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        kind, role, text = row.get("kind"), row.get("role"), row.get("text") or ""
        est = row.get("ts_exact") is False
        ts = row.get("ts_ms")

        def add(k: str, sev: str, detail: str) -> None:
            rep.signals.append(Signal(eid, k, i, sev, detail, ts, est))

        if kind == "message" and role == "agent":
            if row.get("interrupted"):
                nxt = next((r for r in rows[i + 1:] if r.get("kind") == "message" and r.get("role") == "user"), None)
                said = (nxt or {}).get("text", "")
                if nxt is not None and is_backchannel(said):
                    add("backchannel_cutoff", "medium", f'agent stopped for "{said}"')
                else:
                    add("barge_in", "info", f'caller cut in: "{said[:60]}"' if said else "agent interrupted")
            if len(text) >= th.repeat_min_chars:
                for j, prev in agent_said:
                    if SequenceMatcher(None, prev.lower(), text.lower()).ratio() >= th.repeat_ratio:
                        add("agent_repeat", "medium", f"repeats row {j}: \"{text[:60]}\"")
                        break
                agent_said.append((i, text))
        elif kind == "message" and role == "user" and row.get("not_sent_to_agent"):
            add("dropped_user_speech", "medium", f'transcribed, never reached the LLM: "{text[:60]}"')
        elif kind == "function_call":
            status = str(row.get("status") or "").lower()
            code = row.get("response_status_code")
            if (status and status not in OK_TOOL_STATUS) or (isinstance(code, int) and code >= 400):
                add("tool_failure", "high", f"{row.get('tool_name')} status={status or '-'} http={code}")
            lat = row.get("tool_latency_ms")
            if isinstance(lat, (int, float)) and lat > th.slow_tool_ms:
                add("slow_tool", "medium", f"{row.get('tool_name')} took {lat:.0f} ms")

    msgs = [(i, r) for i, r in enumerate(rows) if r.get("kind") == "message"]
    if msgs:
        i, last = msgs[-1]
        if last.get("role") == "user" and not is_closing(last.get("text", "")):
            rep.signals.append(Signal(eid, "unanswered_hangup", i, "high",
                                      f'call ended on the caller: "{last.get("text", "")[:60]}"',
                                      last.get("ts_ms"), last.get("ts_exact") is False))
    return rep
