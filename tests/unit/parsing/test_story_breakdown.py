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
    return json.dumps({"shots": [{
        "description": action, "setting": "a quiet street", "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
        "regions": [{"character_id": character_id, "position": "mid_center", "size": "medium",
                     "orientation": "towards_camera", "action": action}],
    }]})


def _fake_make_caller(prompts: list[str]):
    """Answers the cast schema with CAST_RESPONSE, and each paragraph call with a one-shot response, recording every prompt."""
    shot_responses = iter([_shot_response("alice", "waving"), _shot_response("bob", "waving back"),
                           _shot_response("alice", "walking")])

    def make_caller(schema_model):
        def call_llm(prompt: str) -> str:
            prompts.append(prompt)
            return CAST_RESPONSE if schema_model is LLMCastOutput else next(shot_responses)
        return call_llm
    return make_caller


def test_split_paragraphs_ignores_extra_blank_lines_and_whitespace():
    assert split_paragraphs(STORY) == ["Alice waved.", "Bob waved back.", "They walked off together."]


def test_break_down_story_returns_shots_in_story_order_with_paragraph_indices():
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert [s.paragraph_index for s in breakdown.shots] == [0, 1, 2]
    assert [s.regions[0].action for s in breakdown.shots] == ["waving", "waving back", "walking"]


def test_break_down_story_chains_each_paragraph_on_the_previous_shot():
    prompts: list[str] = []
    break_down_story(STORY, make_caller=_fake_make_caller(prompts))

    paragraph_prompts = prompts[1:]  # prompts[0] is cast extraction
    assert "Previous shot: none" in paragraph_prompts[0]
    assert '"action":"waving"' in paragraph_prompts[1]
    assert '"action":"waving back"' in paragraph_prompts[2]


def test_break_dwon_story_converts_the_cast_to_domain_characters():
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert set(breakdown.characters) == {"alice", "bob"}
    assert breakdown.characters["bob"].description == "A tall bearded man."
    assert breakdown.cast["bob"].aliases == ["the tall man"]

def test_break_down_story_rejects_an_empty_story_before_any_llm_call():
    prompts: list[str] = []
    with pytest.raises(ValueError, match="empty"):
        break_down_story("  \n\n ", make_caller=_fake_make_caller(prompts))
    assert prompts == []