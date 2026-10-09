"""Top-level orchestration for turning a whole story into a cast and an ordered list of shots."""
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from taleboard.parsing.bedrock_caller import make_bedrock_caller
from taleboard.parsing.cast_extraction import CallLLM, extract_cast, to_domain_character
from taleboard.parsing.llm_schemas import LLMCastOutput, LLMCharacterDraft, LLMShotDraft, build_paragraph_output_model
from taleboard.parsing.shot_breakdown import get_shots_for_paragraph, to_domain_shot
from taleboard.schema.models import Character, Shot

MakeCaller = Callable[[type[BaseModel]], CallLLM] #output schema -> a CallLLM constrained to that schema

@dataclass
class StoryBreakdown:
    cast: dict[str, LLMCharacterDraft]  #as extracted, including aliases
    characters: dict[str, Character]    #domain characters, keyed by the same ids, ready for rendering
    shots: list[Shot]                   #in story order


def split_paragraphs(story_text: str) -> list[str]:
    """Paragraphs are separated by one or more blank lines."""
    return [p.strip() for p in story_text.split("\n\n") if p.strip()]


def break_down_story(story_text: str, make_caller: MakeCaller = make_bedrock_caller) -> StoryBreakdown:
    """Extracts the cast once, then breaks each paragraph into shots in order,
    passing each paragraph the last shot of the one before it for continuity."""
    paragraphs = split_paragraphs(story_text)
    cast = extract_cast(story_text, make_caller(LLMCastOutput))
    call_llm = make_caller(build_paragraph_output_model(list(cast)))

    shots: list[Shot] = []
    previous_shot: LLMShotDraft | None = None
    for paragraph_index, paragraph in enumerate(paragraphs):
        results = get_shots_for_paragraph(paragraph, cast, previous_shot, call_llm)
        shots.extend(to_domain_shot(result, paragraph_index) for result in results)
        if results:
            previous_shot = results[-1].shot

    characters = {cast_id: to_domain_character(draft) for cast_id, draft in cast.items()}
    return StoryBreakdown(cast=cast, characters=characters, shots=shots)