import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "web" / "static"

# Every node in the flow chart and the module that renders its page. A slow
# endpoint (/goals takes about a second) used to paint its rows under
# whichever stage had been opened since, so each render must check that its
# own stage is still the one open before it touches the shared body.
SURFACES = {
    "approval": "renderApproval",
    "concepts": "renderConcepts",
    "goals": "renderGoals",
    "ideas": "renderIdeas",
    "inbox": "renderInbox",
    "ingest": "renderIngest",
    "planning": "renderPlanning",
    "queue": "renderQueue",
    "resolution": "renderResolution",
    "scoring": "renderScoring",
    "skills": "renderSkills",
}


def _render_body(stage: str) -> str:
    source = (STATIC / f"{stage}.js").read_text(encoding="utf-8")
    start = source.index(f"export async function {SURFACES[stage]}(")
    # Up to the next top-level function, or the end of the file.
    end = source.find("\nexport ", start + 1)
    end = source.find("\nfunction ", start + 1) if end == -1 else end
    return source[start:] if end == -1 else source[start:end]


def test_every_stage_in_the_drawing_has_a_surface_listed_here():
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    stages = set(re.findall(r'data-stage="([a-z]+)"', markup))
    assert stages == set(SURFACES)


@pytest.mark.parametrize("stage", sorted(SURFACES))
def test_a_render_drops_its_response_when_its_stage_is_no_longer_open(stage):
    body = _render_body(stage)
    guard = body.find(f'if (!showing("{stage}")) return;')
    first_paint = body.find("body.replaceChildren(")

    assert guard != -1, f"{stage}.js paints without checking showing()"
    assert first_paint != -1
    assert guard < first_paint, f"{stage}.js paints before its showing() check"


def test_opening_a_stage_marks_it_and_clears_the_previous_rows():
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    start = source.index("async function openStage(")
    opening = source[start:source.index("if (stage ===", start)]

    assert "surface.dataset.stage = stage" in opening
    assert "showLoading()" in opening


def test_the_name_in_the_top_bar_is_the_way_home():
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<button id="home" class="topbar__home"' in markup
    source = (STATIC / "app.js").read_text(encoding="utf-8")
    home = source[source.index('getElementById("home").addEventListener'):]
    assert "closeSurface()" in home[:200]


def test_the_home_page_hides_while_a_section_is_open():
    css = (STATIC / "panel.css").read_text(encoding="utf-8")
    assert 'body[data-surface="open"] .home { display: none; }' in css
