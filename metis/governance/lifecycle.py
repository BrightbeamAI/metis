"""Governance lifecycle orchestrator.

Wires fragment-state transitions to CHAP review and control events and to the tacit.* record
artefacts (review_decision, promotion_record, rejection_record, re_elicitation_request,
revocation_record, supersession_record). Promotion creates the fragment's TacitMemoryObject,
and a later promotion rebuilds it in place. Every step is appended to the evidence chain, and
people make every decision recorded here.

A fragment is reviewed when it is first submitted, and again whenever a review is reopened: when
a held fragment returns, when someone contests the fragment, or when its review date comes due.
A fragment in use stays in use while its re-review is open, until the reviewers decide.
"""
from __future__ import annotations

from typing import Any

from .. import clock
from ..consent.contestability import ContestabilityRecord, ContestAction
from ..consent.model import ConsentStatus
from ..consent.revocation import RevocationReason, RevocationRecord
from ..fragment.confidence import evidence_confidence
from ..fragment.events import fragment_to_content
from ..fragment.model import TacitFragment
from ..fragment.store import FragmentStore
from ..integrations.chap import review as chap_review
from ..memory.tacit import AgentVisibility, TacitMemoryObject, TacitMemoryStore
from ..retrieval.gate import RetrievalGate
from ..taxonomy.categories import AuthorityLayer, RevocationStatus, ValidationState
from ..validation.mission_group import MissionGroup
from ..validation.promotion import PromotionRecord
from ..validation.re_elicitation import ReElicitationRequest
from ..validation.rejection import RejectionRecord
from ..validation.states import InvalidTransition, assert_transition
from .authority import layer_for_outcome, state_for_outcome
from .policy import GovernancePolicy

