"""
Turns where a story breakdown puts each figure in a shot (a cell of a 3x3 grid, and a rough size) into the shot's layers -- each placed by its transform, so the user can move it from there.

Rows are distance from the camera, not height in the frame: every row's feet stand on the floor in the lower part of the frame, further back meaning higher up that floor and smaller. Layer images are fitted to a standard size (see generation.cutouts), so a layer's scale alone sets how big it is, whether or not it has been drawn yet.

A prop held by a character in the same shot isn't given a cell of its own: it goes at that character's hand, grouped with them, so moving the character moves the prop. A close-up is laid out a little bigger than a medium shot, then cropped to its figures -- by scaling every layer (the background too) up about the crop, so nothing is drawn differently.

Attributes:
    FRAME_SIZE: int - Edge of the (square) frame, in pixels.
    _COLUMN_X: dict[str,int] - X coordinate of each grid column's centre.
    _ROW_Y: dict[str,int] - Y coordinate of the floor (where feet stand) in each grid row.
    _ROW_DEPTH_SCALE: dict[str,float] - Size multiplier for each row, so figures further back are smaller.
    _TOP_MARGIN: int - Smallest gap between a figure's top and the top of the frame -- a taller figure is moved down instead, its feet running off the bottom.
    _POSITION_TO_ROW_COL: dict[PositionCell,tuple[str,str]] - Each grid cell's row and column.
    _CHARACTER_HEIGHT_FRACTION: dict[SizeInFrame,float] - A character's height for each size, as a fraction of the frame.
    _PROP_SIZE_FRACTION: dict[SizeInFrame,float] - A prop's longer side for each size, as a fraction of the frame.
    _HELD_SIZE_FRACTION: dict[SizeInFrame,float] - A held prop's longer side for each size, as a fraction of its holder's height.
    _SHOT_SIZE_SCALE: dict[ShotSize,float] - Size multiplier for each shot size.
    _MAX_HEIGHT_FRACTION: float - Ceiling on any figure's height, as a fraction of the frame.
    _CHARACTER_ASPECT: float - A standing figure's width as a fraction of its height (for working out a close-up's crop before anything is drawn).
    _HAND_HEIGHT: float - How far up a figure its hands hang, as a fraction of its height.
    _HAND_REACH: float - How far to the side of a figure's centre its hand is, as a fraction of its height.
    _HAND_SIDE: dict[Orientation,int] - Which side (-1 left, 1 right, as the camera sees it) a held prop goes for each way the holder faces.
    _CLOSE_UP_PADDING: float - Space kept round a close-up's figures, as a fraction of their extent on each side.
    _CLOSE_UP_MIN_CROP: int - Smallest square a close-up crops to, so nothing is enlarged more than about 2x.
    _CLOSE_UP_DEFAULT_CENTRE: tuple[int,int] - Centre of a close-up's crop with no figures in it -- where figures would stand.
    _SHARED_CELL_STEP: float - Distance between figures sharing a cell, as a fraction of the tallest one's height.
    _SHARED_CELL_SIDE: dict[Orientation,int] - Order figures sharing a cell stand in, left to right -- so one facing right stands on the left, facing the one beside them.
"""
from dataclasses import dataclass
from typing import Literal

from taleboard.generation.cutouts import CHARACTER_HEIGHT, PROP_SIZE
from taleboard.schema.enums import Facing, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, Layer, PropLayer, Transform

FRAME_SIZE = 1024

