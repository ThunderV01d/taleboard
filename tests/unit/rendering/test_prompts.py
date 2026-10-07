import pytest

from taleboard.rendering.prompts import BACKGROUND_NEGATIVE_PROMPT, BACKGROUND_STYLE_PREFIX, CAMERA_ANGLE_PHRASES, MAX_SUBJECT_LENGTH, NEGATIVE_PROMPT, ORIENTATION_PHRASES, SHOT_SIZE_PHRASES, STYLE_PREFIX, build_background_prompt, build_character_prompt
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region


def _character(description: str = "A tall man in his 30's with a beard, wearing a jacket.") -> Character:
    return Character(name="Bob", description=description, colour="#0000ff")


def _region(action: str = "standing", orientation: Orientation = Orientation.TOWARDS_CAMERA) -> Region:
    return Region(
        character_id="bob",
        position=PositionCell.MID_CENTER,
        size=SizeInFrame.MEDIUM,
        orientation=orientation,
        action=action,
    )


def test_style_prefix_comes_before_subject_text():
    """if FLUX's text encoder ever has to drop trailing tokens, it should drop subject detail, never the style instructions. That only holds if the style prefix genuinely comes first in the string.
    """
    prompt = build_character_prompt(_character(), _region())
    assert prompt.text.startswith(STYLE_PREFIX)


def test_subject_text_includes_description_and_action():
    character = _character("A woman with short red hair.")
    region = _region("waving")

    prompt = build_character_prompt(character, region)

    assert "A woman with short red hair." in prompt.text
    assert "waving" in prompt.text


def test_negative_prompt_is_returned_unchanged():
    prompt = build_character_prompt(_character(), _region())
    assert prompt.negative_text == NEGATIVE_PROMPT


def test_long_description_is_truncated():
    character = _character("A" * 1000)
    region = _region()
    prompt = build_character_prompt(character, region)
    prefix = STYLE_PREFIX + ORIENTATION_PHRASES[region.orientation]
    subject_portion = prompt.text[len(prefix):]
    assert len(subject_portion) <= MAX_SUBJECT_LENGTH


def test_short_description_is_not_truncated():
    character = _character("A short description.")
    region = _region("standing")
 
    prompt = build_character_prompt(character, region)
 
    orientation_phrase = ORIENTATION_PHRASES[region.orientation]
    assert prompt.text == f"{STYLE_PREFIX}{orientation_phrase}{character.description}, {region.action}"


def test_truncation_still_keeps_style_prefix_intact():
    """Regression guard: even when the subject text is long enough to need truncating, the style prefix itself must never be the part that gets cut -- that would defeat the entire front-loading design.
    """
    character = _character("B" * 1000)
    prompt = build_character_prompt(character, _region())

    assert prompt.text.startswith(STYLE_PREFIX)

def test_orientation_phrase_appears_for_every_orientation():
    """Every Orientation value must map to real prompt text -- a KeyError
    here means ORIENTATION_PHRASES fell out of sync with the enum.
    """
    for orientation in Orientation:
        region = _region(orientation=orientation)
        prompt = build_character_prompt(_character(), region)
 
        assert ORIENTATION_PHRASES[orientation] in prompt.text
 
 
def test_different_orientations_produce_different_prompts():
    left = build_character_prompt(_character(), _region(orientation=Orientation.LEFT))
    right = build_character_prompt(_character(), _region(orientation=Orientation.RIGHT))
    assert left.text != right.text

def test_character_prompt_defaults_to_eye_level_with_an_empty_phrase():
    with_default = build_character_prompt(_character(), _region())
    with_explicit_eye_level = build_character_prompt(_character(), _region(), angle=CameraAngle.EYE_LEVEL)
 
    assert with_default.text == with_explicit_eye_level.text
    orientation_phrase = ORIENTATION_PHRASES[Orientation.TOWARDS_CAMERA]
    assert with_default.text == f"{STYLE_PREFIX}{orientation_phrase}{_character().description}, standing"
 
 
def test_character_prompt_includes_the_camera_angle_phrase():
    prompt = build_character_prompt(_character(), _region(), angle=CameraAngle.LOW)
    assert CAMERA_ANGLE_PHRASES[CameraAngle.LOW] in prompt.text
 
 
