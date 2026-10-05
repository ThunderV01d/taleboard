"""Maps a Region's coarse PositionCell/SizeInFrame onto concrete pixel
geometry for a 1024x1024 canvas.
"""

from dataclasses import dataclass
from taleboard.schema.enums import PositionCell, SizeInFrame
from taleboard.schema.models import Region

CANVAS_SIZE = 1024

#Columns
_COLUMN_X = {
    "left": CANVAS_SIZE // 6,           #170
    "center": CANVAS_SIZE // 2,         #512
    "right": CANVAS_SIZE * 5 // 6,      #853
}

#Rows
"""Note: The bottom row's ground line sits a small margin above the canvas edge rather than exactly on it, so a character placed there doesn't look like they're clipping out of frame."""
_BOTTOM_MARGIN = 40
_ROW_Y = {
    "top": CANVAS_SIZE // 3,                #341
    "mid": CANVAS_SIZE * 2 // 3,            #682
    "bottom": CANVAS_SIZE - _BOTTOM_MARGIN, #984
}

#PositionCell -> (row, column) mapping
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

#SizeInFrame -> target height mapping
_SIZE_TO_HEIGHT_FRACTION: dict[SizeInFrame, float] = {
    SizeInFrame.SMALL: 0.25,
    SizeInFrame.MEDIUM: 0.45,
    SizeInFrame.LARGE: 0.70,
}


@dataclass(frozen=True)
class Placement:
    """Where a region's cutout should end up on the canvas."""
    anchor_x: int       #Pixel x of the bottom-center anchor point
    anchor_y: int       #Pixel y of the bottom-center anchor point
    target_height: int  #The cutout should be scaled to this height


def resolve_placement(region: Region) -> Placement:
    """Resolve a region's PositionCell/SizeInFrame into pixel geometry."""
    row, col = _POSITION_TO_ROW_COL[region.position]
    anchor_x = _COLUMN_X[col]
    anchor_y = _ROW_Y[row]
    target_height = round(CANVAS_SIZE * _SIZE_TO_HEIGHT_FRACTION[region.size])
    return Placement(anchor_x=anchor_x, anchor_y=anchor_y, target_height=target_height)


def resolve_paste_box(
    region: Region,
    cutout_width: int,
    cutout_height: int,
) -> tuple[int, int, int, int]:
    """Given a region and the unscaled pixel size of its cutout, return (paste_x, paste_y,scaled_width, scaled_height).
    These are the scaled dimensions the cutout should be resized to, and the top-left coordinate to paste it at so its bottom-center lands on the region's anchor point.
    """
    placement = resolve_placement(region)
    scale = placement.target_height / cutout_height
    scaled_width = round(cutout_width * scale)
    scaled_height = placement.target_height
    paste_x = placement.anchor_x - scaled_width // 2
    paste_y = placement.anchor_y - scaled_height
    return paste_x, paste_y, scaled_width, scaled_height