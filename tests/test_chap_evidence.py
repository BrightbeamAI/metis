
from metis.audit.replay import replay
from metis.integrations.chap.adapter import CHAPAdapter


def test_chain_links_and_verifies():
    a = CHAPAdapter("wsp_ev", "Evidence test", deterministic=True)
    a.join("human:alice@x", "operator")
    tid = a.create_task("tacit.capture", assignee="agent:w#1", delegator="human:alice@x")
    a.append_artefact("tacit.fragment", produced_by="human:alice@x", content={"k": "v"}, task=tid)
    vr = a.verify()
    assert vr.ok and vr.checked >= 4
    # genesis prev_hash
    assert a.chain.entries[0].prev_hash.endswith("0" * 8)


def test_tamper_is_detected():
    a = CHAPAdapter("wsp_ev2", "Tamper test", deterministic=True)
    a.join("human:bob@x", "operator")
    a.chain.entries[1].envelope["params"]["injected"] = True
    assert not a.verify().ok


def test_export_replays_independently(tmp_path, manufacturing_run):
    out = tmp_path / "evidence.jsonl"
    n = manufacturing_run.engine.export_audit(str(out))
    result = replay(out)
    assert result.ok
    assert result.checked == n
    assert result.methods[0] == "workspace.create"


def test_chain_is_hash_linked():
    a = CHAPAdapter("wsp_ev3", "Chain test", deterministic=True)
    a.join("human:carol@x", "operator")
    # The canonical chain is hash-linked: genesis prev is zero, the head is a sha256 digest.
    assert a.chain.entries[0].prev_hash.endswith("0" * 8)
    assert a.chain.head.startswith("sha256:")
    assert a.verify().ok
