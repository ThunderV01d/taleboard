import pytest
from taleboard.rendering.layout import CANVAS_SIZE, resolve_paste_box, resolve_placement
from taleboard.schema.enums import Orientation, PositionCell, SizeInFrame
from taleboard.schema.models import Region


def _region(position: PositionCell, size: SizeInFrame = SizeInFrame.MEDIUM) -> Region:
    return Region(
        character_id="alice",
        position=position,
        size=size,
        orientation=Orientation.TOWARDS_CAMERA,
        action="standing",
    )

def test_center_cell_anchors_to_canvas_horizontal_center():
    placement = resolve_placement(_region(PositionCell.MID_CENTER))
    assert placement.anchor_x == CANVAS_SIZE // 2


def test_left_cell_is_left_of_center_cell():
    left = resolve_placement(_region(PositionCell.MID_LEFT))
    center = resolve_placement(_region(PositionCell.MID_CENTER))
    right = resolve_placement(_region(PositionCell.MID_RIGHT))
    assert left.anchor_x < center.anchor_x < right.anchor_x


def test_top_row_is_above_mid_row_is_above_bottom_row():
    """'Above' means a smaller y -- row 0,0 is the top-left of the image."""
    top = resolve_placement(_region(PositionCell.TOP_CENTER))
    mid = resolve_placement(_region(PositionCell.MID_CENTER))
    bottom = resolve_placement(_region(PositionCell.BOTTOM_CENTER))
    assert top.anchor_y < mid.anchor_y < bottom.anchor_y


def test_bottom_row_anchor_stays_inside_the_canvas():
    """Regression guard: the bottom row's ground line must sit above the
    canvas edge (with a margin), not exactly on/past it, or a character
    placed there would look like they're clipping out of frame.
    """
    bottom = resolve_placement(_region(PositionCell.BOTTOM_CENTER))
    assert 0 < bottom.anchor_y < CANVAS_SIZE


def test_larger_size_in_frame_gives_a_taller_target_height():
    small = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.SMALL))
    medium = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM))
    large = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.LARGE))
    assert small.target_height < medium.target_height < large.target_height


def test_target_height_never_exceeds_canvas_size():
    for size in SizeInFrame:
        placement = resolve_placement(_region(PositionCell.MID_CENTER, size))
        assert 0 < placement.target_height <= CANVAS_SIZE


@pytest.mark.parametrize("position", list(PositionCell))
def test_every_position_cell_resolves_without_error(position):
    """Regression guard: every PositionCell the LLM can actually output
    must have an entry in the lookup table, or this raises a KeyError at
    render time for a shot that otherwise validated fine.
    """
    placement = resolve_placement(_region(position))
    assert 0 <= placement.anchor_x <= CANVAS_SIZE
    assert 0 <= placement.anchor_y <= CANVAS_SIZE

def test_paste_box_preserves_cutout_aspect_ratio():
    #A 2:1 (wide) cutout, e.g. 200x100
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    _, _, scaled_width, scaled_height = resolve_paste_box(region, cutout_width=200, cutout_height=100)

    assert scaled_width / scaled_height == pytest.approx(200 / 100)

def test_paste_box_scales_cutout_height_to_the_target_height():
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    placement = resolve_placement(region)

    _, _, _, scaled_height = resolve_paste_box(region, cutout_width=300, cutout_height=600)

    assert scaled_height == placement.target_height

def test_paste_box_bottom_center_lands_exactly_on_the_anchor():
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    placement = resolve_placement(region)
    paste_x, paste_y, scaled_width, scaled_height = resolve_paste_box(
        region, cutout_width=400, cutout_height=800
    )
    bottom_center_x = paste_x + scaled_width / 2
    bottom_center_y = paste_y + scaled_height
    assert bottom_center_x == pytest.approx(placement.anchor_x, abs=1)
    assert bottom_center_y == placement.anchor_y


def test_paste_box_for_a_square_cutout_is_centered_horizontally_on_anchor():
    region = _region(PositionCell.TOP_LEFT, SizeInFrame.SMALL)
    placement = resolve_placement(region)
    paste_x, _, scaled_width, _ = resolve_paste_box(region, cutout_width=100, cutout_height=100)
    assert paste_x == placement.anchor_x - scaled_width // 2