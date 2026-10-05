"""Image generation via Together AI's Images API, using Stable Diffusion XL."""

import base64
from together import Together
from dotenv import load_dotenv

MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
DEFAULT_GUIDANCE_SCALE = 9.0
DEFAULT_STEPS = 35


load_dotenv()
_client: Together | None = None

def _get_client() -> Together:
    """Lazily constructs the Together client on first real use, rather than at import time."""
    global _client
    if _client is None:
        load_dotenv()
        _client = Together()  #reads TOGETHER_API_KEY from the environment
    return _client


def generate_character_image(
    text: str,
    negative_text: str | None = None,
    width: int = 1024,
    height: int = 1024,
    steps: int | None = DEFAULT_STEPS,
    guidance_scale: float | None = DEFAULT_GUIDANCE_SCALE,
    seed: int | None = None,
) -> bytes:
    """Generates one image from a text prompt. Returns raw image bytes (PNG)."""
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

    response = _get_client().images.generate(**kwargs)
    return base64.b64decode(response.data[0].b64_json)