"""
Unit tests for scene_breakdown.

Covers splitting paragraphs into scenes, what the prompt lists, retries, and the one-scene fallback. No LLM calls are made.
"""
import json

import pytest

from taleboard.parsing.llm_schemas import LLMLocationDraft
from taleboard.parsing.prompts import SCENE_BREAKDOWN_INSTRUCTIONS
from taleboard.parsing.scene_breakdown import SCENE_RETRIES, break_into_scenes

PARAGRAPHS = ["Mara climbed the stairs.", "She lit the lamp.", "Below, Tomas waited.", "Mara came down."]

_VIEWS = {"north": "a", "east": "b", "south": "c", "west": "d"}


def _locations() -> dict[str, LLMLocationDraft]:
    return {
        "lamp_room": LLMLocationDraft(name="Lamp Room", setting="interior", description="a round stone room", views=_VIEWS),
        "quay": LLMLocationDraft(name="Quay", setting="exterior", description="a stone quay", views=_VIEWS),
    }


def _scene(first: int, location_id: str = "lamp_room", time: str = "night", weather: str = "stormy") -> dict:
    return {"first_paragraph": first, "location_id": location_id, "time_of_day": time, "atmosphere": weather, "name": f"Scene {first}", "description": "..."}


def _response(*scenes: dict) -> str:
    return json.dumps({"scenes": list(scenes)})


def test_each_scene_runs_until_the_next_one_starts():
    """
    Verifies that every paragraph lands in exactly one scene, in order, with each scene's location and lighting kept.
    """
    scenes = break_into_scenes(PARAGRAPHS, _locations(), lambda prompt: _response(_scene(0), _scene(2, "quay", "night", "rainy")))

    assert [(scene.location_id, paragraphs) for scene, paragraphs in scenes] == [("lamp_room", [0, 1]), ("quay", [2, 3])]
    assert (scenes[1][0].time_of_day, scenes[1][0].atmosphere) == ("night", "rainy")


def test_the_prompt_numbers_the_paragraphs_and_lists_the_locations():
    """
    Verifies that the model sees each paragraph's number and each location's ID and setting.
    """
    prompts: list[str] = []

    break_into_scenes(PARAGRAPHS, _locations(), lambda prompt: prompts.append(prompt) or _response(_scene(0)))

    assert prompts[0].startswith(SCENE_BREAKDOWN_INSTRUCTIONS)
    assert "[0] Mara climbed the stairs." in prompts[0] and "[3] Mara came down." in prompts[0]
    assert "- id: quay, name: Quay (exterior), description: a stone quay" in prompts[0]


@pytest.mark.parametrize("bad, problem", [
    (_response(_scene(1)), "start at paragraph 0"),
    (_response(_scene(-1)), "start at paragraph 0"),
    (_response(_scene(0), _scene(2), _scene(2)), "after the one before it"),
    (_response(_scene(0), _scene(7)), "paragraphs 0 to 3"),
    (_response(_scene(0, "lighthouse")), "location_id"),
])
def test_a_bad_split_is_sent_back_with_the_problem(bad, problem):
    """
    Verifies that a split that doesn't start at 0 (or starts before it), goes backwards, runs past the story or names an unknown location is sent back once, saying what's wrong.

    Arguments:
        bad: str - The model's first (bad) response.
        problem: str - Part of what the retry prompt should say.
    """
    responses = iter([bad, _response(_scene(0))])
    prompts: list[str] = []

    scenes = break_into_scenes(PARAGRAPHS, _locations(), lambda prompt: prompts.append(prompt) or next(responses))

    assert problem in prompts[1]
    assert [paragraphs for _, paragraphs in scenes] == [[0, 1, 2, 3]]


def test_a_split_that_keeps_failing_becomes_one_scene_for_the_whole_story():
    """
    Verifies the fallback: after its retries, the story is one scene in the first location, by day in clear weather.
    """
    calls: list[str] = []

    [(scene, paragraphs)] = break_into_scenes(PARAGRAPHS, _locations(), lambda prompt: calls.append(prompt) or "not json")

    assert len(calls) == SCENE_RETRIES + 1
    assert (scene.location_id, scene.time_of_day, scene.atmosphere, paragraphs) == ("lamp_room", "day", "clear", [0, 1, 2, 3])
