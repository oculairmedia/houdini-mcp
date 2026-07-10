"""Docs-link lint: guard the language/boundaries ADR and its cross-links.

This is a lightweight, dependency-free test (no live Houdini needed) that fails
if the architecture ADR, its README/AGENTS links, or its required structural
sections disappear. It exists to keep the decision recorded in
``houdini-mcp-vzp.10`` discoverable and intact.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ADR_REL_PATH = "docs/adr/0001-language-and-process-boundaries.md"
ADR_PATH = REPO_ROOT / ADR_REL_PATH
README_PATH = REPO_ROOT / "README.md"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"

# Required headings/anchors in the ADR. If any of these are removed the decision
# has lost a mandated section and CI should fail.
REQUIRED_ADR_SECTIONS = [
    "## Module Boundaries",
    "## Options Considered",
    "## Profiling Baseline",
    "## Thresholds That Justify a Non-Python Component",
    "## Migration & Compatibility Plan",
    "ADR-BOUNDARY-SECTION",
]


def test_adr_file_exists() -> None:
    assert ADR_PATH.is_file(), f"Missing architecture ADR: {ADR_REL_PATH}"


def test_adr_required_sections_present() -> None:
    text = ADR_PATH.read_text(encoding="utf-8")
    missing = [section for section in REQUIRED_ADR_SECTIONS if section not in text]
    assert not missing, f"ADR is missing required sections: {missing}"


def test_readme_links_to_adr() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert ADR_REL_PATH in text, (
        f"README.md must link to the ADR ({ADR_REL_PATH}). "
        "Add it under the 'Architecture Decisions' section."
    )


def test_agents_links_to_adr() -> None:
    text = AGENTS_PATH.read_text(encoding="utf-8")
    assert ADR_REL_PATH in text, (
        f"AGENTS.md must link to the ADR ({ADR_REL_PATH}). "
        "Add it under the 'Architecture Decisions (ADRs)' section."
    )
