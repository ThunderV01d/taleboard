"""
Unit tests for location_extraction.

Covers location ID assignment, the empty-story guard, retries and conversion to domain locations. No LLM calls are made.
"""
import json

import pytest
from pydantic import ValidationError

from taleboard.parsing.llm_schemas import LLMLocationDraft
from taleboard.parsing.location_extraction import LOCATION_RETRIES, extract_locations, to_domain_location
from taleboard.parsing.prompts import LOCATION_EXTRACTION_INSTRUCTIONS

LOCATIONS_RESPONSE = json.dumps({"locations": [
    {"name": "The Harbourmaster's Office", "description": "a small wood-panelled office with a desk and a telephone"},
    {"name": "Lamp Room", "description": "a round stone room around a huge brass lamp"},
]})


def test_extract_locations_gives_each_location_an_id_in_story_order():
    """
    Verifies that each location gets a slugified ID from its name, in the order the model listed them, and that the story is in the prompt.
    """
    prompts: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns two locations.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Location extraction response (JSON).
        """
        prompts.append(prompt)
        return LOCATIONS_RESPONSE

    locations = extract_locations("Brandt climbed to the lamp room.", fake_call_llm)

    assert list(locations) == ["the_harbourmaster_s_office", "lamp_room"]
    assert prompts[0].startswith(LOCATION_EXTRACTION_INSTRUCTIONS) and prompts[0].endswith("Brandt climbed to the lamp room.")


@pytest.mark.parametrize("story", ["", "   \n\n "])
def test_extract_locations_rejects_an_empty_story_before_calling_the_llm(story):
    """
    Verifies that an empty story raises a ValueError before any (paid) LLM call is made.

    Arguments:
        story: str - An empty or whitespace-only story.
    """
    calls: list[str] = []
    with pytest.raises(ValueError, match="empty"):
        extract_locations(story, lambda prompt: calls.append(prompt) or LOCATIONS_RESPONSE)
    assert calls == []


def test_extract_locations_retries_an_empty_location_list_with_the_error():
    """
    Verifies that a response with no locations fails validation and is sent back once, with the error, before being accepted.
    """
    responses = iter([json.dumps({"locations": []}), LOCATIONS_RESPONSE])
    prompts: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns no locations, then two.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        prompts.append(prompt)
        return next(responses)

    locations = extract_locations("Brandt climbed.", fake_call_llm)

    assert len(locations) == 2
    assert "at least one location" in prompts[1] and '{"locations": []}' in prompts[1]


def test_extract_locations_gives_up_after_its_retries():
    """
    Verifies that a location list that keeps failing validation raises after LOCATION_RETRIES retries.
    """
    calls: list[str] = []
    with pytest.raises(ValidationError):
        extract_locations("Brandt climbed.", lambda prompt: calls.append(prompt) or json.dumps({"locations": []}))
    assert len(calls) == LOCATION_RETRIES + 1


def test_to_domain_location_maps_fields_with_no_master_plate_yet():
    """
    Verifies that a location draft converts to a domain Location with the same name and description, and no master plate.
    """
    location = to_domain_location(LLMLocationDraft(name="Lamp Room", description="a round stone room"))

    assert (location.name, location.description, location.master_plate) == ("Lamp Room", "a round stone room", None)
