"""Generate README_PYPI.md from README.md for the PyPI project page.

PyPI cannot render repository-relative images or links. This points each figure at its file
in the release's tag on GitHub (raw.githubusercontent.com serves SVG as an image, which PyPI's
image proxy accepts) and rewrites relative links to the tag's pages, so each version's page
shows that version's figures and documents. Run by `make build`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "BrightbeamAI/metis"
REPO_URL = f"https://github.com/{REPO}"


def release_ref(pyproject: str) -> str:
    """The git tag of the release in ``pyproject.toml``: ``v0.1.5`` for 0.1.5, and for a post
    or development release of it, whose files are the same."""
    version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if version is None:
        raise ValueError("pyproject.toml names no version")
    return "v" + re.split(r"\.(?:post|dev)", version.group(1))[0]


IMG_SRC = re.compile(r'(<img\s[^>]*?src=")(docs/assets/[^"]+)(")')


def _absolute(target: str, blob: str) -> str | None:
    """The absolute GitHub URL for a repository-relative target, or None if already absolute."""
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return f"{blob}/{target}"


def build() -> str:
    text = (ROOT / "README.md").read_text()
    ref = release_ref((ROOT / "pyproject.toml").read_text())
    raw = f"https://raw.githubusercontent.com/{REPO}/{ref}"
    blob = f"{REPO_URL}/blob/{ref}"

    assert "docs/assets/metis-banner.svg" in text, "expected the banner in README.md"
    text = IMG_SRC.sub(lambda m: f"{m.group(1)}{raw}/{m.group(2)}{m.group(3)}", text)

    # Rewrite relative markdown links and HTML hrefs to the tag's pages on GitHub.
    def _link(match: re.Match) -> str:
        url = _absolute(match.group(2), blob)
        return match.group(0) if url is None else f"[{match.group(1)}]({url})"

    def _href(match: re.Match) -> str:
        url = _absolute(match.group(1), blob)
        return match.group(0) if url is None else f'href="{url}"'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, text)
    text = re.sub(r'href="([^"]+)"', _href, text)

    header = "<!-- Generated from README.md by scripts/build_pypi_readme.py; do not edit. -->\n"
    return header + text


if __name__ == "__main__":
    out = ROOT / "README_PYPI.md"
    out.write_text(build())
    print(f"wrote {out}")
