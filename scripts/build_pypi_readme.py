"""Generate README_PYPI.md from README.md for the PyPI project page.

PyPI cannot render repository-relative images or links. This turns the banner into
a text title, replaces each figure with its alt text, and rewrites relative links
to absolute GitHub URLs. Run by `make build`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/BrightbeamAI/metis"
BLOB = f"{REPO_URL}/blob/main"
SITE_URL = "https://metis.brightbeam.works"

PYPI_HEADER = (
    "# Metis\n\n"
    "**Amplify your experts’ judgement.** Open-source tacit memory for AI agents, from Brightbeam "
    "Applied Research.\n\n"
    f"*The illustrated version of this page is on [GitHub]({REPO_URL}), and the interactive "
    f"walkthrough is at [metis.brightbeam.works]({SITE_URL}).*\n"
)

IMG_BLOCK = re.compile(r'<p align="center">\s*<img src="docs/assets/[^"]+"[^>]*>\s*</p>\n?')
ALT = re.compile(r'alt="([^"]*)"')


def _absolute(target: str) -> str | None:
    """The absolute GitHub URL for a repository-relative target, or None if already absolute."""
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return f"{BLOB}/{target}"


def build() -> str:
    text = (ROOT / "README.md").read_text()

    blocks = IMG_BLOCK.findall(text)
    assert any("metis-banner" in b for b in blocks), "expected the banner in README.md"

    def _figure(match: re.Match) -> str:
        block = match.group(0)
        if "metis-banner" in block:
            return PYPI_HEADER
        alt = ALT.search(block)
        return f"*{alt.group(1)}*\n" if alt and alt.group(1) else ""

    text = IMG_BLOCK.sub(_figure, text)

    # Rewrite relative markdown links and HTML hrefs to absolute GitHub URLs.
    def _link(match: re.Match) -> str:
        url = _absolute(match.group(2))
        return match.group(0) if url is None else f"[{match.group(1)}]({url})"

    def _href(match: re.Match) -> str:
        url = _absolute(match.group(1))
        return match.group(0) if url is None else f'href="{url}"'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)
    text = re.sub(r'href="([^"]+)"', _href, text)

    header = "<!-- Generated from README.md by scripts/build_pypi_readme.py; do not edit. -->\n"
    return header + text


if __name__ == "__main__":
    out = ROOT / "README_PYPI.md"
    out.write_text(build())
    print(f"wrote {out}")
