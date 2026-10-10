"""
Defines the prompts used to generate the character and background images.

Acts as a 'cinematographer' -- building the prompts dynamically.

Attributes:
    STYLE_PREFIX: str - Instructions for the model to adhere to a specific style guideline (in the foreground).
    NEGATIVE_PROMPT: str - Negative prompt instructions for the model to avoid generating certain things (in the foreground). 
    MAX_SUBJECT_LENGTH: int - Keeps the subject description from growing too long (although there is no hard maximum enforced by FLUX).
    ORIENTATION_PHRASES: dict[Orientation,str] - Mapping between Orientation enums and natural language phrases used in the prompt.
    CAMERA_ANGLE_PHRASES: dict[CameraAngle,str] - Mapping between CameraAngle enums and natural language phrases used in the prompt.
    BACKGROUND_STYLE_PREFIX: str - Instructions for the model to adhere to a specific style guideline (in the background).
    BACKGROUND_NEGATIVE_PROMPT: str - Negative prompt instructions for the model to avoid generating certain things (in the background).
    SHOT_SIZE_PHRASES: dict[ShotSize,str] - Mapping between ShotSize enums and natural language phrases used in the prompt.
"""
from dataclasses import dataclass

from taleboard.schema.enums import CameraAngle, Orientation, ShotSize
from taleboard.schema.models import Character, Region

STYLE_PREFIX = (
    "Storyboard panel, pencil sketch, black and white line art, "
    "full body shot, entire body visible, head-to-toe, "
    "no shading or lighting, rough hand-drawn illustration style, simple white background, "
)
 
NEGATIVE_PROMPT = ""

MAX_SUBJECT_LENGTH = 500

ORIENTATION_PHRASES: dict[Orientation, str] = {
    Orientation.TOWARDS_CAMERA: "facing directly towards the camera towards the viewer, front view, ",
    Orientation.AWAY_FROM_CAMERA: "viewed directly from behind, facing away from the viewer, back view, ",
    Orientation.LEFT: "facing directly to the left, side profile view, ",
    Orientation.RIGHT: "facing directly to the right, side profile view, ",
}

CAMERA_ANGLE_PHRASES: dict[CameraAngle, str] = {
    CameraAngle.EYE_LEVEL: "",
    CameraAngle.LOW: "low angle, camera looking up at scene/subject, ",
    CameraAngle.HIGH: "high angle, camera looking down on scene/subject, ",
}

@dataclass(frozen=True)
class RenderPrompt:
    """
    Dataclass used to represent the prompt.
    
    Attributes:
        text: str - Prompt text.
        negative_text: str - Negative prompt text. Used to veer the model away from generating certain things.
    """
    text: str
    negative_text: str


def build_character_prompt(character: Character, region: Region, angle: CameraAngle = CameraAngle.EYE_LEVEL) -> RenderPrompt:
    """
    Builds the FLUX prompt for generating one region's character cutout.

    Couples character description and region action as the "subject".

    Also incorporates orientation of the character and camera angle (extrinsic factors) into the generation.

    Arguments:
        character: Character - Character being generated.
        region: Region - Region being generated.
        angle: CameraAngle - Camera angle to use. Defaults to EYE_LEVEL.

    Returns:
        RenderPrompt - A RenderPrompt object, representing the character prompt to be handed off to the model.
    """
    subject = f"{character.description}, {region.action}"
    # Safety check: technically unnecessary
    if len(subject) > MAX_SUBJECT_LENGTH:
        subject = subject[:MAX_SUBJECT_LENGTH].rstrip()

    orientation_phrase = ORIENTATION_PHRASES[region.orientation]
    angle_phrase = CAMERA_ANGLE_PHRASES[angle]

    return RenderPrompt(
        text=STYLE_PREFIX + orientation_phrase + angle_phrase + subject,
        negative_text=NEGATIVE_PROMPT,
    )

BACKGROUND_STYLE_PREFIX = (
    "Pencil sketch, black and white line art, filling full frame, "
    "environment establishing shot, no shading or lighting, rough hand-drawn illustration style, "
)

BACKGROUND_NEGATIVE_PROMPT = ""

SHOT_SIZE_PHRASES: dict[ShotSize, str] = {
    ShotSize.CLOSE_UP: "close-up framing, tightly framed on the subject, ",
    ShotSize.MEDIUM: "medium shot framing, ",
    ShotSize.WIDE: "wide shot, expansive view of the scene, ",
}

def build_background_prompt(setting: str, shot_size: ShotSize, angle: CameraAngle) -> RenderPrompt:
    """
    Builds the FLUX prompt for generating a shot's background/environment.
    
    Incorporates the shot size and angle alongside the shot 'setting' (which is where the real background information lives).

    Arguments:
        setting: str - Setting of the shot whose background is to be generated. Arguably, the most important part of the prompt.
        shot_size: ShotSize - Size of the shot being composited.
        angle: CameraAngle - Camera angle to be used in the generation.

    Returns:
        RenderPrompt - A RenderPrompt object, representing the background prompt to be handed off to the model.
    """
    size_phrase = SHOT_SIZE_PHRASES[shot_size]
    angle_phrase = CAMERA_ANGLE_PHRASES[angle]
 
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + size_phrase + angle_phrase + setting,
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )