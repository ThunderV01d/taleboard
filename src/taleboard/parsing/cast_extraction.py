import re
import json

from collections import Counter
from typing import Callable

from taleboard.schema.models import Character
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMCastOutput
from taleboard.parsing.prompts import build_cast_extraction_prompt

CallLLM = Callable[[str], str]

def slugify(name: str) -> str:
    """Convert a character name to a slug suitable for use as an ID."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)  # collapse any run of non-alphanumerics to one "_"
    slug = slug.strip("_")
    return slug or "character"  # fallback if the name had nothing usable

def assign_char_ids(characters:list[LLMCharacterDraft]) -> dict[str,LLMCharacterDraft]:
    """Assign a unique ID to each character based on their name.
    If multiple characters have the same name, a numeric suffix is added to make the IDs unique.
    Also ensures there will be no collisions with the suffix-appended IDs.
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
        # Global safety net: never overwrite an id another character already has.
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
    """Extracts a cast of characters from the story."""
    if not story_text.strip():
        raise ValueError("Story is empty -- there is nothing to extract a cast from.")
    prompt = build_cast_extraction_prompt(story_text)
    response_text = call_llm(prompt)
    data = json.loads(response_text)
    output = LLMCastOutput.model_validate(data)
    return assign_char_ids(output.characters)

def to_domain_character(draft: LLMCharacterDraft, appearance_reference: str | None = None) -> Character:
    "Converts an LLMCharacterDraft to a domain Character, adding the optional appearance reference."
    return Character(
        name=draft.name,
        description=draft.description,
        appearance_reference=appearance_reference
    )