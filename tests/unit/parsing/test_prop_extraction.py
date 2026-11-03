"""
Unit tests for prop_extraction.

Covers prop ID assignment, a story with no props, the empty-story guard and retries. No LLM calls are made.
"""
import json

import pytest
from pydantic import ValidationError

from taleboard.parsing.prompts import PROP_EXTRACTION_INSTRUCTIONS
from taleboard.parsing.prop_extraction import PROP_RETRIES, extract_props

PROPS_RESPONSE = json.dumps({"props": [
    {"name": "Brass Lantern", "description": "an old brass storm lantern with a glass chimney"},
    {"name": "Letter", "description": "a folded letter of cream paper"},
]})


def test_extract_props_gives_each_prop_an_id_in_story_order():
    """
    Verifies that each prop gets a slugified ID from its name, in the order the model listed them, and that the story is in the prompt.
    """
    prompts: list[str] = []

    props = extract_props("Mara lit the lantern and read the letter.", lambda prompt: prompts.append(prompt) or PROPS_RESPONSE)

    assert list(props) == ["brass_lantern", "letter"]
    assert props["letter"].description == "a folded letter of cream paper"
    assert prompts[0].startswith(PROP_EXTRACTION_INSTRUCTIONS) and prompts[0].endswith("Mara lit the lantern and read the letter.")


def test_a_story_with_no_props_has_none():
    """
    Verifies that an empty prop list is a valid answer, not a retry.
    """
    calls: list[str] = []

    assert extract_props("Mara waited.", lambda prompt: calls.append(prompt) or json.dumps({"props": []})) == {}
    assert len(calls) == 1


@pytest.mark.parametrize("story", ["", "   \n\n "])
def test_extract_props_rejects_an_empty_story_before_calling_the_llm(story):
    """
    Verifies that an empty story raises a ValueError before any (paid) LLM call is made.

    Arguments:
        story: str - An empty or whitespace-only story.
    """
    calls: list[str] = []
    with pytest.raises(ValueError, match="empty"):
        extract_props(story, lambda prompt: calls.append(prompt) or PROPS_RESPONSE)
    assert calls == []


def test_a_description_too_long_is_sent_back_with_the_error():
    """
    Verifies that a prop list failing validation is sent back once, with the error and the response, before being accepted.
    """
    too_long = json.dumps({"props": [{"name": "Letter", "description": "x" * 301}]})
    responses = iter([too_long, PROPS_RESPONSE])
    prompts: list[str] = []

    props = extract_props("Mara read the letter.", lambda prompt: prompts.append(prompt) or next(responses))

    assert len(props) == 2
    assert "failed validation" in prompts[1] and too_long in prompts[1]


def test_extract_props_gives_up_after_its_retries():
    """
    Verifies that a prop list that keeps failing validation raises after PROP_RETRIES retries.
    """
    calls: list[str] = []
    with pytest.raises(ValidationError):
        extract_props("Mara read.", lambda prompt: calls.append(prompt) or "not json")
    assert len(calls) == PROP_RETRIES + 1
