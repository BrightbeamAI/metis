"""Remember, create an Evidence-layer TacitFragment from a confirmed candidate.

The fragment enters the Evidence layer. It is NOT retrievable for operational advice until
Tier-2 review promotes it. It is stored as a CHAP artefact of kind ``tacit.fragment``.
"""
from __future__ import annotations

from ..conditions.context import TacitContext
from ..consent.model import ConsentRecord
from ..fragment.model import Attribution, FragmentEvidence, Provenance, TacitFragment
from ..taxonomy.categories import (
    AuthorityLayer,
    Category,
    SourcePathway,
    ValidationState,
    domain_of,
)
from .confirm import ConfirmationResult
from .infer import InferenceCandidate
from .observe import Observation


def build_fragment(
    observation: Observation,
    candidate: InferenceCandidate,
    confirmation: ConfirmationResult,
    *,
    fragment_id: str,
    capture_cell: str,
    operator_uri: str,
    consent: ConsentRecord,
    title: str | None = None,
    conditions: TacitContext | None = None,
    attribution: Attribution | None = None,
    evidence: FragmentEvidence | None = None,
    source_pathway: SourcePathway = SourcePathway.exogenous,
) -> TacitFragment:
    content = confirmation.corrected_content or confirmation.summary or candidate.hypothesis
    category = Category(candidate.category)
    provenance = Provenance(
        observed_by=operator_uri,
        originating_participant=operator_uri,
        capture_cell=capture_cell,
        source_pathway=source_pathway,
        source_event=observation.observation_id,
        capture_method=f"observe->infer->whisper->confirm ({observation.source})",
        human_confirmed_by=operator_uri,
    )
    return TacitFragment.new(
        fragment_id=fragment_id,
        title=title or f"{category.value}: {content[:48]}",
        content=content,
        category=category,
        domain=domain_of(category),
        source_pathway=source_pathway,
        provenance=provenance,
        conditions=conditions or observation.context,
        evidence=evidence or FragmentEvidence(),
        confidence=candidate.confidence,
        authority_layer=AuthorityLayer.evidence,
        validation_state=ValidationState.tier1_confirmed,
        consent=consent,
        attribution=attribution or Attribution(mode=consent.attribution_mode.value),
    )
