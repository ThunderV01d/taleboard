"""
Unit tests for shot_breakdown, plus the alias-related parts of prompts and llm_schemas.

Uses fake LLM call functions, so no LLM calls are made.

Attributes:
    INVALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that fails validation, as its character ID is not in the cast.
    VALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that passes validation.
"""
import json

from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, build_shot_draft_model
from taleboard.parsing.shot_breakdown import find_cast_mentions, get_shots_for_paragraph, ShotResult, to_domain_shot


def _make_cast() -> dict[str, LLMCharacterDraft]:
    """
    Builds a two-character cast (Alice and Bob).

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of character IDs ("alice", "bob") to character drafts.
    """
    drafts = [
        LLMCharacterDraft(name="Alice", description="..."),
        LLMCharacterDraft(name="Bob", description="..."),
    ]
    return assign_ids(drafts)


def _make_locations() -> dict[str, LLMLocationDraft]:
    """
    Builds two locations (a street and a harbour).

    Returns:
        dict[str,LLMLocationDraft] - Mapping of location IDs ("street", "harbour") to location drafts.
    """
    return {
        "street": LLMLocationDraft(name="Street", description="a quiet street corner with a lamppost"),
        "harbour": LLMLocationDraft(name="Harbour", description="a stone harbour wall with moored boats"),
    }


# Character ID "carol" is not in the cast built by _make_cast(), so this fails validation against the cast-constrained schema
INVALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at a stranger.",
            "location_id": "street",
            "details": "",
            "shot_size": "medium",
            "angle": "eye_level",
            "duration_s": 2.0,
            "regions": [
                {
                    "character_id": "carol",
                    "position": "mid_left",
                    "size": "medium",
                    "orientation": "towards_camera",
                    "action": "waving",
                }
            ],
        }
    ]
})

VALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at Bob.",
            "location_id": "street",
            "details": "",
            "shot_size": "medium",
            "angle": "eye_level",
            "duration_s": 2.0,
            "regions": [
                {
                    "character_id": "alice",
                    "position": "mid_left",
                    "size": "medium",
                    "orientation": "towards_camera",
                    "action": "waving",
                }
            ],
        }
    ]
})


