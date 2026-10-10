"""
Unit tests for shot_breakdown, plus the alias-related parts of prompts and llm_schemas.

Uses fake LLM call functions, so no LLM calls are made.

Attributes:
    INVALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that fails validation, as its character ID is not in the cast.
    VALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that passes validation.
"""
import json

from taleboard.parsing.cast_extraction import assign_char_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft, build_shot_draft_model
from taleboard.parsing.shot_breakdown import get_shots_for_paragraph, ShotResult, to_domain_shot


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
    return assign_char_ids(drafts)


# Character ID "carol" is not in the cast built by _make_cast(), so this fails validation against the cast-constrained schema
INVALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at a stranger.",
            "setting": "a quiet street corner",
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
            "setting": "a quiet street corner",
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

def test_get_shots_for_paragraph_fallback_shot_has_a_setting():
    """
    Verifies that the fallback shot still has a (placeholder) setting, as every shot needs one to render a background.
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

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert results[0].shot.setting  # Non-empty placeholder

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
        "setting": "a quiet street corner",
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
    assert shot.setting == "a quiet street corner"
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
        "setting": "unknown -- needs manual review",
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


def test_aliases_are_required_for_the_llm_but_optional_in_python():
    """
    Verifies that 'aliases' is a required field in the schema sent to the LLM, while still defaulting to [] in Python.
    """
    from taleboard.parsing.llm_schemas import LLMCastOutput
    schema = LLMCastOutput.model_json_schema()
    assert "aliases" in schema["$defs"]["LLMCharacterDraft"]["required"]
    assert LLMCharacterDraft(name="Alice", description="...").aliases == []
