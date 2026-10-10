"""
Unit tests for compositor.

Uses solid-colour squares in place of real cutouts and backgrounds, so placement and paste order can be checked by sampling pixels.

Attributes:
    RED: tuple[int,int,int,int] - Opaque red (RGBA).
    BLUE: tuple[int,int,int,int] - Opaque blue (RGBA).
    GREEN: tuple[int,int,int,int] - Opaque green (RGBA), used for backgrounds.
"""
import io

import pytest
from PIL import Image

from taleboard.rendering.compositor import compose_shot
from taleboard.rendering.layout import CANVAS_SIZE
from taleboard.schema.enums import Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Region


def _solid_cutout(color: tuple[int, int, int, int], size: tuple[int, int] = (100, 100)) -> bytes:
    """
    Builds a fully opaque, solid-colour square, standing in for a real background_removal cutout.

    Good enough to check placement and paste order without needing a real generated image.

    Arguments:
        color: tuple[int,int,int,int] - Colour of the square (RGBA).
        size: tuple[int,int] - Width and height of the square. Defaults to (100, 100).

    Returns:
        bytes - Square image file (PNG, in bytes).
    """
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _region(
    character_id: str,
    position: PositionCell,
    size: SizeInFrame = SizeInFrame.MEDIUM,
) -> Region:
    """
    Builds a camera-facing, standing region.

    Arguments:
        character_id: str - Character ID of the region.
        position: PositionCell - Position of the region in the 3x3 grid.
        size: SizeInFrame - Size of the region in the frame. Defaults to MEDIUM.

    Returns:
        Region - A Region object.
    """
    return Region(
        character_id=character_id,
        position=position,
        size=size,
        orientation=Orientation.TOWARDS_CAMERA,
        action="standing",
    )


