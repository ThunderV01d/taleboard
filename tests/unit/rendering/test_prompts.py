"""
Unit tests for the rendering prompts.

Covers how character, background and master plate prompts are assembled from the style prefixes, orientation, camera angle, composition and subject/location text.
"""
import pytest

from taleboard.rendering.prompts import BACKGROUND_NEGATIVE_PROMPT, BACKGROUND_STYLE_PREFIX, CAMERA_ANGLE_PHRASES, COMPOSITION_PHRASES, MASTER_PLATE_FRAMING, MAX_SUBJECT_LENGTH, NEGATIVE_PROMPT, ORIENTATION_PHRASES, STYLE_PREFIX, build_background_prompt, build_character_prompt, build_master_plate_prompt
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Location, Region

GENERATED_FRAMINGS = [(shot_size, angle) for shot_size in (ShotSize.WIDE, ShotSize.MEDIUM) for angle in CameraAngle]


def _character(description: str = "A tall man in his 30's with a beard, wearing a jacket.") -> Character:
    """
    Builds a character called Bob.

    Arguments:
        description: str - Character description. Defaults to a bearded man in a jacket.

    Returns:
        Character - A Character object.
    """
    return Character(name="Bob", description=description)


def _location(description: str = "an empty hallway with a single overhead bulb") -> Location:
    """
    Builds a hallway location.

    Arguments:
        description: str - Location description. Defaults to an empty hallway.

    Returns:
        Location - A Location object.
    """
    return Location(name="Hallway", description=description)


def _region(action: str = "standing", orientation: Orientation = Orientation.TOWARDS_CAMERA) -> Region:
    """
    Builds a centred, medium-sized region for Bob.

    Arguments:
        action: str - Action of the region. Defaults to "standing".
        orientation: Orientation - Orientation of the region. Defaults to TOWARDS_CAMERA.

    Returns:
        Region - A Region object.
    """
    return Region(
        character_id="bob",
        position=PositionCell.MID_CENTER,
        size=SizeInFrame.MEDIUM,
        orientation=orientation,
        action=action,
    )


def test_style_prefix_comes_before_subject_text():
    """
    Verifies that the character prompt starts with the style prefix.

    The style instructions are front-loaded so they always come before (and take priority over) the subject details.
    """
    prompt = build_character_prompt(_character(), _region())
    assert prompt.text.startswith(STYLE_PREFIX)


def test_subject_text_includes_description_and_action():
    """
    Verifies that the character prompt includes both the character's description and the region's action.
    """
    character = _character("A woman with short red hair.")
    region = _region("waving")

    prompt = build_character_prompt(character, region)

    assert "A woman with short red hair." in prompt.text
    assert "waving" in prompt.text


def test_negative_prompt_is_returned_unchanged():
    """
    Verifies that the character prompt carries the character negative prompt as-is.
    """
    prompt = build_character_prompt(_character(), _region())
    assert prompt.negative_text == NEGATIVE_PROMPT


def test_long_description_is_truncated():
    """
    Verifies that an overly long subject is cut down to MAX_SUBJECT_LENGTH.
    """
    character = _character("A" * 1000)
    region = _region()
    prompt = build_character_prompt(character, region)
    prefix = STYLE_PREFIX + ORIENTATION_PHRASES[region.orientation]
    subject_portion = prompt.text[len(prefix):]
    assert len(subject_portion) <= MAX_SUBJECT_LENGTH


def test_short_description_is_not_truncated():
    """
    Verifies that a short subject is left whole, giving exactly the expected prompt.
    """
    character = _character("A short description.")
    region = _region("standing")

    prompt = build_character_prompt(character, region)

    orientation_phrase = ORIENTATION_PHRASES[region.orientation]
    assert prompt.text == f"{STYLE_PREFIX}{orientation_phrase}{character.description}, {region.action}"


def test_truncation_still_keeps_style_prefix_intact():
    """
    Verifies that truncating a long subject never cuts into the style prefix.

    Regression guard: only the subject text may be truncated -- cutting the style prefix would defeat the front-loading design.
    """
    character = _character("B" * 1000)
    prompt = build_character_prompt(character, _region())

    assert prompt.text.startswith(STYLE_PREFIX)

def test_orientation_phrase_appears_for_every_orientation():
    """
    Verifies that every orientation maps to a phrase that appears in the prompt.

    A KeyError here means ORIENTATION_PHRASES fell out of sync with the Orientation enum.
    """
    for orientation in Orientation:
        region = _region(orientation=orientation)
        prompt = build_character_prompt(_character(), region)

        assert ORIENTATION_PHRASES[orientation] in prompt.text


def test_different_orientations_produce_different_prompts():
    """
    Verifies that facing left and facing right give different prompts.
    """
    left = build_character_prompt(_character(), _region(orientation=Orientation.LEFT))
    right = build_character_prompt(_character(), _region(orientation=Orientation.RIGHT))
    assert left.text != right.text

def test_character_prompt_defaults_to_eye_level_with_an_empty_phrase():
    """
    Verifies that leaving out the camera angle gives the eye-level prompt, which adds no angle phrase at all.
    """
    with_default = build_character_prompt(_character(), _region())
    with_explicit_eye_level = build_character_prompt(_character(), _region(), angle=CameraAngle.EYE_LEVEL)

    assert with_default.text == with_explicit_eye_level.text
    orientation_phrase = ORIENTATION_PHRASES[Orientation.TOWARDS_CAMERA]
    assert with_default.text == f"{STYLE_PREFIX}{orientation_phrase}{_character().description}, standing"


def test_character_prompt_includes_the_camera_angle_phrase():
    """
    Verifies that a non-eye-level camera angle adds its phrase to the character prompt.
    """
    prompt = build_character_prompt(_character(), _region(), angle=CameraAngle.LOW)
    assert CAMERA_ANGLE_PHRASES[CameraAngle.LOW] in prompt.text


