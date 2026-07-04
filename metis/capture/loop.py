"""The Metis operating loop: Observe -> Infer -> Whisper -> Confirm -> Remember.

Each stage is a Metis action emitted as a CHAP event/artefact through the adapter. A
local model may assist at the Infer/Whisper/Confirm stages; every assisted step is recorded
as a ModelAssistRecord (provenance, not authority).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord
from ..fragment.events import fragment_to_content
from ..fragment.model import Attribution, FragmentEvidence, TacitFragment
from ..fragment.store import FragmentStore
from ..models.ollama_client import OllamaClient
from ..models.structured_outputs import AssistPurpose, ModelAssistRecord
from ..taxonomy.categories import SourcePathway
from ..validation.tier1 import OperatorResponse
from .confirm import ConfirmationResult, operator_confirm
from .infer import InferenceCandidate, infer_candidate
from .observe import Observation, build_observation
from .remember import build_fragment
from .whisper import WhisperPrompt, build_whisper


@dataclass
class CaptureResult:
    observation: Observation
    candidate: InferenceCandidate
    whisper: WhisperPrompt
    confirmation: ConfirmationResult
    task_id: str
    fragment: TacitFragment | None = None
    fragment_artefact: str | None = None
    model_assist_records: list[ModelAssistRecord] = field(default_factory=list)
    used_live_model: bool = False


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
    ) -> None:
        self.adapter = adapter
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

    # ---- the loop --------------------------------------------------------------
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
    ) -> CaptureResult:
        mc = self.model_client if use_model else None
        assists: list[ModelAssistRecord] = []

        # 1. Observe
        if isinstance(observation_input, Observation):
            observation = observation_input
        else:
            observation = build_observation(**observation_input)
        task_id = self.adapter.create_task(
            "tacit.capture", assignee=self.whisperer_uri, delegator=self.operator_uri,
            task_input={"observation_id": observation.observation_id})
        obs_art = self.adapter.append_artefact(
            "tacit.capture_observation", produced_by=self.operator_uri,
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

        # 3. Whisper (CHAP whisper capability)
        whisper, whisper_assist = build_whisper(candidate.category, observation, model_client=mc)
        prompt_art = self.adapter.whisper_ask(
            sender=self.whisperer_uri, to=self.operator_uri, task_id=task_id,
            question=whisper.question, options=whisper.options, deadline_ms=60000,
            default_if_lapsed="defer", urgency="low", category=candidate.category)
        if whisper_assist:
            assists.append(self._record_assist(whisper_assist, task_id=task_id,
                           produced_by=self.whisperer_uri, input_refs=[cand_art]))

        # 4. Confirm (Tier-1, descriptive fidelity)
        confirmation, confirm_assist = operator_confirm(
            whisper, response, corrected_content=corrected_content, free_text=free_text, model_client=mc)
        self.adapter.whisper_answer(
            sender=self.operator_uri, to=self.whisperer_uri, task_id=task_id,
            prompt_artefact=prompt_art, response_type=confirmation.response.value,
            text=confirmation.corrected_content or confirmation.free_text,
            option_id=confirmation.response.value)
        self.adapter.append_artefact(
            "tacit.operator_confirmation", produced_by=self.operator_uri,
            content=confirmation.model_dump(mode="json"), task=task_id, based_on=prompt_art)
        if confirm_assist:
            assists.append(self._record_assist(confirm_assist, task_id=task_id,
                           produced_by=self.operator_uri, input_refs=[prompt_art]))

        result = CaptureResult(
            observation=observation, candidate=candidate, whisper=whisper,
            confirmation=confirmation, task_id=task_id, model_assist_records=assists,
            used_live_model=any(a.used_live_model for a in assists))

        # 5. Remember (only on confirm/correct)
        if confirmation.response in (OperatorResponse.confirm, OperatorResponse.correct):
            fid = fragment_id or f"TF-{self._frag_seq:05d}"
            fragment = build_fragment(
                observation, candidate, confirmation, fragment_id=fid,
                capture_cell=self.capture_cell, operator_uri=self.operator_uri,
                consent=consent, title=title, conditions=conditions,
                attribution=attribution, evidence=evidence, source_pathway=source_pathway)
            # record model-assist provenance (provenance, not authority)
            if assists:
                fragment.provenance.model_assist_refs = [a.assist_id for a in assists]
                fragment.provenance.model_provider = assists[0].provider
                fragment.provenance.model_name = assists[0].model_name
                fragment.provenance.model_output_status = "draft_pending_human_review"
                fragment.provenance.human_review_status = "tier1_confirmed"
            fragment.provenance.source_artefacts = [obs_art, cand_art, prompt_art]
            fragment.add_lineage(state=fragment.validation_state.value, by=self.operator_uri,
                                 note="captured into Evidence layer (Tier-1 confirmed)")
            frag_art = self.adapter.append_artefact(
                "tacit.fragment", produced_by=self.operator_uri,
                content=fragment_to_content(fragment), task=task_id, based_on=cand_art)
            self.fragments.put(fragment)
            result.fragment = fragment
            result.fragment_artefact = frag_art
            if self.governance is not None:
                self.governance.register(fid, fragment_artefact=frag_art, task_id=task_id)
        return result
