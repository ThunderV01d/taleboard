"""
Unit tests for story_breakdown.

Uses a fake LLM caller builder, so no LLM calls are made.

Attributes:
    STORY: str - Three-paragraph story, with extra blank lines between the last two paragraphs.
    CAST_RESPONSE: str - Fake cast extraction response (JSON) with two characters, one of whom has an alias.
    PROPS_RESPONSE: str - Fake prop extraction response (JSON) with one prop.
    LOCATIONS_RESPONSE: str - Fake location extraction response (JSON) with two locations.
    SCENES_RESPONSE: str - Fake scenes pass response (JSON): paragraphs 0-1 on the street, paragraph 2 in the park.
    NOTHING_FLAGGED: str - Fake contamination judge response (JSON) that flags nothing.
"""
import json

import pytest

from taleboard.parsing.llm_schemas import LLMCastOutput, LLMJudgeOutput, LLMLocationsOutput, LLMPropsOutput, LLMScenesOutput
from taleboard.parsing.story_breakdown import break_down_story, split_paragraphs

STORY = "Alice waved.\n\nBob waved back.\n\n\n\nThey walked off together."

CAST_RESPONSE = json.dumps({"characters": [
    {"name": "Alice", "description": "A woman in a green coat.", "aliases": []},
    {"name": "Bob", "description": "A tall bearded man.", "aliases": ["the tall man"]},
]})

PROPS_RESPONSE = json.dumps({"props": [{"name": "Umbrella", "description": "a black folding umbrella"}]})

_VIEWS = {"north": "the road ahead", "east": "a row of shops", "south": "the road behind", "west": "a park railing"}

LOCATIONS_RESPONSE = json.dumps({"locations": [
    {"name": "Street", "setting": "exterior", "features": [], "description": "a quiet street corner with a lamppost", "views": _VIEWS},
    {"name": "Park", "setting": "exterior", "features": [], "description": "a small park with a pond", "views": _VIEWS},
]})

SCENES_RESPONSE = json.dumps({"scenes": [
    {"first_paragraph": 0, "location_id": "street", "time_of_day": "dusk", "atmosphere": "rainy", "name": "On the street", "description": "They meet."},
    {"first_paragraph": 2, "location_id": "park", "time_of_day": "dusk", "atmosphere": "clear", "name": "In the park", "description": "They walk."},
]})

NOTHING_FLAGGED = json.dumps({"texts": []})


def _shot_response(character_id: str, action: str) -> str:
    """
    Builds a fake shot breakdown response holding a single one-character shot, with Alice's umbrella in it.

    Arguments:
        character_id: str - Character ID of the shot's only region.
        action: str - Action of the region (also used as the shot description).

    Returns:
        str - Shot breakdown response (JSON).
    """
    return json.dumps({"shots": [{
        "description": action, "facing": "north", "details": "", "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
        "regions": [{"character_id": character_id, "position": "mid_center", "size": "medium", "orientation": "towards_camera", "action": action}],
        "props": [{"prop_id": "umbrella", "position": "mid_left", "size": "small", "orientation": "towards_camera", "held_by": character_id}],
    }]})


def _fake_make_caller(prompts: list[str], others: list[str] | None = None):
    """
    Builds a fake LLM caller builder, matching the MakeCaller signature.

    The cast schema is answered with CAST_RESPONSE, and each paragraph call with the next one-shot response; their prompts go to `prompts`. Prop and location extraction, the scenes pass and the contamination judge are answered with canned responses ("nothing flagged", for the judge), and their prompts go to `others` instead.

    Arguments:
        prompts: list[str] - List that every cast and paragraph prompt sent to the fake LLM is appended to.
        others: list[str] - List that every other prompt is appended to. Defaults to None (not recorded).

    Returns:
        MakeCaller - Fake LLM caller builder function.
    """
    shot_responses = iter([_shot_response("alice", "waving"), _shot_response("bob", "waving back"), _shot_response("alice", "walking")])

    def make_caller(schema_model):
        def call_llm(prompt: str) -> str:
            if issubclass(schema_model, LLMScenesOutput):
                canned = SCENES_RESPONSE
            else:
                canned = {LLMJudgeOutput: NOTHING_FLAGGED, LLMPropsOutput: PROPS_RESPONSE, LLMLocationsOutput: LOCATIONS_RESPONSE}.get(schema_model)
            if canned is not None:
                if others is not None:
                    others.append(prompt)
                return canned
            prompts.append(prompt)
            return CAST_RESPONSE if schema_model is LLMCastOutput else next(shot_responses)
        return call_llm
    return make_caller


