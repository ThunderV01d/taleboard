"""
Unit tests for the v0.2.0 generation prompts.

Covers the character, prop and background prompts: that characters and props are drawn alone (hands empty, props with nobody holding them), that every facing, framing, time of day and atmosphere has its phrase, and that each link of the background chain says what to keep from image 1.
"""
import pytest

from taleboard.generation.prompts import (
    ATMOSPHERE_PHRASES, BACKGROUND_STYLE, CHARACTER_STYLE, COMPOSITION_PHRASES, MASTER_PLATE_FRAMING, NEUTRAL_POSE, ORIENTATION_PHRASES,
    PLATE_FRAMING, PROP_ORIENTATION_PHRASES, PROP_STYLE, SAME_PLACE_PHRASES, TIME_OF_DAY_PHRASES, character_prompt, detail_prompt,
    framing_prompt, lighting_prompt, plate_prompt, prop_prompt,
)
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.storyboard import Character, Location, Prop

MARA = Character(id="mara", name="Mara", description="a lighthouse keeper in her sixties, oilskin coat")
LAMP = Prop(id="lamp", name="Lamp", description="a brass storm lantern with a glass chimney")
LIGHTHOUSE = Location(id="lighthouse", name="Lighthouse", description="the round lamp room at the top of a lighthouse")
OFFICE = Location(id="office", name="Office", description="a small wood-panelled office", views={
    Facing.NORTH: "the back wall: a two-pane window behind a desk",
    Facing.EAST: "a side wall: a filing cabinet and a bookcase",
    Facing.SOUTH: "the front wall: a door with a coat stand beside it",
    Facing.WEST: "the other side wall: a corkboard above a side table",
})
QUAY = Location(id="quay", name="Quay", setting=Setting.EXT, description="a stone harbour quay", views={
    Facing.NORTH: "the harbour and the moored boats",
    Facing.SOUTH: "a row of whitewashed cottages",
})

GENERATED_FRAMINGS = [
    (size, angle) for size in (ShotSize.WIDE, ShotSize.MEDIUM) for angle in CameraAngle if (size, angle) != (ShotSize.WIDE, CameraAngle.EYE_LEVEL)
]


def test_a_character_is_drawn_alone_with_empty_hands_in_their_own_description_and_action():
    """
    Verifies that a character prompt keeps every object out of their image -- hands posed but empty -- and draws their description and action.
    """
    prompt = character_prompt(MARA, Orientation.LEFT, "one hand raised to her ear, gripping")

    assert prompt.startswith(CHARACTER_STYLE)
    assert "empty hands holding nothing, no objects or props" in prompt
    assert ORIENTATION_PHRASES[Orientation.LEFT] in prompt
    assert prompt.endswith(f"{MARA.description}, one hand raised to her ear, gripping")


@pytest.mark.parametrize("action", [NEUTRAL_POSE, ""])
def test_a_character_reference_is_drawn_in_a_neutral_pose(action):
    """
    Verifies that the default action, and an empty one, both draw the neutral reference pose.

    Arguments:
        action: str - The action given.
    """
    assert character_prompt(MARA, Orientation.TOWARDS_CAMERA, action).endswith(f"{MARA.description}, {NEUTRAL_POSE}")


def test_characters_are_no_longer_drawn_with_a_camera_angle():
    """
    Verifies that character prompts never mention a camera angle -- a character's image depends only on their orientation and action.
    """
    assert all("angle" not in character_prompt(MARA, orientation) for orientation in Orientation)


def test_a_prop_is_drawn_alone_with_nobody_holding_it():
    """
    Verifies that a prop prompt keeps people and hands out, and draws its description from the side asked for.
    """
    prompt = prop_prompt(LAMP, Orientation.RIGHT)

    assert prompt.startswith(PROP_STYLE)
    assert "no people, no hands, no other objects" in prompt
    assert prompt.endswith(PROP_ORIENTATION_PHRASES[Orientation.RIGHT] + LAMP.description)


