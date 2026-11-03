"""
Unit tests for location_extraction.

Covers location ID assignment, settings and views, leaving the story's props out, the empty-story guard, retries and conversion to domain locations. No LLM calls are made.
"""
import json

import pytest
from pydantic import ValidationError

from taleboard.parsing.llm_schemas import LLMLocationDraft, LLMPropDraft
from taleboard.parsing.location_extraction import LOCATION_RETRIES, extract_locations, unplaced_features
from taleboard.parsing.prompts import LOCATION_EXTRACTION_INSTRUCTIONS

VIEWS = {
    "north": "the back wall: a two-pane window above a desk",
    "east": "a side wall: a filing cabinet",
    "south": "the front wall: a door",
    "west": "the other side wall, plain and mostly bare",
}

LOCATIONS_RESPONSE = json.dumps({"locations": [
    {"name": "The Harbourmaster's Office", "setting": "interior", "description": "a small wood-panelled office", "views": VIEWS},
    {"name": "Lamp Room", "setting": "interior", "description": "a round stone room", "views": VIEWS},
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

def test_each_location_has_a_setting_and_a_view_for_every_side():
    """
    Verifies that a location keeps its setting and all four views.
    """
    office = extract_locations("Brandt waited.", lambda prompt: LOCATIONS_RESPONSE)["the_harbourmaster_s_office"]

    assert office.setting == "interior"
    assert office.views.model_dump() == VIEWS


def test_a_location_missing_a_view_is_sent_back():
    """
    Verifies that a location without a view for every side fails validation, and the retry asks for one.
    """
    partial = json.dumps({"locations": [{"name": "Quay", "setting": "exterior", "description": "a stone quay", "views": {"north": "the harbour"}}]})
    responses = iter([partial, LOCATIONS_RESPONSE])
    prompts: list[str] = []

    extract_locations("Brandt waited.", lambda prompt: prompts.append(prompt) or next(responses))

    assert "a view for every side" in prompts[1]


def test_the_location_prompt_lists_the_props_to_leave_out():
    """
    Verifies that the story's props are listed in the prompt (they're drawn separately), and "none" when there are none.
    """
    prompts: list[str] = []
    props = {"lantern": LLMPropDraft(name="Lantern", description="an old brass storm lantern")}

    extract_locations("Brandt lit the lantern.", lambda prompt: prompts.append(prompt) or LOCATIONS_RESPONSE, props)
    extract_locations("Brandt waited.", lambda prompt: prompts.append(prompt) or LOCATIONS_RESPONSE)

    assert "PROPS:\n- Lantern: an old brass storm lantern" in prompts[0]
    assert "PROPS:\nnone" in prompts[1]


def _lamp_room(views: dict, features: list[str]) -> dict:
    return {"name": "Lamp Room", "setting": "interior", "description": "a round stone room", "features": features, "views": views}


def test_a_feature_on_no_side_is_found_by_its_noun():
    """
    Verifies the check: a feature counts as placed when its last word (singular or plural) is in the description or a view.
    """
    location = LLMLocationDraft.model_validate(_lamp_room(
        {**VIEWS, "north": "the front of the room: a great lens on a brass pedestal"},
        ["a great lens on a pedestal", "spiral stairs", "a stone room", "a hook", "!"],
    ))

    assert unplaced_features(location) == ["spiral stairs", "a hook"]


def test_a_location_with_a_feature_on_no_side_is_sent_back_once_to_place_it():
    """
    Verifies that a listed feature missing from every view sends the list back, naming the feature -- and that a second miss keeps the location as it is, rather than failing.
    """
    missing = json.dumps({"locations": [_lamp_room(VIEWS, ["spiral stairs"])]})
    placed = json.dumps({"locations": [_lamp_room({**VIEWS, "south": "the back of the room: the top of the spiral stairs"}, ["spiral stairs"])]})
    prompts: list[str] = []
    responses = iter([missing, placed])

    locations = extract_locations("Mara climbed the spiral stairs.", lambda prompt: prompts.append(prompt) or next(responses))

    assert "spiral stairs" in locations["lamp_room"].views.south
    assert "- Lamp Room: spiral stairs" in prompts[1]

    calls: list[str] = []
    kept = extract_locations("Mara climbed.", lambda prompt: calls.append(prompt) or missing)
    assert len(calls) == LOCATION_RETRIES + 1 and kept["lamp_room"].views.south == VIEWS["south"]
