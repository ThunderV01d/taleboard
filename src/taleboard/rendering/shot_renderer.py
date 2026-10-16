"""
Top-level orchestration for turning a Shot into a finished composition.

Also contains a few helper functions for image processing -- the generated images are converted to monochrome to avoid colour leaks in the generation (assumed: we want all storyboard shots to be monochrome).

If a cutout is (close to) transparent, generation will be re-attempted a few times.

Additionally, this module also contains caching logic used to save generation calls and preserve character consistency across shots -- the model generates a reference image on the first time it encounters a character. This reference image is cached and conditions future prompts containing that character (to preserve their facial likeness). Tangentially, the cutouts and background are also cached so that any shot that calls for a similar pose/background reuses the cache instead of wasting a separate generation call.

Locations work the same way: the first time a location is needed, a master plate (a wide, eye-level view of the empty place) is generated and cached, and conditions every other background of that location -- so every shot in it shows the same room. A wide, eye-level shot with no details is the master plate itself. Each generation changes one thing only: another framing is drawn from the master plate, and a shot's details are drawn as an edit of its framing without them -- doing both at once let the room drift. A close-up is never generated: it gets a wide background, and the compositor crops the finished frame.

The caches only need get and [] =, so a plain dict works (eg:- in tests), as do the persistent caches in taleboard.storage.caches (which survive between Lambda invocations).

Attributes:
    CutoutCache: ImageCache[tuple[str,str,str,str]] - Mapping between a specific character ID with a specific action pose in a specific orientation/angle and an already generated cutout image.
    BackgroundCache: ImageCache[tuple[str,str,str,str]] - Mapping between a specific location with specific details, shot in a specific shot size with a specific angle, and an already generated background image.
    ReferenceImageCache: ImageCache[str] - Mapping between a specific character ID and an already generated cutout image (to be used as a reference).
    MasterPlateCache: ImageCache[str] - Mapping between a specific location ID and its already generated master plate (to be used as a reference).
    GenerateImage: Callable[[str,str],bytes] - Image generation function. Takes a prompt and negative prompt and returns an image in bytes (usually comes from together_caller or is mocked during testing).
    RemoveBackground: Callable[[bytes],bytes] - Background removal function. Takes an image and returns a character cutout image in bytes (usually comes from background_removal or is mocked during testing).
    MIN_OPAQUE_FRACTION: float - Minimum threshold of opaque pixels, below which an image is considered a "transparent" image with no subject.
    MAX_PARTIAL_FRACTION: float - Maximum share of a cutout's visible pixels that may be only partly opaque, above which the figure is considered see-through.
    MAX_CUTOUT_ATTEMPTS: int - Number of attempts to generate a failed character cutout region before abandoning it.
    _NEUTRAL_REFERENCE_ACTION: str - Describes a neutral pose for the reference image generation.
"""
import io
import logging
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar
from PIL import Image

from taleboard.rendering import background_removal, compositor, together_caller
from taleboard.rendering.prompts import build_background_prompt, build_character_prompt, build_detail_prompt, build_master_plate_prompt
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Location, Region, Shot

K = TypeVar("K", contravariant=True)

class ImageCache(Protocol[K]):
    """
    Anything that can look up and store images by key -- a dict, or a persistent cache from taleboard.storage.caches.
    """
    def get(self, key: K, /) -> bytes | None: ...
    def __setitem__(self, key: K, value: bytes, /) -> None: ...

CutoutCache = ImageCache[tuple[str, str, str, str]]
BackgroundCache = ImageCache[tuple[str, str, str, str]]
ReferenceImageCache = ImageCache[str]
MasterPlateCache = ImageCache[str]

GenerateImage = Callable[[str, str], bytes]
RemoveBackground = Callable[[bytes], bytes]

MIN_OPAQUE_FRACTION = 0.08 # 8% opacity
MAX_PARTIAL_FRACTION = 0.6 # Measured on 87 real cutouts: good ones sit at 3-46% (a soft shadow beside the figure is the usual culprit), see-through ones at 73% and 98%
_VISIBLE_ALPHA = 16 # Fainter pixels are background removal's edge noise, not part of the figure
_SOLID_ALPHA = 224
MAX_CUTOUT_ATTEMPTS = 2

