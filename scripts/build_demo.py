"""Build the self-contained interactive demo (docs/demo.html) from the real scenarios.

Runs each scenario, embeds its steps, fragment, memory object, contexts, agent context, and
audit chain as JSON, and injects the Brightbeam logo. Run:
    python scripts/build_demo.py
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tacitflow.scenarios import SPECS, run_spec


def build() -> dict:
    scenarios = {}
    order = []
    for key, spec in SPECS.items():
        run = run_spec(spec)
        order.append(key)
        scenarios[key] = {
            "name": spec.name,
            "categories": spec.categories,
            "observation": {
                "work_as_imagined": spec.observation["work_as_imagined"],
                "work_as_done": spec.observation["work_as_done"],
            },
            "steps": run.steps,
            "fragment": run.fragment.model_dump(mode="json"),
            "memory": run.memory.model_dump(mode="json"),
            "match_context": spec.match_context,
            "nonmatch_context": spec.nonmatch_context,
            "agent_context": run.agent_context.model_dump(mode="json"),
            "audit": [
                {"seq": r["seq"], "method_or_type": r["method_or_type"], "from": r["from"]}
                for r in run.engine.adapter.evidence_records()
            ],
        }
    return {"order": order, "scenarios": scenarios}


def main() -> None:
    data = build()
    template = (ROOT / "scripts" / "demo_template.html").read_text()
    logo = base64.b64encode((ROOT / "docs" / "assets" / "brightbeam-logo.png").read_bytes()).decode()
    html = template.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    html = html.replace("__LOGO__", f"data:image/png;base64,{logo}")
    out = ROOT / "docs" / "demo.html"
    out.write_text(html)
    print(f"wrote {out} ({len(html)} bytes, {len(data['order'])} scenarios)")


if __name__ == "__main__":
    main()
