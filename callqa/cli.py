"""callqa: call-quality signals for Bolna executions, and grader-vs-human agreement.

  callqa scan fixtures/calls/*.json --flags-out out/flags.csv
  callqa scan --agent <agent_id> --days 2 --limit 200        (needs BOLNA_API_KEY)
  callqa agree --pred out/flags.csv --human fixtures/human_labels.csv
  callqa judge fixtures/calls/*.json --out out/judge.csv     (needs JUDGE_* env)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import agreement, judge, signals
from .client import BolnaClient, BolnaError

SEV_ORDER = {"high": 0, "medium": 1, "info": 2}
MIN_KAPPA_N = 10


def _ms(v) -> str:
    return "-" if v is None else f"{v:.0f}"


def _pct(v) -> str:
    return "-" if v is None else f"{100 * v:.0f}%"


def load_bundles(args) -> list[dict]:
    if args.agent:
        client = BolnaClient()
        end = datetime.now(timezone.utc)
        bundles = []
        for ex in client.iter_executions(args.agent, end - timedelta(days=args.days), end):
            bundles.append(client.get_debug(ex["id"], include="execution,progression"))
            if len(bundles) >= args.limit:
                break
        return bundles
    return [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.files]


def render_scan(reports: list[signals.CallReport]) -> str:
    out = ["| call | turns | p50 ms | p95 ms | signals |", "|---|---|---|---|---|"]
    kinds: dict[str, int] = {}
    with_high = 0
    for r in reports:
        lat = r.latency_summary()
        c = r.counts()
        for k, v in c.items():
            kinds[k] = kinds.get(k, 0) + v
        with_high += any(s.severity == "high" for s in r.signals)
        sig = ", ".join(f"{k}={v}" for k, v in sorted(c.items())) or "clean"
        out.append(f"| {r.execution_id[:8]} | {lat['turns']} | {_ms(lat['p50_ms'])} | {_ms(lat['p95_ms'])} | {sig} |")
    out.append("")
    out.append(f"{len(reports)} calls, {with_high} with a high-severity signal")
    out.append("by kind: " + (", ".join(f"{k}={v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1])) or "none"))
    out.append("")
    for r in reports:
        for s in sorted(r.signals, key=lambda s: (SEV_ORDER.get(s.severity, 9), s.index)):
            est = " (time estimated)" if s.estimated else ""
            out.append(f"  [{s.severity:<6}] {r.execution_id[:8]} #{s.index:<3} {s.kind:<20} {s.detail}{est}")
    return "\n".join(out)


def cmd_scan(args) -> int:
    th = signals.Thresholds(slow_turn_ms=args.slow_turn_ms, slow_tool_ms=args.slow_tool_ms)
    reports = [signals.analyze(b, th) for b in load_bundles(args)]
    if args.json:
        print(json.dumps([{"execution_id": r.execution_id, "latency": r.latency_summary(),
                           "signals": [s.to_dict() for s in r.signals]} for r in reports], indent=2,
                         ensure_ascii=False))
    else:
        print(render_scan(reports))
    if args.flags_out:
        Path(args.flags_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.flags_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["execution_id", "kind", "index", "severity", "detail", "label"])
            for r in reports:
                for s in r.signals:
                    w.writerow([s.execution_id, s.kind, s.index, s.severity, s.detail, "true"])
    return 0


def cmd_agree(args) -> int:
    pred = agreement.load_csv(args.pred)
    human = (agreement.load_label_studio(args.human) if args.human.endswith(".json")
             else agreement.load_csv(args.human))
    res = agreement.compare(pred, human)
    print("| item | labelled | precision | recall | kappa | false + | missed | unlabelled |")
    print("|---|---|---|---|---|---|---|---|")
    for name in sorted(res, key=lambda k: (k == "ALL", k)):
        a = res[name]
        # kappa on a handful of labels is noise; show it once there are enough
        kappa = "-" if a.kappa is None or a.n < MIN_KAPPA_N else f"{a.kappa:.2f}"
        print(f"| {name} | {a.n} | {_pct(a.precision)} | {_pct(a.recall)} | {kappa} | {a.fp} | {a.fn} | {a.unlabeled} |")
    dis = [d for n, a in res.items() if n != "ALL" for d in a.disagreements]
    if dis:
        print("\ndisagreements (grader -> human):")
        for (eid, item, idx), p, h in dis:
            print(f"  {eid[:8]} #{idx:<3} {item:<20} grader={'issue' if p else 'ok'} human={'issue' if h else 'ok'}")
    return 0


def cmd_judge(args) -> int:
    chat = judge.openai_compatible_chat()
    rows = []
    for p in args.files:
        bundle = json.loads(Path(p).read_text(encoding="utf-8"))
        eid = bundle.get("execution_id", Path(p).stem)
        for item, v in judge.judge_call(bundle, chat).items():
            rows.append([eid, item, 0, "true" if v["verdict"] else "false", v["reason"]])
    w = csv.writer(open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout)
    w.writerow(["execution_id", "item", "index", "label", "reason"])
    w.writerows(rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="callqa", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="flag call-quality signals in debug bundles")
    s.add_argument("files", nargs="*", help="saved GET /executions/{id}/debug responses")
    s.add_argument("--agent", help="pull live executions for this agent (BOLNA_API_KEY)")
    s.add_argument("--days", type=int, default=1)
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--slow-turn-ms", type=float, default=2000)
    s.add_argument("--slow-tool-ms", type=float, default=2500)
    s.add_argument("--json", action="store_true")
    s.add_argument("--flags-out")
    s.set_defaults(fn=cmd_scan)

    a = sub.add_parser("agree", help="score a grader's flags against human labels")
    a.add_argument("--pred", required=True, help="CSV from scan --flags-out or judge --out")
    a.add_argument("--human", required=True, help="CSV, or Label Studio JSON export")
    a.set_defaults(fn=cmd_agree)

    j = sub.add_parser("judge", help="LLM-as-judge rubric over transcripts (JUDGE_* env)")
    j.add_argument("files", nargs="+")
    j.add_argument("--out")
    j.set_defaults(fn=cmd_judge)

    args = ap.parse_args(argv)
    if args.cmd == "scan" and not (args.files or args.agent):
        ap.error("scan needs bundle files or --agent")
    try:
        return args.fn(args)
    except (BolnaError, ValueError) as e:
        print(f"callqa: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
