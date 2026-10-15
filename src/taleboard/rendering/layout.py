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
"""
from dataclasses import dataclass
from taleboard.schema.enums import PositionCell, ShotSize, SizeInFrame
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