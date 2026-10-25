"""How often does an automated grader agree with the people checking it?

Both sides are maps of key -> bool, where a key is (execution_id, item, index)
and True means "this issue really happened". The automated side can be:

- callqa's own signals (flagged = True; anything a human labelled but callqa
  did not flag counts as callqa saying False), or
- any LLM-as-judge's verdicts, loaded from CSV.

The human side comes from a CSV or a Label Studio JSON export.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

Key = tuple[str, str, int]
TRUTHY = {"1", "true", "yes", "y", "real", "correct", "agree", "issue", "happened"}


def _truthy(v) -> bool:
    return str(v).strip().lower() in TRUTHY


def load_csv(path: str | Path) -> dict[Key, bool]:
    """Columns: execution_id, item (or kind), index, label."""
    out: dict[Key, bool] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            item = row.get("item") or row.get("kind")
            out[(row["execution_id"], item, int(row.get("index") or 0))] = _truthy(row["label"])
    return out


def load_label_studio(path: str | Path, choice_field: str | None = None) -> dict[Key, bool]:
    """Label Studio JSON export. Task data needs execution_id, item/kind, index;
    the first choices annotation (or ``choice_field``) holds the verdict."""
    out: dict[Key, bool] = {}
    for task in json.loads(Path(path).read_text(encoding="utf-8")):
        data = task.get("data") or {}
        anns = [a for a in task.get("annotations") or [] if not a.get("was_cancelled")]
        if not anns:
            continue
        for res in anns[-1].get("result") or []:
            if res.get("type") != "choices" or (choice_field and res.get("from_name") != choice_field):
                continue
            choices = (res.get("value") or {}).get("choices") or []
            if choices:
                key = (data["execution_id"], data.get("item") or data.get("kind"), int(data.get("index") or 0))
                out[key] = _truthy(choices[0])
                break
    return out


@dataclass
class Agreement:
    n: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    unlabeled: int = 0          # flagged by the grader, no human label yet
    disagreements: list[tuple[Key, bool, bool]] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def accuracy(self) -> float | None:
        return (self.tp + self.tn) / self.n if self.n else None

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa between grader and human over the labelled keys."""
        if not self.n:
            return None
        po = (self.tp + self.tn) / self.n
        p_yes = ((self.tp + self.fp) / self.n) * ((self.tp + self.fn) / self.n)
        p_no = ((self.fn + self.tn) / self.n) * ((self.fp + self.tn) / self.n)
        pe = p_yes + p_no
        return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def compare(predicted: dict[Key, bool], human: dict[Key, bool]) -> dict[str, Agreement]:
    """Per-item agreement plus an ``ALL`` roll-up."""
    res: dict[str, Agreement] = {"ALL": Agreement()}
    for key, truth in human.items():
        pred = predicted.get(key, False)
        for name in (key[1], "ALL"):
            a = res.setdefault(name, Agreement())
            a.n += 1
            if pred and truth:
                a.tp += 1
            elif pred and not truth:
                a.fp += 1
            elif truth:
                a.fn += 1
            else:
                a.tn += 1
            if pred != truth and name != "ALL":
                a.disagreements.append((key, pred, truth))
    for key, pred in predicted.items():
        if pred and key not in human:
            res.setdefault(key[1], Agreement()).unlabeled += 1
            res["ALL"].unlabeled += 1
    return res
