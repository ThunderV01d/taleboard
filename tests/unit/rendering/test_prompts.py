import pytest

from taleboard.rendering.prompts import MAX_SUBJECT_LENGTH, NEGATIVE_PROMPT, ORIENTATION_PHRASES, STYLE_PREFIX, build_character_prompt
from taleboard.schema.enums import Orientation, PositionCell, SizeInFrame
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
    """if SDXL's text encoder ever has to drop trailing tokens, it should drop subject detail, never the style instructions. That only holds if the style prefix genuinely comes first in the string.
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