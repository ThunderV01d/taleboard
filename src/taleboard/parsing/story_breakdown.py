"""
Top-level orchestration for turning a whole story into its cast, props and locations, and its scenes, each with an ordered list of shots.

Bridges cast_extraction, prop_extraction, location_extraction, scene_breakdown and shot_breakdown.
"""
from dataclasses import dataclass, field

from taleboard.parsing.bedrock_caller import MakeCaller, make_bedrock_caller
from taleboard.parsing.cast_extraction import extract_cast
from taleboard.parsing.contamination_judge import judge_cast, judge_locations, judge_props
from taleboard.parsing.llm_schemas import (
    LLMCastOutput, LLMCharacterDraft, LLMJudgeOutput, LLMLocationDraft, LLMLocationsOutput, LLMPropDraft, LLMPropsOutput,
    LLMSceneDraft, LLMShotDraft, build_paragraph_output_model, build_scenes_output_model,
)
from taleboard.parsing.location_extraction import extract_locations
from taleboard.parsing.prop_extraction import extract_props
from taleboard.parsing.scene_breakdown import break_into_scenes
from taleboard.parsing.shot_breakdown import ShotResult, get_shots_for_paragraph


@dataclass
class SceneBreakdown:
    """
    One scene of the story, with its shots.

    Attributes:
        scene: LLMSceneDraft - The scene (its location, time of day, atmosphere, name and description).
        paragraphs: list[int] - Indices of the story's paragraphs it covers, in order.
        shots: list[tuple[int,ShotResult]] - Its shots in story order, each with the index of the paragraph it comes from. Defaults to [].
    """
    scene: LLMSceneDraft
    paragraphs: list[int]
    shots: list[tuple[int, ShotResult]] = field(default_factory=list)


@dataclass
class StoryBreakdown:
    """
    Dataclass holding information about the story breakdown -- everything as the LLM drafted it (and the judge checked it), before it becomes a project.

    Attributes:
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.
        props: dict[str,LLMPropDraft] - Mapping between prop IDs and LLM prop drafts, in story order.
        locations: dict[str,LLMLocationDraft] - Mapping between location IDs and LLM location drafts, in story order.
        scenes: list[SceneBreakdown] - The scenes, with their shots, in story order.
    """
    cast: dict[str, LLMCharacterDraft]
    props: dict[str, LLMPropDraft]
    locations: dict[str, LLMLocationDraft]
    scenes: list[SceneBreakdown]


def split_paragraphs(story_text: str) -> list[str]:
    """
    Splits a story into an ordered sequence of paragraphs.

    Paragraphs are separated by one or more blank lines.

    Arguments:
        story_text: str - Story (in plain text).

    Returns:
        list[str] - List of paragraphs (in plain text).
    """
    return [p.strip() for p in story_text.split("\n\n") if p.strip()]


def break_down_story(story_text: str, make_caller: MakeCaller = make_bedrock_caller) -> StoryBreakdown:
    """
    Breaks a story down into scenes and shots, complete with a cast, props and locations.

    Extracts the cast, the props and the locations once (props before locations, so the places leave them out), splits the paragraphs into scenes, then breaks each scene's paragraphs into shots in order -- passing each paragraph the scene's last shot so far, for continuity. A scene's first paragraph starts afresh.

    A contamination judge checks the cast's and the props' descriptions and the locations' descriptions and views once, and each paragraph's details and actions, rewriting any text that would be drawn into the wrong image.

    Arguments:
        story_text: str - Story (in plain text).
        make_caller: MakeCaller - LLM caller builder function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        StoryBreakdown - Everything the story was broken down into.
    """
    paragraphs = split_paragraphs(story_text)
    call_judge = make_caller(LLMJudgeOutput)
    cast = judge_cast(extract_cast(story_text, make_caller(LLMCastOutput)), call_judge)
    props = judge_props(extract_props(story_text, make_caller(LLMPropsOutput)), cast, call_judge)
    locations = judge_locations(extract_locations(story_text, make_caller(LLMLocationsOutput), props), cast, call_judge, props)

    scenes = break_into_scenes(paragraphs, locations, make_caller(build_scenes_output_model(list(locations))))
    call_llm = make_caller(build_paragraph_output_model(list(cast), list(props) or None))

    breakdown = []
    for scene, paragraph_indices in scenes:
        scene_breakdown = SceneBreakdown(scene=scene, paragraphs=paragraph_indices)
        previous_shot: LLMShotDraft | None = None  # Each scene starts afresh
        for index in paragraph_indices:
            results = get_shots_for_paragraph(
                paragraphs[index], cast, previous_shot, call_llm, call_judge, props, scene, locations[scene.location_id],
            )
            scene_breakdown.shots.extend((index, result) for result in results)
            if results:
                previous_shot = results[-1].shot
        breakdown.append(scene_breakdown)
    return StoryBreakdown(cast=cast, props=props, locations=locations, scenes=breakdown)
