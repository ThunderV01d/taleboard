"""
Builds the FLUX prompts for every image a v0.2.0 project generates: location plates, re-framings, detail and lighting edits, character references and poses, and prop references.

Every background is drawn as a chain, changing one thing per generation so the place never drifts: the plate for the shot's facing, then its framing, then its details, then its lighting. Each plate shows only what's on its side of the place (the location's view for that facing), so every facing is a different view of the same place. Each prompt below is one link of that chain, and says what to keep from the image it is drawn from (always image 1).

Characters and props are never drawn with anything else in their image: a character's hands are left empty (any object they hold is its own prop layer), and a prop is drawn alone.

Attributes:
    STYLE: str - The drawing style every image shares.
    CHARACTER_STYLE: str - Style and isolation instructions for a character.
    PROP_STYLE: str - Style and isolation instructions for a prop.
    BACKGROUND_STYLE: str - Style instructions for a background (no shading, so the lighting edit is the only place light and weather are drawn).
    NEUTRAL_POSE: str - The action a character's reference image is drawn in.
    ORIENTATION_PHRASES: dict[Orientation,str] - Which way a character faces, relative to the camera.
    PROP_ORIENTATION_PHRASES: dict[Orientation,str] - Which side of a prop faces the camera.
    MASTER_PLATE_FRAMING: str - Framing of the north plate of a location with no views -- a wide, eye-level view of the whole empty place, drawn from its description alone.
    PLATE_FRAMING: str - Framing of a plate drawn from a view -- wide, eye-level and empty.
    PLACE_PHRASES: dict[Setting,str] - Where the camera is, indoors or out ("inside" a room, "at" a place).
    SAME_PLACE_PHRASES: dict[Setting,str] - Takes only what the place is made of, and the drawing style, from the north plate (image 1) when drawing another side of it.
    COMPOSITION_PHRASES: dict[tuple[ShotSize,CameraAngle],str] - Where the camera moves to, from the plate (image 1), for each framing that is generated.
    DETAIL_EDIT_PHRASE: str - Keeps image 1's view exactly, so a shot's details are drawn as an edit.
    LIGHTING_EDIT_PHRASES: dict[Setting,str] - Keeps image 1's view and contents exactly, so a scene's light (and, outdoors, its weather) is drawn as an edit.
    TIME_OF_DAY_PHRASES: dict[Setting,dict[TimeOfDay,str]] - How each time of day is drawn, indoors and out, in pencil.
    ATMOSPHERE_PHRASES: dict[Setting,dict[Atmosphere,str]] - How each kind of weather is drawn: outdoors as weather, indoors as the light it brings.
"""
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.storyboard import Character, Location, Prop

STYLE = "pencil sketch, black and white line art, rough hand-drawn illustration style, no signature, no text, no watermark, "

CHARACTER_STYLE = (
    "Storyboard panel, " + STYLE +
    "full body shot, entire body visible, head-to-toe, no shading or lighting, simple white background, "
    "a single figure alone, no other people, no room, walls, windows or scenery, "
    "empty hands holding nothing, no objects or props -- a hand that would be holding something is shaped as if gripping it, but empty, "
)

PROP_STYLE = (
    "Storyboard panel, " + STYLE +
    "the whole object visible, no shading or lighting, simple white background, "
    "a single object alone, no people, no hands, no other objects, no table, floor or scenery, "
)

BACKGROUND_STYLE = "Storyboard panel, " + STYLE + "filling full frame, no shading or lighting, "

NEUTRAL_POSE = "standing, arms relaxed at the sides, both hands open and empty, holding nothing"

ORIENTATION_PHRASES: dict[Orientation, str] = {
    Orientation.TOWARDS_CAMERA: "facing directly towards the camera towards the viewer, front view, ",
    Orientation.AWAY_FROM_CAMERA: "viewed directly from behind, facing away from the viewer, back view, ",
    Orientation.LEFT: "facing directly to the left, side profile view, ",
    Orientation.RIGHT: "facing directly to the right, side profile view, ",
}

PROP_ORIENTATION_PHRASES: dict[Orientation, str] = {
    Orientation.TOWARDS_CAMERA: "front view, its front facing the viewer, ",
    Orientation.AWAY_FROM_CAMERA: "back view, its back facing the viewer, ",
    Orientation.LEFT: "side view, its front pointing to the left, ",
    Orientation.RIGHT: "side view, its front pointing to the right, ",
}

MASTER_PLATE_FRAMING = "wide shot, establishing view of the whole place at eye level, empty, with nobody in it, "

_SAME_PLACE = "keeping everything in the place, its layout and the drawing style the same as image 1, "

PLATE_FRAMING = "wide shot at eye level, empty, with nobody in it, "

# Where the camera is, for a plate drawn from a view
PLACE_PHRASES: dict[Setting, str] = {Setting.INT: "inside", Setting.EXT: "at"}

# Every facing but north is drawn from what's on that side, with the north plate as image 1 for what the place is made of only.
# Given the whole place's description, or let image 1's composition through, FLUX just draws the north view again
SAME_PLACE_PHRASES: dict[Setting, str] = {
    Setting.INT: " Use image 1 only for the room's materials, walls, proportions and drawing style -- do not copy its composition or anything in it.",
    Setting.EXT: " Use image 1 only for the place's materials, buildings, ground and drawing style -- do not copy its composition or anything in it.",
}

# Wide eye-level has no entry: that is the plate itself. Nor do close-ups, which use the wide background, scaled up on the canvas
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

DETAIL_EDIT_PHRASE = "the same view of the place in image 1, from the same camera position and with the same framing, "

# Indoors, a scene's weather is drawn as the light it brings, never as weather: FLUX draws whatever a prompt names, so naming rain
# or a sky -- even to say "only outside" -- puts them inside a room
LIGHTING_EDIT_PHRASES: dict[Setting, str] = {
    Setting.INT: (
        "the same view of the place in image 1, from the same camera position and with the same framing, with everything in it "
        "unchanged, changed only in its light: "
    ),
    Setting.EXT: (
        "the same view of the place in image 1, from the same camera position and with the same framing, with everything in it "
        "unchanged, changed only in its light and weather: "
    ),
}

# Day is how a plate is drawn already; the rest are drawn in pencil, as hatching and blank paper rather than tone
TIME_OF_DAY_PHRASES: dict[Setting, dict[TimeOfDay, str]] = {
    Setting.INT: {
        TimeOfDay.DAWN: "at dawn, low pale light from one side, long soft shadows drawn with light hatching, ",
        TimeOfDay.DAY: "",
        TimeOfDay.DUSK: "at dusk, fading warm light, long shadows drawn with hatching, ",
        TimeOfDay.NIGHT: (
            "at night: lit only by its own lights, all switched on and as bright as they make the place, "
            "black night showing through anything that looks outside, cross-hatched shadow only where its lights do not reach, "
        ),
    },
    Setting.EXT: {
        TimeOfDay.DAWN: "at dawn, a pale sky low on one side, long soft shadows drawn with light hatching, ",
        TimeOfDay.DAY: "",
        TimeOfDay.DUSK: "at dusk, a fading sky, long shadows drawn with hatching, ",
        TimeOfDay.NIGHT: "at night, a dark night sky, everything in deep cross-hatched shadow, ",
    },
}

ATMOSPHERE_PHRASES: dict[Setting, dict[Atmosphere, str]] = {
    Setting.INT: {
        Atmosphere.CLEAR: "",
        Atmosphere.OVERCAST: "flat, grey light, no hard shadows, ",
        Atmosphere.RAINY: "dim, grey light, ",
        Atmosphere.FOGGY: "hazy, pale light, ",
        Atmosphere.STORMY: "dark, grey light, ",
        Atmosphere.SNOWY: "cold, pale light, ",
    },
    Setting.EXT: {
        Atmosphere.CLEAR: "",
        Atmosphere.OVERCAST: "under a flat overcast sky, no hard shadows, ",
        Atmosphere.RAINY: "in the rain, fine diagonal rain streaks, wet ground, ",
        Atmosphere.FOGGY: "in thick fog, the far distance fading to blank paper, ",
        Atmosphere.STORMY: "in a storm, heavy slanting rain, wind-blown trees and debris, ",
        Atmosphere.SNOWY: "in falling snow, snow lying on the ground and every ledge, ",
    },
}

