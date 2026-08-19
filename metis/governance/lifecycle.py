"""Governance lifecycle orchestrator.

Wires fragment-state transitions to CHAP review/control events and to the tacit.* record
artefacts (review_decision, promotion_record, rejection_record, re_elicitation_request,
revocation_record, supersession_record). Promotion creates a TacitMemoryObject. Every step
is appended to the evidence chain. No local model output may drive any decision here.
"""
from __future__ import annotations

from typing import Any

from ..consent.contestability import ContestabilityRecord, ContestAction
from ..consent.model import ConsentStatus
from ..consent.revocation import RevocationReason, RevocationRecord
from ..fragment.events import fragment_to_content
from ..fragment.model import TacitFragment
from ..fragment.store import FragmentStore
from ..integrations.chap import review as chap_review
from ..memory.tacit import TacitMemoryObject, TacitMemoryStore
from ..retrieval.gate import RetrievalGate
from ..taxonomy.categories import RevocationStatus, ValidationState
from ..validation.mission_group import MissionGroup
from ..validation.promotion import PromotionRecord
from ..validation.re_elicitation import ReElicitationRequest
from ..validation.rejection import RejectionRecord
from ..validation.states import assert_transition
from .authority import layer_for_outcome, state_for_outcome
from .policy import GovernancePolicy

VS = ValidationState


