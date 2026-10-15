"""
Maps a Region's coarse PositionCell/SizeInFrame onto concrete pixel geometry for a canvas.

Attributes:
    CANVAS_SIZE: int - Canvas edge sizes (always calculated as a square canvas).
    _COLUMN_X: dict[str,int] - Mapping between natural language phrases used in the LLM-side to positional X coordinates.
    _BOTTOM_MARGIN: int - Margin above the bottom edge of the canvas, where the nearest row's feet stand.
    _TOP_MARGIN: int - Minimum gap between a figure's head and the top edge of the canvas.
    _ROW_Y: dict[str,int] - Mapping between grid rows and the ground line (Y coordinate) a character's feet stand on in that row.
    _ROW_DEPTH_SCALE: dict[str,float] - Mapping between grid rows and a height multiplier, so characters further back are drawn smaller.
    _POSITION_TO_ROW_COL: dict[PositionCell,tuple[str,str]] - Mapping between PositionCell enums and row/column natural language phrases.
    _SIZE_TO_HEIGHT_FRACTION: dict[SizeInFrame,float] - Mapping between SizeInFrame enums and target height fraction (against canvas size).
    _SHOT_SIZE_SCALE: dict[ShotSize,float] - Mapping between ShotSize enums and target height fraction multiplier.
    _MAX_HEIGHT_FRACTION: float - Ceiling on final height fraction. Serves as cheap insurance against future code changes.
    _CLOSE_UP_PADDING: float - Space kept around the figures when a close-up is cropped, as a fraction of their size on each side.
    _CLOSE_UP_MIN_CROP: int - Smallest square a close-up is cropped to, so it is never enlarged by more than CANVAS_SIZE / _CLOSE_UP_MIN_CROP (about 2x).
    _CLOSE_UP_DEFAULT_CENTER: tuple[int,int] - Centre of a close-up's crop when there are no figures in it -- the centre of the lower two-thirds of the frame, where figures would stand.
    _SHARED_CELL_STEP: float - Horizontal distance between figures who share a cell, as a fraction of the tallest one's height (a standing figure is roughly a third as wide as it is tall, so they end up side by side, slightly overlapping).
    _SHARED_CELL_SIDE: dict[Orientation,int] - Order figures sharing a cell are spread in, left to right -- so a figure facing right stands on the left, facing the one beside it.
"""
from dataclasses import dataclass
from taleboard.schema.enums import Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Region

CANVAS_SIZE = 1024

_COLUMN_X = {
    "left": CANVAS_SIZE // 6, # 170 for a 1024x1024 canvas
    "center": CANVAS_SIZE // 2, # 512 for a 1024x1024 canvas
    "right": CANVAS_SIZE * 5 // 6 # 853 for a 1024x1024 canvas
}

_BOTTOM_MARGIN = 40 # To prevent characters placed on the bottom from clipping out of frame

_TOP_MARGIN = 16

# Rows are read as distance from the camera, not height in the frame: every row's feet stand on the floor in the lower part of
# the frame (where an eye-level background's floor is), further back meaning higher up that floor and smaller.
# The old mid row stood feet at two-thirds of the way down -- tabletop height in most backgrounds, so characters floated or stood on furniture
_ROW_Y = {
    "top": round(CANVAS_SIZE * 0.74), # 758 for a 1024x1024 canvas -- back of the floor
    "mid": round(CANVAS_SIZE * 0.86), # 881 for a 1024x1024 canvas
    "bottom": CANVAS_SIZE - _BOTTOM_MARGIN # 984 for a 1024x1024 canvas -- nearest the camera
}

_ROW_DEPTH_SCALE = {
    "top": 0.65,
    "mid": 0.85,
    "bottom": 1.0
}

