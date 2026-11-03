"""
Turns raw generations into what a layer shows: cut out from its white background (and checked that something solid is left), monochrome, and trimmed to the figure at a standard size -- so a layer's scale alone says how big it is in the frame.

A cutout that background removal leaves (nearly) empty, or see-through -- most of the figure only partly opaque -- is generated again, then given up on (CutoutRejectedError), rather than drawn as an invisible or ghostly figure.

Characters are cut out by a model (see background_removal). Props are cut out by remove_white_background instead: the model can't tell where a lone object drawn in pencil ends, and leaves it see-through, while a prop drawn on plain white is simply everything the white around it doesn't reach.

Attributes:
    GenerateImage: Callable[...,bytes] - Image generation function: a prompt (and negative prompt), and optionally reference_images, to image bytes (from together_caller, or faked in tests).
    RemoveBackground: Callable[[bytes],bytes] - Background removal function (from background_removal, or faked in tests).
    MIN_OPAQUE_FRACTION: float - Minimum threshold of opaque pixels, below which an image is considered a "transparent" image with no subject.
    MAX_PARTIAL_FRACTION: float - Maximum share of a cutout's visible pixels that may be only partly opaque, above which the figure is considered see-through.
    MAX_CUTOUT_ATTEMPTS: int - Generations to try before giving up on a cutout.
    CHARACTER_HEIGHT: int - Height (in pixels) every character layer's image is fitted to.
    PROP_SIZE: int - Longer side (in pixels) every prop layer's image is fitted to.
    WHITE_THRESHOLD: int - Brightness (0-255) at or above which a pixel counts as the white background, for remove_white_background.
"""
import numpy as np
import io
from typing import Callable
from PIL import Image, ImageFilter
from scipy import ndimage

GenerateImage = Callable[..., bytes]
RemoveBackground = Callable[[bytes], bytes]

MIN_OPAQUE_FRACTION = 0.08 # 8% opacity
MAX_PARTIAL_FRACTION = 0.6 # Measured on 87 real cutouts: good ones sit at 3-46% (a soft shadow beside the figure is the usual culprit), see-through ones at 73% and 98%
_VISIBLE_ALPHA = 16 # Fainter pixels are background removal's edge noise, not part of the figure
_SOLID_ALPHA = 224
MAX_CUTOUT_ATTEMPTS = 2
CHARACTER_HEIGHT = 1024
PROP_SIZE = 512
WHITE_THRESHOLD = 230 # Paper white with a little pencil grain; anything darker is part of the drawing

class CutoutRejectedError(RuntimeError):
    """
    Raised when remove_background finds no usable subject -- nothing there, or a see-through figure -- even after regenerating the image.
    """

def to_monochrome(image_bytes: bytes) -> bytes:
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

def opaque_fraction(image_bytes: bytes) -> float:
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


def partial_fraction(image_bytes: bytes) -> float:
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


def generate_cutout(
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
        if opaque_fraction(cutout) >= MIN_OPAQUE_FRACTION and partial_fraction(cutout) <= MAX_PARTIAL_FRACTION:
            return cutout
    raise CutoutRejectedError(f"background removal found no usable subject after {MAX_CUTOUT_ATTEMPTS} generations: {text[:120]!r}")

def fit_character(image_bytes: bytes) -> bytes:
    """
    Trims a character cutout to the figure and scales it to CHARACTER_HEIGHT tall -- so its feet are its bottom edge, and a layer's scale is the figure's height as a fraction of CHARACTER_HEIGHT.
    """
    figure = _trimmed(image_bytes)
    scale = CHARACTER_HEIGHT / figure.height
    return _png(figure.resize((max(1, round(figure.width * scale)), CHARACTER_HEIGHT), Image.LANCZOS))

def fit_prop(image_bytes: bytes) -> bytes:
    """
    Trims a prop cutout to the object and scales it so its longer side is PROP_SIZE.
    """
    figure = _trimmed(image_bytes)
    scale = PROP_SIZE / max(figure.width, figure.height)
    return _png(figure.resize((max(1, round(figure.width * scale)), max(1, round(figure.height * scale))), Image.LANCZOS))

def _trimmed(image_bytes: bytes) -> Image.Image:
    """
    A cutout cropped to what's visible in it (ignoring background removal's faint edge noise). An image with nothing visible, or no transparency, is left whole.
    """
    image = Image.open(io.BytesIO(image_bytes))
    if "A" not in image.getbands():
        return image
    box = image.getchannel("A").point(lambda alpha: 255 if alpha >= _VISIBLE_ALPHA else 0).getbbox()
    return image.crop(box) if box else image

def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()

def remove_white_background(image_bytes: bytes) -> bytes:
    """
    Cuts an object drawn on plain white out of its background: the white reachable from the image's edges goes, and everything inside the object's outline stays solid -- a phone's screen or a clipboard's paper included, so the prop covers what's behind it.
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    light = np.asarray(image.convert("L")) >= WHITE_THRESHOLD
    regions, _ = ndimage.label(light)
    edges = np.unique(np.concatenate([regions[0], regions[-1], regions[:, 0], regions[:, -1]]))
    background = np.isin(regions, edges[edges != 0])  # Region 0 is the drawing itself, never background
    alpha = Image.fromarray(np.where(background, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1))
    image.putalpha(alpha)
    return _png(image)
