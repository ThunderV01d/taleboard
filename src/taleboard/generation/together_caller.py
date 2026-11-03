"""
Manages Together API calls to Together AI.

Used by the generation engine.

This module also includes helper functions to retry generation.

Attributes:
    MODEL_ID: str - Together AI model ID (copied from the Together AI dashboard).
    CHARACTER_WIDTH: int - Width of character generation images.
    CHARACTER_HEIGHT: int - Height of character generation images.
    BACKGROUND_WIDTH: int - Width of background generation images.
    BACKGROUND_HEIGHT: int - Height of background generation images.
    REQUEST_TIMEOUT: httpx.Timeout - Per-request timeout; a response that hasn't started by then is treated as a stall.
    REQUEST_RETRIES: int - Number of times the SDK retries a timed-out or failed request.
    _client: Together - A Together AI client.
    BAD_REQUEST_RETRIES: int - Number of times a bad request should retry before giving up (a content-policy refusal never is).
    RETRY_BACKOFF_S: float - How long we should wait before retrying a bad request.
"""
import base64
import time
import logging
import httpx
from together import Together, BadRequestError, DefaultHttpxClient

MODEL_ID = "black-forest-labs/FLUX.2-dev"

# A portrait-style aspect ratio is the most natural for a single character
CHARACTER_WIDTH = 640
CHARACTER_HEIGHT = 2048

# A square aspect ratio is what we expect from a storyboard shot
BACKGROUND_WIDTH = 1024
BACKGROUND_HEIGHT = 1024

# Text-to-image takes 6-18 seconds, but drawing from reference images (most of v0.2's images) takes 25-30, and sometimes
# up to about 75 -- so a response that hasn't come back after 2 minutes has stalled. One retry covers a stall; more would only wait minutes on an outage (the delivery is retried later for that)
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=5.0)
REQUEST_RETRIES = 1

_client: Together | None = None

def _get_client() -> Together:
    """
    Lazily constructs the Together client on first real use, rather than at import time.

    Uses the global _client variable to ensure that a new client is not built every time a generation call runs.

    Returns:
        Together - A Together AI client.
    """
    global _client
    if _client is None:
        _client = Together(  # Reads TOGETHER_API_KEY from the environment
            timeout=REQUEST_TIMEOUT,
            max_retries=REQUEST_RETRIES,
            # A fresh connection per request
            http_client=DefaultHttpxClient(limits=httpx.Limits(max_keepalive_connections=0)),
        )
    return _client

def _encode_reference_images(reference_images: list[bytes]) -> list[str]:
    """
    Encodes reference images for the prompt in a form the model will accept.

    Together API's reference_images parameter is documented as "an array of image URLs", but accepts an inline base64 data URI too -- this is the form we convert our byte-shaped images to.

    Arguments:
        reference_images: list[bytes] - List of reference images (in bytes).
    
    Returns:
        list[str] - List of reference images (in inline base64 data URI form).
    """
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
    """
    Shared call to generate images from prompts. 

    Arguments:
        text: str - Prompt to be used to generate images.
        negative_text: str - Negative prompt to be used to generate images.
        width: int - Width of the generated image.
        height: int - Height of the generated image.
        steps: int - Number of inference steps.
        guidance_scale: float - Guidance scale for prompt adherence.
        seed: int - Seed for reproducibility.
        reference_images: list[bytes] - Reference images to be included in the prompt (optionally). Defaults to None.
    
    Returns:
        bytes - Generated image (in bytes).
    """
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
    response = _generate_with_retry(kwargs)
    return base64.b64decode(response.data[0].b64_json) 

BAD_REQUEST_RETRIES = 4
RETRY_BACKOFF_S = 5.0

class RequestRejectedError(RuntimeError):
    """
    Raised when Together AI keeps answering a request with a 400 (that isn't a content refusal) after every retry -- eg:- its "Inference error occurred" on image edits. It's that one image that can't be drawn just now, so it fails alone rather than holding up the rest of a job.
    """

class ContentRefusedError(RuntimeError):
    """
    Raised when Together AI refuses a prompt under its safety policy. Unlike its occasional spurious 400s, this never succeeds on a retry -- the text has to change.
    """

def _is_content_refusal(error: BadRequestError) -> bool:
    """
    Tells a content-policy refusal apart from Together AI's spurious 400s, by what its message says.

    Arguments:
        error: BadRequestError - The 400 Together AI returned.

    Returns:
        bool - True if the prompt was refused for its content.
    """
    message = str(error).lower()
    return "flagged" in message or "safety" in message

def _generate_with_retry(kwargs: dict, sleep=time.sleep):
    """
    Low-level generation call to generate images, retrying on bad requests.

    Raises a ContentRefusedError at once, without retrying, if the prompt is refused for its content.
    
    Arguments:
        kwargs: dict - Keyword arguments to be passed into the generate call.
        sleep: time.sleep - Sleep function (for waiting between retries).
    
    Returns:
        ImageFile - Generated image file (as a Together API ImageFile object).
    """
    for attempt in range(BAD_REQUEST_RETRIES + 1):
        try:
            start = time.monotonic()
            response = _get_client().images.generate(**kwargs)
            logging.getLogger(__name__).info("Together generation took %.1fs", time.monotonic() - start)
            return response
        except BadRequestError as e:
            if _is_content_refusal(e):
                raise ContentRefusedError("Together AI refused to draw this prompt under its safety policy") from e
            if attempt == BAD_REQUEST_RETRIES:
                raise RequestRejectedError(f"Together AI kept rejecting the request: {e}") from e
            logging.getLogger(__name__).warning("Together 400 (attempt %d), retrying: %s", attempt + 1, e)
            sleep(RETRY_BACKOFF_S * (attempt + 1))


def generate_character_image(
    text: str,
    negative_text: str | None = None,
    steps: int | None = None,
    guidance_scale: float | None = None,
    seed: int | None = None,
    reference_images: list[bytes] | None = None,
) -> bytes:
    """
    Generates one character cutout image from a text prompt.

    Calls _generate_image function with character-specific arguments passed.

    Arguments:
        text: str - Prompt to be used to generate character images.
        negative_text: str - Negative prompt to be used to generate character images.
        steps: int - Number of inference steps.
        guidance_scale: float - Guidance scale for prompt adherence.
        seed: int - Seed for reproducibility.
        reference_images: list[bytes] - Character reference images to be included in the prompt (optionally). Defaults to None.

    Returns:
        bytes - Generated character image file (in bytes).
    """
    return _generate_image(
        text, negative_text, CHARACTER_WIDTH, CHARACTER_HEIGHT, steps, guidance_scale, seed, reference_images
    )

def generate_background_image(
    text: str,
    negative_text: str | None = None,
    steps: int | None = None,
    guidance_scale: float | None = None,
    seed: int | None = None,
    reference_images: list[bytes] | None = None,
) -> bytes:
    """
    Generates one background image from a text prompt.
    
    Calls _generate_image function with background-specific arguments passed.

    Arguments:
        text: str - Prompt to be used to generate background images.
        negative_text: str - Negative prompt to be used to generate background images.
        steps: int - Number of inference steps.
        guidance_scale: float - Guidance scale for prompt adherence.
        seed: int - Seed for reproducibility.
        reference_images: list[bytes] - Location master plate to be included in the prompt (optionally). Defaults to None (for the master plate itself).

    Returns:
        bytes - Generated background image file (in bytes).
    """
    return _generate_image(
        text, negative_text, BACKGROUND_WIDTH, BACKGROUND_HEIGHT, steps, guidance_scale, seed, reference_images
    )