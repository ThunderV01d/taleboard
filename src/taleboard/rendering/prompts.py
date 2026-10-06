"""Builds the actual SDXL prompt for a single region's character cutout.

SDXL's text encoder truncates from the END of the prompt once it runs out of tokens. A character's description or a region's action text has no fixed length, so if anything gets silently dropped, it should be trailing subject detail, not the style instructions that make the output usable at all. That's why the style keywords are front-loaded and the character/action text comes last.

Note that shot_renderer.py never actually calls this with Orientation.RIGHT in practice -- it generates RIGHT-facing regions by mirroring a cached LEFT cutout instead of a real generation, since the two are true horizontal reflections of each other for a symmetric character. ORIENTATION_PHRASES still defines RIGHT here so this function is correct on its own terms regardless of what shot_renderer.py chooses to do with it.
"""

from dataclasses import dataclass

from taleboard.schema.enums import CameraAngle, Orientation, ShotSize
from taleboard.schema.models import Character, Region

STYLE_PREFIX = (
    # "Storyboard panel, pencil sketch, black and white line art, "
    "Pencil sketch, black and white line art, "
    "full body shot, entire body visible, head-to-toe, "
    "no shading or lighting, rough hand-drawn illustration style, simple white background, "
)
 
NEGATIVE_PROMPT = (
    "color, colour, painted, shaded, gradient, photorealistic, 3d render, "
    "multiple views, multiple poses, character sheet, collage, grid, "
    "cropped, close-up, portrait, headshot, waist-up, upper body only, zoomed in, other subjects, detailed background, shadow, reflection, furniture, walls, floor, ceiling, environment"
)

#This just keeps the subject description from growing long enough to push the style prefix itself out of SDXL's effective token window.
MAX_SUBJECT_LENGTH = 300

ORIENTATION_PHRASES: dict[Orientation, str] = {
    Orientation.TOWARDS_CAMERA: "facing directly towards the camera towards the viewer, front view, ",
    Orientation.AWAY_FROM_CAMERA: "viewed directly from behind, facing away from the viewer, back view, ",
    Orientation.LEFT: "facing directly to their right, side profile view, ",
    Orientation.RIGHT: "facing directly to their left, side profile view, ",
}

CAMERA_ANGLE_PHRASES: dict[CameraAngle, str] = {
    CameraAngle.EYE_LEVEL: "",
    CameraAngle.LOW: "low angle, ",
    CameraAngle.HIGH: "high angle, ",
}

@dataclass(frozen=True)
class RenderPrompt:
    text: str
    negative_text: str


def build_character_prompt(character: Character, region: Region, angle: CameraAngle = CameraAngle.EYE_LEVEL) -> RenderPrompt:
    """Builds the SDXL prompt for generating one region's character cutout."""
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
    "Storyboard panel, pencil sketch, black and white line art, "
    "environment establishing shot, no shading or lighting, rough hand-drawn illustration style, "
)

BACKGROUND_NEGATIVE_PROMPT = (
    "color, colour, painted, shaded, gradient, photorealistic, 3d render, "
    "text, watermark, signature, blurry"
)

SHOT_SIZE_PHRASES: dict[ShotSize, str] = {
    ShotSize.CLOSE_UP: "close-up framing, tightly framed on the subject, ",
    ShotSize.MEDIUM: "medium shot framing, ",
    ShotSize.WIDE: "wide shot, expansive view of the scene, ",
}

def build_background_prompt(setting: str, shot_size: ShotSize, angle: CameraAngle) -> RenderPrompt:
    """Builds the SDXL prompt for a shot's background/environment render."""
    size_phrase = SHOT_SIZE_PHRASES[shot_size]
    angle_phrase = CAMERA_ANGLE_PHRASES[angle]
 
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + size_phrase + angle_phrase + setting,
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )