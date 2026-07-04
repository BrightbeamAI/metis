"""CLI session state: persist a Metis run so later commands can query it.

The CHAP evidence chain is exported to ``.metis/evidence.jsonl`` (the audit source of
truth). A ``state.json`` snapshot mirrors live fragment/memory/store state so read commands
(fragment list, memory query, retrieve) work across invocations without re-running capture.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..audit.export import export_jsonl
from ..conditions.context import TacitContext
from ..fragment.model import TacitFragment
from ..fragment.store import FragmentStore
from ..memory.agent_context import MemoryEntry
from ..memory.broker import MemoryBroker
from ..memory.episodic import EpisodicMemoryStore
from ..memory.procedural import ProceduralMemoryStore
from ..memory.semantic import SemanticMemoryStore
from ..memory.tacit import TacitMemoryObject, TacitMemoryStore
from ..models.model_config import project_home
from ..retrieval.gate import RetrievalGate


def home() -> Path:
    return project_home()


def state_path() -> Path:
    return home() / "state.json"


def evidence_path() -> Path:
    return home() / "evidence.jsonl"


def save_state(engine, *, scenario: str | None = None) -> Path:
    home().mkdir(parents=True, exist_ok=True)
    state = {
        "scenario": scenario,
        "workspace": engine.adapter.descriptor(),
        "fragments": [f.model_dump(mode="json") for f in engine.fragments.all()],
        "memory_objects": [m.model_dump(mode="json") for m in engine.tacit_store.all()],
        "procedural": [e.model_dump(mode="json") for e in engine.procedural.entries],
        "semantic": [e.model_dump(mode="json") for e in engine.semantic.entries],
        "episodic": [e.model_dump(mode="json") for e in engine.episodic.entries],
    }
    state_path().write_text(json.dumps(state, indent=2))
    export_jsonl(engine.adapter, evidence_path())
    try:
        from ..storage.sqlite_store import SqliteStore
        store = SqliteStore(home() / "metis.db")
        store.persist_engine(engine)
        store.close()
    except Exception:
        pass
    return state_path()


def load_state() -> dict[str, Any]:
    if not state_path().exists():
        raise FileNotFoundError(
            "No Metis state found. Run `metis demo manufacturing-pump-vibration` first.")
    return json.loads(state_path().read_text())


def rebuild_fragment_store(state: dict[str, Any]) -> FragmentStore:
    fs = FragmentStore()
    for f in state.get("fragments", []):
        fs.put(TacitFragment.model_validate(f))
    return fs


def rebuild_tacit_store(state: dict[str, Any]) -> TacitMemoryStore:
    ts = TacitMemoryStore()
    for m in state.get("memory_objects", []):
        ts.put(TacitMemoryObject.model_validate(m))
    return ts


def rebuild_broker(state: dict[str, Any]) -> MemoryBroker:
    proc, sem, epi = ProceduralMemoryStore(), SemanticMemoryStore(), EpisodicMemoryStore()
    for e in state.get("procedural", []):
        proc.entries.append(MemoryEntry.model_validate(e))
    for e in state.get("semantic", []):
        sem.entries.append(MemoryEntry.model_validate(e))
    for e in state.get("episodic", []):
        epi.entries.append(MemoryEntry.model_validate(e))
    return MemoryBroker(procedural=proc, semantic=sem, episodic=epi,
                        fragment_store=rebuild_fragment_store(state),
                        tacit_store=rebuild_tacit_store(state), gate=RetrievalGate())


def load_context(path: str) -> TacitContext:
    data = json.loads(Path(path).read_text())
    return TacitContext.model_validate(data)
