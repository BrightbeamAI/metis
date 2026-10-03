"""The Metis operating loop: Observe -> Infer -> Whisper -> Confirm -> Store.

Each stage is a Metis action emitted as a CHAP event/artefact through the adapter. A
local model may assist at the Infer/Whisper/Confirm stages; every assisted step is recorded
as a ModelAssistRecord, for provenance only.

The loop runs in two halves. ``begin`` observes, infers, and asks the worker one whisper;
``complete`` records the worker's own answer and stores a confirmed fragment. ``run`` does
both when the response is known up front (demos, tests). Whispers are rationed per worker
(``WhisperBudget``): a capture that would exceed the budget is deferred and recorded.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord
from ..fragment.events import fragment_to_content
from ..fragment.model import Attribution, FragmentEvidence, TacitFragment
from ..fragment.store import FragmentStore
from ..models.ollama_client import OllamaClient
from ..models.structured_outputs import AssistPurpose, ModelAssistRecord
from ..taxonomy.categories import Category, SourcePathway
from ..validation.tier1 import OperatorResponse
from .confirm import ConfirmationResult, operator_confirm
from .infer import InferenceCandidate, infer_candidate
from .observe import Observation, build_observation
from .remember import build_fragment
from .whisper import WhisperPrompt, build_whisper


@dataclass
class WhisperBudget:
    """At most ``max_per_worker`` whispers to one worker within ``window_minutes``.

    Excessive prompting tires workers and degrades what they report, so whispers are
    rationed. A capture that would exceed the budget is deferred: no question is asked, and
    the deferral is recorded on the chain for later re-elicitation.
    """

    max_per_worker: int = 5
    window_minutes: int = 480


class PendingCapture(BaseModel):
    """A capture waiting for the worker's answer to its whisper."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    worker: str
    observation: Observation
    candidate: InferenceCandidate
    consent: ConsentRecord
    whisper: WhisperPrompt | None = None
    whisper_id: str | None = None
    category: str | None = None
    conditions: TacitContext | None = None
    attribution: Attribution | None = None
    evidence: FragmentEvidence | None = None
    title: str | None = None
    source_pathway: SourcePathway = SourcePathway.exogenous
    fragment_id: str | None = None
    artefacts: dict[str, str] = Field(default_factory=dict)
    assist_records: list[ModelAssistRecord] = Field(default_factory=list)
    deferred: bool = False
    deferred_reason: str | None = None


@dataclass
class CaptureResult:
    observation: Observation
    candidate: InferenceCandidate
    whisper: WhisperPrompt | None
    confirmation: ConfirmationResult | None
    task_id: str
    fragment: TacitFragment | None = None
    fragment_artefact: str | None = None
    model_assist_records: list[ModelAssistRecord] = field(default_factory=list)
    used_live_model: bool = False
    deferred: bool = False
    deferred_reason: str | None = None


