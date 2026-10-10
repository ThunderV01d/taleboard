"""
Manages the shot composition, placing regions onto a background.

Attributes:
    BACKGROUND_COLOR: tuple[int,int,int,int] - RGBA tuple for background colour. This is only used when there is no background image provided.
"""

import io

from PIL import Image

from taleboard.rendering.layout import CANVAS_SIZE, resolve_paste_box, resolve_placement
from taleboard.schema.enums import ShotSize
from taleboard.schema.models import Region

BACKGROUND_COLOR = (255, 255, 255, 255) # Solid white


def compose_shot(regions: list[Region], cutouts: dict[str, bytes], shot_size: ShotSize = ShotSize.MEDIUM, background: bytes | None = None) -> bytes:
    """
    Composites a shot's regions onto one canvas.

    Arguments:
        regions: list[Region] - List of regions. Used for calculating cutout placement.
        cutouts: dict[str,bytes] - Mapping of character IDs to associated cutout images (in bytes).
        shot_size: ShotSize - Shot size. Used for calculating cutout placement. Defaults to MEDIUM.
        background: bytes - Background image file in bytes (if provided). Defaults to None.

    Returns:
        bytes - Composited image file in bytes.
    """
    if background is not None:
        canvas = Image.open(io.BytesIO(background)).convert("RGBA").resize((CANVAS_SIZE, CANVAS_SIZE))
    else:
        canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), BACKGROUND_COLOR)

    # Regions are ordered so that the regions that are higher up the canvas represent someone standing further away.
    # Consequently, these regions are pasted first, with the lower-positioned regions pasted over them.
    # This only matters when regions actually overlap, but costs nothing when they don't.
    ordered_regions = sorted(regions, key=lambda r: resolve_placement(r).anchor_y)
    for region in ordered_regions:
        cutout_bytes = cutouts.get(region.character_id)
        if cutout_bytes is None:
            continue

        cutout = Image.open(io.BytesIO(cutout_bytes)).convert("RGBA")
        paste_x, paste_y, scaled_width, scaled_height = resolve_paste_box(
            region, cutout.width, cutout.height, shot_size
        )
        resized_cutout = cutout.resize((scaled_width, scaled_height))
        canvas.paste(resized_cutout, (paste_x, paste_y), resized_cutout)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()