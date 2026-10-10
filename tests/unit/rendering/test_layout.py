"""
Unit tests for layout.

Covers how a region's position, size and the shot size resolve into anchor points, target heights and paste boxes.
"""
import pytest
from taleboard.rendering.layout import CANVAS_SIZE, resolve_paste_box, resolve_placement
from taleboard.schema.enums import Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Region


def _region(position: PositionCell, size: SizeInFrame = SizeInFrame.MEDIUM) -> Region:
    """
    Builds a camera-facing, standing region for Alice.

    Arguments:
        position: PositionCell - Position of the region in the 3x3 grid.
        size: SizeInFrame - Size of the region in the frame. Defaults to MEDIUM.

    Returns:
        Region - A Region object.
    """
    return Region(
        character_id="alice",
        position=position,
        size=size,
        orientation=Orientation.TOWARDS_CAMERA,
        action="standing",
    )

def test_center_cell_anchors_to_canvas_horizontal_center():
    """
    Verifies that a centre-column region is anchored at the horizontal centre of the canvas.
    """
    placement = resolve_placement(_region(PositionCell.MID_CENTER))
    assert placement.anchor_x == CANVAS_SIZE // 2


def test_left_cell_is_left_of_center_cell():
    """
    Verifies that the left, centre and right columns are anchored in that order from left to right.
    """
    left = resolve_placement(_region(PositionCell.MID_LEFT))
    center = resolve_placement(_region(PositionCell.MID_CENTER))
    right = resolve_placement(_region(PositionCell.MID_RIGHT))
    assert left.anchor_x < center.anchor_x < right.anchor_x


def test_top_row_is_above_mid_row_is_above_bottom_row():
    """
    Verifies that the top, mid and bottom rows are anchored in that order from top to bottom.

    'Above' means a smaller y, as (0, 0) is the top-left of the image.
    """
    top = resolve_placement(_region(PositionCell.TOP_CENTER))
    mid = resolve_placement(_region(PositionCell.MID_CENTER))
    bottom = resolve_placement(_region(PositionCell.BOTTOM_CENTER))
    assert top.anchor_y < mid.anchor_y < bottom.anchor_y


def test_bottom_row_anchor_stays_inside_the_canvas():
    """
    Verifies that the bottom row's anchor sits above the bottom edge of the canvas, not on or past it.

    Regression guard: without the margin, a character placed there would look like they're clipping out of frame.
    """
    bottom = resolve_placement(_region(PositionCell.BOTTOM_CENTER))
    assert 0 < bottom.anchor_y < CANVAS_SIZE


def test_larger_size_in_frame_gives_a_taller_target_height():
    """
    Verifies that small, medium and large regions get increasingly tall target heights.
    """
    small = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.SMALL))
    medium = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM))
    large = resolve_placement(_region(PositionCell.MID_CENTER, SizeInFrame.LARGE))
    assert small.target_height < medium.target_height < large.target_height


def test_target_height_never_exceeds_canvas_size():
    """
    Verifies that no region size gives a target height taller than the canvas.
    """
    for size in SizeInFrame:
        placement = resolve_placement(_region(PositionCell.MID_CENTER, size))
        assert 0 < placement.target_height <= CANVAS_SIZE


@pytest.mark.parametrize("position", list(PositionCell))
def test_every_position_cell_resolves_without_error(position):
    """
    Verifies that every position cell resolves to an anchor point inside the canvas.

    Regression guard: every PositionCell the LLM can output must have an entry in the lookup tables, or this raises a KeyError at render time for a shot that otherwise validated fine.

    Arguments:
        position: PositionCell - Position cell being resolved (parametrized over every cell).
    """
    placement = resolve_placement(_region(position))
    assert 0 <= placement.anchor_x <= CANVAS_SIZE
    assert 0 <= placement.anchor_y <= CANVAS_SIZE

def test_paste_box_preserves_cutout_aspect_ratio():
    """
    Verifies that scaling a cutout keeps its aspect ratio.
    """
    # A 2:1 (wide) cutout, eg:- 200x100
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    _, _, scaled_width, scaled_height = resolve_paste_box(region, cutout_width=200, cutout_height=100)

    assert scaled_width / scaled_height == pytest.approx(200 / 100)