def test_every_orientation_has_a_phrase_for_characters_and_for_props():
    """
    Verifies that no orientation is missing a phrase, and that each one draws a different prompt.
    """
    assert set(ORIENTATION_PHRASES) == set(PROP_ORIENTATION_PHRASES) == set(Orientation)
    assert len({prop_prompt(LAMP, o) for o in Orientation}) == len({character_prompt(MARA, o) for o in Orientation}) == len(Orientation)


def test_a_north_with_no_view_is_a_wide_view_of_the_whole_place_from_its_description():
    """
    Verifies that a location with nothing said about its sides gets its north plate from the whole description, as before views existed.
    """
    assert plate_prompt(LIGHTHOUSE, Facing.NORTH) == BACKGROUND_STYLE + MASTER_PLATE_FRAMING + LIGHTHOUSE.description


def test_a_plate_with_a_view_shows_the_whole_place_and_only_that_side():
    """
    Verifies that north is drawn from what the place has in common plus its own side -- and never says to keep anything from image 1 (it has none).
    """
    prompt = plate_prompt(OFFICE, Facing.NORTH)

    assert prompt == BACKGROUND_STYLE + PLATE_FRAMING + f"inside {OFFICE.description}, looking straight at {OFFICE.views[Facing.NORTH]}."
    assert "image 1" not in prompt


@pytest.mark.parametrize("facing", [Facing.EAST, Facing.SOUTH, Facing.WEST])
def test_every_other_side_is_its_own_view_with_the_north_plate_for_materials_only(facing):
    """
    Verifies that each other side shows its own view, with none of the others' contents, and takes only materials and style from image 1.

    Arguments:
        facing: Facing - A facing other than north.
    """
    prompt = plate_prompt(OFFICE, facing)

    assert OFFICE.views[facing] in prompt
    assert not any(view in prompt for other, view in OFFICE.views.items() if other != facing)
    assert prompt.endswith(SAME_PLACE_PHRASES[Setting.INT])


def test_an_exterior_is_drawn_at_the_place_rather_than_inside_it():
    """
    Verifies that an outdoor place's plates say "at" it, and take its buildings and ground (not walls) from image 1.
    """
    north, south = plate_prompt(QUAY, Facing.NORTH), plate_prompt(QUAY, Facing.SOUTH)

    assert f"at {QUAY.description}, looking straight at" in north and "inside" not in north
    assert south.endswith(SAME_PLACE_PHRASES[Setting.EXT]) and "buildings, ground" in south


def test_a_side_with_no_view_has_no_plate_prompt():
    """
    Verifies that a facing other than north with no view is never drawn (the engine shows the north plate instead).
    """
    with pytest.raises(KeyError):
        plate_prompt(LIGHTHOUSE, Facing.SOUTH)


def test_a_place_with_no_description_is_named_instead():
    """
    Verifies that a plate drawn from a view still says what the place is when its description is empty.
    """
    bare = Location(id="cellar", name="Cellar", views={Facing.NORTH: "a stone wall with wine racks"})

    assert "inside Cellar, looking straight at a stone wall with wine racks." in plate_prompt(bare, Facing.NORTH)


@pytest.mark.parametrize("size, angle", GENERATED_FRAMINGS)
def test_every_generated_framing_moves_the_camera_from_the_plate(size, angle):
    """
    Verifies that each framing other than wide eye-level has its own phrase, relative to image 1.

    Arguments:
        size: ShotSize - WIDE or MEDIUM.
        angle: CameraAngle - Any angle.
    """
    assert framing_prompt(LIGHTHOUSE, size, angle) == BACKGROUND_STYLE + COMPOSITION_PHRASES[(size, angle)] + LIGHTHOUSE.description


@pytest.mark.parametrize("size, angle", [(ShotSize.WIDE, CameraAngle.EYE_LEVEL)] + [(ShotSize.CLOSE_UP, a) for a in CameraAngle])
def test_the_plates_own_framing_and_close_ups_are_never_generated(size, angle):
    """
    Verifies that wide eye-level (the plate itself) and close-ups (the wide background, scaled up) have no framing prompt.

    Arguments:
        size: ShotSize - The shot size.
        angle: CameraAngle - The angle.
    """
    with pytest.raises(KeyError):
        framing_prompt(LIGHTHOUSE, size, angle)