class Governance:
    def __init__(
        self,
        *,
        fragment_store: FragmentStore,
        adapter,
        tacit_store: TacitMemoryStore | None = None,
        policy: GovernancePolicy | None = None,
        mission_group: MissionGroup | None = None,
        gate: RetrievalGate | None = None,
    ) -> None:
        self.fragments = fragment_store
        self.adapter = adapter
        self.tacit_store = tacit_store if tacit_store is not None else TacitMemoryStore()
        self.policy = policy or GovernancePolicy()
        self.mission_group = mission_group or MissionGroup()
        self.gate = gate or RetrievalGate()
        self.refs: dict[str, dict[str, str]] = {}
        self._mem_seq = 0

    # ---- CHAP references -------------------------------------------------------
    def register(self, fragment_id: str, *, fragment_artefact: str, task_id: str) -> None:
        self.refs[fragment_id] = {"artefact": fragment_artefact, "task": task_id}

    def _ensure_refs(self, fragment: TacitFragment) -> dict[str, str]:
        ref = self.refs.get(fragment.fragment_id)
        if ref is None:
            task_id = self.adapter.create_task(
                "tacit.validate.tier2", assignee=self.mission_group.uri,
                delegator=self.mission_group.uri, task_input={"fragment_id": fragment.fragment_id})
            art = self.adapter.append_artefact(
                "tacit.fragment", produced_by=self.mission_group.uri,
                content=fragment_to_content(fragment), task=task_id)
            ref = {"artefact": art, "task": task_id}
            self.refs[fragment.fragment_id] = ref
        return ref

    def _ev(self, artefact_id: str) -> int | None:
        return self.adapter.artefact_evidence.get(artefact_id)

    # ---- Tier-2 ----------------------------------------------------------------
    def submit_for_tier2(self, fragment_id: str, *, by: str) -> None:
        frag = self.fragments.require(fragment_id)
        ref = self._ensure_refs(frag)
        assert_transition(frag.validation_state, VS.tier2_pending)
        frag.validation_state = VS.tier2_pending
        entry = self.adapter.review_request(
            sender=by, reviewers=[self.mission_group.uri],
            artefact_id=ref["artefact"], task_id=ref["task"])
        frag.add_lineage(state=VS.tier2_pending.value, by=by,
                         note="submitted for Mission Group review", chap_evidence_seq=entry.seq)
        self.fragments.put(frag)

    def tier2_review(
        self,
        fragment_id: str,
        outcome: str,
        *,
        by: str | None = None,
        reviewers: list[str] | None = None,
        dimension_assessments: dict[str, str] | None = None,
        summary: str = "",
        change_control: dict[str, Any] | None = None,
        model_assist_ref: str | None = None,
        linked_procedural_refs: list[str] | None = None,
        linked_semantic_refs: list[str] | None = None,
        linked_episodic_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        frag = self.fragments.require(fragment_id)
        by = by or self.mission_group.uri
        if frag.validation_state == VS.tier1_confirmed:
            self.submit_for_tier2(fragment_id, by=by)
            frag = self.fragments.require(fragment_id)
        if frag.validation_state not in (VS.tier2_pending, VS.held):
            assert_transition(frag.validation_state, VS.tier2_pending)
        ref = self._ensure_refs(frag)

        review = self.mission_group.review(
            fragment_id, outcome, reviewers=reviewers,
            dimension_assessments=dimension_assessments, summary=summary,
            model_assist_ref=model_assist_ref)

        method = chap_review.OUTCOME_TO_METHOD[outcome]
        self.adapter.decide(method, sender=by, based_on=ref["artefact"], task_id=ref["task"],
                            content={"outcome": outcome, "summary": summary})
        review_art = self.adapter.append_artefact(
            "tacit.review_decision", produced_by=by, content=review.model_dump(mode="json"),
            task=ref["task"], based_on=ref["artefact"])
        result: dict[str, Any] = {"review": review, "review_artefact": review_art}

        if outcome in ("promoted_to_advisory", "promoted_to_controlled"):
            target = layer_for_outcome(outcome)
            ok, why = self.policy.can_promote(frag, target, change_control=change_control,
                                              mission_group_reviewed=True)
            if not ok:
                raise PermissionError(f"Promotion blocked by policy: {why}")
            new_state = state_for_outcome(outcome)
            assert_transition(frag.validation_state, new_state)
            old_layer = frag.authority_layer
            frag.authority_layer = target
            frag.validation_state = new_state
            frag.provenance.mission_group_reviewed_by = by
            pr = PromotionRecord(fragment_id=fragment_id, from_layer=old_layer, to_layer=target,
                                 new_state=new_state, promoted_by=by, review_ref=review_art,
                                 change_control=change_control, rationale=summary)
            pr_art = self.adapter.append_artefact("tacit.promotion_record", produced_by=by,
                        content=pr.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            frag.add_lineage(state=new_state.value, by=by, note="promoted",
                             chap_evidence_seq=self._ev(pr_art))
            self.fragments.put(frag)
            mem = self._create_memory_object(
                frag, change_control=change_control, review_art=review_art,
                linked_procedural_refs=linked_procedural_refs,
                linked_semantic_refs=linked_semantic_refs,
                linked_episodic_refs=linked_episodic_refs)
            result.update({"promotion_record": pr_art, "memory": mem})
            return result

        if outcome == "rejected":
            assert_transition(frag.validation_state, VS.rejected)
            frag.validation_state = VS.rejected
            frag.revocation_status = RevocationStatus.rejected
            rr = RejectionRecord(fragment_id=fragment_id, rejected_by=by,
                                 reason=summary or "rejected at Tier-2", review_ref=review_art)
            rr_art = self.adapter.append_artefact("tacit.rejection_record", produced_by=by,
                        content=rr.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            frag.add_lineage(state=VS.rejected.value, by=by, note="rejected (retained for audit)",
                             chap_evidence_seq=self._ev(rr_art))
            self.fragments.put(frag)
            result["rejection_record"] = rr_art
            return result

        if outcome == "held":
            assert_transition(frag.validation_state, VS.held)
            frag.validation_state = VS.held
            frag.add_lineage(state=VS.held.value, by=by, note=summary, chap_evidence_seq=self._ev(review_art))
            self.fragments.put(frag)
            return result

        if outcome == "re_elicit":
            assert_transition(frag.validation_state, VS.re_elicit)
            frag.validation_state = VS.re_elicit
            frag.revocation_status = RevocationStatus.under_re_elicitation
            req = ReElicitationRequest(fragment_id=fragment_id, requested_by=by,
                                       reason=summary or "re-elicitation requested", review_ref=review_art)
            req_art = self.adapter.append_artefact("tacit.re_elicitation_request", produced_by=by,
                        content=req.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            frag.add_lineage(state=VS.re_elicit.value, by=by, chap_evidence_seq=self._ev(req_art))
            self.fragments.put(frag)
            result["re_elicitation_request"] = req_art
            return result

        raise ValueError(f"Unknown outcome: {outcome}")

    # ---- memory object ---------------------------------------------------------
    def _create_memory_object(self, frag: TacitFragment, *, change_control=None, review_art=None,
                              linked_procedural_refs=None, linked_semantic_refs=None,
                              linked_episodic_refs=None) -> TacitMemoryObject:
        self._mem_seq += 1
        memory_id = f"TM-{self._mem_seq:05d}"
        ref = self.refs.get(frag.fragment_id, {})
        evidence_refs = []
        for art in (ref.get("artefact"), review_art):
            seq = self._ev(art) if art else None
            if seq is not None:
                evidence_refs.append(seq)
        mem = TacitMemoryObject.from_fragment(
            frag, memory_id=memory_id, change_control=change_control,
            linked_procedural_refs=linked_procedural_refs or [],
            linked_semantic_refs=linked_semantic_refs or [],
            linked_episodic_refs=linked_episodic_refs or [],
            linked_chap_evidence_refs=sorted(set(evidence_refs)),
            model_assist_refs=frag.provenance.model_assist_refs)
        self.tacit_store.put(mem)
        self.adapter.append_artefact("tacit.memory_object", produced_by=self.mission_group.uri,
            content=mem.model_dump(mode="json"), task=ref.get("task"), based_on=ref.get("artefact"))
        return mem

    # ---- revocation / supersession --------------------------------------------
    def revoke(self, fragment_id: str, *, reason: RevocationReason, by: str,
               note: str | None = None, superseded_by: str | None = None) -> str:
        frag = self.fragments.require(fragment_id)
        ref = self._ensure_refs(frag)
        status_map = {
            RevocationReason.consent_withdrawn: RevocationStatus.withdrawn,
            RevocationReason.superseded: RevocationStatus.superseded,
            RevocationReason.rejected: RevocationStatus.rejected,
            RevocationReason.retired: RevocationStatus.retired,
            RevocationReason.drift: RevocationStatus.retired,
            RevocationReason.safety_concern: RevocationStatus.retired,
            RevocationReason.re_elicitation: RevocationStatus.under_re_elicitation,
        }
        new_status = status_map.get(RevocationReason(reason), RevocationStatus.retired)
        rec = RevocationRecord(fragment_id=fragment_id, new_status=new_status, reason=reason,
                               actioned_by=by, note=note, superseded_by=superseded_by)
        self.adapter.control_event("control.cancel", sender=by, params={
            "task_id": ref["task"], "reason": str(reason), "fragment_id": fragment_id})
        rec_art = self.adapter.append_artefact("tacit.revocation_record", produced_by=by,
            content=rec.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
        frag.revocation_status = new_status
        if new_status == RevocationStatus.withdrawn:
            frag.validation_state = VS.withdrawn
        elif new_status == RevocationStatus.superseded:
            frag.validation_state = VS.superseded
        frag.add_lineage(state=new_status.value, by=by, note=note or str(reason),
                         chap_evidence_seq=self._ev(rec_art))
        self.fragments.put(frag)
        for mo in self.tacit_store.by_fragment(fragment_id):
            mo.revocation_status = new_status
        return rec_art

    def supersede(self, old_fragment_id: str, new_fragment_id: str, *, by: str,
                  note: str | None = None) -> str:
        old = self.fragments.require(old_fragment_id)
        ref = self._ensure_refs(old)
        self.adapter.control_event("control.supersede", sender=by, params={
            "task_id": ref["task"], "supersedes": old_fragment_id, "by_fragment": new_fragment_id})
        sup_art = self.adapter.append_artefact("tacit.supersession_record", produced_by=by,
            content={"superseded": old_fragment_id, "superseded_by": new_fragment_id, "note": note},
            task=ref["task"], based_on=ref["artefact"])
        old.revocation_status = RevocationStatus.superseded
        old.validation_state = VS.superseded
        old.add_lineage(state=VS.superseded.value, by=by,
                        note=f"superseded by {new_fragment_id}", chap_evidence_seq=self._ev(sup_art))
        self.fragments.put(old)
        for mo in self.tacit_store.by_fragment(old_fragment_id):
            mo.revocation_status = RevocationStatus.superseded
        return sup_art

    def withdraw_consent(self, fragment_id: str, *, by: str, note: str | None = None) -> str:
        frag = self.fragments.require(fragment_id)
        frag.consent.consent_status = ConsentStatus.withdrawn
        self.fragments.put(frag)
        return self.revoke(fragment_id, reason=RevocationReason.consent_withdrawn, by=by, note=note)

    # ---- contestability --------------------------------------------------------
    def contest(self, fragment_id: str, action: ContestAction, *, raised_by: str,
                rationale: str, proposed_correction: str | None = None) -> dict[str, Any]:
        """Record a worker or reviewer contest action as an auditable event.

        Every action first appends a ``tacit.validation_event`` carrying the
        contestability record, then routes: withdraw revokes via consent
        withdrawal; re-elicitation and challenge/correct escalate the fragment's
        task to the Mission Group for the appropriate follow-up.
        """
        action = ContestAction(action)
        record = ContestabilityRecord(fragment_id=fragment_id, action=action, raised_by=raised_by,
                                      rationale=rationale, proposed_correction=proposed_correction)
        frag = self.fragments.require(fragment_id)
        ref = self._ensure_refs(frag)
        rec_art = self.adapter.append_artefact(
            "tacit.validation_event", produced_by=raised_by,
            content={"event": "contestability", **record.model_dump(mode="json")},
            task=ref["task"], based_on=ref["artefact"])
        frag.add_lineage(state=frag.validation_state.value, by=raised_by,
                         note=f"contested: {action.value}", chap_evidence_seq=self._ev(rec_art))
        self.fragments.put(frag)
        result: dict[str, Any] = {"contestability_record": rec_art}

        if action == ContestAction.withdraw:
            result["revocation"] = self.withdraw_consent(fragment_id, by=raised_by, note=rationale)
            return result

        if action == ContestAction.request_re_elicitation:
            self.adapter.escalate(sender=raised_by, original_task_id=ref["task"],
                                  assignee=self.mission_group.uri, kind="tacit.re_elicit",
                                  task_input={"fragment_id": fragment_id, "reason": rationale})
            req = ReElicitationRequest(fragment_id=fragment_id, requested_by=raised_by, reason=rationale)
            result["re_elicitation_request"] = self.adapter.append_artefact(
                "tacit.re_elicitation_request", produced_by=raised_by,
                content=req.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            return result

        # challenge / correct: escalate to the Mission Group for Tier-2 re-review.
        result["escalated_task"] = self.adapter.escalate(
            sender=raised_by, original_task_id=ref["task"],
            assignee=self.mission_group.uri, kind="tacit.validate.tier2",
            task_input={"fragment_id": fragment_id, "contest": action.value,
                        "reason": rationale, "proposed_correction": proposed_correction})
        return result
