import json

import pytest

from callqa import agreement


def test_compare_counts_and_metrics():
    human = {("e1", "barge_in", 0): True, ("e1", "barge_in", 5): False,
             ("e2", "barge_in", 1): True, ("e3", "barge_in", 2): False}
    pred = {("e1", "barge_in", 0): True, ("e1", "barge_in", 5): True, ("e9", "barge_in", 0): True}
    a = agreement.compare(pred, human)["barge_in"]
    assert (a.tp, a.fp, a.fn, a.tn, a.unlabeled) == (1, 1, 1, 1, 1)
    assert a.precision == 0.5 and a.recall == 0.5 and a.accuracy == 0.5
    assert a.kappa == pytest.approx(0.0)
    assert len(a.disagreements) == 2


def test_kappa_perfect_and_all_rollup():
    human = {("e1", "x", 0): True, ("e2", "x", 0): False, ("e3", "y", 0): True}
    pred = {("e1", "x", 0): True, ("e3", "y", 0): True}
    res = agreement.compare(pred, human)
    assert res["x"].kappa == pytest.approx(1.0)
    assert res["ALL"].n == 3 and res["ALL"].tp == 2 and res["ALL"].tn == 1


def test_empty_is_none_not_zero_division():
    a = agreement.compare({}, {})["ALL"]
    assert a.precision is None and a.recall is None and a.kappa is None


def test_load_csv_accepts_kind_or_item(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("execution_id,kind,index,label\ne1,slow_turn,2,true\ne1,barge_in,0,no\n")
    assert agreement.load_csv(p) == {("e1", "slow_turn", 2): True, ("e1", "barge_in", 0): False}


def test_load_label_studio_export(tmp_path):
    export = [
        {"id": 1, "data": {"execution_id": "e1", "kind": "barge_in", "index": 0},
         "annotations": [{"result": [{"from_name": "verdict", "type": "choices",
                                      "value": {"choices": ["Correct"]}}]}]},
        {"id": 2, "data": {"execution_id": "e2", "kind": "barge_in", "index": 3},
         "annotations": [{"result": [{"from_name": "verdict", "type": "choices",
                                      "value": {"choices": ["Wrong"]}}]}]},
        {"id": 3, "data": {"execution_id": "e3", "kind": "barge_in", "index": 1},
         "annotations": [{"was_cancelled": True, "result": []}]},
    ]
    p = tmp_path / "ls.json"
    p.write_text(json.dumps(export))
    assert agreement.load_label_studio(p) == {("e1", "barge_in", 0): True, ("e2", "barge_in", 3): False}
