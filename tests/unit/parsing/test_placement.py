"""
Unit tests for laying out a shot's layers from where the story breakdown puts each figure.

Covers the background, where and how big figures go (by cell, size, row and shot size), their order front to back, figures sharing a cell, props held by a character, and close-ups.
"""
import pytest

from taleboard.generation.cutouts import CHARACTER_HEIGHT, PROP_SIZE
from taleboard.parsing.placement import FRAME_SIZE, Figure, close_up_crop, place_layers
from taleboard.schema.enums import Facing, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer


def _character(ref_id: str = "mara", position=PositionCell.MID_CENTER, size=SizeInFrame.MEDIUM, orientation=Orientation.TOWARDS_CAMERA, action="") -> Figure:
    return Figure("character", ref_id, ref_id.title(), position, size, orientation, action)


def _prop(ref_id: str = "lamp", position=PositionCell.MID_CENTER, size=SizeInFrame.MEDIUM, held_by=None) -> Figure:
    return Figure("prop", ref_id, ref_id.title(), position, size, held_by=held_by)


def _height(layer) -> float:
    """
    A character layer's height in the frame.
    """
    return layer.transform.scale_y * CHARACTER_HEIGHT


def _feet(layer) -> float:
    return layer.transform.y + _height(layer) / 2


def test_a_shot_starts_with_a_background_for_its_facing_and_nothing_is_drawn_yet():
    """
    Verifies that the bottom layer is the background, facing the shot's way and filling the frame, and no layer has an image.
    """
    layers = place_layers(ShotSize.MEDIUM, Facing.EAST, [_character()])

    background = layers[0]
    assert isinstance(background, BackgroundLayer) and background.facing == Facing.EAST
    assert (background.transform.x, background.transform.y, background.transform.scale_x) == (FRAME_SIZE / 2, FRAME_SIZE / 2, 1.0)
    assert all(layer.image is None for layer in layers)


def test_a_character_layer_carries_what_the_breakdown_says_about_them():
    """
    Verifies that a character's layer names them, and keeps their orientation and action.
    """
    [_, layer] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character(orientation=Orientation.LEFT, action="waving")])

    assert isinstance(layer, CharacterLayer)
    assert (layer.character_id, layer.name, layer.orientation, layer.action) == ("mara", "Mara", Orientation.LEFT, "waving")


@pytest.mark.parametrize("position, x", [(PositionCell.MID_LEFT, 170), (PositionCell.MID_CENTER, 512), (PositionCell.MID_RIGHT, 853)])
def test_a_figure_stands_in_its_cells_column(position, x):
    """
    Verifies the three columns.

    Arguments:
        position: PositionCell - The figure's cell.
        x: int - Its column's centre.
    """
    [_, layer] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character(position=position)])

    assert layer.transform.x == x


def test_a_figure_further_back_stands_higher_up_the_floor_and_smaller():
    """
    Verifies that rows are depth: the back row's feet are higher in the frame, and its figures smaller.
    """
    back = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character(position=PositionCell.TOP_CENTER)])[1]
    front = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character(position=PositionCell.BOTTOM_CENTER)])[1]

    assert _feet(back) < _feet(front)
    assert _height(back) < _height(front)


def test_a_medium_figure_in_the_middle_row_is_sized_as_it_was_in_0_1():
    """
    Verifies the size: 45% of the frame, times 0.85 for the middle row -- with its feet on the middle row's floor.
    """
    [_, layer] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character()])

    assert _height(layer) == pytest.approx(FRAME_SIZE * 0.45 * 0.85)
    assert _feet(layer) == pytest.approx(881)


def test_a_wide_shot_makes_figures_smaller():
    """
    Verifies that the same figure is smaller in a wide shot than in a medium one.
    """
    medium = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character()])[1]
    wide = place_layers(ShotSize.WIDE, Facing.NORTH, [_character()])[1]

    assert _height(wide) == pytest.approx(_height(medium) * 0.7)


def test_a_figure_too_tall_for_the_frame_keeps_its_head_in_and_loses_its_feet():
    """
    Verifies that a large figure at the front is moved down to keep its top in frame.
    """
    [_, layer] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character(position=PositionCell.TOP_CENTER, size=SizeInFrame.LARGE)])
    [_, giant] = place_layers(ShotSize.WIDE, Facing.NORTH, [_character(position=PositionCell.BOTTOM_CENTER, size=SizeInFrame.LARGE)])

    assert layer.transform.y - _height(layer) / 2 >= 16
    assert giant.transform.y - _height(giant) / 2 >= 16