def test_character_prompt_angle_phrase_comes_after_orientation_and_before_subject():
    character = _character("A" * 1000)
    region = _region()
    prompt = build_character_prompt(character, region, angle=CameraAngle.HIGH)
 
    expected_prefix = STYLE_PREFIX + ORIENTATION_PHRASES[region.orientation] + CAMERA_ANGLE_PHRASES[CameraAngle.HIGH]
    assert prompt.text.startswith(expected_prefix)
 
 
def test_different_camera_angles_produce_different_character_prompts():
    low = build_character_prompt(_character(), _region(), angle=CameraAngle.LOW)
    high = build_character_prompt(_character(), _region(), angle=CameraAngle.HIGH)
    eye_level = build_character_prompt(_character(), _region(), angle=CameraAngle.EYE_LEVEL)
 
    assert low.text != high.text != eye_level.text
    assert low.text != eye_level.text
 
 
def test_camera_angle_phrases_are_shared_between_character_and_background_prompts():
    """CAMERA_ANGLE_PHRASES describes the camera's relationship to whatever's in frame."""
    for angle in CameraAngle:
        character_prompt = build_character_prompt(_character(), _region(), angle=angle)
        background_prompt = build_background_prompt("an empty hallway", ShotSize.MEDIUM, angle)
 
        if CAMERA_ANGLE_PHRASES[angle]:
            assert CAMERA_ANGLE_PHRASES[angle] in character_prompt.text
            assert CAMERA_ANGLE_PHRASES[angle] in background_prompt.text

def test_background_prompt_starts_with_background_style_prefix():
    prompt = build_background_prompt("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL)
    assert prompt.text.startswith(BACKGROUND_STYLE_PREFIX)
 
 
def test_background_prompt_includes_the_setting_text():
    prompt = build_background_prompt("a crowded train platform", ShotSize.WIDE, CameraAngle.LOW)
    assert "a crowded train platform" in prompt.text

 
def test_background_prompt_uses_its_own_negative_prompt():
    prompt = build_background_prompt("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL)
    assert prompt.negative_text == BACKGROUND_NEGATIVE_PROMPT
 
 
def test_background_negative_prompt_does_not_exclude_close_up_or_people():
    """Two deliberate differences from the character NEGATIVE_PROMPT:
    there's no cropped/close-up exclusion (a close-up ShotSize should be
    free to actually look like one for a background), and no blanket
    "no people"/crowd exclusion (some settings describe a populated scene
    and some an empty one -- that distinction lives in the setting text,
    not a fixed term that would fight half of all settings).
    """
    for excluded_term in ("cropped", "close-up", "portrait", "headshot", "people", "crowd"):
        assert excluded_term not in BACKGROUND_NEGATIVE_PROMPT
 
 
def test_every_shot_size_has_a_background_phrase():
    for shot_size in ShotSize:
        prompt = build_background_prompt("an empty hallway", shot_size, CameraAngle.EYE_LEVEL)
        assert SHOT_SIZE_PHRASES[shot_size] in prompt.text
 
 
def test_every_camera_angle_has_a_background_phrase():
    for angle in CameraAngle:
        prompt = build_background_prompt("an empty hallway", ShotSize.MEDIUM, angle)
        assert CAMERA_ANGLE_PHRASES[angle] in prompt.text or CAMERA_ANGLE_PHRASES[angle] == ""
 
 
def test_different_shot_sizes_produce_different_background_prompts():
    close_up = build_background_prompt("an empty hallway", ShotSize.CLOSE_UP, CameraAngle.EYE_LEVEL)
    wide = build_background_prompt("an empty hallway", ShotSize.WIDE, CameraAngle.EYE_LEVEL)
    assert close_up.text != wide.text
 
 
def test_different_angles_produce_different_background_prompts():
    low = build_background_prompt("an empty hallway", ShotSize.MEDIUM, CameraAngle.LOW)
    high = build_background_prompt("an empty hallway", ShotSize.MEDIUM, CameraAngle.HIGH)
    assert low.text != high.text
 
 
def test_background_prompt_does_not_share_the_character_style_prefix():
    """build_background_prompt is deliberately a separate style, not a
    variant of the character one -- a character cutout wants an isolated
    subject on a simple white background, a background render wants the
    opposite.
    """
    prompt = build_background_prompt("an empty hallway", ShotSize.MEDIUM, CameraAngle.EYE_LEVEL)
    assert STYLE_PREFIX not in prompt.text