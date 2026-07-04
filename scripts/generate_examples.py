"""Regenerate example data files and expected outputs from the scenarios.

Keeps the examples/ folder in lock-step with the implementation. Run:
    python scripts/generate_examples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metis.audit.export import export_records
from metis.scenarios import SPECS, run_spec

DIRS = {
    "manufacturing-pump-vibration": "manufacturing_pump_vibration",
    "batch-quality-visual-inspection": "batch_quality_visual_inspection",
    "shift-handover-gap": "shift_handover_gap",
}
ROOT = Path(__file__).resolve().parents[1] / "examples"
# Manufacturing keeps its hand-authored, richer inputs; we only refresh its expected outputs.
INPUTS_MANAGED = {"batch-quality-visual-inspection", "shift-handover-gap"}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


for key, spec in SPECS.items():
    base = ROOT / DIRS[key]
    run = run_spec(spec)

    if key in INPUTS_MANAGED:
        # Inputs
        write_json(base / "observation.json", {
            "observation_id": spec.observation["observation_id"],
            "work_as_imagined": spec.observation["work_as_imagined"],
            "work_as_done": spec.observation["work_as_done"],
            "source": "synthetic",
            "context": {k: v for k, v in spec.conditions.items()},
        })
        write_json(base / "context_matching.json", spec.match_context)
        write_json(base / "context_non_matching.json", spec.nonmatch_context)
        write_json(base / "fragment_evidence.json", run.fragment.evidence.model_dump(mode="json"))
        write_json(base / "mission_group_review.json", {
            "fragment_id": run.fragment.fragment_id,
            "outcome": "promoted_to_advisory",
            "reviewers": [spec_uri := "group:mission-group@metis.local"],
            "dimension_assessments": spec.review_dimensions,
            "summary": spec.review_summary,
        })
        write_json(base / "whisper_response.json", {
            "prompt_category": spec.category,
            "response_type": "confirm",
            "operator_statement": spec.corrected_content,
        })
        # Memory seed files
        (base / "procedural_memory").mkdir(parents=True, exist_ok=True)
        for src, content in spec.procedural:
            (base / "procedural_memory" / f"{src}.md").write_text(f"# {src}\n\n{content}\n")
        (base / "semantic_memory").mkdir(parents=True, exist_ok=True)
        for src, content, meta in spec.semantic:
            write_json(base / "semantic_memory" / f"{src}.json", {"content": content, **meta})
        (base / "episodic_memory").mkdir(parents=True, exist_ok=True)
        with (base / "episodic_memory" / "prior_cases.jsonl").open("w") as fh:
            for src, content, meta in spec.episodic:
                fh.write(json.dumps({"id": src, "summary": content, **meta}) + "\n")

    # Expected outputs (all scenarios)
    write_json(base / "tacit_memory" / "expected_tacit_memory_object.json",
               run.memory.model_dump(mode="json"))
    write_json(base / "expected_agent_context.json", run.agent_context.model_dump(mode="json"))
    with (base / "expected_audit.jsonl").open("w") as fh:
        for rec in export_records(run.engine.adapter):
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")

    print(f"{key}: fragment={run.fragment.fragment_id} memory={run.memory.memory_id} "
          f"audit={run.engine.adapter.chain.count} entries")

print("examples regenerated")
