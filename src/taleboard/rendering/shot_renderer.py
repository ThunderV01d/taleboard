"""Top-level orchestration for turning one Shot into a finished image."""
import io
from typing import Callable
from PIL import Image, ImageOps

from taleboard.rendering import background_removal, compositor, together_caller
from taleboard.rendering.prompts import build_character_prompt
from taleboard.schema.enums import Orientation
from taleboard.schema.models import Character, Region

CutoutCache = dict[tuple[str, str, str], bytes] #(character_id, action, orientation) -> cutout bytes mapping

GenerateImage = Callable[[str, str], bytes] #(text, negative_text) -> raw image bytes mapping
RemoveBackground = Callable[[bytes], bytes] #raw image bytes -> cutout bytes mapping


def _canonicalize_orientation(orientation: Orientation) -> tuple[Orientation, bool]:
    """Returns (orientation to actually generate/cache."""
    if orientation == Orientation.RIGHT:
        return Orientation.LEFT, True
    return orientation, False

def _cache_key(character_id: str, action: str, canonical_orientation: Orientation) -> tuple[str, str, str]:
    return (character_id, action, canonical_orientation.value)

def _mirror_horizontally(image_bytes: bytes) -> bytes:
    """Used to derive a RIGHT-facing cutout from a cached LEFT one."""
    image = Image.open(io.BytesIO(image_bytes))
    mirrored = ImageOps.mirror(image)
    buffer = io.BytesIO()
    mirrored.save(buffer, format="PNG")
    return buffer.getvalue()

def _to_monochrome(image_bytes: bytes) -> bytes:
    """Deterministically strips all colour from a raw generation."""
    image = Image.open(io.BytesIO(image_bytes))
    if "A" in image.getbands():
        alpha = image.getchannel("A")
        greyscale = image.convert("L").convert("RGB")
        greyscale.putalpha(alpha)
        result = greyscale
    else:
        result = image.convert("L").convert("RGB")
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()

def render_shot(
    regions: list[Region],
    characters: dict[str, Character],
    cache: CutoutCache,
    generate_image: GenerateImage = together_caller.generate_character_image,
    remove_background: RemoveBackground = background_removal.remove_background,
) -> bytes:
    """Render one shot to a composited PNG."""
    cutouts: dict[str, bytes] = {}

    for region in regions:
        canonical_orientation, needs_mirror = _canonicalize_orientation(region.orientation)
        key = _cache_key(region.character_id, region.action, canonical_orientation)
        cutout = cache.get(key)

        if cutout is None:
            character = characters[region.character_id]
            canonical_region = region.model_copy(update={"orientation": canonical_orientation})
            prompt = build_character_prompt(character, canonical_region)
            raw_image = generate_image(prompt.text, prompt.negative_text)
            cutout = remove_background(raw_image)
            cutout = _to_monochrome(cutout)
            cache[key] = cutout

        if needs_mirror:
            cutout = _mirror_horizontally(cutout)

        #Debug: writes the raw cutouts to disk.
        # from pathlib import Path
        # debug_dir = Path(__file__).resolve().parent
        # (debug_dir / f"debug_{region.character_id}_{region.orientation.value}.png").write_bytes(cutout)

        cutouts[region.character_id] = cutout

    return compositor.compose_shot(regions, cutouts)