VS = ValidationState
_PROMOTIONS = ("promoted_to_advisory", "promoted_to_controlled")
# A fragment in these states is re-reviewed in place: its state holds until the decision.
_IN_USE = (VS.promoted_to_advisory, VS.promoted_to_controlled, VS.expired)
_OPEN = "open"


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
        clock_source=None,
    ) -> None:
        self.clock_source = clock_source
        self.fragments = fragment_store
        self.adapter = adapter
        self.tacit_store = tacit_store if tacit_store is not None else TacitMemoryStore()
        self.policy = policy or GovernancePolicy()
        self.mission_group = mission_group or MissionGroup()
        self.gate = gate or RetrievalGate()
        # fragment_id -> the CHAP task and fragment artefact its current review runs on, plus
        # "review": "open" while a re-review of a fragment in use awaits its decision.
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

    def _open_review_task(self, fragment: TacitFragment, *, reason: str) -> dict[str, str]:
        """A fresh Mission Group review task carrying a snapshot of the fragment as it stands."""
        task_id = self.adapter.create_task(
            "tacit.validate.tier2", assignee=self.mission_group.uri,
            delegator=self.mission_group.uri,
            task_input={"fragment_id": fragment.fragment_id, "reason": reason or "review"})
        art = self.adapter.append_artefact(
            "tacit.fragment", produced_by=self.mission_group.uri,
            content=fragment_to_content(fragment), task=task_id)
        ref = {"artefact": art, "task": task_id}
        self.refs[fragment.fragment_id] = ref
        return ref

    def _close_review(self, fragment_id: str) -> None:
        ref = self.refs.get(fragment_id)
        if ref is not None:
            ref.pop("review", None)

    def _ev(self, artefact_id: str) -> int | None:
        return self.adapter.artefact_evidence.get(artefact_id)

    # ---- Tier-2 ----------------------------------------------------------------
    def _sync_review_status(self, frag: TacitFragment) -> None:
        frag.provenance.human_review_status = frag.validation_state.value

    def _deciders(self, outcome: str, decided_by: list[str] | None) -> list[str]:
        """The reviewers whose decisions are recorded for ``outcome``.

        Granting authority needs as many distinct Mission Group approvals as the review rule
        demands; rejecting, holding, or re-eliciting needs one reviewer. When ``decided_by``
        is omitted, the configured members are used in order (a convenience for demos and
        tests; production callers pass authenticated reviewer identities).
        """
        members = self.mission_group.reviewers()
        chosen = list(dict.fromkeys(decided_by)) if decided_by else None
        if chosen:
            outsiders = [u for u in chosen if u not in members]
            if outsiders:
                raise PermissionError(f"Not Mission Group reviewers: {', '.join(outsiders)}")
        if outcome in _PROMOTIONS:
            need = self.policy.approvals_required(len(members))
            chosen = chosen or members[:need]
            if len(chosen) < need:
                raise PermissionError(
                    f"Promotion needs {need} distinct Mission Group approvals under "
                    f"{self.policy.review_rule}; got {len(chosen)}.")
            return chosen
        return (chosen or members)[:1]

    def _awaiting(self, ref: dict[str, str] | None) -> bool:
        """True when the CHAP task behind ``ref`` still awaits a review decision."""
        return bool(ref) and self.adapter.task_state(ref["task"]) == "review_requested"

    def review_open(self, fragment_id: str) -> bool:
        """True while a Mission Group review of the fragment awaits its decision in CHAP."""
        frag = self.fragments.require(fragment_id)
        ref = self.refs.get(fragment_id)
        if frag.validation_state == VS.tier2_pending or (ref or {}).get("review") == _OPEN:
            return self._awaiting(ref)
        return False

    @staticmethod
    def _require_active(frag: TacitFragment) -> None:
        if frag.revocation_status != RevocationStatus.active:
            raise InvalidTransition(
                f"{frag.fragment_id} is {frag.revocation_status.value}; it is out of review.")

    @clock.scoped
    def submit_for_tier2(self, fragment_id: str, *, by: str) -> None:
        frag = self.fragments.require(fragment_id)
        ref = self._ensure_refs(frag)
        assert_transition(frag.validation_state, VS.tier2_pending)
        frag.validation_state = VS.tier2_pending
        entry = self.adapter.review_request(
            sender=by, reviewers=self.mission_group.reviewers(),
            artefact_id=ref["artefact"], task_id=ref["task"], rule=self.policy.review_rule)
        frag.add_lineage(state=VS.tier2_pending.value, by=by,
                         note=f"submitted for Mission Group review ({self.policy.review_rule})",
                         chap_evidence_seq=entry.seq, chap_artefact_ref=ref["artefact"])
        self._sync_review_status(frag)
        self.fragments.put(frag)

    @clock.scoped
    def request_review(self, fragment_id: str, *, by: str | None = None, reason: str = "") -> str:
        """Open a Mission Group review of a fragment; return the CHAP task it runs on.

        A fragment awaiting a decision keeps the review it has, and a confirmed fragment is
        submitted on its capture task. A held fragment, and a fragment in use or past its
        review date, get a fresh ``tacit.validate.tier2`` task with a snapshot of the
        fragment. A fragment in use stays in use until the reviewers decide.
        """
        frag = self.fragments.require(fragment_id)
        by = by or self.mission_group.uri
        self._require_active(frag)
        if self.review_open(fragment_id):
            return self.refs[fragment_id]["task"]
        state = frag.validation_state
        if state == VS.tier1_confirmed:
            self.submit_for_tier2(fragment_id, by=by)
            return self.refs[fragment_id]["task"]
        if state == VS.held:
            ref = self._open_review_task(frag, reason=reason)
            self.submit_for_tier2(fragment_id, by=by)
            return ref["task"]
        if state in _IN_USE or state == VS.tier2_pending:
            # tier2_pending here means its review task closed without a recorded decision.
            ref = self._open_review_task(frag, reason=reason)
            entry = self.adapter.review_request(
                sender=by, reviewers=self.mission_group.reviewers(),
                artefact_id=ref["artefact"], task_id=ref["task"], rule=self.policy.review_rule)
            if state in _IN_USE:
                ref["review"] = _OPEN
                note = f"re-review opened ({self.policy.review_rule})"
            else:
                note = f"review reopened ({self.policy.review_rule})"
            frag.add_lineage(state=state.value, by=by, note=f"{note}: {reason}" if reason else note,
                             chap_evidence_seq=entry.seq, chap_artefact_ref=ref["artefact"])
            self.fragments.put(frag)
            return ref["task"]
        raise InvalidTransition(
            f"{fragment_id} is {state.value}; a Mission Group review cannot be opened for it.")

    @clock.scoped
    def tier2_review(
        self,
        fragment_id: str,
        outcome: str,
        *,
        by: str | None = None,
        reviewers: list[str] | None = None,
        decided_by: list[str] | None = None,
        dimension_assessments: dict[str, str] | None = None,
        summary: str = "",
        change_control: dict[str, Any] | None = None,
        model_assist_ref: str | None = None,
        linked_procedural_refs: list[str] | None = None,
        linked_semantic_refs: list[str] | None = None,
        linked_episodic_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Record the Mission Group's decision on a fragment, opening its review if needed.

        Promotion, renewal, and moves between the Advisory and Controlled layers need the
        review rule's quorum of distinct named reviewers; holding, rejecting, or re-eliciting
        needs one. The outcome and the policy are checked before any decision is recorded.
        """
        if outcome not in chap_review.OUTCOME_TO_METHOD:
            raise ValueError(f"Unknown outcome: {outcome}")
        frag = self.fragments.require(fragment_id)
        by = by or self.mission_group.uri
        deciders = self._deciders(outcome, decided_by)
        self._require_active(frag)

        new_state = state_for_outcome(outcome)
        reviewing = (VS.tier2_pending if frag.validation_state in (VS.tier1_confirmed, VS.held)
                     else frag.validation_state)
        assert_transition(reviewing, new_state)
        target = None
        if outcome in _PROMOTIONS:
            target = layer_for_outcome(outcome)
            ok, why = self.policy.can_promote(frag, target, change_control=change_control,
                                              mission_group_reviewed=True)
            if not ok:
                raise PermissionError(f"Promotion blocked by policy: {why}")

        if not self.review_open(fragment_id):
            self.request_review(fragment_id, by=by, reason=summary)
            frag = self.fragments.require(fragment_id)
        ref = self._ensure_refs(frag)
        in_use = frag.validation_state in _IN_USE

        # Confidence follows the evidence as it stands at review.
        frag.confidence = evidence_confidence(frag.evidence)

        review = self.mission_group.review(
            fragment_id, outcome, reviewers=reviewers or deciders,
            dimension_assessments=dimension_assessments, summary=summary,
            model_assist_ref=model_assist_ref)

        method = chap_review.OUTCOME_TO_METHOD[outcome]
        state = None
        decided: list[str] = []
        for reviewer in deciders:
            state = self.adapter.decide(method, sender=reviewer, based_on=ref["artefact"],
                                        task_id=ref["task"],
                                        content={"outcome": outcome, "summary": summary}).get("state")
            decided.append(reviewer)
            if target is not None and state == "completed":
                break  # the review rule is met, and CHAP accepts no further decisions
        if target is not None and state != "completed":
            raise PermissionError(
                f"The Mission Group review did not complete under {self.policy.review_rule}.")
        if not reviewers and decided != deciders:
            review = review.model_copy(update={"reviewers": decided})
        review_art = self.adapter.append_artefact(
            "tacit.review_decision", produced_by=by, content=review.model_dump(mode="json"),
            task=ref["task"], based_on=ref["artefact"])
        self._close_review(fragment_id)
        result: dict[str, Any] = {"review": review, "review_artefact": review_art,
                                  "decided_by": decided, "review_task": ref["task"]}

        if target is not None:
            old_layer = frag.authority_layer
            frag.authority_layer = target
            frag.validation_state = new_state
            frag.provenance.mission_group_reviewed_by = by
            frag.review_due_at = self.policy.review_due(frag, target, clock.now_dt()).isoformat()
            if not frag.expiry_triggers:
                frag.expiry_triggers = list(self.policy.expiry_triggers)
            pr = PromotionRecord(fragment_id=fragment_id, from_layer=old_layer, to_layer=target,
                                 new_state=new_state, promoted_by=by, approvers=decided,
                                 decision_rule=self.policy.review_rule, review_ref=review_art,
                                 change_control=change_control, rationale=summary)
            pr_art = self.adapter.append_artefact("tacit.promotion_record", produced_by=by,
                        content=pr.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            if old_layer == AuthorityLayer.evidence:
                verb = "promoted"
            elif old_layer == target:
                verb = "renewed" if in_use else "reinstated"
            else:
                verb = f"moved from {old_layer.value} to {target.value}"
            frag.add_lineage(state=new_state.value, by=by,
                             note=f"{verb} by the Mission Group ({self.policy.review_rule}: "
                                  f"{', '.join(decided)})",
                             chap_evidence_seq=self._ev(pr_art), chap_artefact_ref=pr_art)
            self._sync_review_status(frag)
            self.fragments.put(frag)
            mem = self._upsert_memory_object(
                frag, change_control=change_control, review_art=review_art,
                linked_procedural_refs=linked_procedural_refs,
                linked_semantic_refs=linked_semantic_refs,
                linked_episodic_refs=linked_episodic_refs)
            result.update({"promotion_record": pr_art, "memory": mem})
            return result

        decider = decided[0]
        if outcome == "rejected":
            frag.validation_state = VS.rejected
            frag.revocation_status = RevocationStatus.rejected
            frag.authority_layer = AuthorityLayer.evidence  # rejected fragments sit in Evidence
            rr = RejectionRecord(fragment_id=fragment_id, rejected_by=decider,
                                 reason=summary or "rejected at Tier-2", review_ref=review_art)
            rr_art = self.adapter.append_artefact("tacit.rejection_record", produced_by=by,
                        content=rr.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
            frag.add_lineage(state=VS.rejected.value, by=decider, note="rejected (retained for audit)",
                             chap_evidence_seq=self._ev(rr_art), chap_artefact_ref=rr_art)
            self._sync_review_status(frag)
            self.fragments.put(frag)
            self._sync_memory(frag)
            result["rejection_record"] = rr_art
            return result

        if outcome == "held":
            frag.validation_state = VS.held
            frag.add_lineage(state=VS.held.value, by=decider, note=summary,
                             chap_evidence_seq=self._ev(review_art), chap_artefact_ref=review_art)
            self._sync_review_status(frag)
            self.fragments.put(frag)
            self._sync_memory(frag)
            return result

        # re_elicit
        frag.validation_state = VS.re_elicit
        frag.revocation_status = RevocationStatus.under_re_elicitation
        req = ReElicitationRequest(fragment_id=fragment_id, requested_by=decider,
                                   reason=summary or "re-elicitation requested", review_ref=review_art)
        req_art = self.adapter.append_artefact("tacit.re_elicitation_request", produced_by=by,
                    content=req.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
        frag.add_lineage(state=VS.re_elicit.value, by=decider,
                         chap_evidence_seq=self._ev(req_art), chap_artefact_ref=req_art)
        self._sync_review_status(frag)
        self.fragments.put(frag)
        self._sync_memory(frag)
        result["re_elicitation_request"] = req_art
        return result

    # ---- memory object ---------------------------------------------------------
    def _upsert_memory_object(self, frag: TacitFragment, *, change_control=None, review_art=None,
                              linked_procedural_refs=None, linked_semantic_refs=None,
                              linked_episodic_refs=None) -> TacitMemoryObject:
        """Create the fragment's memory object, or rebuild it in place after a later promotion.

        A rebuilt object keeps its memory id and its links, and adds the new review's evidence.
        """
        ref = self.refs.get(frag.fragment_id, {})
        previous = next(iter(self.tacit_store.by_fragment(frag.fragment_id)), None)
        if previous is None:
            self._mem_seq += 1
            memory_id = f"TM-{self._mem_seq:05d}"
            evidence_refs: list[int] = []
        else:
            memory_id = previous.memory_id
            evidence_refs = list(previous.linked_chap_evidence_refs)
            linked_procedural_refs = linked_procedural_refs or previous.linked_procedural_refs
            linked_semantic_refs = linked_semantic_refs or previous.linked_semantic_refs
            linked_episodic_refs = linked_episodic_refs or previous.linked_episodic_refs
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

    def _sync_memory(self, frag: TacitFragment) -> None:
        """Keep the fragment's memory objects in step with its state. (The gate itself reads
        the fragment, so a fragment out of use is withheld either way.)"""
        for mo in self.tacit_store.by_fragment(frag.fragment_id):
            mo.authority_layer = frag.authority_layer
            mo.validation_state = frag.validation_state
            mo.revocation_status = frag.revocation_status
            mo.review_due_at = frag.review_due_at
            if not frag.is_operationally_usable():
                mo.agent_visibility = AgentVisibility.hidden

    # ---- revocation / supersession --------------------------------------------
    @clock.scoped
    def revoke(self, fragment_id: str, *, reason: RevocationReason, by: str,
               note: str | None = None, superseded_by: str | None = None) -> str:
        frag = self.fragments.require(fragment_id)
        if RevocationReason(reason) == RevocationReason.consent_withdrawn:
            # Consent is the contributing worker's to withdraw, through any entry point.
            self._require_contributor(frag, by)
            frag.consent.consent_status = ConsentStatus.withdrawn
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
        if self._awaiting(ref):  # the revocation ends the open review
            self.adapter.cancel_task(ref["task"], sender=by,
                                     reason=f"revoked: {RevocationReason(reason).value}")
        self.adapter.control_event("control.cancel", sender=by, params={
            "task_id": ref["task"], "reason": str(reason), "fragment_id": fragment_id})
        rec_art = self.adapter.append_artefact("tacit.revocation_record", produced_by=by,
            content=rec.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
        self._close_review(fragment_id)
        frag.revocation_status = new_status
        if new_status == RevocationStatus.withdrawn:
            frag.validation_state = VS.withdrawn
        elif new_status == RevocationStatus.superseded:
            frag.validation_state = VS.superseded
        frag.add_lineage(state=new_status.value, by=by, note=note or str(reason),
                         chap_evidence_seq=self._ev(rec_art), chap_artefact_ref=rec_art)
        self._sync_review_status(frag)
        self.fragments.put(frag)
        self._sync_memory(frag)
        return rec_art

    @clock.scoped
    def supersede(self, old_fragment_id: str, new_fragment_id: str, *, by: str,
                  note: str | None = None) -> str:
        old = self.fragments.require(old_fragment_id)
        ref = self._ensure_refs(old)
        if self._awaiting(ref):  # the supersession ends the open review
            self.adapter.cancel_task(ref["task"], sender=by,
                                     reason=f"superseded by {new_fragment_id}")
        self.adapter.control_event("control.supersede", sender=by, params={
            "task_id": ref["task"], "supersedes": old_fragment_id, "by_fragment": new_fragment_id})
        sup_art = self.adapter.append_artefact("tacit.supersession_record", produced_by=by,
            content={"superseded": old_fragment_id, "superseded_by": new_fragment_id, "note": note},
            task=ref["task"], based_on=ref["artefact"])
        self._close_review(old_fragment_id)
        old.revocation_status = RevocationStatus.superseded
        old.validation_state = VS.superseded
        old.add_lineage(state=VS.superseded.value, by=by,
                        note=f"superseded by {new_fragment_id}", chap_evidence_seq=self._ev(sup_art),
                        chap_artefact_ref=sup_art)
        self._sync_review_status(old)
        self.fragments.put(old)
        self._sync_memory(old)
        return sup_art

    @staticmethod
    def _require_contributor(frag: TacitFragment, who: str) -> None:
        contributors = {frag.provenance.originating_participant, frag.provenance.observed_by,
                        frag.provenance.human_confirmed_by, frag.attribution.worker_or_group}
        if who not in contributors - {None}:
            raise PermissionError(
                "Only the worker who contributed this fragment can withdraw consent; "
                "reviewers retire fragments with revoke().")

    @clock.scoped
    def withdraw_consent(self, fragment_id: str, *, by: str, note: str | None = None) -> str:
        frag = self.fragments.require(fragment_id)
        self._require_contributor(frag, by)
        frag.consent.consent_status = ConsentStatus.withdrawn
        self.fragments.put(frag)
        return self.revoke(fragment_id, reason=RevocationReason.consent_withdrawn, by=by, note=note)

    # ---- contestability --------------------------------------------------------
    @clock.scoped
    def contest(self, fragment_id: str, action: ContestAction, *, raised_by: str,
                rationale: str, proposed_correction: str | None = None) -> dict[str, Any]:
        """Record a worker or reviewer contest action as an auditable event.

        Every action first appends a ``tacit.validation_event`` carrying the contestability
        record. Withdraw revokes the fragment through consent withdrawal and is open only to
        the contributing worker. Every other action (challenge, correct, supersede, request
        re-elicitation) puts the fragment before the Mission Group: it joins the open review
        or opens one, and the reviewers decide it with ``tier2_review``. A fragment already
        out of review (rejected, withdrawn, superseded, or awaiting re-elicitation) keeps the
        record, and the result names no review task.
        """
        action = ContestAction(action)
        record = ContestabilityRecord(fragment_id=fragment_id, action=action, raised_by=raised_by,
                                      rationale=rationale, proposed_correction=proposed_correction)
        frag = self.fragments.require(fragment_id)
        review_task = None
        if action == ContestAction.withdraw:
            self._require_contributor(frag, raised_by)
        else:
            try:
                review_task = self.request_review(
                    fragment_id, reason=f"{action.value}: {rationale}")
            except InvalidTransition:
                review_task = None
        ref = self._ensure_refs(frag)  # the open review's task, when there is one
        rec_art = self.adapter.append_artefact(
            "tacit.validation_event", produced_by=raised_by,
            content={"event": "contestability", **record.model_dump(mode="json")},
            task=ref["task"], based_on=ref["artefact"])
        frag.add_lineage(state=frag.validation_state.value, by=raised_by,
                         note=f"contested: {action.value}", chap_evidence_seq=self._ev(rec_art),
                         chap_artefact_ref=rec_art)
        self.fragments.put(frag)
        result: dict[str, Any] = {"contestability_record": rec_art}
        if review_task is not None:
            result["mission_group_task"] = review_task

        if action == ContestAction.withdraw:
            result["revocation"] = self.withdraw_consent(fragment_id, by=raised_by, note=rationale)
            return result

        if action == ContestAction.request_re_elicitation:
            req = ReElicitationRequest(fragment_id=fragment_id, requested_by=raised_by, reason=rationale)
            result["re_elicitation_request"] = self.adapter.append_artefact(
                "tacit.re_elicitation_request", produced_by=raised_by,
                content=req.model_dump(mode="json"), task=ref["task"], based_on=ref["artefact"])
        return result
