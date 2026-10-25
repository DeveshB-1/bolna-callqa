# bolna-callqa

Call-quality signals for Bolna voice agent calls, plus a way to check any automated grader against the people who listen to the calls.

It reads the debug bundle Bolna already exposes (`GET /executions/{execution_id}/debug`: per-turn latency and the structured transcript), flags the moments worth a listen, and points each flag at a transcript row or turn id. Then `callqa agree` scores those flags, or an LLM judge's verdicts, against human labels from a CSV or a Label Studio export: precision, recall, Cohen's kappa and the exact rows where grader and human disagree.

Stdlib only. Python 3.10+.

## Why this is for Bolna

Bolna's Conversation Quality Analyst posting describes the loop this tool is built around: automated systems grade calls ("LLM-as-judge evals and quantitative signal detection"), and people verify them, for example "confirming whether a detected barge-in ... genuinely happened" and flagging "false positives/negatives so we can tighten detection logic". callqa is a small open version of both halves:

1. **Signals** a counter can find in the debug bundle, each with a row to jump to.
2. **Agreement** between any grader and human labels, so a detector or judge change shows up as a number before it ships.

## Signals

| kind | severity | fires when |
|---|---|---|
| `tool_failure` | high | a function_call row has a non-success status or HTTP >= 400 |
| `unanswered_hangup` | high | the last message is the caller's and it isn't a goodbye (`?` or no bye/dhanyavaad/shukriya/thanks) |
| `slow_turn` | medium | caller stops speaking to agent speaking (sum of the 4 measured stages) > 2000 ms; names the worst stage |
| `slow_tool` | medium | `tool_latency_ms` > 2500 |
| `backchannel_cutoff` | medium | agent message `interrupted` and the caller's next words are only an acknowledgement ("haan", "ok ok", "हाँ जी") |
| `agent_repeat` | medium | an agent message is >= 85% similar to an earlier one in the call |
| `dropped_user_speech` | medium | a user row has `not_sent_to_agent: true` |
| `barge_in` | info | agent message `interrupted` and the caller said something real |

Rows with `ts_exact: false` keep a `(time estimated)` marker so a reviewer knows the position is approximate. Thresholds are flags (`--slow-turn-ms`, `--slow-tool-ms`).

## Quickstart

```bash
# offline, on the bundled fixtures
python -m callqa scan fixtures/calls/*.json --flags-out out/flags.csv
python -m callqa agree --pred out/flags.csv --human fixtures/human_labels.csv

# live, against your account (last 2 days of completed calls for one agent)
export BOLNA_API_KEY=...
python -m callqa scan --agent <agent_id> --days 2 --limit 200 --flags-out out/flags.csv

# score an LLM judge instead of the signals (any OpenAI-compatible endpoint)
export JUDGE_BASE_URL=https://api.openai.com/v1 JUDGE_API_KEY=... JUDGE_MODEL=gpt-4o-mini
python -m callqa judge fixtures/calls/*.json --out out/judge.csv
python -m callqa agree --pred out/judge.csv --human my_judge_labels.csv

# tests
uv run --with pytest python -m pytest -q
```

Human labels: CSV with `execution_id,kind,index,label` (`item` works in place of `kind`), or a Label Studio JSON export whose task data carries `execution_id`, `kind`, `index` and whose choices answer is Correct/Yes/True vs anything else.

## Demo run

On the 6 bundled calls (2 EMI reminders, order status, clinic booking, loan lead, policy renewal):

