"""
Top-level orchestration for turning a Shot into a finished composition.

Also contains a few helper functions for image processing -- the generated images are converted to monochrome to avoid colour leaks in the generation (assumed: we want all storyboard shots to be monochrome).

If a cutout is (close to) transparent, generation will be re-attempted a few times.

Additionally, this module also contains caching logic used to save generation calls and preserve character consistency across shots -- the model generates a reference image on the first time it encounters a character. This reference image is cached and conditions future prompts containing that character (to preserve their facial likeness). Tangentially, the cutouts and background are also cached so that any shot that calls for a similar pose/background reuses the cache instead of wasting a separate generation call.

Attributes:
    CutoutCache: dict[tuple[str,str,str,str],bytes] - Mapping between a specific character ID with a specific action pose in a specific orientation/angle and an already generated cutout image.
    BackgroundCache: dict[tuple[str,str,str],bytes] - Mapping between a specific setting shot in a specific shot size with a specific angle and an already generated background image.
    ReferenceImageCache: dict[str,bytes] - Mapping between a specific character ID and an already generated cutout image (to be used as a reference).
    GenerateImage: Callable[[str,str],bytes] - Image generation function. Takes a prompt and negative prompt and returns an image in bytes (usually comes from together_caller or is mocked during testing).
    RemoveBackground: Callable[[bytes],bytes] - Background removal function. Takes an image and returns a character cutout image in bytes (usually comes from background_removal or is mocked during testing).
    MIN_OPAQUE_FRACTION: float - Minimum threshold of opaque pixels, below which an image is considered a "transparent" image with no subject.
    MAX_CUTOUT_ATTEMPTS: int - Number of attempts to generate a failed character cutout region before abandoning it.
    _NEUTRAL_REFERENCE_ACTION: str - Describes a neutral pose for the reference image generation.
"""
import io
import logging
from typing import Callable
from PIL import Image

from taleboard.rendering import background_removal, compositor, together_caller
from taleboard.rendering.prompts import build_background_prompt, build_character_prompt
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region, Shot

CutoutCache = dict[tuple[str, str, str, str], bytes]
BackgroundCache = dict[tuple[str, str, str], bytes]
ReferenceImageCache = dict[str, bytes]

GenerateImage = Callable[[str, str], bytes]
RemoveBackground = Callable[[bytes], bytes]

MIN_OPAQUE_FRACTION = 0.08 # 8% opacity
MAX_CUTOUT_ATTEMPTS = 2

class CutoutRejectedError(RuntimeError):
    """
    Raised when remove_background finds no usable subject, even after regenerating the image.
    """

def _cache_key(character_id: str, action: str, orientation: Orientation, angle: CameraAngle) -> tuple[str, str, str, str]:
    """
    Packs the character ID, action, orientation and angle into one single tuple to be used as a cache key for the cutout cache.

    Self-explanatory arguments and return value.
    """
    return (character_id, action, orientation.value, angle.value)

def _to_monochrome(image_bytes: bytes) -> bytes:
    """
    Deterministically strips all colour from a raw generation.

    Uses the PIL library for image processing.

    Arguments:
        image_bytes: bytes - Full-colour image file (in bytes).
    
    Returns:
        bytes - Monochromatic image file (in bytes).
    """
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

def _opaque_fraction(image_bytes: bytes) -> float:
    """
    Computes the fraction of pixels that are "mostly opaque".
    
    A "mostly opaque" pixel is defined here as a pixel with an alpha value of 128 or greater.
    
    Note: An image with no alpha channel counts as fully opaque.

    Arguments:
        image_bytes: bytes - Image file (in bytes).
    
    Returns:
        float - Fraction of pixels that are "mostly opaque" (against all pixels in the image).
    """
    image = Image.open(io.BytesIO(image_bytes))
    if "A" not in image.getbands():
        return 1.0
    opaque = sum(image.getchannel("A").histogram()[128:])
    return opaque / (image.width * image.height)