def test_details_are_an_edit_that_keeps_the_view():
    """
    Verifies that a detail prompt keeps image 1's view and adds only the details.
    """
    prompt = detail_prompt(LIGHTHOUSE, "the lamp lit")

    assert "same camera position and with the same framing" in prompt
    assert prompt.endswith(f"{LIGHTHOUSE.description}, changed only as follows: the lamp lit")


@pytest.mark.parametrize("setting", list(Setting))
def test_daytime_in_clear_weather_needs_no_lighting_edit(setting):
    """
    Verifies that the way every view is drawn already needs no edit, indoors or out.

    Arguments:
        setting: Setting - Indoors or out.
    """
    assert lighting_prompt(setting, TimeOfDay.DAY, Atmosphere.CLEAR) is None


@pytest.mark.parametrize("setting, time_of_day, atmosphere", [
    (s, t, a) for s in Setting for t in TimeOfDay for a in Atmosphere if (t, a) != (TimeOfDay.DAY, Atmosphere.CLEAR)
])
def test_every_other_light_and_weather_is_an_edit_that_keeps_the_view(setting, time_of_day, atmosphere):
    """
    Verifies that every other combination is drawn as an edit of image 1 that keeps everything in it, and says both its time and weather.

    Arguments:
        setting: Setting - Indoors or out.
        time_of_day: TimeOfDay - The scene's time of day.
        atmosphere: Atmosphere - The scene's weather.
    """
    prompt = lighting_prompt(setting, time_of_day, atmosphere)

    assert "same camera position and with the same framing, with everything in it unchanged" in prompt
    assert "no shading" not in prompt  # Light and weather are drawn with hatching, here only
    assert TIME_OF_DAY_PHRASES[setting][time_of_day].rstrip(", ") in prompt
    assert ATMOSPHERE_PHRASES[setting][atmosphere].rstrip(", ") in prompt
    assert not prompt.endswith(",")


@pytest.mark.parametrize("time_of_day, atmosphere", [(t, a) for t in TimeOfDay for a in Atmosphere])
def test_indoors_nothing_is_named_that_would_be_drawn_inside_a_room(time_of_day, atmosphere):
    """
    Verifies that an interior's lighting never names a sky, weather or windows -- FLUX draws whatever is named, so naming them (even to say "only outside") puts them in the room.

    Arguments:
        time_of_day: TimeOfDay - The scene's time of day.
        atmosphere: Atmosphere - The scene's weather.
    """
    prompt = lighting_prompt(Setting.INT, time_of_day, atmosphere) or ""

    assert not any(word in prompt for word in ("sky", "rain", "snow", "fog", "storm", "window", "weather"))


def test_outdoors_the_weather_itself_is_drawn():
    """
    Verifies that an exterior's lighting draws the sky and the weather, and says it may change the weather as well as the light.
    """
    prompt = lighting_prompt(Setting.EXT, TimeOfDay.NIGHT, Atmosphere.RAINY)

    assert "changed only in its light and weather" in prompt and "night sky" in prompt and "rain streaks" in prompt


def test_every_time_of_day_and_atmosphere_has_a_phrase_and_only_the_defaults_are_empty():
    """
    Verifies the phrase tables cover every value, indoors and out, and that only day and clear are left as drawn.
    """
    for setting in Setting:
        assert set(TIME_OF_DAY_PHRASES[setting]) == set(TimeOfDay) and set(ATMOSPHERE_PHRASES[setting]) == set(Atmosphere)
        assert [t for t, phrase in TIME_OF_DAY_PHRASES[setting].items() if not phrase] == [TimeOfDay.DAY]
        assert [a for a, phrase in ATMOSPHERE_PHRASES[setting].items() if not phrase] == [Atmosphere.CLEAR]
