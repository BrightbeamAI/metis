"""The README's figures render on GitHub, PyPI, and Glama, and PyPI shows the release's own."""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
FIGURE = re.compile(
    r"!\[[^\]]+\]\(https://raw\.githubusercontent\.com/BrightbeamAI/metis/main/(docs/assets/[^)]+)\)"
)


def _builder():
    path = ROOT / "scripts" / "build_pypi_readme.py"
    spec = importlib.util.spec_from_file_location("build_pypi_readme", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_figures_are_markdown_images_of_files_in_the_repository():
    # Glama drops HTML images from a README, so each figure is a Markdown image.
    figures = FIGURE.findall(README)
    assert figures
    assert all((ROOT / path).is_file() for path in figures)
    assert '<img src="docs/assets' not in README


def test_the_pypi_page_shows_the_figures_of_its_release():
    builder = _builder()
    ref = builder.release_ref((ROOT / "pyproject.toml").read_text())
    page = builder.build()
    assert "/BrightbeamAI/metis/main/" not in page
    for path in FIGURE.findall(README):
        assert f"https://raw.githubusercontent.com/BrightbeamAI/metis/{ref}/{path}" in page
