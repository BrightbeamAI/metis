"""Cross-walks from K1-K17 categories to whisper templates and governance defaults."""
from __future__ import annotations

from .categories import Category

# Categories that ship with a dedicated low-burden whisper template (prompts/whispers/).
CATEGORY_WHISPER_TEMPLATE: dict[Category, str] = {
    Category.K2_embodied: "K2_embodied",
    Category.K3_rhythmic: "K3_rhythmic",
    Category.K5_material: "K5_material",
    Category.K7_sensory: "K7_sensory",
    Category.K9_heuristic: "K9_heuristic",
    Category.K10_diagnostic: "K10_diagnostic",
    Category.K11_anticipatory: "K11_anticipatory",
    Category.K12_metacognitive: "K12_metacognitive",
    Category.K14_collaborative: "K14_collaborative",
}

# Categories that require extra scrutiny before promotion (paper S4, S5, P12).
HIGH_SCRUTINY_CATEGORIES: set[Category] = {
    Category.K8_aesthetic,            # do not convert perception into a universal rule
    Category.K13_affective_regulatory,  # consent-bound; avoid covert inference
    Category.K15_cultural_narrative,
    Category.K16_judgemental_ethical,   # never automated
    Category.K17_strategic,
}

# Categories that must never become Controlled-layer automated instruction.
NEVER_CONTROLLED: set[Category] = {
    Category.K16_judgemental_ethical,
    Category.K13_affective_regulatory,
}


def whisper_template_for(category: Category) -> str:
    return CATEGORY_WHISPER_TEMPLATE.get(Category(category), "generic_low_burden")


def k_number(category: Category) -> int:
    return int(Category(category).value.split("_", 1)[0][1:])