class CutoutRejectedError(RuntimeError):
    """
    Raised when remove_background finds no usable subject -- nothing there, or a see-through figure -- even after regenerating the image.
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


def _partial_fraction(image_bytes: bytes) -> float:
    """
    Computes the share of an image's visible pixels that are only partly opaque.

    A solid figure is opaque inside, with partial opacity only at its edges; a see-through one (background removal unsure where the figure ends) is partly opaque throughout.

    Note: An image with no alpha channel counts as fully solid.

    Arguments:
        image_bytes: bytes - Image file (in bytes).

    Returns:
        float - Fraction of visible pixels (alpha of _VISIBLE_ALPHA or more) that are below _SOLID_ALPHA. 0 if nothing is visible.
    """
    image = Image.open(io.BytesIO(image_bytes))
    if "A" not in image.getbands():
        return 0.0
    histogram = image.getchannel("A").histogram()
    visible = sum(histogram[_VISIBLE_ALPHA:])
    return sum(histogram[_VISIBLE_ALPHA:_SOLID_ALPHA]) / visible if visible else 0.0


def _generate_cutout(
    text: str,
    negative_text: str,
    generate_image: GenerateImage,
    remove_background: RemoveBackground,
    reference_images: list[bytes] | None = None,
) -> bytes:
    """
    Generates an image and isolates its subject, regenerating if the cutout comes back (near-)empty or see-through.

    Uses the helper functions defined above to check the cutout.

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
        if _opaque_fraction(cutout) >= MIN_OPAQUE_FRACTION and _partial_fraction(cutout) <= MAX_PARTIAL_FRACTION:
            return cutout
    raise CutoutRejectedError(f"background removal found no usable subject after {MAX_CUTOUT_ATTEMPTS} generations: {text[:120]!r}")


@dataclass(frozen=True)
class RenderResult:
    """
    Outcome of rendering one shot.

    Attributes:
        image: bytes - Final composited shot image (in bytes).
        rejected_character_ids: tuple[str,...] - Characters left out of the shot because their cutout was rejected. Defaults to ().
    """
    image: bytes
    rejected_character_ids: tuple[str, ...] = ()

    @property
    def needs_review(self) -> bool:
        """
        Whether a human needs to review the shot -- true when any character was left out of it.

        Returns:
            bool - True if any character was left out.
        """
        return bool(self.rejected_character_ids)

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

def _background_cache_key(location_id: str, details: str, shot_size: ShotSize, angle: CameraAngle) -> tuple[str, str, str, str]:
    """
    Packs the location ID, details, shot size, and angle into one single tuple to be used as a cache key for the background cache.

    Self-explanatory arguments and return value.
    """
    return (location_id, details, shot_size.value, angle.value)

def _background_framing(shot_size: ShotSize) -> ShotSize:
    """
    Picks the framing a shot's background is drawn at -- a close-up gets a wide background, which the compositor crops once the characters are on it.

    Arguments:
        shot_size: ShotSize - Size of the shot.

    Returns:
        ShotSize - WIDE for a close-up; otherwise the shot's own size.
    """
    return ShotSize.WIDE if shot_size == ShotSize.CLOSE_UP else shot_size

def _get_or_create_master_plate(
    location_id: str,
    location: Location,
    cache: MasterPlateCache,
    generate_image: GenerateImage,
) -> bytes:
    """
    Returns location_id's cached master plate.

    The master plate is generated only once, the first time the location is needed -- from its description alone, as a wide, eye-level view of the empty place.

    Arguments:
        location_id: str - Unique location ID.
        location: Location - Location whose master plate will be generated.
        cache: MasterPlateCache - Cache where master plates will be dumped.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).

    Returns:
        bytes - Master plate (in bytes).
    """
    master_plate = cache.get(location_id)
    if master_plate is None:
        prompt = build_master_plate_prompt(location)
        master_plate = _to_monochrome(generate_image(prompt.text, prompt.negative_text))
        cache[location_id] = master_plate
    return master_plate


def _get_or_create_framing(
    location_id: str,
    location: Location,
    framing: ShotSize,
    angle: CameraAngle,
    cache: BackgroundCache,
    master_plate_cache: MasterPlateCache,
    generate_image: GenerateImage,
) -> bytes:
    """
    Returns a location's background at a framing, without any details -- the master plate itself for a wide, eye-level framing, or else a re-framing drawn from it.

    Arguments:
        location_id: str - Unique ID of the location.
        location: Location - The location.
        framing: ShotSize - Framing to draw it at (WIDE or MEDIUM; see _background_framing).
        angle: CameraAngle - Camera angle to draw it at.
        cache: BackgroundCache - Background cache used to save generation calls.
        master_plate_cache: MasterPlateCache - Master plate cache, keeping every background of a location the same place.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).

    Returns:
        bytes - The background (in bytes).
    """
    if framing == ShotSize.WIDE and angle == CameraAngle.EYE_LEVEL:
        return _get_or_create_master_plate(location_id, location, master_plate_cache, generate_image)

    key = _background_cache_key(location_id, "", framing, angle)
    background = cache.get(key)
    if background is None:
        master_plate = _get_or_create_master_plate(location_id, location, master_plate_cache, generate_image)
        prompt = build_background_prompt(location, framing, angle)
        background = _to_monochrome(generate_image(prompt.text, prompt.negative_text, reference_images=[master_plate]))
        cache[key] = background
    return background


