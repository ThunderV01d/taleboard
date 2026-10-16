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
    MASTER_PLATE_FRAMING: str - Framing of a location's master plate -- a wide, eye-level view of the whole place, which every other background of it is drawn from.
    COMPOSITION_PHRASES: dict[tuple[ShotSize,CameraAngle],str] - Mapping between (shot size, camera angle) and where the camera is relative to the master plate, used in the prompt.
    DETAIL_EDIT_PHRASE: str - Tells the model to keep image 1's view exactly, so a shot's details are drawn as an edit rather than a new picture.
"""
from dataclasses import dataclass

from taleboard.schema.enums import CameraAngle, Orientation, ShotSize
from taleboard.schema.models import Character, Location, Region

STYLE_PREFIX = (
    "Storyboard panel, pencil sketch, black and white line art, "
    "full body shot, entire body visible, head-to-toe, "
    "no shading or lighting, rough hand-drawn illustration style, simple white background, "
    "a single figure alone, no other people, no room, walls, windows or scenery, "
    "no signature, no text, no watermark, "
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
    "no shading or lighting, rough hand-drawn illustration style, "
    "no signature, no text, no watermark, "
)

BACKGROUND_NEGATIVE_PROMPT = ""

MASTER_PLATE_FRAMING = "wide shot, establishing view of the whole place at eye level, empty, with nobody in it, "

# Every other framing of a location is drawn with its master plate as image 1. Without saying exactly where the camera has moved to,
# FLUX treats the reference as an image to edit and keeps its framing -- so each phrase says where the camera is and what is in and out of frame.
# Wide eye-level has no entry, as it is the master plate itself; nor do close-ups, which are cropped from a finished wide shot (see shot_renderer).
_SAME_PLACE = "keeping everything in the place, its layout and the drawing style the same as image 1, "
COMPOSITION_PHRASES: dict[tuple[ShotSize, CameraAngle], str] = {
    (ShotSize.WIDE, CameraAngle.LOW): (
        "a new view of the place in image 1, with the camera close to the ground looking steeply upward: the sky or ceiling and the tops "
        "of the nearest structures fill the upper half of the frame, and very little of the ground or floor is visible, " + _SAME_PLACE
    ),
    (ShotSize.WIDE, CameraAngle.HIGH): (
        "a new view of the place in image 1, with the camera high up looking steeply down: the ground or floor and the layout of "
        "everything on it fill the frame, seen from above, and the sky or ceiling is out of frame, " + _SAME_PLACE
    ),
    (ShotSize.MEDIUM, CameraAngle.EYE_LEVEL): (
        "a new, closer view of the place in image 1, with the camera a few steps further in at eye level: the middle of the place "
        "fills the frame, and the left and right edges of image 1 are out of frame, " + _SAME_PLACE
    ),
    (ShotSize.MEDIUM, CameraAngle.LOW): (
        "a new, closer view of the place in image 1, with the camera a few steps further in and close to the ground, looking upward: "
        "the nearest objects tower over the viewer and the sky or ceiling fills the top of the frame, " + _SAME_PLACE
    ),
    (ShotSize.MEDIUM, CameraAngle.HIGH): (
        "a new, closer view of the place in image 1, with the camera a few steps further in and above head height, looking down: "
        "the ground or floor and the tops of the nearest objects fill the frame, and the sky or ceiling is out of frame, " + _SAME_PLACE
    ),
}

def build_master_plate_prompt(location: Location) -> RenderPrompt:
    """
    Builds the FLUX prompt for generating a location's master plate -- the one background of it drawn from text alone.

    Arguments:
        location: Location - Location whose master plate is to be generated.

    Returns:
        RenderPrompt - A RenderPrompt object, representing the master plate prompt to be handed off to the model.
    """
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + MASTER_PLATE_FRAMING + location.description,
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )

DETAIL_EDIT_PHRASE = "the same view of the place in image 1, from the same camera position and with the same framing, "

def build_background_prompt(location: Location, shot_size: ShotSize, angle: CameraAngle) -> RenderPrompt:
    """
    Builds the FLUX prompt for re-framing a location -- drawing it at a shot size and angle other than the master plate's, with the master plate as image 1.

    Raises a KeyError for a wide, eye-level shot (that is the master plate itself) and for a close-up (never generated -- see COMPOSITION_PHRASES).

    Arguments:
        location: Location - Location the shot takes place in.
        shot_size: ShotSize - Size of the shot being composited (WIDE or MEDIUM).
        angle: CameraAngle - Camera angle to be used in the generation.

    Returns:
        RenderPrompt - A RenderPrompt object, representing the background prompt to be handed off to the model.
    """
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + COMPOSITION_PHRASES[(shot_size, angle)] + location.description,
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )

def build_detail_prompt(location: Location, details: str) -> RenderPrompt:
    """
    Builds the FLUX prompt for drawing a shot's details as an edit of the same framing without them (given as image 1) -- the camera never moves in the same generation.

    Arguments:
        location: Location - Location the shot takes place in.
        details: str - Small, visible changes to the location in this shot.

    Returns:
        RenderPrompt - A RenderPrompt object, representing the detail edit prompt to be handed off to the model.
    """
    return RenderPrompt(
        text=BACKGROUND_STYLE_PREFIX + DETAIL_EDIT_PHRASE + location.description + f", changed only as follows: {details}",
        negative_text=BACKGROUND_NEGATIVE_PROMPT,
    )