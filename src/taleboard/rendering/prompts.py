"""Builds the actual FLUX prompt for a single region's character cutout."""

from dataclasses import dataclass

from taleboard.schema.enums import CameraAngle, Orientation, ShotSize
from taleboard.schema.models import Character, Region

STYLE_PREFIX = (
    "Storyboard panel, pencil sketch, black and white line art, "
    "full body shot, entire body visible, head-to-toe, "
    "no shading or lighting, rough hand-drawn illustration style, simple white background, "
)
 
NEGATIVE_PROMPT = ""

#This just keeps the subject description from growing too long (although there is no hard maximum enforced by FLUX)
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
    text: str
    negative_text: str


def build_character_prompt(character: Character, region: Region, angle: CameraAngle = CameraAngle.EYE_LEVEL) -> RenderPrompt:
    """Builds the FLUX prompt for generating one region's character cutout."""
    subject = f"{character.description}, {region.action}"
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
    """Builds the FLUX prompt for a shot's background/environment render."""
    size_phrase = SHOT_SIZE_PHRASES[shot_size]
    angle_phrase = CAMERA_ANGLE_PHRASES[angle]
 
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + size_phrase + angle_phrase + setting,
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )