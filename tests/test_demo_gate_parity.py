"""The interactive demo's JavaScript gate must agree with the Python gate, case by case."""
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from metis import clock
from metis.conditions.context import TacitContext
from metis.consent.model import ConsentStatus
from metis.retrieval.gate import RetrievalGate
from metis.scenarios import SPECS, run_spec
from metis.taxonomy.categories import AuthorityLayer, RevocationStatus

NODE = shutil.which("node")
TEMPLATE = Path(__file__).resolve().parents[1] / "scripts" / "demo_template.html"


def _cases():
    out = []
    for key, spec in SPECS.items():
        run = run_spec(spec)
        frag = run.fragment
        m = dict(spec.match_context)
        conditions = frag.conditions.model_dump(mode="json")
        identity = next(k for k in ("equipment_family", "product_family", "area") if conditions.get(k))
        situational = next(k for k in ("operating_mode", "shift_pattern", "trigger_context")
                           if conditions.get(k))
        ex = (conditions.get("exclusion_conditions") or [None])[0]
        variants = [
            ("match", m, {}),
            ("wrong identity", {**m, identity: "other_" + identity}, {}),
            ("wrong identity at high risk", {**m, identity: "other_" + identity, "risk_class": "high"}, {}),
            ("near miss", {**m, situational: "other_" + situational}, {}),
            ("near miss at high risk", {**m, situational: "other_" + situational, "risk_class": "high"}, {}),
            ("unknown situation", {**m, situational: None}, {}),
            ("high risk", {**m, "risk_class": "high"}, {}),
            ("visitor role", {**m, "role": "visitor"}, {}),
            ("consent withdrawn", m, {"consent": "withdrawn"}),
            ("consent withdrawn, wrong identity", {**m, identity: "other_" + identity}, {"consent": "withdrawn"}),
            ("revoked", m, {"revoked": True}),
            ("expired", m, {"expired": True}),
            ("evidence layer", m, {"authority": "evidence"}),
        ]
        if ex:
            k, v = next(iter(ex.items()))
            variants.append(("exclusion", {**m, k: [m[k], v]}, {}))
        for name, ctx, ov in variants:
            out.append((f"{key}: {name}", run.engine, frag, ctx, ov))
    return out


def _python(engine, frag, ctx, ov):
    with clock.use(engine.clock_source):
        return _python_on_timeline(frag, ctx, ov)


def _python_on_timeline(frag, ctx, ov):
    f = frag.model_copy(deep=True)
    if ov.get("authority"):
        f.authority_layer = AuthorityLayer(ov["authority"])
    if ov.get("revoked"):
        f.revocation_status = RevocationStatus.superseded
    if ov.get("consent") == "withdrawn":
        f.consent.consent_status = ConsentStatus.withdrawn
    if ov.get("expired"):
        f.review_due_at = (clock.now_dt() - dt.timedelta(days=1)).isoformat()
    context = TacitContext(**{k: v for k, v in ctx.items() if v is not None})
    role = ctx.get("role") if isinstance(ctx.get("role"), str) else None
    el = RetrievalGate().evaluate(f, context, role=role)
    return [el.ok, el.reason.value if el.reason else None, el.escalate]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_demo_gate_matches_python_gate(tmp_path):
    cases = _cases()
    template = TEMPLATE.read_text()
    logic = template[template.index("const CONTEXT_KEYS"):template.index("function el(id)")]
    payload = [{"name": n, "fragment": f.model_dump(mode="json"), "ctx": c, "ov": o} for n, _, f, c, o in cases]
    script = tmp_path / "parity.mjs"
    script.write_text(logic + "\nconst CASES = " + json.dumps(payload) + ";\n" +
                      "console.log(JSON.stringify(CASES.map(c => { const r = gate(c.fragment, c.ctx, c.ov);"
                      " return [r.ok, r.reason || null, Boolean(r.escalate)]; })));\n")
    js = json.loads(subprocess.run([NODE, str(script)], capture_output=True, text=True, check=True).stdout)
    mismatches = [(n, py, j) for (n, e, f, c, o), j in zip(cases, js, strict=True)
                  if (py := _python(e, f, c, o)) != j]
    assert not mismatches, mismatches
