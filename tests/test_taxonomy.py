from metis.taxonomy.categories import (
    ALL_CATEGORIES,
    CATEGORY_META,
    AuthorityLayer,
    Category,
    Domain,
    RevocationStatus,
    SourcePathway,
    ValidationState,
    categories_in_domain,
    domain_of,
)


def test_seventeen_categories():
    assert len(CATEGORY_META) == 17
    assert len(ALL_CATEGORIES) == 17
    for i in range(1, 18):
        assert any(c.value.startswith(f"K{i}_") for c in ALL_CATEGORIES)


def test_every_category_has_complete_metadata():
    for m in CATEGORY_META.values():
        assert m.label and m.description and m.capture_modality and m.loop_role
        assert isinstance(m.domain, Domain)


def test_domain_helpers():
    assert domain_of(Category.K7_sensory) == Domain.perceptual_aesthetic
    assert set(categories_in_domain(Domain.inferential)) == {
        Category.K9_heuristic, Category.K10_diagnostic, Category.K11_anticipatory}


def test_enums_have_expected_members():
    assert {p.value for p in SourcePathway} == {"exogenous", "endogenous"}
    assert {a.value for a in AuthorityLayer} == {"evidence", "advisory", "controlled"}
    assert "promoted_to_advisory" in {v.value for v in ValidationState}
    assert "withdrawn" in {r.value for r in RevocationStatus}