_COLUMN_X = {"left": FRAME_SIZE // 6, "center": FRAME_SIZE // 2, "right": FRAME_SIZE * 5 // 6}  # 170, 512, 853

_ROW_Y = {
    "top": round(FRAME_SIZE * 0.74),  # 758 -- back of the floor
    "mid": round(FRAME_SIZE * 0.86),  # 881
    "bottom": FRAME_SIZE - 40,  # 984 -- nearest the camera
}

_ROW_DEPTH_SCALE = {"top": 0.65, "mid": 0.85, "bottom": 1.0}

_TOP_MARGIN = 16

_POSITION_TO_ROW_COL: dict[PositionCell, tuple[str, str]] = {
    PositionCell.TOP_LEFT: ("top", "left"),
    PositionCell.TOP_CENTER: ("top", "center"),
    PositionCell.TOP_RIGHT: ("top", "right"),
    PositionCell.MID_LEFT: ("mid", "left"),
    PositionCell.MID_CENTER: ("mid", "center"),
    PositionCell.MID_RIGHT: ("mid", "right"),
    PositionCell.BOTTOM_LEFT: ("bottom", "left"),
    PositionCell.BOTTOM_CENTER: ("bottom", "center"),
    PositionCell.BOTTOM_RIGHT: ("bottom", "right"),
}

_CHARACTER_HEIGHT_FRACTION = {SizeInFrame.SMALL: 0.25, SizeInFrame.MEDIUM: 0.45, SizeInFrame.LARGE: 0.70}

_PROP_SIZE_FRACTION = {SizeInFrame.SMALL: 0.06, SizeInFrame.MEDIUM: 0.15, SizeInFrame.LARGE: 0.35}

_HELD_SIZE_FRACTION = {SizeInFrame.SMALL: 0.1, SizeInFrame.MEDIUM: 0.2, SizeInFrame.LARGE: 0.4}

_SHOT_SIZE_SCALE = {ShotSize.CLOSE_UP: 1.35, ShotSize.MEDIUM: 1.0, ShotSize.WIDE: 0.7}

_MAX_HEIGHT_FRACTION = 0.97

_CHARACTER_ASPECT = 0.35

_HAND_HEIGHT = 0.45

_HAND_REACH = 0.15

_HAND_SIDE = {Orientation.TOWARDS_CAMERA: -1, Orientation.AWAY_FROM_CAMERA: 1, Orientation.LEFT: -1, Orientation.RIGHT: 1}

_CLOSE_UP_PADDING = 0.1

_CLOSE_UP_MIN_CROP = 512

_CLOSE_UP_DEFAULT_CENTRE = (FRAME_SIZE // 2, FRAME_SIZE * 2 // 3)

_SHARED_CELL_STEP = 0.3

_SHARED_CELL_SIDE = {Orientation.RIGHT: 0, Orientation.TOWARDS_CAMERA: 1, Orientation.AWAY_FROM_CAMERA: 1, Orientation.LEFT: 2}


@dataclass(frozen=True)
class Figure:
    """
    A character or prop in a shot, as the story breakdown places it.

    Attributes:
        kind: Literal["character","prop"] - What it is.
        ref_id: str - ID of its registry entry.
        name: str - Its name (the layer's name).
        position: PositionCell - Its grid cell (ignored for a held prop).
        size: SizeInFrame - Its rough size.
        orientation: Orientation - The way it faces. Defaults to towards the camera.
        action: str - What a character is doing (empty for a prop). Defaults to "".
        held_by: str | None - ref_id of the character holding a prop, if that character is in the shot. Defaults to None.
    """
    kind: Literal["character", "prop"]
    ref_id: str
    name: str
    position: PositionCell
    size: SizeInFrame
    orientation: Orientation = Orientation.TOWARDS_CAMERA
    action: str = ""
    held_by: str | None = None


@dataclass(frozen=True)
class _Box:
    """
    Where a figure goes: its centre, and its height and width in the frame.
    """
    x: float
    y: float
    height: float
    width: float


def place_layers(shot_size: ShotSize, facing: Facing, figures: list[Figure]) -> list[Layer]:
    """
    Lays out a shot: a background, then each figure in front of it, furthest from the camera first.

    Arguments:
        shot_size: ShotSize - The shot's framing.
        facing: Facing - The way the camera faces (the background's facing).
        figures: list[Figure] - The shot's characters and props.

    Returns:
        list[Layer] - The shot's layers, bottom to top. None has an image yet.
    """
    holders = {f.ref_id for f in figures if f.kind == "character"}
    held = [f for f in figures if f.kind == "prop" and f.held_by in holders]
    standing = [f for f in figures if f not in held]

    boxes = _boxes(standing, shot_size)
    layers: list[tuple[float, Layer]] = []  # (feet y, layer) -- sorted back to front below
    for figure, box in zip(standing, boxes):
        layer = _layer(figure, box)
        props = [f for f in held if f.held_by == figure.ref_id]
        if props:
            layer = _group(figure, box, layer, props)
        layers.append((box.y + box.height / 2, layer))
    ordered: list[Layer] = [BackgroundLayer(name="Background", facing=facing)]
    ordered += [layer for _, layer in sorted(layers, key=lambda pair: pair[0])]  # Stable, so ties keep the breakdown's order
    return _crop(ordered, boxes) if shot_size == ShotSize.CLOSE_UP else ordered


def _boxes(figures: list[Figure], shot_size: ShotSize) -> list[_Box]:
    """
    Each standing figure's box: on its cell's floor, sized by its size, row and the shot size, and spread sideways from anyone sharing its cell.
    """
    boxes = []
    for figure in figures:
        row, column = _POSITION_TO_ROW_COL[figure.position]
        fractions = _CHARACTER_HEIGHT_FRACTION if figure.kind == "character" else _PROP_SIZE_FRACTION
        height = FRAME_SIZE * min(fractions[figure.size] * _SHOT_SIZE_SCALE[shot_size] * _ROW_DEPTH_SCALE[row], _MAX_HEIGHT_FRACTION)
        width = height * _CHARACTER_ASPECT if figure.kind == "character" else height
        top = max(_ROW_Y[row] - height, _TOP_MARGIN)
        boxes.append(_Box(x=_COLUMN_X[column], y=top + height / 2, height=height, width=width))

    cells: dict[PositionCell, list[int]] = {}
    for index, figure in enumerate(figures):
        cells.setdefault(figure.position, []).append(index)
    for indices in cells.values():
        if len(indices) < 2:
            continue
        indices = sorted(indices, key=lambda i: _SHARED_CELL_SIDE[figures[i].orientation])  # Stable, so ties keep the breakdown's order
        step = max(boxes[i].height for i in indices) * _SHARED_CELL_STEP
        for slot, i in enumerate(indices):
            box = boxes[i]
            boxes[i] = _Box(x=box.x + (slot - (len(indices) - 1) / 2) * step, y=box.y, height=box.height, width=box.width)
    return boxes


def _layer(figure: Figure, box: _Box, x: float | None = None, y: float | None = None) -> Layer:
    """
    A figure's layer, centred on its box (or on (x, y)) and scaled to its height.
    """
    transform = lambda scale: Transform(x=box.x if x is None else x, y=box.y if y is None else y, scale_x=scale, scale_y=scale)
    if figure.kind == "character":
        return CharacterLayer(name=figure.name, character_id=figure.ref_id, orientation=figure.orientation, action=figure.action, transform=transform(box.height / CHARACTER_HEIGHT))
    return PropLayer(name=figure.name, prop_id=figure.ref_id, orientation=figure.orientation, transform=transform(box.height / PROP_SIZE))


def _group(holder: Figure, box: _Box, holder_layer: Layer, props: list[Figure]) -> GroupLayer:
    """
    A character grouped with the props they hold -- the group centred on them, each prop at their hand (in front of them).
    """
    side = _HAND_SIDE[holder.orientation]
    hand_x = side * _HAND_REACH * box.height
    hand_y = box.height / 2 - _HAND_HEIGHT * box.height  # From the holder's centre: feet are box.height / 2 below it
    children: list[Layer] = [holder_layer.model_copy(update={"transform": Transform(x=0, y=0, scale_x=holder_layer.transform.scale_x, scale_y=holder_layer.transform.scale_y)})]
    for prop in props:
        size = box.height * _HELD_SIZE_FRACTION[prop.size]
        children.append(_layer(prop, _Box(x=0, y=0, height=size, width=size), x=hand_x, y=hand_y))
    return GroupLayer(name=holder.name, transform=Transform(x=box.x, y=box.y), children=children)


def close_up_crop(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float]:
    """
    The square a close-up is cropped to: centred on its figures with some padding, no smaller than _CLOSE_UP_MIN_CROP, no bigger than the frame, and kept inside it.

    Arguments:
        boxes: list[tuple[float,float,float,float]] - (left, top, right, bottom) of each figure. Parts outside the frame are ignored.

    Returns:
        tuple[float,float,float] - The square's left, top and side.
    """
    visible = [(max(l, 0), max(t, 0), min(r, FRAME_SIZE), min(b, FRAME_SIZE)) for l, t, r, b in boxes]
    visible = [box for box in visible if box[0] < box[2] and box[1] < box[3]]
    if visible:
        left, top = min(b[0] for b in visible), min(b[1] for b in visible)
        right, bottom = max(b[2] for b in visible), max(b[3] for b in visible)
        centre_x, centre_y = (left + right) / 2, (top + bottom) / 2
        side = max(right - left, bottom - top) * (1 + 2 * _CLOSE_UP_PADDING)
    else:
        centre_x, centre_y = _CLOSE_UP_DEFAULT_CENTRE
        side = _CLOSE_UP_MIN_CROP
    side = min(max(side, _CLOSE_UP_MIN_CROP), FRAME_SIZE)
    left = min(max(centre_x - side / 2, 0), FRAME_SIZE - side)
    top = min(max(centre_y - side / 2, 0), FRAME_SIZE - side)
    return left, top, side


def _crop(layers: list[Layer], boxes: list[_Box]) -> list[Layer]:
    """
    A close-up: the frame cropped to its figures, then scaled back up to fill it -- every layer (the background too) moved and scaled to match.
    """
    left, top, side = close_up_crop([(b.x - b.width / 2, b.y - b.height / 2, b.x + b.width / 2, b.y + b.height / 2) for b in boxes])
    zoom = FRAME_SIZE / side
    return [
        layer.model_copy(update={"transform": layer.transform.model_copy(update={
            "x": (layer.transform.x - left) * zoom, "y": (layer.transform.y - top) * zoom,
            "scale_x": layer.transform.scale_x * zoom, "scale_y": layer.transform.scale_y * zoom,
        })})
        for layer in layers
    ]