"""Generate README_PYPI.md from README.md for the PyPI project page.

PyPI cannot render repository-relative images or links, so this strips the image
blocks and rewrites relative links to absolute GitHub URLs. Run by `make build`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/BrightbeamAI/metis"
BLOB = f"{REPO_URL}/blob/main"

VISUALS_NOTE = (
    "*Architecture diagrams, an interactive demo, and an illustrated explainer live in the "
    f"[GitHub repository]({REPO_URL}).*\n"
)


def build() -> str:
    text = (ROOT / "README.md").read_text()

    # Drop centred image blocks (logo and diagrams). Replace the first diagram
    # with a single pointer to the repository visuals.
    img_block = re.compile(r'<p align="center">\s*<img src="docs/assets/[^"]+"[^>]*>\s*</p>\n?')
    blocks = img_block.findall(text)
    replaced_once = False

    def _sub(match: re.Match) -> str:
        nonlocal replaced_once
        if "brightbeam-logo" in match.group(0):
            return ""
        if not replaced_once:
            replaced_once = True
            return VISUALS_NOTE
        return ""

    text = img_block.sub(_sub, text)
    assert blocks, "expected image blocks in README.md"

    # Rewrite relative markdown links to absolute GitHub URLs.
    def _link(match: re.Match) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        return f"[{label}]({BLOB}/{target})"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)

    header = "<!-- Generated from README.md by scripts/build_pypi_readme.py; do not edit. -->\n"
    return header + text


if __name__ == "__main__":
    out = ROOT / "README_PYPI.md"
    out.write_text(build())
    print(f"wrote {out}")
