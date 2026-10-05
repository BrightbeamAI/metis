"""The MCP Registry entry (server.json) describes the package that ships with it."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = json.loads((ROOT / "server.json").read_text())
PYPROJECT = (ROOT / "pyproject.toml").read_text()


def project(key: str) -> str:
    return re.search(rf'^{key}\s*=\s*"([^"]+)"', PYPROJECT, re.M).group(1)


def test_the_entry_names_the_released_package():
    name, version = project("name"), project("version")
    (package,) = SERVER["packages"]
    assert SERVER["version"] == version
    assert (package["registryType"], package["identifier"], package["version"]) == ("pypi", name, version)
    assert package["runtimeHint"] == "uvx" and package["transport"] == {"type": "stdio"}
    assert package["packageArguments"] == [{"type": "positional", "value": "mcp"}]
    # uvx runs the command named after the package, with no extras installed
    assert re.search(rf'^{name}\s*=\s*"metis\.cli\.main:main"', PYPROJECT, re.M)
    core = re.search(r"^dependencies\s*=\s*\[(.*?)\]", PYPROJECT, re.M | re.S).group(1)
    assert '"mcp>=' in core


def test_pypi_shows_who_owns_the_entry():
    marker = f"mcp-name: {SERVER['name']}"
    assert marker in (ROOT / "README.md").read_text()
    assert marker in (ROOT / "README_PYPI.md").read_text()


def test_the_entry_meets_the_registry_rules():
    assert re.fullmatch(r"io\.github\.BrightbeamAI/[a-zA-Z0-9._-]+", SERVER["name"])
    assert 1 <= len(SERVER["description"]) <= 100 and 1 <= len(SERVER["title"]) <= 100
    assert SERVER["repository"]["url"] == "https://github.com/BrightbeamAI/metis"
    (home,) = SERVER["packages"][0]["environmentVariables"]
    assert home["name"] == "METIS_HOME" and home["isRequired"] and home["format"] == "filepath"
