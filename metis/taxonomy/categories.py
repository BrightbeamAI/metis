"""The K1-K17 tacit taxonomy, six domains, pathways, authority layers, and lifecycle
states, from "The Fourth Stratum".

The taxonomy is descriptive and governs *how* a fragment is captured and *what evidence*
it needs before it can influence work. It is never a claim that a fragment is true.
"""
from __future__ import annotations

from enum import Enum


class Domain(str, Enum):
    procedural_embodied = "procedural_embodied"
    material_equipment = "material_equipment"
    perceptual_aesthetic = "perceptual_aesthetic"
    inferential = "inferential"
    metacognitive_affective = "metacognitive_affective"
    social_normative = "social_normative"


class SourcePathway(str, Enum):
    exogenous = "exogenous"   # captured from situated human practice
    endogenous = "endogenous"  # surfaced from an agent's own operational traces


class AuthorityLayer(str, Enum):
    evidence = "evidence"
    advisory = "advisory"
    controlled = "controlled"


class ValidationState(str, Enum):
    captured = "captured"
    worker_confirmed = "worker_confirmed"
    tier1_confirmed = "tier1_confirmed"
    tier2_pending = "tier2_pending"
    promoted_to_advisory = "promoted_to_advisory"
    promoted_to_controlled = "promoted_to_controlled"
    held = "held"
    rejected = "rejected"
    re_elicit = "re_elicit"
    withdrawn = "withdrawn"
    superseded = "superseded"
    expired = "expired"


class RevocationStatus(str, Enum):
    active = "active"
    withdrawn = "withdrawn"
    superseded = "superseded"
    rejected = "rejected"
    under_re_elicitation = "under_re_elicitation"
    retired = "retired"


class Category(str, Enum):
    K1_procedural = "K1_procedural"
    K2_embodied = "K2_embodied"
    K3_rhythmic = "K3_rhythmic"
    K4_equipment_specific = "K4_equipment_specific"
    K5_material = "K5_material"
    K6_tool_extended = "K6_tool_extended"
    K7_sensory = "K7_sensory"
    K8_aesthetic = "K8_aesthetic"
    K9_heuristic = "K9_heuristic"
    K10_diagnostic = "K10_diagnostic"
    K11_anticipatory = "K11_anticipatory"
    K12_metacognitive = "K12_metacognitive"
    K13_affective_regulatory = "K13_affective_regulatory"
    K14_collaborative = "K14_collaborative"
    K15_cultural_narrative = "K15_cultural_narrative"
    K16_judgemental_ethical = "K16_judgemental_ethical"
    K17_strategic = "K17_strategic"


class CategoryMeta:
    __slots__ = ("category", "label", "domain", "spender_quadrant", "capture_modality",
                 "loop_role", "description")

    def __init__(self, category, label, domain, spender_quadrant, capture_modality,
                 loop_role, description):
        self.category = category
        self.label = label
        self.domain = domain
        self.spender_quadrant = spender_quadrant
        self.capture_modality = capture_modality
        self.loop_role = loop_role
        self.description = description


