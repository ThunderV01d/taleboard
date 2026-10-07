"""Image generation via Together AI's Images API, using FLUX.2-dev."""

import base64
from together import Together
from dotenv import load_dotenv

MODEL_ID = "black-forest-labs/FLUX.2-dev"

#A portrait-style aspect ratio is the most natural for a single character
CHARACTER_WIDTH = 640
CHARACTER_HEIGHT = 2048

#A square aspect ratio is what we expect from a storyboard shot
BACKGROUND_WIDTH = 1024
BACKGROUND_HEIGHT = 1024


load_dotenv()
_client: Together | None = None

def _get_client() -> Together:
    """Lazily constructs the Together client on first real use, rather than at import time."""
    global _client
    if _client is None:
        load_dotenv()
        _client = Together()  #reads TOGETHER_API_KEY from the environment
    return _client

def _encode_reference_images(reference_images: list[bytes]) -> list[str]:
    """Together's reference_images parameter is documented as "an array of image URLs", but accepts an inline base64 data URI too."""
    encoded = []
    for image_bytes in reference_images:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        encoded.append(f"data:image/png;base64,{b64}")
    return encoded

def _generate_image(
        text: str,
        negative_text: str | None,
        width: int,
        height: int,
        steps: int | None,
        guidance_scale: float | None,
        seed: int | None,
        reference_images: list[bytes] | None = None,
) -> bytes:
    "Shared low-level call."
    kwargs: dict = {
        "model": MODEL_ID,
        "prompt": text,
        "width": width,
        "height": height,
        "n": 1,
        "response_format": "base64",
    }
    if negative_text:
        kwargs["negative_prompt"] = negative_text
    if steps is not None:
        kwargs["steps"] = steps
    if guidance_scale is not None:
        kwargs["guidance_scale"] = guidance_scale
    if seed is not None:
        kwargs["seed"] = seed
    if reference_images:
        kwargs["reference_images"] = _encode_reference_images(reference_images)
    response = _get_client().images.generate(**kwargs)
    return base64.b64decode(response.data[0].b64_json) 


def generate_character_image(
    text: str,
    negative_text: str | None = None,
    steps: int | None = None,
    guidance_scale: float | None = None,
    seed: int | None = None,
    reference_images: list[bytes] | None = None,
) -> bytes:
    """Generates one character cutout image from a text prompt. Returns raw image bytes (PNG)."""
    return _generate_image(
        text, negative_text, CHARACTER_WIDTH, CHARACTER_HEIGHT, steps, guidance_scale, seed, reference_images
    )

def generate_background_image(
    text: str,
    negative_text: str | None = None,
    steps: int | None = None,
    guidance_scale: float | None = None,
    seed: int | None = None,
) -> bytes:
    """Generates one environment/establishing image. Returns raw image bytes (PNG)."""
    return _generate_image(
        text, negative_text, BACKGROUND_WIDTH, BACKGROUND_HEIGHT, steps, guidance_scale, seed
    )
