"""The committed JSON Schemas must match the models they describe."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("generate_schemas", ROOT / "scripts" / "generate_schemas.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def test_committed_schemas_match_the_models():
    stale = [name for name in gen.SCHEMAS
             if (ROOT / "schemas" / f"{name}.schema.json").read_text() != gen.render(name)]
    assert not stale, f"regenerate with `python scripts/generate_schemas.py`: {stale}"