def test_character_prompt_angle_phrase_comes_after_orientation_and_before_subject():
    """
    Verifies the order of the character prompt: style prefix, then orientation, then camera angle, then subject.
    """
    character = _character("A" * 1000)
    region = _region()
    prompt = build_character_prompt(character, region, angle=CameraAngle.HIGH)

    expected_prefix = STYLE_PREFIX + ORIENTATION_PHRASES[region.orientation] + CAMERA_ANGLE_PHRASES[CameraAngle.HIGH]
    assert prompt.text.startswith(expected_prefix)


def test_different_camera_angles_produce_different_character_prompts():
    """
    Verifies that each camera angle gives a different character prompt.
    """
    low = build_character_prompt(_character(), _region(), angle=CameraAngle.LOW)
    high = build_character_prompt(_character(), _region(), angle=CameraAngle.HIGH)
    eye_level = build_character_prompt(_character(), _region(), angle=CameraAngle.EYE_LEVEL)

    assert low.text != high.text != eye_level.text
    assert low.text != eye_level.text


def test_background_prompt_starts_with_background_style_prefix():
    """
    Verifies that the background and master plate prompts start with the background style prefix.
    """
    assert build_background_prompt(_location(), "", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL).text.startswith(BACKGROUND_STYLE_PREFIX)
    assert build_master_plate_prompt(_location()).text.startswith(BACKGROUND_STYLE_PREFIX)


def test_background_style_prefix_does_not_force_an_establishing_shot():
    """
    Verifies that the shared background prefix doesn't ask for an establishing shot -- it used to, which pulled every background (close-ups included) towards a wide view.
    """
    assert "establishing" not in BACKGROUND_STYLE_PREFIX


def test_background_prompt_includes_the_location_description_and_the_details():
    """
    Verifies that the background prompt includes the location's description and the shot's details, as a change.
    """
    prompt = build_background_prompt(_location(), "the bulb is switched off", ShotSize.WIDE, CameraAngle.LOW)
    assert "an empty hallway with a single overhead bulb" in prompt.text
    assert "changed only as follows: the bulb is switched off" in prompt.text


def test_background_prompt_without_details_asks_for_no_change():
    """
    Verifies that a shot with no details doesn't add an (empty) change to the prompt.
    """
    prompt = build_background_prompt(_location(), "", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL)
    assert "changed only as follows" not in prompt.text
    assert prompt.text.endswith("an empty hallway with a single overhead bulb")


def test_background_prompts_use_their_own_negative_prompt():
    """
    Verifies that background and master plate prompts carry the background negative prompt, not the character one.
    """
    assert build_background_prompt(_location(), "", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL).negative_text == BACKGROUND_NEGATIVE_PROMPT
    assert build_master_plate_prompt(_location()).negative_text == BACKGROUND_NEGATIVE_PROMPT


def test_background_negative_prompt_does_not_exclude_close_up_or_people():
    """
    Verifies that the background negative prompt never excludes close-ups or people.

    Some shots' details add unnamed figures ("crowded with unnamed shoppers") and some don't -- that distinction lives in the details, not in a fixed exclusion that would fight half of all shots.
    """
    for excluded_term in ("cropped", "close-up", "portrait", "headshot", "people", "crowd"):
        assert excluded_term not in BACKGROUND_NEGATIVE_PROMPT


def test_every_generated_framing_has_its_own_composition_phrase_relative_to_the_master_plate():
    """
    Verifies that every wide and medium framing has a distinct composition phrase that appears in the prompt, and that each one refers to the master plate (image 1).
    """
    phrases = set()
    for shot_size, angle in GENERATED_FRAMINGS:
        prompt = build_background_prompt(_location(), "", shot_size, angle)
        assert COMPOSITION_PHRASES[(shot_size, angle)] in prompt.text
        assert "image 1" in COMPOSITION_PHRASES[(shot_size, angle)]
        phrases.add(COMPOSITION_PHRASES[(shot_size, angle)])
    assert len(phrases) == len(GENERATED_FRAMINGS)


def test_low_and_high_angle_backgrounds_say_where_the_camera_points():
    """
    Verifies that low and high angle compositions say the camera looks up and down -- without that, FLUX keeps the master plate's framing.
    """
    for shot_size in (ShotSize.WIDE, ShotSize.MEDIUM):
        assert "upward" in COMPOSITION_PHRASES[(shot_size, CameraAngle.LOW)]
        assert "down" in COMPOSITION_PHRASES[(shot_size, CameraAngle.HIGH)]


def test_a_close_up_background_is_never_generated():
    """
    Verifies that there is no close-up background prompt -- a close-up is cropped from a wide shot instead.
    """
    with pytest.raises(KeyError):
        build_background_prompt(_location(), "", ShotSize.CLOSE_UP, CameraAngle.EYE_LEVEL)


def test_master_plate_prompt_is_a_wide_view_of_the_location_with_no_reference():
    """
    Verifies that the master plate prompt asks for a wide view of the location's description, and doesn't refer to a reference image (it is the reference).
    """
    prompt = build_master_plate_prompt(_location())
    assert MASTER_PLATE_FRAMING in prompt.text
    assert prompt.text.endswith("an empty hallway with a single overhead bulb")
    assert "image 1" not in prompt.text


def test_background_prompt_does_not_share_the_character_style_prefix():
    """
    Verifies that the background prompt uses its own style, not the character one.

    A character cutout wants an isolated subject on a simple white background; a background render wants the opposite.
    """
    prompt = build_background_prompt(_location(), "", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL)
    assert STYLE_PREFIX not in prompt.text
