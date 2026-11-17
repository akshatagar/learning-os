"""The home page's "How it flows" chart, read straight out of index.html.

The chart is hand-authored SVG, so its geometry is pinned here: a stage
added at the wrong place, or an arrow that stops short, shows up as a test
failure rather than by eye.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "web" / "static" / "index.html"

# panel.js draws every node at this size. It lives in JavaScript and cannot
# be imported here, so a change there has to be mirrored in this file.
BOX_WIDTH = 120
BOX_HEIGHT = 48

# Every stage /state reports, plus the Inbox, which the Reel Inbox package
# supplies on its own.
FLOW_STAGES = {
    "inbox", "ingest", "resolution", "queue", "concepts", "goals",
    "skills", "ideas", "approval", "scoring", "planning",
}


def _markup() -> str:
    return INDEX.read_text(encoding="utf-8")


def _svg() -> str:
    match = re.search(r'<svg id="panel".*?</svg>', _markup(), re.S)
    assert match, 'no <svg id="panel"> in index.html'
    return match.group(0)


def _viewbox(svg: str) -> tuple[float, float]:
    _, _, width, height = re.search(r'viewBox="([^"]+)"', svg).group(1).split()
    return float(width), float(height)


def _boxes(svg: str) -> dict[str, tuple[int, int, int, int]]:
    pattern = r'data-stage="(\w+)"\s+transform="translate\((\d+),\s*(\d+)\)"'
    return {
        stage: (int(x), int(y), int(x) + BOX_WIDTH, int(y) + BOX_HEIGHT)
        for stage, x, y in re.findall(pattern, svg)
    }


def _runs(svg: str):
    """(path, start, end) for each arrow: an M then H and V segments."""
    runs = []
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', svg):
        tokens = re.findall(r"([MHV])\s*(-?\d+)(?:\s+(-?\d+))?", d)
        if not tokens or tokens[0][0] != "M":
            continue
        _, x, y = tokens[0]
        start = cx, cy = (float(x), float(y))
        for command, a, _ in tokens[1:]:
            if command == "H":
                cx = float(a)
            else:
                cy = float(a)
        runs.append((d, start, (cx, cy)))
    return runs


def _on_an_edge(point, boxes) -> bool:
    px, py = point
    for left, top, right, bottom in boxes.values():
        if px in (left, right) and top <= py <= bottom:
            return True
        if py in (top, bottom) and left <= px <= right:
            return True
    return False


def test_the_flow_shows_every_stage():
    assert set(_boxes(_svg())) == FLOW_STAGES


def test_every_node_fits_inside_the_drawing():
    width, height = _viewbox(_svg())
    for stage, (left, top, right, bottom) in _boxes(_svg()).items():
        assert left >= 0 and top >= 0, stage
        assert right <= width and bottom <= height, stage


def test_no_two_nodes_touch():
    boxes = sorted(_boxes(_svg()).items())
    for i, (a, (al, at, ar, ab)) in enumerate(boxes):
        for b, (bl, bt, br, bb) in boxes[i + 1:]:
            apart = ar < bl or br < al or ab < bt or bb < at
            assert apart, f"{a} and {b} overlap or share an edge"


def test_every_arrow_starts_and_ends_on_a_node():
    """An arrow that stops short of a node, or hangs past one, connects nothing."""
    svg = _svg()
    boxes = _boxes(svg)
    runs = [run for run in _runs(svg) if not run[0].startswith("M0 0 L")]
    assert runs, "the flow has no arrows"
    for d, start, end in runs:
        assert _on_an_edge(start, boxes), f"arrow {d!r} starts off every node"
        assert _on_an_edge(end, boxes), f"arrow {d!r} ends off every node"


def test_every_nav_button_opens_a_flow_stage():
    nav = re.search(r'<nav class="topbar__nav".*?</nav>', _markup(), re.S).group(0)
    targets = set(re.findall(r'data-surface="(\w+)"', nav))
    assert targets, "the top bar has no sections"
    assert targets <= FLOW_STAGES
