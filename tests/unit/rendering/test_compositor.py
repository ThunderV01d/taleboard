import io

import pytest
from PIL import Image

from taleboard.rendering.compositor import compose_shot
from taleboard.rendering.layout import CANVAS_SIZE
from taleboard.schema.enums import Orientation, PositionCell, SizeInFrame
from taleboard.schema.models import Region


def _solid_cutout(color: tuple[int, int, int, int], size: tuple[int, int] = (100, 100)) -> bytes:
    """A fully-opaque solid-color square, standing in for a real background_removal.py cutout -- good enough to check placement and z-ordering without needing a real generated image.
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
    return Region(
        character_id=character_id,
        position=position,
        size=size,
        orientation=Orientation.TOWARDS_CAMERA,
        action="standing",
    )


def _pixel(image_bytes: bytes, x: int, y: int) -> tuple[int, int, int]:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return image.getpixel((x, y))


RED = (255, 0, 0, 255)
BLUE = (0, 0, 255, 255)


def test_compose_shot_returns_a_full_canvas_sized_png():
    result = compose_shot(regions=[], cutouts={})
    image = Image.open(io.BytesIO(result))

    assert image.size == (CANVAS_SIZE, CANVAS_SIZE)
    assert image.format == "PNG"


def test_background_is_white_where_nothing_is_pasted():
    result = compose_shot(regions=[], cutouts={})
    assert _pixel(result, 0, 0) == (255, 255, 255)


def test_region_cutout_appears_near_its_anchor_point():
    region = _region("alice", PositionCell.MID_CENTER)
    result = compose_shot(
        regions=[region],
        cutouts={"alice": _solid_cutout(RED)},
    )
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3 - 10) == (255, 0, 0)


def test_region_with_no_matching_cutout_is_skipped_without_error():
    region = _region("ghost", PositionCell.MID_CENTER)
    result = compose_shot(regions=[region], cutouts={})
    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE // 2) == (255, 255, 255)


def test_other_regions_still_render_when_one_cutout_is_missing():
    present = _region("alice", PositionCell.MID_CENTER)
    missing = _region("bob", PositionCell.TOP_LEFT)

    result = compose_shot(
        regions=[present, missing],
        cutouts={"alice": _solid_cutout(RED)},
    )

    assert _pixel(result, CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3 - 10) == (255, 0, 0)


def test_closer_region_is_pasted_over_a_farther_overlapping_region():
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