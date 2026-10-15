"""
Top-level orchestration for turning a whole story into a cast and an ordered list of shots.

Bridges cast_extraction, location_extraction and shot_breakdown.
"""
from dataclasses import dataclass, field

from taleboard.parsing.bedrock_caller import MakeCaller, make_bedrock_caller
from taleboard.parsing.cast_extraction import extract_cast, to_domain_character
from taleboard.parsing.contamination_judge import judge_cast, judge_locations
from taleboard.parsing.llm_schemas import LLMCastOutput, LLMCharacterDraft, LLMJudgeOutput, LLMLocationsOutput, LLMShotDraft, build_paragraph_output_model
from taleboard.parsing.location_extraction import extract_locations, to_domain_location
from taleboard.parsing.shot_breakdown import get_shots_for_paragraph, to_domain_shot
from taleboard.schema.models import Character, Location, Shot

@dataclass
class StoryBreakdown:
    """
    Dataclass holding information about the story breakdown.
    
    Attributes:
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts. Unordered.
        characters: dict[str,Character] - Mapping between character IDs and domain characters.
        shots: list[Shot] - List of shots in story order.
        locations: dict[str,Location] - Mapping between location IDs and domain locations. Defaults to {}.
    """
    cast: dict[str,LLMCharacterDraft]
    characters: dict[str,Character]
    shots: list[Shot]
    locations: dict[str,Location] = field(default_factory=dict)


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
    Breaks a story down into shots, complete with a cast of characters.

    Extracts the cast and the locations once, then breaks each paragraph into shots in order, passing each paragraph the last shot of the one before it for continuity.

    A contamination judge checks the cast's and the locations' descriptions once, and each paragraph's details and actions, rewriting any text that would be drawn into the wrong image.

    Arguments:
        story_text: str - Story (in plain text).
        make_caller: MakeCaller - LLM caller builder function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        StoryBreakdown - A StoryBreakdown object with complete information about the breakdown of characters and shots.
    """
    paragraphs = split_paragraphs(story_text)
    call_judge = make_caller(LLMJudgeOutput)
    cast = judge_cast(extract_cast(story_text, make_caller(LLMCastOutput)), call_judge)
    locations = judge_locations(extract_locations(story_text, make_caller(LLMLocationsOutput)), cast, call_judge)
    call_llm = make_caller(build_paragraph_output_model(list(cast), list(locations)))

    shots: list[Shot] = []
    previous_shot: LLMShotDraft | None = None # Initialised to None
    for paragraph_index, paragraph in enumerate(paragraphs):
        results = get_shots_for_paragraph(paragraph, cast, previous_shot, call_llm, call_judge, locations)
        shots.extend(to_domain_shot(result, paragraph_index) for result in results)
        if results:
            previous_shot = results[-1].shot # Sets the previous_shot field to the last shot of this paragraph, so that the next paragraph receives it

    characters = {cast_id: to_domain_character(draft) for cast_id, draft in cast.items()}
    return StoryBreakdown(cast=cast, characters=characters, shots=shots, locations={location_id: to_domain_location(draft) for location_id, draft in locations.items()})