_POSITION_TO_ROW_COL: dict[PositionCell, tuple[str, str]] = {
    PositionCell.TOP_LEFT: ("top", "left"),
    PositionCell.TOP_CENTER: ("top", "center"),
    PositionCell.TOP_RIGHT: ("top", "right"),
    PositionCell.MID_LEFT: ("mid", "left"),
    PositionCell.MID_CENTER: ("mid", "center"),
    PositionCell.MID_RIGHT: ("mid", "right"),
    PositionCell.BOTTOM_LEFT: ("bottom", "left"),
    PositionCell.BOTTOM_CENTER: ("bottom", "center"),
    PositionCell.BOTTOM_RIGHT: ("bottom", "right")
}

_SIZE_TO_HEIGHT_FRACTION: dict[SizeInFrame, float] = {
    SizeInFrame.SMALL: 0.25,
    SizeInFrame.MEDIUM: 0.45,
    SizeInFrame.LARGE: 0.70
}

_SHOT_SIZE_SCALE: dict[ShotSize, float] = {
    ShotSize.CLOSE_UP: 1.35,
    ShotSize.MEDIUM: 1.0,
    ShotSize.WIDE: 0.7
}

_MAX_HEIGHT_FRACTION = 0.97

@dataclass(frozen=True)
class Placement:
    """
    Dataclass that stores info about where a region's cutout should end up on the canvas.

    Attributes:
        anchor_x: int - X coordinate (pixel) of the bottom-center anchor point.
        anchor_y: int - Y coordinate (pixel) of the bottom-center anchor point.
        target_height: int - Height to scale the cutout to.
    """
    anchor_x: int
    anchor_y: int
    target_height: int

def resolve_placement(region: Region, shot_size: ShotSize = ShotSize.MEDIUM) -> Placement:
    """
    Resolves a region's PositionCell/SizeInFrame into pixel geometry.

    Uses the module's map attributes to resolve placement.

    Arguments:
        region: Region - Region that is to be resolved.
        shot_size: ShotSize - Shot size of composition. Defaults to MEDIUM.
    
    Returns:
        Placement - Placement object with information about where the region's cutout should end up.
    """
    row, col = _POSITION_TO_ROW_COL[region.position]
    anchor_x = _COLUMN_X[col]
    anchor_y = _ROW_Y[row]
    height_fraction = _SIZE_TO_HEIGHT_FRACTION[region.size] * _SHOT_SIZE_SCALE[shot_size] * _ROW_DEPTH_SCALE[row]
    height_fraction = min(height_fraction, _MAX_HEIGHT_FRACTION)
    target_height = round(CANVAS_SIZE * height_fraction) # We want an integer
    return Placement(anchor_x=anchor_x, anchor_y=anchor_y, target_height=target_height)

def resolve_paste_box(
    region: Region,
    cutout_width: int,
    cutout_height: int,
    shot_size: ShotSize = ShotSize.MEDIUM,
) -> tuple[int, int, int, int]:
    """
    Returns the scaled dimensions the cutout should be resized to, as well as the top-left coordinate to paste it at (so that the bottom-center lands on the region's anchor point).

    The head always stays in frame: if the figure would reach above the top margin, it is moved down instead, letting the feet run off the bottom -- the way a real close-up crops.
    The cutout should already be trimmed to the figure (see compositor), so its bottom edge is where the feet are.

    Arguments:
        region: Region - Region of cutout.
        cutout_width: int - Width of cutout.
        cutout_height: int - Height of cutout.
        shot_size: ShotSize - Shot size of composition. Defaults to MEDIUM.

    Returns:
        tuple[int,int,int,int] - X position to paste at, Y position to paste at, scaled width, scaled height.
    """
    placement = resolve_placement(region, shot_size)
    scale = placement.target_height / cutout_height
    scaled_width = round(cutout_width * scale)
    scaled_height = placement.target_height
    paste_x = placement.anchor_x - scaled_width // 2
    paste_y = max(placement.anchor_y - scaled_height, _TOP_MARGIN)
    return paste_x, paste_y, scaled_width, scaled_height