def character_prompt(character: Character, orientation: Orientation, action: str = NEUTRAL_POSE) -> str:
    """
    Builds the prompt for one character image -- their reference in an orientation (the default action), or a pose for a shot.

    A reference facing the camera is drawn from this prompt alone. Every other image of the character is drawn with a reference as image 1, which keeps them looking the same.

    Arguments:
        character: Character - The character.
        orientation: Orientation - Which way they face, relative to the camera.
        action: str - What their body is doing. Defaults to NEUTRAL_POSE (a reference).

    Returns:
        str - The prompt.
    """
    return CHARACTER_STYLE + ORIENTATION_PHRASES[orientation] + f"{character.description}, {action or NEUTRAL_POSE}"


def prop_prompt(prop: Prop, orientation: Orientation) -> str:
    """
    Builds the prompt for a prop's reference in an orientation -- which is also the image a prop layer shows. Every orientation but the front is drawn with the front as image 1.

    Arguments:
        prop: Prop - The prop.
        orientation: Orientation - Which side of it faces the camera.

    Returns:
        str - The prompt.
    """
    return PROP_STYLE + PROP_ORIENTATION_PHRASES[orientation] + prop.description


def plate_prompt(location: Location, facing: Facing) -> str:
    """
    Builds the prompt for a location's plate in one facing -- a wide, eye-level view of the empty place.

    With a view for the facing, the plate shows what the whole place has in common (its description) and only what's on that side; every facing but north is also drawn with the north plate as image 1, for what the place is made of. A north with no view is drawn from the whole description. Any other facing with no view is never drawn -- it shows the north plate -- so asking for its prompt is a KeyError.

    Arguments:
        location: Location - The location.
        facing: Facing - Which way the camera faces.

    Returns:
        str - The prompt.
    """
    view = location.views.get(facing)
    if view is None:
        if facing != Facing.NORTH:
            raise KeyError(f"Location {location.id!r} has no view facing {facing.value}")
        return BACKGROUND_STYLE + MASTER_PLATE_FRAMING + location.description
    place = location.description or location.name
    prompt = BACKGROUND_STYLE + PLATE_FRAMING + f"{PLACE_PHRASES[location.setting]} {place}, looking straight at {view}."
    if facing != Facing.NORTH:
        prompt += SAME_PLACE_PHRASES[location.setting]
    return prompt


def framing_prompt(location: Location, shot_size: ShotSize, angle: CameraAngle) -> str:
    """
    Builds the prompt for re-framing a plate (image 1) at a shot size and angle. Raises a KeyError for a wide, eye-level framing (the plate itself) and a close-up (never generated).

    Arguments:
        location: Location - The location.
        shot_size: ShotSize - WIDE or MEDIUM.
        angle: CameraAngle - The camera angle.

    Returns:
        str - The prompt.
    """
    return BACKGROUND_STYLE + COMPOSITION_PHRASES[(shot_size, angle)] + location.description


def detail_prompt(location: Location, details: str) -> str:
    """
    Builds the prompt for drawing a shot's details as an edit of the same view without them (image 1) -- the camera never moves in the same generation.

    Arguments:
        location: Location - The location.
        details: str - Small, visible changes to the location in this shot.

    Returns:
        str - The prompt.
    """
    return BACKGROUND_STYLE + DETAIL_EDIT_PHRASE + location.description + f", changed only as follows: {details}"


def lighting_prompt(setting: Setting, time_of_day: TimeOfDay, atmosphere: Atmosphere) -> str | None:
    """
    Builds the prompt for drawing a scene's light and weather as an edit of the finished view (image 1) -- the last link of the chain, so one view can be relit for any scene without being drawn again.

    Outdoors, the weather itself is drawn; indoors, only the light it brings (a rainy day is a dim, grey room), so no rain, snow or sky is ever drawn inside. Shading is allowed here (only here): it is how night, dusk and weather are drawn in pencil.

    Arguments:
        setting: Setting - Whether the location is indoors or out.
        time_of_day: TimeOfDay - The scene's time of day.
        atmosphere: Atmosphere - The scene's weather.

    Returns:
        str - The prompt, or None for daytime in clear weather -- how every view is drawn already, so there is nothing to edit.
    """
    change = TIME_OF_DAY_PHRASES[setting][time_of_day] + ATMOSPHERE_PHRASES[setting][atmosphere]
    if not change:
        return None
    return "Storyboard panel, " + STYLE + "filling full frame, " + LIGHTING_EDIT_PHRASES[setting] + change.rstrip(", ")

