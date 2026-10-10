"""
Unit tests for story_breakdown.

Uses a fake LLM caller builder, so no LLM calls are made.

Attributes:
    STORY: str - Three-paragraph story, with extra blank lines between the last two paragraphs.
    CAST_RESPONSE: str - Fake cast extraction response (JSON) with two characters, one of whom has an alias.
"""
import json

import pytest

from taleboard.parsing.llm_schemas import LLMCastOutput
from taleboard.parsing.story_breakdown import break_down_story, split_paragraphs

STORY = "Alice waved.\n\nBob waved back.\n\n\n\nThey walked off together."

CAST_RESPONSE = json.dumps({"characters": [
    {"name": "Alice", "description": "A woman in a green coat.", "aliases": []},
    {"name": "Bob", "description": "A tall bearded man.", "aliases": ["the tall man"]},
]})


def _shot_response(character_id: str, action: str) -> str:
    """
    Builds a fake shot breakdown response holding a single one-character shot.

    Arguments:
        character_id: str - Character ID of the shot's only region.
        action: str - Action of the region (also used as the shot description).

    Returns:
        str - Shot breakdown response (JSON).
    """
    return json.dumps({"shots": [{
        "description": action, "setting": "a quiet street", "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
        "regions": [{"character_id": character_id, "position": "mid_center", "size": "medium",
                     "orientation": "towards_camera", "action": action}],
    }]})


def _fake_make_caller(prompts: list[str]):
    """
    Builds a fake LLM caller builder, matching the MakeCaller signature.

    The cast schema is answered with CAST_RESPONSE, and each paragraph call with the next one-shot response. Every prompt is recorded.

    Arguments:
        prompts: list[str] - List that every prompt sent to the fake LLM is appended to.

    Returns:
        MakeCaller - Fake LLM caller builder function.
    """
    shot_responses = iter([_shot_response("alice", "waving"), _shot_response("bob", "waving back"),
                           _shot_response("alice", "walking")])

    def make_caller(schema_model):
        """
        Returns a fake LLM call function for the given output schema.

        Arguments:
            schema_model: type[BaseModel] - Output schema.

        Returns:
            CallLLM - Fake LLM call function.
        """
        def call_llm(prompt: str) -> str:
            """
            Records the prompt and returns the canned response for this schema.

            Arguments:
                prompt: str - Prompt sent to the fake LLM.

            Returns:
                str - Canned response (JSON).
            """
            prompts.append(prompt)
            return CAST_RESPONSE if schema_model is LLMCastOutput else next(shot_responses)
        return call_llm
    return make_caller


def test_split_paragraphs_ignores_extra_blank_lines_and_whitespace():
    """
    Verifies that runs of blank lines between paragraphs don't produce empty paragraphs.
    """
    assert split_paragraphs(STORY) == ["Alice waved.", "Bob waved back.", "They walked off together."]


def test_break_down_story_returns_shots_in_story_order_with_paragraph_indices():
    """
    Verifies that shots come back in story order, each tagged with the index of its paragraph.
    """
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert [s.paragraph_index for s in breakdown.shots] == [0, 1, 2]
    assert [s.regions[0].action for s in breakdown.shots] == ["waving", "waving back", "walking"]


def test_break_down_story_chains_each_paragraph_on_the_previous_shot():
    """
    Verifies that each paragraph's prompt includes the last shot of the paragraph before it.

    The first paragraph has no previous shot.
    """
    prompts: list[str] = []
    break_down_story(STORY, make_caller=_fake_make_caller(prompts))

    paragraph_prompts = prompts[1:]  # prompts[0] is cast extraction
    assert "Previous shot: none" in paragraph_prompts[0]
    assert '"action":"waving"' in paragraph_prompts[1]
    assert '"action":"waving back"' in paragraph_prompts[2]


def test_break_dwon_story_converts_the_cast_to_domain_characters():
    """
    Verifies that the extracted cast is converted to domain characters, while the drafts (and their aliases) are kept.
    """
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert set(breakdown.characters) == {"alice", "bob"}
    assert breakdown.characters["bob"].description == "A tall bearded man."
    assert breakdown.cast["bob"].aliases == ["the tall man"]

def test_break_down_story_rejects_an_empty_story_before_any_llm_call():
    """
    Verifies that an empty story raises a ValueError before any (paid) LLM call is made.
    """
    prompts: list[str] = []
    with pytest.raises(ValueError, match="empty"):
        break_down_story("  \n\n ", make_caller=_fake_make_caller(prompts))
    assert prompts == []