def _generate_cutout(
    text: str,
    negative_text: str,
    generate_image: GenerateImage,
    remove_background: RemoveBackground,
    reference_images: list[bytes] | None = None,
) -> bytes:
    """
    Generates an image and isolates its subject, regenerating if the cutout comes back (near-)empty.
    
    Uses the helper function defined above to check if the cutout is (near-)empty.

    Arguments:
        text: str - Prompt to be used to generate the image.
        negative_text: str - Negative prompt to be used to generate the image.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).
        remove_background: RemoveBackground - Background removal function (usually comes from background_removal or is mocked during testing).
        reference_images: list[bytes] - Reference image(s) to condition the generation on. Defaults to None (for the first time a character is generated).

    Returns:
        bytes - Generated cutout image (in bytes).
    """
    extra = {"reference_images": reference_images} if reference_images else {} # Optional part of the prompt
    for _ in range(MAX_CUTOUT_ATTEMPTS):
        cutout = remove_background(generate_image(text, negative_text, **extra))
        if _opaque_fraction(cutout) >= MIN_OPAQUE_FRACTION:
            return cutout
    raise CutoutRejectedError(f"background removal found no subject after {MAX_CUTOUT_ATTEMPTS} generations: {text[:120]!r}")


_NEUTRAL_REFERENCE_ACTION = "standing, neutral relaxed pose"

def _get_or_create_reference_image(
    character_id: str,
    character: Character,
    cache: ReferenceImageCache,
    generate_image: GenerateImage,
    remove_background: RemoveBackground,
) -> bytes:
    """
    Returns character_id's cached reference image.

    The reference image is generated only once on first use, ie:- if a character has been generated before, it will have a reference image in the cache. If not, then a new image will be generated and added to the cache.

    Arguments:
        character_id: str - Unique character ID.
        character: Character - Character whose reference image will be generated.
        cache: ReferenceImageCache - Cache where reference images will be dumped.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).
        remove_background: RemoveBackground - Background removal function (usually comes from background_removal or is mocked during testing).

    Returns:
        bytes - Generated reference image (in bytes).
    """
    reference = cache.get(character_id)
    if reference is not None:
        return reference

    # Mocks up a new region for reference image generation
    neutral_region = Region(
        character_id=character_id,
        position=PositionCell.MID_CENTER,
        size=SizeInFrame.MEDIUM,
        orientation=Orientation.TOWARDS_CAMERA,
        action=_NEUTRAL_REFERENCE_ACTION,
    )
    prompt = build_character_prompt(character, neutral_region, CameraAngle.EYE_LEVEL) # Choose eye-level as a neutral and easily understood camera angle
    reference = _generate_cutout(prompt.text, prompt.negative_text, generate_image, remove_background)
    cache[character_id] = reference
    return reference

def render_characters(
    regions: list[Region],
    characters: dict[str, Character],
    cache: CutoutCache,
    reference_cache: ReferenceImageCache,
    angle: CameraAngle = CameraAngle.EYE_LEVEL,
    shot_size: ShotSize = ShotSize.MEDIUM,
    generate_image: GenerateImage = together_caller.generate_character_image,
    remove_background: RemoveBackground = background_removal.remove_background,
    background: bytes | None = None,
    rejected: list[str] | None = None,
) -> bytes:
    """
    Renders one shot's character regions to a composited PNG.

    The background can be passed here, as this should be the final render pass -- called only after the background is already generated.

    Arguments:
        regions: list[Region] - List of regions to be generated.
        characters: dict[str,Character] - Mapping between character ID and characters.
        cache: CutoutCache - Cutout cache used to save generation calls.
        reference_cache: ReferenceImageCache - Character reference cache used to preserve character consistency between shots.
        angle: CameraAngle - Camera angle of the shot. Defaults to EYE_LEVEL.
        shot_size: ShotSize - Size of the shot. Defaults to MEDIUM.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).
        remove_background: RemoveBackground - Background removal function (usually comes from background_removal or is mocked during testing).
        background: bytes - Background image to render characters against. Defaults to None.
        rejected: list[str] - List of rejected regions' character ID's, built during this function call. These are regions where the CutoutRejectedError is raised (and caught), and subsequently the region is not rendered. Defaults to None.

    Returns:
        bytes - Final composited shot image (in bytes).
    """
    cutouts: dict[str, bytes] = {}

    for region in regions:
        key = _cache_key(region.character_id, region.action, region.orientation, angle)
        cutout = cache.get(key)

        if cutout is None:
            character = characters[region.character_id]
            try:
                reference  = _get_or_create_reference_image(region.character_id, character, reference_cache, generate_image, remove_background)
                prompt = build_character_prompt(character, region, angle)
                cutout = _generate_cutout(prompt.text, prompt.negative_text, generate_image,remove_background,reference_images=[reference])
            except CutoutRejectedError as e:
                logging.getLogger(__name__).warning("Leaving %s out of the shot: %s", region.character_id, e)
                if rejected is not None:
                    rejected.append(region.character_id)
                continue
            cutout = _to_monochrome(cutout)
            cache[key] = cutout

        # Debug: writes the raw cutouts to disk.
        # from pathlib import Path
        # debug_dir = Path(__file__).resolve().parent
        # (debug_dir / f"debug_{region.character_id}_{region.orientation.value}.png").write_bytes(cutout)

        cutouts[region.character_id] = cutout
    return compositor.compose_shot(regions, cutouts, shot_size, background)