```
$ python -m callqa scan fixtures/calls/*.json --flags-out out/flags.csv
| call | turns | p50 ms | p95 ms | signals |
|---|---|---|---|---|
| a1c04e2b | 3 | 1020 | 1040 | barge_in=1 |
| b2d19a7e | 3 | 1050 | 3600 | agent_repeat=1, backchannel_cutoff=1, slow_tool=1, slow_turn=1 |
| c3e88b10 | 2 | 2030 | 3090 | slow_turn=1, tool_failure=1, unanswered_hangup=1 |
| d4f2c7a9 | 3 | 1010 | 3010 | dropped_user_speech=1, slow_turn=1 |
| e5a6d3f1 | 2 | 970 | 980 | backchannel_cutoff=1 |
| f6b3e9c2 | 2 | 1030 | 1040 | clean |

6 calls, 1 with a high-severity signal
by kind: slow_turn=3, backchannel_cutoff=2, barge_in=1, agent_repeat=1, slow_tool=1, tool_failure=1, unanswered_hangup=1, dropped_user_speech=1

  [info  ] a1c04e2b #0   barge_in             caller cut in: "Ruko ruko, maine kal hi pay kar diya hai"
  [medium] b2d19a7e #0   backchannel_cutoff   agent stopped for "haan"
  [medium] b2d19a7e #2   slow_turn            3600 ms to respond, worst stage llm_to_tts
  [medium] b2d19a7e #2   agent_repeat         repeats row 0: "Hi Priya, this is Kart support. I can see you have an order "
  [medium] b2d19a7e #4   slow_tool            get_order_status took 3400 ms
  [high  ] c3e88b10 #2   tool_failure         book_slot status=error http=500
  [high  ] c3e88b10 #4   unanswered_hangup    call ended on the caller: "Hello? Kya hua, booking hua ki nahi?"
  [medium] c3e88b10 #2   slow_turn            3090 ms to respond, worst stage llm_to_tts
  [medium] d4f2c7a9 #1   slow_turn            3010 ms to respond, worst stage endpointing
  [medium] d4f2c7a9 #3   dropped_user_speech  transcribed, never reached the LLM: "Ek minute, mere paas PAN card bhi hai" (time estimated)
  [medium] e5a6d3f1 #0   backchannel_cutoff   agent stopped for "ok ok"
```

Then against 13 human labels (2 of which disagree with the grader on purpose):

```
$ python -m callqa agree --pred out/flags.csv --human fixtures/human_labels.csv
| item | labelled | precision | recall | kappa | false + | missed | unlabelled |
|---|---|---|---|---|---|---|---|
| agent_repeat | 1 | 100% | 100% | - | 0 | 0 | 0 |
| backchannel_cutoff | 2 | 50% | 100% | - | 1 | 0 | 0 |
| barge_in | 2 | 100% | 50% | - | 0 | 1 | 0 |
| dropped_user_speech | 1 | 100% | 100% | - | 0 | 0 | 0 |
| slow_tool | 1 | 100% | 100% | - | 0 | 0 | 0 |
| slow_turn | 2 | 100% | 100% | - | 0 | 0 | 1 |
| tool_failure | 1 | 100% | 100% | - | 0 | 0 | 0 |
| unanswered_hangup | 3 | 100% | 100% | - | 0 | 0 | 0 |
| ALL | 13 | 90% | 90% | 0.57 | 1 | 1 | 1 |

disagreements (grader -> human):
  f6b3e9c2 #0   barge_in             grader=ok human=issue
  e5a6d3f1 #0   backchannel_cutoff   grader=issue human=ok
```

The two disagreements are the interesting part, and they are the kind a real annotation pass turns up:

- `e5a6d3f1 backchannel_cutoff`: the caller said "ok ok" and the agent stopped listing plans. The heuristic calls that a cut-off on a backchannel; the human says the caller meant "skip it", so stopping was right. One word-list can't tell those apart, so this kind needs a judge or audio.
- `f6b3e9c2 barge_in`: the annotator heard the caller talk over the opener, but the transcript has no `interrupted` flag on that row, so no transcript-only detector can catch it. That miss is a pointer back at the detection logic upstream.

Kappa is only printed once an item has 10+ labels; on 1 or 2 labels it's noise.

## Honest scope

- The 6 calls in `fixtures/calls/` are **synthetic**. I wrote them (`fixtures/make_fixtures.py`) to match the documented debug-bundle schema; I don't have a Bolna API key, so no real call data went through this. The human labels are synthetic too.
- The live path is wired and was exercised up to auth: `scan --agent` with a bad key reaches `api.bolna.ai` and returns `Bolna API returned 403: {"detail":"Unrecognized access token"}`. With a real key it should work as-is, but field names in real bundles may differ from the docs in places I couldn't check.
- The LLM judge path (`callqa judge`) is unit-tested with a stubbed model; I haven't run it against a live model.
- Agreement treats an unflagged, human-labelled key as the grader saying "no issue". Flags with no human label are counted as `unlabelled`, never as wrong.

## Layout

```
callqa/signals.py    detectors over one debug bundle
callqa/agreement.py  grader vs human: precision, recall, kappa, disagreements
callqa/judge.py      rubric LLM judge (OpenAI-compatible), JSON verdicts
callqa/client.py     GET /v2/agent/{id}/executions (7-day windows, paginated), GET /executions/{id}/debug
callqa/cli.py        scan | agree | judge
```