def test_figures_are_layered_furthest_from_the_camera_first():
    """
    Verifies the order: back row, middle, then front -- whatever order the breakdown lists them in.
    """
    layers = place_layers(ShotSize.MEDIUM, Facing.NORTH, [
        _character("front", PositionCell.BOTTOM_LEFT), _character("back", PositionCell.TOP_RIGHT), _character("mid", PositionCell.MID_CENTER),
    ])

    assert [layer.character_id for layer in layers[1:]] == ["back", "mid", "front"]


def test_figures_sharing_a_cell_stand_side_by_side_facing_each_other():
    """
    Verifies that two figures in one cell are spread either side of it -- the one facing right on the left.
    """
    layers = place_layers(ShotSize.MEDIUM, Facing.NORTH, [
        _character("tom", orientation=Orientation.LEFT), _character("mara", orientation=Orientation.RIGHT),
    ])
    x = {layer.character_id: layer.transform.x for layer in layers[1:]}

    assert x["mara"] < 512 < x["tom"]
    assert x["mara"] + x["tom"] == pytest.approx(1024)


def test_a_prop_on_its_own_is_placed_like_a_figure_and_sized_as_a_prop():
    """
    Verifies that a prop no one holds gets its own cell, and is far smaller than a character of the same size.
    """
    [_, lamp] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_prop(position=PositionCell.MID_RIGHT)])

    assert isinstance(lamp, PropLayer) and lamp.prop_id == "lamp"
    assert lamp.transform.x == 853
    assert lamp.transform.scale_y * PROP_SIZE < FRAME_SIZE * 0.45 * 0.85 / 2


def test_a_held_prop_is_grouped_with_its_holder_at_their_hand():
    """
    Verifies that a held prop is grouped with the character holding it: the group where the character stands, the character at its centre, and the prop in front of them, at hand height on the side they face.
    """
    layers = place_layers(ShotSize.MEDIUM, Facing.NORTH, [
        _character(orientation=Orientation.RIGHT), _prop("phone", position=PositionCell.TOP_LEFT, size=SizeInFrame.SMALL, held_by="mara"),
    ])

    assert len(layers) == 2
    group = layers[1]
    assert isinstance(group, GroupLayer) and group.name == "Mara"
    mara, phone = group.children
    assert (mara.transform.x, mara.transform.y) == (0, 0)
    assert (group.transform.x, _feet(mara) + group.transform.y) == (512, pytest.approx(881))
    assert isinstance(phone, PropLayer) and phone.prop_id == "phone"
    assert phone.transform.x > 0  # Facing right, so the right hand
    assert 0 < phone.transform.y < _height(mara) / 4  # A little below the middle of the figure, where hands hang
    assert phone.transform.scale_y * PROP_SIZE < _height(mara) / 5


def test_a_prop_held_by_someone_not_in_the_shot_stands_on_its_own():
    """
    Verifies that a prop whose holder isn't in the shot is placed in its own cell rather than lost.
    """
    [_, phone] = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_prop("phone", position=PositionCell.MID_LEFT, held_by="tom")])

    assert isinstance(phone, PropLayer) and phone.transform.x == 170


def test_a_close_up_crops_to_its_figures_by_scaling_every_layer():
    """
    Verifies that a close-up of one figure enlarges it -- and the background by the same amount, so the background still covers the frame.
    """
    medium = place_layers(ShotSize.MEDIUM, Facing.NORTH, [_character()])
    background, mara = place_layers(ShotSize.CLOSE_UP, Facing.NORTH, [_character()])

    zoom = background.transform.scale_x
    assert zoom > 1
    assert _height(mara) == pytest.approx(_height(medium[1]) * 1.35 * zoom)
    assert mara.transform.x == pytest.approx(512)
    half = FRAME_SIZE * zoom / 2
    assert background.transform.y - half <= 0 and background.transform.y + half >= FRAME_SIZE


def test_a_close_up_crop_stays_inside_the_frame_and_is_never_too_small():
    """
    Verifies the crop's limits: at least 512 a side, at most the frame, moved back inside the frame, and centred lower down with no figures.
    """
    assert close_up_crop([(500, 500, 520, 520)]) == (pytest.approx(254), pytest.approx(254), 512)
    assert close_up_crop([(0, 0, 1024, 1024)]) == (0, 0, 1024)
    assert close_up_crop([(0, 900, 40, 1000)]) == (0, 512, 512)
    assert close_up_crop([]) == (256, 426, 512)
