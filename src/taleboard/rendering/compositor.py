"""
Manages the shot composition, placing regions onto a background.

Attributes:
    BACKGROUND_COLOR: tuple[int,int,int,int] - RGBA tuple for background colour. This is only used when there is no background image provided.
    _ALPHA_THRESHOLD: int - Opacity (0-255) a pixel needs to count as part of the figure when trimming a cutout; skips background removal's faint edge noise.
"""

import io

from PIL import Image

from taleboard.rendering.layout import CANVAS_SIZE, resolve_paste_box, resolve_placement
from taleboard.schema.enums import ShotSize
from taleboard.schema.models import Region

BACKGROUND_COLOR = (255, 255, 255, 255) # Solid white

_ALPHA_THRESHOLD = 32


def _trim_to_figure(cutout: Image.Image) -> Image.Image:
    """
    Crops a cutout to the figure in it, dropping the transparent padding background removal leaves around it.

    Without this, sizing and placement apply to the whole generated canvas -- a figure filling half of it comes out half the intended size, standing on empty space above its anchor.

    Arguments:
        cutout: Image.Image - Cutout (RGBA).

    Returns:
        Image.Image - The cutout cropped to its visible figure; unchanged if it has nothing visible.
    """
    figure_box = cutout.getchannel("A").point(lambda alpha: 255 if alpha > _ALPHA_THRESHOLD else 0).getbbox()
    return cutout.crop(figure_box) if figure_box else cutout


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

        cutout = _trim_to_figure(Image.open(io.BytesIO(cutout_bytes)).convert("RGBA"))
        paste_x, paste_y, scaled_width, scaled_height = resolve_paste_box(
            region, cutout.width, cutout.height, shot_size
        )
        resized_cutout = cutout.resize((scaled_width, scaled_height))
        canvas.paste(resized_cutout, (paste_x, paste_y), resized_cutout)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()