class CaptureLoop:
    def __init__(
        self,
        *,
        adapter,
        fragment_store: FragmentStore,
        operator_uri: str,
        whisperer_uri: str,
        mission_group_uri: str = "group:mission-group@metis.local",
        model_client: OllamaClient | None = None,
        capture_cell: str | None = None,
        governance=None,
        whisper_budget: WhisperBudget | None = None,
    ) -> None:
        self.adapter = adapter
        self.whisper_budget = whisper_budget
        self.fragments = fragment_store
        self.operator_uri = operator_uri
        self.whisperer_uri = whisperer_uri
        self.mission_group_uri = mission_group_uri
        self.model_client = model_client
        self.capture_cell = capture_cell or adapter.workspace_id
        self.governance = governance
        self._frag_seq = 0
        self._assist_seq = 0

    # ---- model assist recording ------------------------------------------------
    def _record_assist(self, assist: dict[str, Any], *, task_id: str, produced_by: str,
                       input_refs: list[str]) -> ModelAssistRecord:
        self._assist_seq += 1
        cfg = self.model_client.config if self.model_client else None
        record = ModelAssistRecord(
            assist_id=f"MA-{self._assist_seq:04d}",
            provider=cfg.provider if cfg else "ollama",
            model_name=cfg.name if cfg else "gemma4",
            model_url=cfg.url if cfg else "http://localhost:11434",
            purpose=AssistPurpose(assist["purpose"]),
            prompt_template=assist["prompt"],
            input_refs=input_refs,
            output=assist["output"],
            used_live_model=assist.get("used_live_model", False),
            human_review_required=True,
            human_review_status="pending",
        )
        art = self.adapter.append_artefact(
            "tacit.model_assist_record", produced_by=produced_by,
            content=record.model_dump(mode="json"), task=task_id)
        record.chap_artefact_ref = art
        record.chap_evidence_ref = self.adapter.artefact_evidence.get(art)
        return record

    # ---- whisper budget --------------------------------------------------------
    def _whispers_in_window(self, worker: str) -> int:
        """Whispers addressed to ``worker`` within the budget window, read from the chain."""
        since = clock.now_dt() - _dt.timedelta(minutes=self.whisper_budget.window_minutes)
        count = 0
        for entry in self.adapter.chain.entries:
            if entry.envelope.get("method") != "whisper.ask":
                continue
            to = (entry.envelope.get("params") or {}).get("to") or []
            to = [to] if isinstance(to, str) else to
            arrived = _dt.datetime.fromisoformat(entry.arrived.replace("Z", "+00:00"))
            if worker in to and arrived >= since:
                count += 1
        return count

    # ---- the loop --------------------------------------------------------------
    def begin(
        self,
        observation_input: dict[str, Any] | Observation,
        *,
        consent: ConsentRecord,
        category: str | None = None,
        conditions: TacitContext | None = None,
        attribution: Attribution | None = None,
        evidence: FragmentEvidence | None = None,
        title: str | None = None,
        source_pathway: SourcePathway = SourcePathway.exogenous,
        use_model: bool = True,
        fragment_id: str | None = None,
        worker: str | None = None,
    ) -> PendingCapture:
        """Observe, infer, and ask the worker one whisper. The worker answers later."""
        if category is not None:
            Category(category)  # reject an unknown category before anything is recorded
        worker = worker or self.operator_uri
        mc = self.model_client if use_model else None
        assists: list[ModelAssistRecord] = []

        # 1. Observe
        if isinstance(observation_input, Observation):
            observation = observation_input
        else:
            observation = build_observation(**observation_input)
        task_id = self.adapter.create_task(
            "tacit.capture", assignee=self.whisperer_uri, delegator=worker,
            task_input={"observation_id": observation.observation_id})
        obs_art = self.adapter.append_artefact(
            "tacit.capture_observation", produced_by=worker,
            content=observation.model_dump(mode="json"), task=task_id)

        # 2. Infer (candidate only)
        self._frag_seq += 1
        candidate_id = f"IC-{self._frag_seq:04d}"
        candidate, infer_assist = infer_candidate(observation, candidate_id=candidate_id,
                                                  model_client=mc, category=category)
        cand_art = self.adapter.append_artefact(
            "tacit.inference_candidate", produced_by=self.whisperer_uri,
            content=candidate.model_dump(mode="json"), task=task_id, based_on=obs_art)
        if infer_assist:
            assists.append(self._record_assist(infer_assist, task_id=task_id,
                           produced_by=self.whisperer_uri, input_refs=[obs_art]))

        pending = PendingCapture(
            task_id=task_id, worker=worker, observation=observation, candidate=candidate,
            consent=consent, category=category, conditions=conditions, attribution=attribution,
            evidence=evidence, title=title, source_pathway=source_pathway,
            fragment_id=fragment_id or f"TF-{self._frag_seq:05d}",
            artefacts={"observation": obs_art, "candidate": cand_art}, assist_records=assists)

        # 3. Whisper (CHAP whisper capability), within the worker's prompt budget
        if self.whisper_budget is not None:
            asked = self._whispers_in_window(worker)
            if asked >= self.whisper_budget.max_per_worker:
                self.adapter.append_artefact(
                    "tacit.validation_event", produced_by=self.whisperer_uri,
                    content={"event": "whisper_deferred", "reason": "worker_prompt_budget",
                             "worker": worker, "candidate_id": candidate.candidate_id,
                             "asked_in_window": asked,
                             "budget": {"max_per_worker": self.whisper_budget.max_per_worker,
                                        "window_minutes": self.whisper_budget.window_minutes}},
                    task=task_id, based_on=cand_art)
                pending.deferred = True
                pending.deferred_reason = "worker_prompt_budget"
                return pending

        whisper, whisper_assist = build_whisper(candidate.category, observation, model_client=mc)
        prompt_art = self.adapter.whisper_ask(
            sender=self.whisperer_uri, to=worker, task_id=task_id,
            question=whisper.question, options=whisper.options, deadline_ms=60000,
            default_if_lapsed="defer", urgency="low", category=candidate.category)
        if whisper_assist:
            assists.append(self._record_assist(whisper_assist, task_id=task_id,
                           produced_by=self.whisperer_uri, input_refs=[cand_art]))
        pending.whisper = whisper
        pending.whisper_id = prompt_art
        pending.artefacts["prompt"] = prompt_art
        return pending

    def complete(
        self,
        pending: PendingCapture,
        *,
        response: OperatorResponse | str = OperatorResponse.confirm,
        corrected_content: str | None = None,
        free_text: str | None = None,
        use_model: bool = True,
        answered_by: str | None = None,
        store: bool = True,
    ) -> CaptureResult:
        """Record the worker's own answer (Tier-1) and store a confirmed fragment.

        ``store=False`` records the answer but stores nothing (the worker declined consent).
        """
        if pending.deferred or pending.whisper is None or pending.whisper_id is None:
            raise ValueError("This capture was deferred; no whisper was asked.")
        worker = pending.worker
        if answered_by is not None and answered_by != worker:
            raise PermissionError(f"Only {worker}, the worker who was asked, may answer this whisper.")
        mc = self.model_client if use_model else None
        assists = list(pending.assist_records)
        obs_art, cand_art = pending.artefacts["observation"], pending.artefacts["candidate"]
        prompt_art = pending.whisper_id

        # 4. Confirm (Tier-1, descriptive fidelity)
        confirmation, confirm_assist = operator_confirm(
            pending.whisper, response, corrected_content=corrected_content, free_text=free_text,
            confirmed_text=pending.candidate.hypothesis, model_client=mc)
        self.adapter.whisper_answer(
            sender=worker, to=self.whisperer_uri, task_id=pending.task_id,
            prompt_artefact=prompt_art, response_type=confirmation.response.value,
            text=confirmation.corrected_content or confirmation.free_text,
            option_id=confirmation.response.value)
        self.adapter.append_artefact(
            "tacit.operator_confirmation", produced_by=worker,
            content=confirmation.model_dump(mode="json"), task=pending.task_id, based_on=prompt_art)
        if confirm_assist:
            assists.append(self._record_assist(confirm_assist, task_id=pending.task_id,
                           produced_by=worker, input_refs=[prompt_art]))

        result = CaptureResult(
            observation=pending.observation, candidate=pending.candidate, whisper=pending.whisper,
            confirmation=confirmation, task_id=pending.task_id, model_assist_records=assists,
            used_live_model=any(a.used_live_model for a in assists))

        if not store:
            self.adapter.append_artefact(
                "tacit.validation_event", produced_by=worker,
                content={"event": "consent_declined", "worker": worker,
                         "candidate_id": pending.candidate.candidate_id},
                task=pending.task_id, based_on=prompt_art)
            return result

        # 5. Store (only on confirm/correct)
        if confirmation.response in (OperatorResponse.confirm, OperatorResponse.correct):
            fragment = build_fragment(
                pending.observation, pending.candidate, confirmation, fragment_id=pending.fragment_id,
                capture_cell=self.capture_cell, operator_uri=worker,
                consent=pending.consent, title=pending.title, conditions=pending.conditions,
                attribution=pending.attribution, evidence=pending.evidence,
                source_pathway=pending.source_pathway)
            # Model-assist provenance. Name a model only when one actually ran; deterministic
            # fixtures are recorded as such.
            if assists:
                live = [a for a in assists if a.used_live_model]
                fragment.provenance.model_assist_refs = [a.assist_id for a in assists]
                fragment.provenance.model_assist_mode = "live_model" if live else "deterministic_fixture"
                if live:
                    fragment.provenance.model_provider = live[0].provider
                    fragment.provenance.model_name = live[0].model_name
                fragment.provenance.model_output_status = (
                    "corrected_by_worker" if confirmation.response == OperatorResponse.correct
                    else "confirmed_by_worker")
            fragment.provenance.human_review_status = fragment.validation_state.value
            fragment.provenance.source_artefacts = [obs_art, cand_art, prompt_art]
            fragment.add_lineage(state=fragment.validation_state.value, by=worker,
                                 note="captured into Evidence layer (Tier-1 confirmed)")
            frag_art = self.adapter.append_artefact(
                "tacit.fragment", produced_by=worker,
                content=fragment_to_content(fragment), task=pending.task_id, based_on=cand_art)
            fragment.lineage[-1].chap_artefact_ref = frag_art
            fragment.lineage[-1].chap_evidence_seq = self.adapter.artefact_evidence.get(frag_art)
            self.fragments.put(fragment)
            result.fragment = fragment
            result.fragment_artefact = frag_art
            if self.governance is not None:
                self.governance.register(fragment.fragment_id, fragment_artefact=frag_art,
                                         task_id=pending.task_id)
        return result

    def run(
        self,
        observation_input: dict[str, Any] | Observation,
        *,
        consent: ConsentRecord,
        response: OperatorResponse | str = OperatorResponse.confirm,
        corrected_content: str | None = None,
        free_text: str | None = None,
        category: str | None = None,
        conditions: TacitContext | None = None,
        attribution: Attribution | None = None,
        evidence: FragmentEvidence | None = None,
        title: str | None = None,
        source_pathway: SourcePathway = SourcePathway.exogenous,
        use_model: bool = True,
        fragment_id: str | None = None,
        worker: str | None = None,
    ) -> CaptureResult:
        """The whole loop in one call, with the worker's response supplied up front."""
        pending = self.begin(
            observation_input, consent=consent, category=category, conditions=conditions,
            attribution=attribution, evidence=evidence, title=title, source_pathway=source_pathway,
            use_model=use_model, fragment_id=fragment_id, worker=worker)
        if pending.deferred:
            return CaptureResult(
                observation=pending.observation, candidate=pending.candidate, whisper=None,
                confirmation=None, task_id=pending.task_id,
                model_assist_records=list(pending.assist_records), deferred=True,
                deferred_reason=pending.deferred_reason)
        return self.complete(pending, response=response, corrected_content=corrected_content,
                             free_text=free_text, use_model=use_model)