def _pixel(image_bytes: bytes, x: int, y: int) -> tuple[int, int, int]:
    """
    Reads the colour of one pixel.

    Arguments:
        image_bytes: bytes - Image file (in bytes).
        x: int - X coordinate of the pixel.
        y: int - Y coordinate of the pixel.

    Returns:
        tuple[int,int,int] - Colour of the pixel (RGB).
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image.getpixel((x, y))


RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)


def test_compose_shot_returns_a_full_canvas_sized_png():
    """
    Verifies that the composited shot is a PNG the size of the full canvas.
    """
    result = compose_shot(regions=[], cutouts={})
    image = Image.open(io.BytesIO(result))

    assert image.size == (CANVAS_SIZE, CANVAS_SIZE)
    assert image.format == "PNG"


def test_background_is_white_where_nothing_is_pasted():
    """
    Verifies that, with no background image, the canvas is white wherever nothing is pasted.
    """
    result = compose_shot(regions=[], cutouts={})
    assert _pixel(result, 0, 0) == (255, 255, 255)


def test_region_cutout_appears_near_its_anchor_point():
    """
    Verifies that a cutout is pasted just above its region's anchor point.
    """
    region = _region("alice", PositionCell.MID_CENTER)
    result = compose_shot(
        regions=[region],
        cutouts={"alice": _solid_cutout(RED)},
    )
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3 - 10) == (255, 0, 0)


def test_region_with_no_matching_cutout_is_skipped_without_error():
    """
    Verifies that a region with no cutout is skipped rather than raising an error.

    This is what lets rejected characters be left out of a shot.
    """
    region = _region("ghost", PositionCell.MID_CENTER)
    result = compose_shot(regions=[region], cutouts={})
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE // 2) == (255, 255, 255)


def test_other_regions_still_render_when_one_cutout_is_missing():
    """
    Verifies that one missing cutout doesn't stop the other regions from rendering.
    """
    present = _region("alice", PositionCell.MID_CENTER)
    missing = _region("bob", PositionCell.TOP_LEFT)

    result = compose_shot(
        regions=[present, missing],
        cutouts={"alice": _solid_cutout(RED)},
    )

    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3 - 10) == (255, 0, 0)


def test_closer_region_is_pasted_over_a_farther_overlapping_region():
    """
    Verifies that where two cutouts overlap, the lower (closer) region is pasted on top.
    """
    back = _region("back_character", PositionCell.TOP_CENTER, SizeInFrame.LARGE)
    front = _region("front_character", PositionCell.MID_CENTER, SizeInFrame.LARGE)

    result = compose_shot(
        regions=[back, front],
        cutouts={
            "back_character": _solid_cutout(BLUE, size=(200, 200)),
            "front_character": _solid_cutout(RED, size=(200, 200)),
        },
    )
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE // 3) == (255, 0, 0)


def test_paste_order_is_independent_of_input_list_order():
    """
    Verifies that the paste order depends on region position, not on the order the regions are passed in.
    """
    back = _region("back_character", PositionCell.TOP_CENTER, SizeInFrame.LARGE)
    front = _region("front_character", PositionCell.MID_CENTER, SizeInFrame.LARGE)
    cutouts = {
        "back_character": _solid_cutout(BLUE, size=(200, 200)),
        "front_character": _solid_cutout(RED, size=(200, 200)),
    }

    result_forward = compose_shot(regions=[back, front], cutouts=cutouts)
    result_reversed = compose_shot(regions=[front, back], cutouts=cutouts)

    point = (CANVAS_SIZE // 2, CANVAS_SIZE // 3)
    assert _pixel(result_forward, *point) == _pixel(result_reversed, *point) == (255, 0, 0)

def test_shot_size_defaults_to_medium_and_leaves_old_output_unchanged():
    """
    Verifies that leaving out the shot size gives exactly the same image as passing MEDIUM.
    """
    region = _region("alice", PositionCell.MID_CENTER)
    cutouts = {"alice": _solid_cutout(RED)}

    with_default = compose_shot(regions=[region], cutouts=cutouts)
    with_explicit_medium = compose_shot(regions=[region], cutouts=cutouts, shot_size=ShotSize.MEDIUM)

    assert with_default == with_explicit_medium


def test_close_up_shot_size_makes_the_same_region_visibly_bigger():
    """
    Verifies that a close-up shot makes a character appear bigger on the canvas than the same region would in a wide shot.
    """
    region = _region("alice", PositionCell.MID_CENTER)
    cutouts = {"alice": _solid_cutout(RED, size=(100, 100))}

    wide_result = compose_shot(regions=[region], cutouts=cutouts, shot_size=ShotSize.WIDE)
    close_up_result = compose_shot(regions=[region], cutouts=cutouts, shot_size=ShotSize.CLOSE_UP)
    probe_point = (CANVAS_SIZE // 2, 200)

    assert _pixel(wide_result, *probe_point) == (255, 255, 255)
    assert _pixel(close_up_result, *probe_point) == (255, 0, 0)


GREEN = (10, 200, 10, 255)


def test_background_defaults_to_none_and_keeps_the_old_white_canvas():
    """
    Verifies that leaving out the background gives exactly the same white canvas as passing None.
    """
    with_default = compose_shot(regions=[], cutouts={})
    with_explicit_none = compose_shot(regions=[], cutouts={}, background=None)

    assert with_default == with_explicit_none
    assert _pixel(with_default, 0, 0) == (255, 255, 255)


def test_background_image_replaces_the_white_backdrop():
    """
    Verifies that a background image is actually used as the canvas, not just accepted and silently ignored.
    """
    background = _solid_cutout(GREEN, size=(50, 50))

    result = compose_shot(regions=[], cutouts={}, background=background)

    assert _pixel(result, 0, 0) == GREEN[:3]


def test_background_is_resized_to_the_full_canvas():
    """
    Verifies that a background of any size is stretched to fill the whole canvas.

    render_background already generates square images, but compose_shot shouldn't rely on that -- a smaller background would otherwise be pasted at its own size, leaving the rest of the canvas white.
    """
    small_background = _solid_cutout(GREEN, size=(20, 20))

    result = compose_shot(regions=[], cutouts={}, background=small_background)
    image = Image.open(io.BytesIO(result))

    assert image.size == (CANVAS_SIZE, CANVAS_SIZE)
    assert _pixel(result, CANVAS_SIZE - 1, CANVAS_SIZE - 1) == GREEN[:3]


def test_character_cutout_still_pastes_over_a_background_image():
    """
    Verifies that character cutouts are pasted over the background image, with the background showing everywhere else.
    """
    background = _solid_cutout(GREEN, size=(50, 50))
    region = _region("alice", PositionCell.MID_CENTER)

    result = compose_shot(
        regions=[region],
        cutouts={"alice": _solid_cutout(RED)},
        background=background,
    )

    # Inside the character's own box, the character wins
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3 - 10) == (255, 0, 0)
    # Outside any character's box, the background shows through -- not white
    assert _pixel(result, 0, 0) == GREEN[:3]
