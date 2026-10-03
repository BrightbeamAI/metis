"""The condition-aware retrieval gate.

This is NOT semantic search. A fragment is eligible only when every governance check
passes, evaluated in a fixed priority order so the first failing check is the recorded
reason. Applicability (conditions and exclusions) is decided before risk escalation, so a
fragment that does not apply is reported as not applying, never as an escalation. Local
models never decide eligibility; the gate is fully deterministic.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from dataclasses import dataclass

from .. import clock
from ..conditions.context import TacitContext
from ..conditions.matcher import match
from ..fragment.model import TacitFragment
from ..taxonomy.categories import AuthorityLayer, RevocationStatus, SourcePathway, ValidationState
from .blocked_reasons import BlockedReason
from .decision import BlockedItem, EligibleItem, RetrievalDecision

_USABLE_STATES = {ValidationState.promoted_to_advisory, ValidationState.promoted_to_controlled}
_ESCALATE_RISK = {"high", "critical"}
# Conditions that identify *what* a fragment is about. A near miss matches all of these but
# fails a situational condition (mode, shift, trigger, environment) or an exclusion.
_IDENTITY_KEYS = frozenset({"site", "area", "line", "equipment_family", "equipment_id",
                            "product_family", "material_lot"})


@dataclass
class Eligibility:
    ok: bool
    reason: BlockedReason | None = None
    detail: str = ""
    near_miss: bool = False

    @property
    def escalate(self) -> bool:
        """True when a person must decide: a near miss, or an applicable high-risk case."""
        return self.near_miss or self.reason == BlockedReason.risk_class_requires_human_escalation


def _near_miss(conditions: TacitContext, unmatched: list[str], excluded: bool) -> bool:
    identity_constrained = any(getattr(conditions, k) is not None for k in _IDENTITY_KEYS)
    if not identity_constrained or "role" in unmatched:
        return False
    if any(k in _IDENTITY_KEYS for k in unmatched):
        return False
    return excluded or bool(unmatched)


def _parse_dt(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    try:
        dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=_dt.timezone.utc)
    except Exception:
        return None


class RetrievalGate:
    def __init__(self, *, escalate_risk_classes: set[str] | None = None) -> None:
        self.escalate_risk_classes = escalate_risk_classes or set(_ESCALATE_RISK)

    def evaluate(
        self,
        fragment: TacitFragment,
        context: TacitContext,
        *,
        role: str | None = None,
        now: _dt.datetime | None = None,
    ) -> Eligibility:
        now = now or clock.now_dt()

        # 1. Revocation status (most decisive).
        if fragment.revocation_status != RevocationStatus.active:
            return Eligibility(False, BlockedReason.revoked_or_superseded,
                               f"revocation_status={fragment.revocation_status.value}")

        # 2. Consent.
        if not fragment.consent.permits_retrieval():
            return Eligibility(False, BlockedReason.consent_withdrawn, "consent withdrawn")

        # 3. Endogenous fragments not yet promoted require review (more specific than #4).
        if fragment.source_pathway == SourcePathway.endogenous and not fragment.is_operationally_usable():
            return Eligibility(False, BlockedReason.endogenous_fragment_requires_review,
                               "endogenous fragment must pass Mission Group review")

        # 4. Authority layer.
        if fragment.authority_layer == AuthorityLayer.evidence:
            return Eligibility(False, BlockedReason.evidence_layer_not_authorised,
                               "Evidence-layer fragment")

        # 5. Validation state.
        if fragment.validation_state not in _USABLE_STATES:
            if fragment.validation_state == ValidationState.expired:
                return Eligibility(False, BlockedReason.expired_review_date, "validation_state=expired")
            return Eligibility(False, BlockedReason.tier2_validation_missing,
                               f"validation_state={fragment.validation_state.value}")

        # 6. Review date / expiry.
        review_due = _parse_dt(fragment.review_due_at)
        if review_due is not None and now > review_due:
            return Eligibility(False, BlockedReason.expired_review_date, "review_due_at elapsed")

        # 7. Role authorisation (distinct from generic condition match).
        if role is not None and fragment.conditions.role is not None:
            allowed = fragment.conditions.role
            allowed_set = set(allowed) if isinstance(allowed, list) else {allowed}
            if role not in allowed_set:
                return Eligibility(False, BlockedReason.role_not_authorised, f"role={role}")

        # 8. Applicability: conditions and exclusions.
        m = match(fragment.conditions, context, now=now)
        if not m.ok:
            if m.out_of_window and "elapsed" in m.detail:
                return Eligibility(False, BlockedReason.expired_review_date, m.detail)
            near = _near_miss(fragment.conditions, m.unmatched, m.excluded_by is not None)
            if m.excluded_by is not None:
                return Eligibility(False, BlockedReason.exclusion_condition_applies,
                                   str(m.excluded_by), near_miss=near)
            return Eligibility(False, BlockedReason.conditions_do_not_match,
                               ",".join(m.unmatched) or m.detail, near_miss=near)

        # 9. Controlled layer requires exact (scalar, fully-specified) matching.
        if fragment.authority_layer == AuthorityLayer.controlled:
            if not self._is_exact_match(fragment.conditions, context):
                return Eligibility(False, BlockedReason.controlled_layer_requires_exact_match,
                                   "controlled layer needs exact, fully-specified conditions")

        # 10. Risk class: the fragment applies, but the situation needs a person.
        if context.risk_class in self.escalate_risk_classes:
            return Eligibility(False, BlockedReason.risk_class_requires_human_escalation,
                               f"risk_class={context.risk_class}")

        return Eligibility(True, None, "all governance checks passed")

    @staticmethod
    def _is_exact_match(conditions: TacitContext, context: TacitContext) -> bool:
        from ..conditions.context import CONTEXT_KEYS

        for key in CONTEXT_KEYS:
            constraint = getattr(conditions, key)
            if constraint is None:
                continue
            if isinstance(constraint, list):  # loose "any-of" is not exact enough for controlled
                return False
            if getattr(context, key) != constraint:
                return False
        return True

    # ---- batch retrieval -------------------------------------------------------
    def retrieve(
        self,
        fragments: Iterable[TacitFragment],
        context: TacitContext,
        *,
        role: str | None = None,
        now: _dt.datetime | None = None,
        memory_ids: dict[str, str] | None = None,
    ) -> RetrievalDecision:
        memory_ids = memory_ids or {}
        now = now or clock.now_dt()
        decision = RetrievalDecision(
            requested_role=role,
            runtime_context=context.model_dump(mode="json", exclude_none=True),
            hints_observed={"role": role, "risk_class": context.risk_class},
        )
        for frag in fragments:
            el = self.evaluate(frag, context, role=role, now=now)
            if el.ok:
                decision.eligible.append(EligibleItem(
                    fragment_id=frag.fragment_id,
                    memory_id=memory_ids.get(frag.fragment_id),
                    authority_layer=frag.authority_layer.value,
                    confidence=frag.confidence,
                    use_constraints=frag.use_constraints,
                ))
            else:
                decision.blocked.append(BlockedItem(
                    fragment_id=frag.fragment_id,
                    memory_id=memory_ids.get(frag.fragment_id),
                    reason=el.reason.value if el.reason else "unknown",
                    detail=el.detail,
                    escalate=el.escalate,
                ))
        escalated = sum(1 for b in decision.blocked if b.escalate)
        decision.rationale = (
            f"{len(decision.eligible)} eligible, {len(decision.blocked)} blocked "
            f"({escalated} for a person to decide) under condition-aware governance "
            f"(not semantic similarity)."
        )
        return decision
