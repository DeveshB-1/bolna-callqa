import json
from pathlib import Path

from callqa import cli

ROOT = Path(__file__).parent.parent
CALLS = sorted(str(p) for p in (ROOT / "fixtures" / "calls").glob("*.json"))


def test_scan_then_agree_end_to_end(tmp_path, capsys):
    flags = tmp_path / "flags.csv"
    assert cli.main(["scan", *CALLS, "--flags-out", str(flags)]) == 0
    out = capsys.readouterr().out
    assert "6 calls, 1 with a high-severity signal" in out
    assert flags.read_text().count("\n") == 12  # header + 11 flags

    assert cli.main(["agree", "--pred", str(flags), "--human", str(ROOT / "fixtures" / "human_labels.csv")]) == 0
    out = capsys.readouterr().out
    assert "| ALL | 13 | 90% | 90% | 0.57 | 1 | 1 | 1 |" in out
    assert "e5a6d3f1 #0   backchannel_cutoff   grader=issue human=ok" in out


def test_scan_json(capsys):
    cli.main(["scan", CALLS[0], "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data[0]["signals"][0]["kind"] == "barge_in"


def test_scan_live_path_uses_client(monkeypatch, capsys):
    bundle = json.loads(Path(CALLS[2]).read_text())

    class FakeClient:
        def iter_executions(self, agent_id, start, end):
            assert agent_id == "agent-1"
            yield from [{"id": "x1"}, {"id": "x2"}]

        def get_debug(self, eid, include=None):
            assert include == "execution,progression"
            return {**bundle, "execution_id": eid}

    monkeypatch.setattr(cli, "BolnaClient", FakeClient)
    cli.main(["scan", "--agent", "agent-1", "--limit", "1"])
    out = capsys.readouterr().out
    assert "1 calls" in out and "x1" in out and "x2" not in out
