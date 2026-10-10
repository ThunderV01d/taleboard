"""
Manages the cast-extraction part of the pipeline.

Includes helper functions to parse cast attributes.
"""
import re
import json

from collections import Counter

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.schema.models import Character
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMCastOutput
from taleboard.parsing.prompts import build_cast_extraction_prompt

def slugify(name: str) -> str:
    """
    Converts a character name to a slug suitable for use as an ID.

    Arguments:
        name: str - Character name (in plain text).

    Returns:
        str - Slugified name. Defaults to "character" if nothing usable remains.

    Example:
        slugify("Jason Voorhees") -> "jason_voorhees"
    """
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug) # Collapses any run of non-alphanumerics to one "_"
    slug = slug.strip("_")
    return slug or "character" # Fallback

def assign_char_ids(characters:list[LLMCharacterDraft]) -> dict[str,LLMCharacterDraft]:
    """
    Assigns a unique ID to each character based on their name.

    If multiple characters have the same name, a numeric suffix is added to make the IDs unique.
    Also ensures there will be no collisions with the suffix-appended IDs.

    Arguments:
        characters: list[LLMCharacterDraft] - List of characters catalogued by the LLM.

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of unique character IDs to each character catalogued by the LLM.
    """
    base_slugs = [slugify(c.name) for c in characters]
    counts = Counter(base_slugs)
    next_suffix: dict[str, int] = {}
    result: dict[str, LLMCharacterDraft] = {}
    for character, base in zip(characters, base_slugs):
        if counts[base] == 1:
            candidate = base
        else:
            n = next_suffix.get(base, 0) + 1
            next_suffix[base] = n
            candidate = f"{base}_{n}"
        # Global safety net: never overwrite an ID another character already has
        final = candidate
        bump = 2
        while final in result:
            final = f"{candidate}_{bump}"
            bump += 1
        result[final] = character
    return result


def extract_cast(
    story_text: str,
    call_llm: CallLLM
) -> dict[str, LLMCharacterDraft]:
    """
    Extracts a cast of characters from the story.

    If the story is empty, raises a ValueError.

    Arguments:
        story_text: str - Entire story (in plain text).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of unique character IDs to each character catalogued by the LLM.
    """
    if not story_text.strip():
        raise ValueError("Story is empty -- there is nothing to extract a cast from.")
    prompt = build_cast_extraction_prompt(story_text)
    response_text = call_llm(prompt)
    data = json.loads(response_text)
    output = LLMCastOutput.model_validate(data) # Ensures output validation against our model
    return assign_char_ids(output.characters)

def to_domain_character(draft: LLMCharacterDraft, appearance_reference: str | None = None) -> Character:
    """
    Converts an LLMCharacterDraft to a domain Character, keeping its aliases and adding an optional appearance reference.

    Appearance reference is useful in the domain, not in the draft -- this is why this function exists.

    Arguments:
        draft: LLMCharacterDraft - An LLMCharacterDraft object.
        appearance_reference: str - An appearance reference to bind this draft to when constructing our Character object. Defaults to None.

    Returns:
        Character - A Character object, with an appearance reference (maybe) attached.
    """
    return Character(
        name=draft.name,
        description=draft.description,
        aliases=list(draft.aliases),
        appearance_reference=appearance_reference
    )