import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "web" / "static" / "index.html"

# panel.js draws every stage box at this height, and puts the label above it
# at y=-8 in 11px type, so the ascender reaches roughly 16px above the box.
# Both live in JavaScript and cannot be imported here, so a change to either
# has to be mirrored in this file. Named rather than inlined for that reason.
BOX_HEIGHT = 46
BOX_WIDTH = 110
LABEL_CLEARANCE = 20

# The rail must fit the window with no scrollbar of its own. The shipped
# window is 1280x820 (web/shell.py); subtract the title bar, the .plate
# header and main's var(--step-4) padding top and bottom, and roughly 700px
# is left. Derived in the design, section 3.1.
RAIL_HEIGHT_BUDGET = 700


def _svg(panel_id: str) -> str:
    """Pull one inline <svg> block out of index.html, as text.

    Read with regex rather than an XML parser on purpose. The page as a whole
    is not well-formed XML - <!doctype>, unclosed <meta> - and the three things
    this file needs are attribute values in markup we author by hand. An XML
    parser here would mean either the stdlib one, which expands entities, or a
    new dependency, for no gain over the four patterns below.
    """
    markup = INDEX.read_text(encoding="utf-8")
    match = re.search(rf'<svg id="{panel_id}".*?</svg>', markup, re.S)
    assert match, f'no <svg id="{panel_id}"> in index.html'
    return match.group(0)


def _viewbox_height(svg: str) -> float:
    return float(re.search(r'viewBox="([^"]+)"', svg).group(1).split()[3])


def _stages(svg: str) -> dict[str, tuple[int, int]]:
    pattern = r'data-stage="(\w+)"\s+transform="translate\((\d+),\s*(\d+)\)"'
    return {
        stage: (int(x), int(y))
        for stage, x, y in re.findall(pattern, svg)
    }


def _run_extents(svg: str) -> list[float]:
    """Every y coordinate any connector run reaches."""
    ys = []
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg):
        move = re.search(r"M\s*(-?\d+)\s+(-?\d+)", d)
        if move:
            ys.append(float(move.group(2)))
        ys += [float(n) for n in re.findall(r"V\s*(-?\d+)", d)]
    return ys


def test_the_rail_fits_the_window_without_scrolling():
    """The one rule this layout cannot bend.

    The panel exists to show where attention is owed. A rail with its own
    scrollbar can put an amber lamp off-screen, so the drawing has to fit
    the window outright rather than being scrolled through.
    """
    assert _viewbox_height(_svg("panel-narrow")) <= RAIL_HEIGHT_BUDGET


def test_every_stage_box_is_inside_the_rail_viewbox():
    svg = _svg("panel-narrow")
    lowest = max(y for _, y in _stages(svg).values())
    assert lowest + BOX_HEIGHT <= _viewbox_height(svg)


def test_no_run_extends_past_the_rail_viewbox():
    """overflow is visible, so a run leaving the viewBox still draws - it
    just hangs below the drawing with nothing to connect to."""
    svg = _svg("panel-narrow")
    assert max(_run_extents(svg)) <= _viewbox_height(svg)


def test_both_drawings_carry_every_stage():
    assert set(_stages(_svg("panel"))) == set(_stages(_svg("panel-narrow")))


def test_the_rail_main_line_uses_one_pitch():
    """A stage added at the wrong offset shows up here rather than by eye."""
    stages = _stages(_svg("panel-narrow"))
    spine = sorted(y for x, y in stages.values() if x == 40)
    gaps = {b - a for a, b in zip(spine, spine[1:])}
    assert len(gaps) == 1, f"main line is not evenly pitched: {sorted(gaps)}"


def _boxes(svg: str) -> dict[str, tuple[int, int, int, int]]:
    return {
        stage: (x, y, x + BOX_WIDTH, y + BOX_HEIGHT)
        for stage, (x, y) in _stages(svg).items()
    }


def _run_endpoints(svg: str) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    """Where each connector run starts and ends. Runs are an M followed by
    H and V segments only, which is all this drawing uses."""
    runs = []
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg):
        tokens = re.findall(r"([MHV])\s*(-?\d+)(?:\s+(-?\d+))?", d)
        _, x, y = tokens[0]
        start = (float(x), float(y))
        cx, cy = start
        for command, a, _ in tokens[1:]:
            if command == "H":
                cx = float(a)
            else:
                cy = float(a)
        runs.append((d, start, (cx, cy)))
    return runs


def _on_an_edge(point, boxes) -> bool:
    """On a box's edge, or stopped just above its label. A run coming down
    into a box ends LABEL_CLEARANCE above it rather than striking through
    the label that sits there."""
    px, py = point
    for left, top, right, bottom in boxes.values():
        on_vertical = px in (left, right) and top <= py <= bottom
        on_horizontal = py in (top, bottom) and left <= px <= right
        above_label = py == top - LABEL_CLEARANCE and left <= px <= right
        if on_vertical or on_horizontal or above_label:
            return True
    return False


@pytest.mark.parametrize("panel_id", ["panel", "panel-narrow"])
def test_no_two_stage_boxes_touch(panel_id):
    """The rail's side branches once shared an edge with the main line, so
    Goals read as part of Ideas and Skills as part of Planning."""
    boxes = sorted(_boxes(_svg(panel_id)).items())
    for i, (a, (al, at, ar, ab)) in enumerate(boxes):
        for b, (bl, bt, br, bb) in boxes[i + 1:]:
            apart = ar < bl or br < al or ab < bt or bb < at
            assert apart, f"{a} and {b} overlap or share an edge"


@pytest.mark.parametrize("panel_id", ["panel", "panel-narrow"])
def test_every_run_starts_and_ends_on_a_stage_box(panel_id):
    """A run that stops short of a box, or hangs past one, connects nothing."""
    svg = _svg(panel_id)
    boxes = _boxes(svg)
    for d, start, end in _run_endpoints(svg):
        assert _on_an_edge(start, boxes), f"run {d!r} starts off every box"
        assert _on_an_edge(end, boxes), f"run {d!r} ends off every box"