_CLOSE_UP_PADDING = 0.1

_CLOSE_UP_MIN_CROP = 512
   
_CLOSE_UP_DEFAULT_CENTER = (CANVAS_SIZE // 2, CANVAS_SIZE * 2 // 3) # (512, 682) for a 1024x1024 canvas

def resolve_close_up_crop(figure_boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    """
    Works out the square of a finished frame a close-up is cropped to, before being enlarged back to the full canvas.

    The crop is centred on the shot's own figures, with some padding around them, so different close-ups in the same place focus on wherever that shot's characters are.
    It never goes below _CLOSE_UP_MIN_CROP (enlarging further would blur the lines), never above the canvas (figures already filling the frame are left as they are), and is moved back inside the canvas if it would run off an edge.

    Arguments:
        figure_boxes: list[tuple[int,int,int,int]] - (left, top, right, bottom) of each figure pasted into the frame. Parts outside the canvas are ignored. Empty if there are no figures.

    Returns:
        tuple[int,int,int,int] - (left, top, right, bottom) of the square to crop to.
    """
    visible = [
        (max(left, 0), max(top, 0), min(right, CANVAS_SIZE), min(bottom, CANVAS_SIZE))
        for left, top, right, bottom in figure_boxes
    ]
    visible = [box for box in visible if box[0] < box[2] and box[1] < box[3]]
    if visible:
        left, top = min(box[0] for box in visible), min(box[1] for box in visible)
        right, bottom = max(box[2] for box in visible), max(box[3] for box in visible)
        center_x, center_y = (left + right) // 2, (top + bottom) // 2
        side = round(max(right - left, bottom - top) * (1 + 2 * _CLOSE_UP_PADDING))
    else:
        center_x, center_y = _CLOSE_UP_DEFAULT_CENTER
        side = _CLOSE_UP_MIN_CROP
    side = min(max(side, _CLOSE_UP_MIN_CROP), CANVAS_SIZE)
    crop_left = min(max(center_x - side // 2, 0), CANVAS_SIZE - side)
    crop_top = min(max(center_y - side // 2, 0), CANVAS_SIZE - side)
    return crop_left, crop_top, crop_left + side, crop_top + side


_SHARED_CELL_STEP = 0.3

_SHARED_CELL_SIDE: dict[Orientation, int] = {
    Orientation.RIGHT: 0,
    Orientation.TOWARDS_CAMERA: 1,
    Orientation.AWAY_FROM_CAMERA: 1,
    Orientation.LEFT: 2,
}

def resolve_shared_cell_offsets(regions: list[Region], shot_size: ShotSize = ShotSize.MEDIUM) -> list[int]:
    """
    Works out how far to move each figure sideways so that figures sharing a grid cell stand side by side, instead of exactly on top of each other.

    Figures in a cell of their own aren't moved. Figures sharing a cell are spread evenly around the cell's usual spot, ordered by the way they face (see _SHARED_CELL_SIDE), and stay close together -- a shared cell usually means the story has them together.

    Arguments:
        regions: list[Region] - The shot's regions (only those that will actually be drawn).
        shot_size: ShotSize - Shot size the figures are placed at. Defaults to MEDIUM.

    Returns:
        list[int] - Horizontal offset (in pixels) for each region, in the same order as regions.
    """
    offsets = [0] * len(regions)
    cells: dict[PositionCell, list[int]] = {}
    for index, region in enumerate(regions):
        cells.setdefault(region.position, []).append(index)
    for indices in cells.values():
        if len(indices) < 2:
            continue
        indices = sorted(indices, key=lambda index: _SHARED_CELL_SIDE[regions[index].orientation]) # Stable, so ties keep the shot's order
        step = round(max(resolve_placement(regions[index], shot_size).target_height for index in indices) * _SHARED_CELL_STEP)
        for slot, index in enumerate(indices):
            offsets[index] = round((slot - (len(indices) - 1) / 2) * step)
    return offsets