def _background_cache_key(setting: str, shot_size: ShotSize, angle: CameraAngle) -> tuple[str, str, str]:
    """
    Packs the scene setting, shot size, and angle into one single tuple to be used as a cache key for the background cache.

    Self-explanatory arguments and return value.
    """
    return (setting, shot_size.value, angle.value)

def render_background(
    setting: str,
    shot_size: ShotSize,
    angle: CameraAngle,
    cache: BackgroundCache,
    generate_image: GenerateImage = together_caller.generate_background_image,
) -> bytes:
    """
    Renders a shot's background/environment as a standalone image.
    
    This should be the first render pass, as the background is the layer that sits at the very bottom.

    Arguments:
        setting: str - Setting description of the shot.
        shot_size: ShotSize - Size of the shot.
        angle: CameraAngle - Camera angle of the shot.
        cache: BackgroundCache - Background cache used to save generation calls.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).

    Returns:
        bytes - Generated background image (in bytes).
    """
    key = _background_cache_key(setting, shot_size, angle)
    background = cache.get(key)
 
    if background is None:
        prompt = build_background_prompt(setting, shot_size, angle)
        raw_image = generate_image(prompt.text, prompt.negative_text)
        background = _to_monochrome(raw_image)
        cache[key] = background
 
    return background

def render_shot(
    shot: Shot,
    characters: dict[str, Character],
    character_cache: CutoutCache,
    background_cache: BackgroundCache,
    reference_cache: ReferenceImageCache,
    generate_image: GenerateImage | None = None,
    remove_background: RemoveBackground = background_removal.remove_background,
) -> bytes:
    """
    Top-level entry point for rendering a shot, background and all.
    
    Dispatches to a pure background render when the shot has no character regions at all -- eg:- an establishing shot, scenery etc.

    A shot with rejected regions (ie:- one or more characters who were supposed to be in the shot were not rendered) is flagged as a shot that needs to be manually reviewed by a human.

    Arguments:
        shot: Shot - Shot to be rendered.
        characters: dict[str,Character] - Mapping between character IDs and characters.
        character_cache: CutoutCache - Cutout cache used to save generation calls.
        background_cache: BackgroundCache - Background cache used to save generation calls.
        reference_cache: ReferenceImageCache - Character reference cache used to preserve character consistency between shots.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).
        remove_background: RemoveBackground - Background removal function (usually comes from background_removal or is mocked during testing).
    
    Returns:
        bytes - Final composited shot image (in bytes).
    """
    background_generate = generate_image or together_caller.generate_background_image
    character_generate = generate_image or together_caller.generate_character_image

    background = render_background(shot.setting, shot.shot_size, shot.angle, background_cache, background_generate)

    if not shot.regions:
        return background
 
    rejected: list[str] = []
    image = render_characters(shot.regions, characters, character_cache, reference_cache, shot.angle, shot.shot_size, generate_image=character_generate, remove_background=remove_background, background=background, rejected=rejected)
    if rejected:
        shot.needs_review = True
    return image