def test_paste_box_scales_cutout_height_to_the_target_height():
    """
    Verifies that a cutout is scaled so its height matches the region's target height.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    placement = resolve_placement(region)

    _, _, _, scaled_height = resolve_paste_box(region, cutout_width=300, cutout_height=600)

    assert scaled_height == placement.target_height

def test_paste_box_bottom_center_lands_exactly_on_the_anchor():
    """
    Verifies that the bottom-centre of the pasted cutout lands on the region's anchor point.
    """
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
    """
    Verifies that a square cutout is centred horizontally on its anchor point.
    """
    region = _region(PositionCell.TOP_LEFT, SizeInFrame.SMALL)
    placement = resolve_placement(region)
    paste_x, _, scaled_width, _ = resolve_paste_box(region, cutout_width=100, cutout_height=100)
    assert paste_x == placement.anchor_x - scaled_width // 2

def test_shot_size_defaults_to_medium_and_leaves_old_geometry_unchanged():
    """
    Verifies that leaving out the shot size gives exactly the same target height as passing MEDIUM.

    A caller that hasn't been updated to pass the shot size through must get exactly the old geometry.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    with_default = resolve_placement(region)
    with_explicit_medium = resolve_placement(region, shot_size=ShotSize.MEDIUM)

    assert with_default.target_height == with_explicit_medium.target_height
    assert with_default.target_height == round(CANVAS_SIZE * 0.45)


def test_close_up_shot_size_gives_a_taller_target_height_than_medium():
    """
    Verifies that a close-up shot makes the same region taller than a medium shot does.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    medium_shot = resolve_placement(region, shot_size=ShotSize.MEDIUM)
    close_up_shot = resolve_placement(region, shot_size=ShotSize.CLOSE_UP)

    assert close_up_shot.target_height > medium_shot.target_height


def test_wide_shot_size_gives_a_shorter_target_height_than_medium():
    """
    Verifies that a wide shot makes the same region shorter than a medium shot does.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    medium_shot = resolve_placement(region, shot_size=ShotSize.MEDIUM)
    wide_shot = resolve_placement(region, shot_size=ShotSize.WIDE)

    assert wide_shot.target_height < medium_shot.target_height


def test_shot_size_scales_every_size_in_frame_the_same_way():
    """
    Verifies that the shot size scales every region size by the same factor.

    ShotSize and SizeInFrame are two independent factors that are multiplied together.
    """
    for size in SizeInFrame:
        region = _region(PositionCell.MID_CENTER, size)
        medium_shot = resolve_placement(region, shot_size=ShotSize.MEDIUM)
        wide_shot = resolve_placement(region, shot_size=ShotSize.WIDE)

        ratio = wide_shot.target_height / medium_shot.target_height
        assert ratio == pytest.approx(0.7, abs=0.02)


def test_shot_size_does_not_affect_the_anchor_point():
    """
    Verifies that the shot size changes a region's scale, not its position.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    medium_shot = resolve_placement(region, shot_size=ShotSize.MEDIUM)
    close_up_shot = resolve_placement(region, shot_size=ShotSize.CLOSE_UP)

    assert medium_shot.anchor_x == close_up_shot.anchor_x
    assert medium_shot.anchor_y == close_up_shot.anchor_y


def test_target_height_never_exceeds_canvas_size_for_any_shot_size_combination():
    """
    Verifies that no combination of region size and shot size gives a target height taller than the canvas.

    Regression guard for the height ceiling in layout.py: even the largest combination (LARGE x CLOSE_UP) must stay within the canvas.
    """
    for size in SizeInFrame:
        for shot_size in ShotSize:
            region = _region(PositionCell.MID_CENTER, size)
            placement = resolve_placement(region, shot_size=shot_size)
            assert 0 < placement.target_height <= CANVAS_SIZE


def test_paste_box_scales_cutout_height_to_the_target_height_for_a_given_shot_size():
    """
    Verifies that the paste box uses the same shot-size-adjusted target height as the placement.
    """
    region = _region(PositionCell.MID_CENTER, SizeInFrame.MEDIUM)
    placement = resolve_placement(region, shot_size=ShotSize.CLOSE_UP)

    _, _, _, scaled_height = resolve_paste_box(
        region, cutout_width=300, cutout_height=600, shot_size=ShotSize.CLOSE_UP
    )

    assert scaled_height == placement.target_height
