"""
Manages the scenes pass of the pipeline: splitting the story into scenes before any shot is drawn up.

A scene is a run of consecutive paragraphs in one location, at one time of day and in one atmosphere -- so every shot of it shares a location (and its plates) and the same lighting. The model gives each scene the number of its first paragraph; each runs until the next one starts, so every paragraph belongs to exactly one scene.

Attributes:
    SCENE_RETRIES: int - Number of times a scene list that fails validation (or doesn't split the paragraphs properly) is sent back to the model, before falling back to one scene for the whole story.
"""
import logging

from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.llm_schemas import LLMLocationDraft, LLMSceneDraft, build_scenes_output_model
from taleboard.parsing.prompts import build_scene_breakdown_prompt
from taleboard.schema.enums import Atmosphere, TimeOfDay

SCENE_RETRIES = 1

logger = logging.getLogger(__name__)


def break_into_scenes(paragraphs: list[str], locations: dict[str, LLMLocationDraft], call_llm: CallLLM) -> list[tuple[LLMSceneDraft, list[int]]]:
    """
    Splits the story's paragraphs into scenes.

    A response that fails validation, or doesn't start at paragraph 0 and go forward, is sent back with the problem; if it still fails, the whole story becomes one scene in the first location -- the user can split it in the editor.

    Arguments:
        paragraphs: list[str] - The story's paragraphs, in order. Must not be empty.
        locations: dict[str,LLMLocationDraft] - Mapping between location IDs and LLM location drafts. Must not be empty.
        call_llm: CallLLM - LLM caller function for build_scenes_output_model's schema.

    Returns:
        list[tuple[LLMSceneDraft,list[int]]] - Each scene, with the indices of its paragraphs, in story order.
    """
    ScenesOutput = build_scenes_output_model(list(locations))
    prompt = build_scene_breakdown_prompt(paragraphs, locations)
    for attempt in range(SCENE_RETRIES + 1):
        response_text = call_llm(prompt)
        try:
            scenes = ScenesOutput.model_validate_json(response_text).scenes
            problem = _split_problem(scenes, len(paragraphs))
        except ValidationError as e:
            problem = str(e)
        if problem is None:
            return _with_paragraphs(scenes, len(paragraphs))
        if attempt < SCENE_RETRIES:
            prompt = _build_scenes_retry_prompt(response_text, problem)
    logger.warning("Scenes pass failed, so the story is one scene: %s", problem)
    return [(_fallback_scene(next(iter(locations))), list(range(len(paragraphs))))]


def _split_problem(scenes: list[LLMSceneDraft], paragraph_count: int) -> str | None:
    """
    Says what's wrong with how scenes split the paragraphs, or None if nothing is.
    """
    starts = [scene.first_paragraph for scene in scenes]
    if starts[0] != 0:
        return f"The first scene must start at paragraph 0, not {starts[0]}."
    if any(later <= earlier for earlier, later in zip(starts, starts[1:])):
        return f"Each scene must start after the one before it, but they start at paragraphs {starts}."
    if starts[-1] >= paragraph_count:
        return f"The story has paragraphs 0 to {paragraph_count - 1}, but a scene starts at paragraph {starts[-1]}."
    return None


def _with_paragraphs(scenes: list[LLMSceneDraft], paragraph_count: int) -> list[tuple[LLMSceneDraft, list[int]]]:
    """
    Pairs each (validly split) scene with its paragraphs: from its first to the one before the next scene's first.
    """
    ends = [scene.first_paragraph for scene in scenes[1:]] + [paragraph_count]
    return [(scene, list(range(scene.first_paragraph, end))) for scene, end in zip(scenes, ends)]


def _build_scenes_retry_prompt(response_text: str, problem: str) -> str:
    """
    Builds the prompt for the LLM to fix a scene list.

    Arguments:
        response_text: str - The model's failing response.
        problem: str - What's wrong with it.

    Returns:
        str - Prompt for the LLM to retry the scenes.
    """
    return (
        "The scene list you sent can't be used. Fix it and return the whole list again, in the same JSON shape, under a "
        "\"scenes\" key: the first scene starts at paragraph 0, and each scene starts after the one before it."
        f"\n\nScenes you sent:\n{response_text}\n\nProblem:\n{problem}"
    )


def _fallback_scene(location_id: str) -> LLMSceneDraft:
    """
    One scene for the whole story, used when the scenes pass fails -- by day, in clear weather, in the given location.
    """
    return LLMSceneDraft(
        first_paragraph=0, location_id=location_id, time_of_day=TimeOfDay.DAY, atmosphere=Atmosphere.CLEAR,
        name="The story", description="",
    )
