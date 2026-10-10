"""
Maps a Region's coarse PositionCell/SizeInFrame onto concrete pixel geometry for a canvas.

Attributes:
    CANVAS_SIZE: int - Canvas edge sizes (always calculated as a square canvas).
    _COLUMN_X: dict[str,int] - Mapping between natural language phrases used in the LLM-side to positional X coordinates.
    _BOTTOM_MARGIN: int - Margin above the bottom edge of the canvas. Cutouts are pasted strictly above this margin.
    _ROW_Y: dict[str,int] - Mapping between natural language phrases used in the LLM-side to positional Y coordinates.
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

_ROW_Y = {
    "top": CANVAS_SIZE // 3, # 341 for a 1024x1024 canvas
    "mid": CANVAS_SIZE * 2 // 3, # 682 for a 1024x1024 canvas
    "bottom": CANVAS_SIZE - _BOTTOM_MARGIN # 984 for a 1024x1024 canvas
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
    height_fraction = _SIZE_TO_HEIGHT_FRACTION[region.size] * _SHOT_SIZE_SCALE[shot_size]
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
    paste_y = placement.anchor_y - scaled_height
    return paste_x, paste_y, scaled_width, scaled_height