def test_split_paragraphs_ignores_extra_blank_lines_and_whitespace():
    """
    Verifies that runs of blank lines between paragraphs don't produce empty paragraphs.
    """
    assert split_paragraphs(STORY) == ["Alice waved.", "Bob waved back.", "They walked off together."]


def test_break_down_story_groups_shots_into_their_scenes_with_paragraph_indices():
    """
    Verifies that each scene gets the shots of its own paragraphs, in story order, each tagged with its paragraph's index.
    """
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert [(s.scene.location_id, s.paragraphs) for s in breakdown.scenes] == [("street", [0, 1]), ("park", [2])]
    assert [[(index, result.shot.regions[0].action) for index, result in s.shots] for s in breakdown.scenes] == [
        [(0, "waving"), (1, "waving back")], [(2, "walking")],
    ]


def test_each_paragraph_is_broken_down_in_its_scene_continuing_from_the_scenes_last_shot():
    """
    Verifies that a paragraph's prompt has its scene and location, and the previous shot only within the same scene -- a new scene starts afresh.
    """
    prompts: list[str] = []
    break_down_story(STORY, make_caller=_fake_make_caller(prompts))

    paragraph_prompts = prompts[1:]  # prompts[0] is cast extraction
    assert "SCENE: On the street" in paragraph_prompts[0] and "LOCATION: Street (exterior)" in paragraph_prompts[0]
    assert "Previous shot: none" in paragraph_prompts[0]
    assert '"action":"waving"' in paragraph_prompts[1]
    assert "SCENE: In the park" in paragraph_prompts[2] and "Previous shot: none" in paragraph_prompts[2]


def test_break_down_story_keeps_the_drafts_and_the_props_in_shots():
    """
    Verifies that the breakdown keeps the cast (with aliases), the locations (with views) and the props -- and that a shot's held prop comes through.
    """
    breakdown = break_down_story(STORY, make_caller=_fake_make_caller([]))

    assert breakdown.cast["bob"].aliases == ["the tall man"]
    assert breakdown.locations["park"].views.east == "a row of shops"
    assert breakdown.props["umbrella"].description == "a black folding umbrella"
    [(_, result)] = breakdown.scenes[1].shots
    assert [(p.prop_id, p.held_by) for p in result.shot.props] == [("umbrella", "alice")]


def test_break_down_story_extracts_the_props_before_the_locations_and_tells_them_apart():
    """
    Verifies that the props are extracted, judged as objects, and listed to the location extraction and the location judge -- so no place draws them.
    """
    others: list[str] = []
    break_down_story(STORY, make_caller=_fake_make_caller([], others))

    [location_prompt] = [p for p in others if p.startswith("You are listing the locations")]
    assert "- Umbrella: a black folding umbrella" in location_prompt
    assert any("kind: prop, object: Umbrella" in p for p in others)
    assert any("kind: view, place: Street" in p and "- Umbrella:" in p for p in others)


def test_the_scenes_pass_sees_every_paragraph_and_location():
    """
    Verifies that the scenes pass is given the numbered paragraphs and the extracted locations.
    """
    others: list[str] = []
    break_down_story(STORY, make_caller=_fake_make_caller([], others))

    [scenes_prompt] = [p for p in others if p.startswith("You are splitting a short story into scenes")]
    assert "[2] They walked off together." in scenes_prompt and "- id: park, name: Park (exterior)" in scenes_prompt


def test_break_down_story_rejects_an_empty_story_before_any_llm_call():
    """
    Verifies that an empty story raises a ValueError before any (paid) LLM call is made.
    """
    prompts: list[str] = []
    others: list[str] = []
    with pytest.raises(ValueError, match="empty"):
        break_down_story("  \n\n ", make_caller=_fake_make_caller(prompts, others))
    assert prompts == [] and others == []