def test_get_shots_for_paragraph_retries_once_and_succeeds():
    """
    Verifies that a shot failing validation is retried, and accepted without a review flag once the retry passes.
    """
    cast = _make_cast()
    responses = [INVALID_SHOT_RESPONSE, VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns an invalid response, then a valid one.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 2  # Initial call + one retry
    assert len(results) == 1
    assert results[0].needs_review is False
    assert results[0].shot.regions[0].character_id == "alice"


def test_get_shots_for_paragraph_falls_back_after_max_retries():
    """
    Verifies that a shot still failing after every permitted retry is replaced by a flagged fallback shot with no regions.
    """
    cast = _make_cast()
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and always returns an invalid response.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Invalid shot breakdown response (JSON).
        """
        calls.append(prompt)
        return INVALID_SHOT_RESPONSE  # Always invalid, never recovers

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 3  # Initial call + MAX_RETRIES (2) retries
    assert len(results) == 1
    assert results[0].needs_review is True
    assert results[0].shot.regions == []

def test_get_shots_for_paragraph_fallback_shot_is_placed_in_a_known_location():
    """
    Verifies that the fallback shot is placed in the previous shot's location -- or, for the first shot, the story's first location -- as every shot needs one to render a background.
    """
    cast = _make_cast()

    def fake_call_llm(prompt: str) -> str:
        """
        Always returns an invalid response.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Invalid shot breakdown response (JSON).
        """
        return INVALID_SHOT_RESPONSE

    locations = _make_locations()
    previous_shot = build_shot_draft_model(["alice", "bob"]).model_validate({**json.loads(VALID_SHOT_RESPONSE)["shots"][0], "location_id": "harbour"})

    first_results = get_shots_for_paragraph(paragraph="Alice waves.", cast=cast, previous_shot=None, call_llm=fake_call_llm, locations=locations)
    later_results = get_shots_for_paragraph(paragraph="Alice waves.", cast=cast, previous_shot=previous_shot, call_llm=fake_call_llm, locations=locations)

    assert first_results[0].shot.location_id == "street"
    assert later_results[0].shot.location_id == "harbour"

def test_get_shots_for_paragraph_handles_unparseable_response():
    """
    Verifies that a response that isn't JSON at all ends in a flagged fallback shot, not a crash.
    """
    cast = _make_cast()

    def fake_call_llm(prompt: str) -> str:
        """
        Always returns text that is not JSON.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Unparseable response.
        """
        return "this is not json at all"

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(results) == 1
    assert results[0].needs_review is True

def test_to_domain_shot_maps_fields():
    """
    Verifies that every field of a validated shot draft carries over to the domain Shot, along with the paragraph index.
    """
    ShotModel = build_shot_draft_model(["alice", "bob"])
    draft = ShotModel.model_validate({
        "description": "Alice waves at Bob.",
        "location_id": "street",
        "details": "",
        "shot_size": "medium",
        "angle": "eye_level",
        "duration_s": 2.0,
        "regions": [
            {
                "character_id": "alice",
                "position": "mid_left",
                "size": "medium",
                "orientation": "towards_camera",
                "action": "waving",
            }
        ],
    })
    result = ShotResult(shot=draft, needs_review=False)

    shot = to_domain_shot(result, paragraph_index=3)

    assert shot.description == "Alice waves at Bob."
    assert shot.location_id == "street"
    assert shot.details == ""
    assert shot.paragraph_index == 3
    assert shot.needs_review is False
    assert len(shot.regions) == 1
    assert shot.regions[0].character_id == "alice"
    assert shot.regions[0].action == "waving"

def test_to_domain_shot_carries_needs_review_flag():
    """
    Verifies that the review flag on a ShotResult carries over to the domain Shot.
    """
    ShotModel = build_shot_draft_model(["alice"])
    draft = ShotModel.model_validate({
        "description": "fallback",
        "location_id": "street",
        "details": "",
        "shot_size": "medium",
        "angle": "eye_level",
        "duration_s": 2.0,
        "regions": [],
    })
    result = ShotResult(shot=draft, needs_review=True)

    shot = to_domain_shot(result, paragraph_index=0)

    assert shot.needs_review is True
    assert shot.regions == []

def test_breakdown_prompt_lists_each_cast_members_aliases():
    """
    Verifies that the shot breakdown prompt lists each cast member's aliases next to their ID.

    This is what lets the LLM resolve a reference like "the harbourmaster" to the right character.
    """
    from taleboard.parsing.prompts import build_shot_breakdown_prompt
    cast = {"elias_brandt": LLMCharacterDraft(name="Elias Brandt", description="A bearded old man.",
                                              aliases=["Brandt", "the harbourmaster"])}

    prompt = build_shot_breakdown_prompt("The harbourmaster frowned.", cast, previous_shot=None)

    assert "id: elias_brandt" in prompt
    assert "also called: Brandt, the harbourmaster" in prompt


def test_breakdown_prompt_lists_each_location_with_its_description():
    """
    Verifies that the shot breakdown prompt lists each location's ID and description, so the LLM can pick one by ID.
    """
    from taleboard.parsing.prompts import build_shot_breakdown_prompt

    prompt = build_shot_breakdown_prompt("Alice waves.", _make_cast(), None, _make_locations())

    assert "id: street, name: Street, description: a quiet street corner with a lamppost" in prompt
    assert "id: harbour" in prompt


def test_a_location_id_outside_the_known_locations_is_retried():
    """
    Verifies that a shot placed in a location that isn't in the list fails validation and is sent back for a retry.
    """
    unknown = json.loads(VALID_SHOT_RESPONSE)
    unknown["shots"][0]["location_id"] = "lighthouse"
    responses = [json.dumps(unknown), VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns a shot in an unknown location, then a valid one.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(paragraph="Alice waves.", cast=_make_cast(), previous_shot=None, call_llm=fake_call_llm, locations=_make_locations())

    assert len(calls) == 2
    assert "lighthouse" in calls[1]
    assert results[0].shot.location_id == "street"
    assert results[0].needs_review is False


def test_aliases_are_required_for_the_llm_but_optional_in_python():
    """
    Verifies that 'aliases' is a required field in the schema sent to the LLM, while still defaulting to [] in Python.
    """
    from taleboard.parsing.llm_schemas import LLMCastOutput
    schema = LLMCastOutput.model_json_schema()
    assert "aliases" in schema["$defs"]["LLMCharacterDraft"]["required"]
    assert LLMCharacterDraft(name="Alice", description="...").aliases == []

def test_find_cast_mentions_catches_names_possessives_and_aliases_but_not_common_words():
    """
    Verifies that details naming a cast member are caught by name (possessive included) or multi-word alias, and that a single-word name doesn't match an ordinary lowercase word.
    """
    cast = {
        "eleanor": LLMCharacterDraft(name="Eleanor", description="...", aliases=["the girl"]),
        "rose": LLMCharacterDraft(name="Rose", description="..."),
    }

    assert find_cast_mentions("golden light in Eleanor's hands", cast) == ["Eleanor"]
    assert find_cast_mentions("The girl's face is pressed against the glass", cast) == ["the girl"]
    assert find_cast_mentions("a garden of rose bushes", cast) == []
    assert find_cast_mentions("an empty hallway", cast) == []


def test_details_naming_a_cast_member_are_retried_with_the_reason():
    """
    Verifies that a schema-valid shot whose details name a cast member is sent back for a retry, with an error naming who was mentioned.
    """
    cast = _make_cast()
    leaky = json.loads(VALID_SHOT_RESPONSE)
    leaky["shots"][0]["details"] = "rain falling where Alice stands waiting"
    responses = [json.dumps(leaky), VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns a shot whose details name Alice, then a clean one.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(paragraph="Alice waits.", cast=cast, previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 2
    assert "'Alice'" in calls[1]  # The retry prompt says who was mentioned
    assert results[0].needs_review is False
    assert results[0].shot.details == ""

def test_an_action_naming_another_cast_member_is_retried_but_a_character_may_name_themselves():
    """
    Verifies that a region whose action names a different cast member is sent back for a retry, while one naming its own character passes.
    """
    cast = _make_cast()
    leaky = json.loads(VALID_SHOT_RESPONSE)
    leaky["shots"][0]["regions"][0]["action"] = "waving at Bob"
    clean = json.loads(VALID_SHOT_RESPONSE)
    clean["shots"][0]["regions"][0]["action"] = "waving, Alice's hand raised high"
    responses = [json.dumps(leaky), json.dumps(clean)]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns an action naming Bob, then one naming only Alice herself.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(paragraph="Alice waves.", cast=cast, previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 2
    assert "'Bob'" in calls[1]
    assert results[0].needs_review is False
    assert results[0].shot.regions[0].action == "waving, Alice's hand raised high"


def test_a_character_given_two_regions_keeps_only_the_first_without_a_retry():
    """
    Verifies that a duplicate region for the same character is dropped (keeping the first), without another LLM call or a review flag.
    """
    duplicated = json.loads(VALID_SHOT_RESPONSE)
    first = duplicated["shots"][0]["regions"][0]
    duplicated["shots"][0]["regions"].append({**first, "position": "mid_right", "action": "waving again"})
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns a shot with Alice in it twice.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Shot breakdown response (JSON).
        """
        calls.append(prompt)
        return json.dumps(duplicated)

    results = get_shots_for_paragraph(paragraph="Alice waves.", cast=_make_cast(), previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 1
    assert [(r.character_id, r.action) for r in results[0].shot.regions] == [("alice", "waving")]
    assert results[0].needs_review is False
