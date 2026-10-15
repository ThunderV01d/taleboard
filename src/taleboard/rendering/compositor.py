"""
Manages the shot composition, placing regions onto a background.

Attributes:
    BACKGROUND_COLOR: tuple[int,int,int,int] - RGBA tuple for background colour. This is only used when there is no background image provided.
    _ALPHA_THRESHOLD: int - Opacity (0-255) a pixel needs to count as part of the figure when trimming a cutout; skips background removal's faint edge noise.
"""

import io

from PIL import Image

from taleboard.rendering.layout import CANVAS_SIZE, resolve_close_up_crop, resolve_paste_box, resolve_placement, resolve_shared_cell_offsets
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

    Figures sharing a grid cell are spread side by side rather than pasted on top of each other. A character with more than one region is drawn once, at their first.
    
    A close-up is composited like a wide shot -- its background is a wide view of the place, so its figures are placed at a wide shot's scale to match -- then, as the very last step, cropped to the square around its figures and enlarged back to the full canvas. The crop zooms in on figures and room together, rather than drawing a new room or a giant figure in front of a distant one.

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

    drawn: list[Region] = [] # Each character once, and only if they have a cutout -- so a character left out never holds a place in a shared cell
    for region in regions:
        if region.character_id in cutouts and all(region.character_id != other.character_id for other in drawn):
            drawn.append(region)
    placement_size = ShotSize.WIDE if shot_size == ShotSize.CLOSE_UP else shot_size # A close-up's zoom comes from the crop, not from bigger figures
    offsets = resolve_shared_cell_offsets(drawn, placement_size)
    figure_boxes: list[tuple[int, int, int, int]] = []
    # Regions are ordered so that the regions that are higher up the canvas represent someone standing further away.
    # Consequently, these regions are pasted first, with the lower-positioned regions pasted over them.
    # This only matters when regions actually overlap, but costs nothing when they don't.
    for index in sorted(range(len(drawn)), key=lambda index: resolve_placement(drawn[index]).anchor_y):
        region = drawn[index]
        cutout = _trim_to_figure(Image.open(io.BytesIO(cutouts[region.character_id])).convert("RGBA"))
        paste_x, paste_y, scaled_width, scaled_height = resolve_paste_box(
            region, cutout.width, cutout.height, placement_size
        )
        paste_x += offsets[index]
        resized_cutout = cutout.resize((scaled_width, scaled_height))
        canvas.paste(resized_cutout, (paste_x, paste_y), resized_cutout)
        figure_boxes.append((paste_x, paste_y, paste_x + scaled_width, paste_y + scaled_height))

    if shot_size == ShotSize.CLOSE_UP:
        canvas = canvas.crop(resolve_close_up_crop(figure_boxes)).resize((CANVAS_SIZE, CANVAS_SIZE), Image.LANCZOS)

    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()