def render_background(
    location_id: str,
    location: Location,
    details: str,
    shot_size: ShotSize,
    angle: CameraAngle,
    cache: BackgroundCache,
    master_plate_cache: MasterPlateCache,
    generate_image: GenerateImage = together_caller.generate_background_image,
) -> bytes:
    """
    Renders a shot's background/environment as a standalone image.
    
    This should be the first render pass, as the background is the layer that sits at the very bottom.

    Without details, this is the location at the shot's framing (see _get_or_create_framing). With details, that same background is edited to add them -- so the first shot with details at a framing nobody has used yet costs two generations, and every later one costs one. A close-up gets the same background as a wide shot (see _background_framing).

    Arguments:
        location_id: str - Unique ID of the shot's location.
        location: Location - The shot's location.
        details: str - Small, visible changes to the location in this shot. "" if it looks as described.
        shot_size: ShotSize - Size of the shot.
        angle: CameraAngle - Camera angle of the shot.
        cache: BackgroundCache - Background cache used to save generation calls.
        master_plate_cache: MasterPlateCache - Master plate cache, keeping every background of a location the same place.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).

    Returns:
        bytes - Generated background image (in bytes).
    """
    details = details.strip()
    framing = _background_framing(shot_size)
    if not details:
        return _get_or_create_framing(location_id, location, framing, angle, cache, master_plate_cache, generate_image)

    key = _background_cache_key(location_id, details, framing, angle)
    background = cache.get(key)
    if background is None:
        without_details = _get_or_create_framing(location_id, location, framing, angle, cache, master_plate_cache, generate_image)
        prompt = build_detail_prompt(location, details)
        background = _to_monochrome(generate_image(prompt.text, prompt.negative_text, reference_images=[without_details]))
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
    *,
    locations: dict[str, Location],
    master_plate_cache: MasterPlateCache,
) -> RenderResult:

    """
    Top-level entry point for rendering a shot, background and all.
    
    Skips character rendering when the shot has no character regions at all -- eg:- an establishing shot, scenery etc.

    The shot itself is never modified. If any character was left out (their cutout was rejected), the result says so -- it is up to the caller to flag the shot for review.

    Raises a ValueError if the shot's location isn't one of the given locations -- eg:- a shot broken down before locations existed, which has none.

    Arguments:
        shot: Shot - Shot to be rendered.
        characters: dict[str,Character] - Mapping between character IDs and characters.
        character_cache: CutoutCache - Cutout cache used to save generation calls.
        background_cache: BackgroundCache - Background cache used to save generation calls.
        reference_cache: ReferenceImageCache - Character reference cache used to preserve character consistency between shots.
        generate_image: GenerateImage - Image generation function (usually comes from together_caller or is mocked during testing).
        remove_background: RemoveBackground - Background removal function (usually comes from background_removal or is mocked during testing).
        locations: dict[str,Location] - Mapping between location IDs and locations.
        master_plate_cache: MasterPlateCache - Master plate cache, keeping every background of a location the same place.

    Returns:
        RenderResult - The composited image, plus any characters that were left out.
    """
    background_generate = generate_image or together_caller.generate_background_image
    character_generate = generate_image or together_caller.generate_character_image

    location = locations.get(shot.location_id) if shot.location_id is not None else None
    if location is None:
        raise ValueError(f"Shot has no known location ({shot.location_id!r}) -- resubmit the story to break it down again")
    background = render_background(shot.location_id, location, shot.details, shot.shot_size, shot.angle, background_cache, master_plate_cache, background_generate)

    if not shot.regions:
        return RenderResult(image=compositor.compose_shot([], {}, shot.shot_size, background)) # Still composited, so a close-up is cropped

    rejected: list[str] = []
    image = render_characters(shot.regions, characters, character_cache, reference_cache, shot.angle, shot.shot_size, generate_image=character_generate, remove_background=remove_background, background=background, rejected=rejected)
    return RenderResult(image=image, rejected_character_ids=tuple(rejected))