_D = Domain
CATEGORY_META: dict[Category, CategoryMeta] = {
    Category.K1_procedural: CategoryMeta(
        Category.K1_procedural, "Procedural", _D.procedural_embodied, "Conscious / Social",
        "Document ingestion; procedure analysis", "Reference baseline; not a primary tacit target",
        "Formal routines and prescribed task sequences. Usually already documented."),
    Category.K2_embodied: CategoryMeta(
        Category.K2_embodied, "Embodied", _D.procedural_embodied, "Automatic / Individual",
        "Multimodal observation; expert confirmation", "Observe action; prompt for confirmation at a natural pause",
        "Bodily skill and felt physical adjustment that is hard to state in words."),
    Category.K3_rhythmic: CategoryMeta(
        Category.K3_rhythmic, "Rhythmic", _D.procedural_embodied, "Automatic / Individual",
        "Action-timing analysis; pause/tempo comparison", "Detect cadence, waiting, tempo and timing differences",
        "Timing and process cadence: when to wait, when to act, how long a step really takes."),
    Category.K4_equipment_specific: CategoryMeta(
        Category.K4_equipment_specific, "Equipment-specific", _D.material_equipment, "Automatic / Individual-Social",
        "Maintenance logs; cross-equipment comparison", "Compare equipment-specific deviations and adaptations",
        "Adaptations specific to a particular machine, line, or asset."),
    Category.K5_material: CategoryMeta(
        Category.K5_material, "Material", _D.material_equipment, "Automatic / Individual",
        "Outcome correlation with material lots; operator narration", "Prompt on lot, batch, or material-state changes",
        "Feel for materials and how they behave under specific lots or conditions."),
    Category.K6_tool_extended: CategoryMeta(
        Category.K6_tool_extended, "Tool-extended", _D.material_equipment, "Automatic / Individual",
        "Tool-use traces; substitution events", "Detect tool substitutions and workarounds",
        "Skill that lives partly in the tool: substitutions, jigs, and workarounds."),
    Category.K7_sensory: CategoryMeta(
        Category.K7_sensory, "Sensory", _D.perceptual_aesthetic, "Automatic / Individual",
        "Multimodal cue capture; on-cue narration", "Capture cue-triggered noticing; request on-cue narration",
        "Perceptual cues (sound, smell, vibration, look) noticed before a formal measure changes."),
    Category.K8_aesthetic: CategoryMeta(
        Category.K8_aesthetic, "Aesthetic", _D.perceptual_aesthetic, "Automatic / Individual",
        "Expert annotation of exemplars", "Use exemplar annotation and expert comparison",
        "Quality distinctions learned through exemplars: when something 'looks off'."),
    Category.K9_heuristic: CategoryMeta(
        Category.K9_heuristic, "Heuristic", _D.inferential, "Conscious-Automatic / Individual",
        "In-flow prompt; exception logging", "Prompt at an exception, threshold, or deviation moment",
        "Rules-of-thumb used at exceptions and thresholds."),
    Category.K10_diagnostic: CategoryMeta(
        Category.K10_diagnostic, "Diagnostic", _D.inferential, "Conscious / Individual",
        "Critical decision method; incident reconstruction", "Trigger mini-CTA or incident reconstruction",
        "Reasoning that localises a fault or explains an anomaly."),
    Category.K11_anticipatory: CategoryMeta(
        Category.K11_anticipatory, "Anticipatory", _D.inferential, "Automatic / Individual",
        "Pre-event prompting on detected divergence", "Prompt before a predicted event or divergence",
        "Sensing that something is about to happen before it shows up in the data."),
    Category.K12_metacognitive: CategoryMeta(
        Category.K12_metacognitive, "Meta-cognitive", _D.metacognitive_affective, "Conscious / Individual",
        "Reflective probing; help-seeking pattern analysis", "Examine hesitation, help-seeking, and escalation patterns",
        "Knowing the limits of one's competence and when to escalate or ask for help."),
    Category.K13_affective_regulatory: CategoryMeta(
        Category.K13_affective_regulatory, "Affective-regulatory", _D.metacognitive_affective, "Automatic / Individual",
        "Consented affective cues; post-event reflection", "Use consented cues and post-event reflection; avoid covert inference",
        "Composure and emotional regulation under pressure. Capture only with explicit consent."),
    Category.K14_collaborative: CategoryMeta(
        Category.K14_collaborative, "Collaborative", _D.social_normative, "Automatic / Social",
        "Analyse handoffs, dependencies, and cross-actor coordination", "Analyse handoffs and cross-actor coordination",
        "Coordination knowledge: handovers, dependencies, who-needs-what-when."),
    Category.K15_cultural_narrative: CategoryMeta(
        Category.K15_cultural_narrative, "Cultural-narrative", _D.social_normative, "Automatic / Social",
        "Long-form interview; story collection", "Capture through stories, interviews, and community interpretation",
        "Shared stories and norms that carry 'how we do things here'."),
    Category.K16_judgemental_ethical: CategoryMeta(
        Category.K16_judgemental_ethical, "Judgemental-ethical", _D.social_normative, "Conscious / Individual",
        "Post-event walk-through; structured reflection", "Use structured reflection and normative review",
        "Judgement about what is acceptable, fair, or safe. Never automated."),
    Category.K17_strategic: CategoryMeta(
        Category.K17_strategic, "Strategic", _D.social_normative, "Conscious / Individual-Social",
        "Strategic interview; cross-level alignment review", "Capture through leadership engagement and cross-level alignment",
        "Sense-making about direction and priorities across levels."),
}


def category_meta(category: Category) -> CategoryMeta:
    return CATEGORY_META[Category(category)]


def domain_of(category: Category) -> Domain:
    return CATEGORY_META[Category(category)].domain


def categories_in_domain(domain: Domain) -> list[Category]:
    return [c for c, m in CATEGORY_META.items() if m.domain == Domain(domain)]


ALL_CATEGORIES: list[Category] = list(CATEGORY_META.keys())
