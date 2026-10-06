"""Pastes a Shot's character cutouts onto a single blank canvas.
"""

import io

from PIL import Image

from taleboard.rendering.layout import CANVAS_SIZE, resolve_paste_box, resolve_placement
from taleboard.schema.enums import ShotSize
from taleboard.schema.models import Region

BACKGROUND_COLOR = (255, 255, 255, 255)  #solid white


def compose_shot(regions: list[Region], cutouts: dict[str, bytes], shot_size: ShotSize = ShotSize.MEDIUM, background: bytes | None = None) -> bytes:
    """Composites a shot's regions onto one canvas.
    Returns the composited image as PNG bytes.
    """
    if background is not None:
        canvas = Image.open(io.BytesIO(background)).convert("RGBA").resize((CANVAS_SIZE, CANVAS_SIZE))
    else:
        canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), BACKGROUND_COLOR)

    """Back-to-front paste order: a region higher up the canvas (smaller anchor_y -- the TOP row) represents someone standing further away, so it's pasted first; MID and BOTTOM rows paste over it where they overlap. This only matters when regions actually overlap, but costs nothing when they don't."""
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