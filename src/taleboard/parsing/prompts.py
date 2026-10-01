from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMShotDraft

CAST_EXTRACTION_INSTRUCTIONS = """\
You are extracting a cast list from a short story, to be used as reference
material for illustrating the story as a storyboard.
 
Identify every character who is referred to by a proper name or a stable,
specific title (e.g. "the Captain") and who takes some action or is
described in the story. Do not include incidental, unnamed background
figures (e.g. "a waiter", "the crowd") — those are handled separately and
do not need an entry here.
 
If the same character is referred to by more than one name or description
in the text (e.g. "Ben" and "the old man"), treat them as one character and
use their most specific proper name.
 
For each character, write a short physical description: build, hair,
clothing, and any distinguishing visual features. Keep it as accurate to details mentioned in the story as possible, inventing details only if absolutely necessary. This description will be
used directly to generate images of the character, so keep it concrete and
visual. Do not include personality, backstory, or relationships to other
characters.
"""

def build_cast_extraction_prompt(story_text: str) -> str:
    """Builds a prompt for extracting the cast of characters from the story."""
    return f"{CAST_EXTRACTION_INSTRUCTIONS}\n\nSTORY:\n{story_text}"

SHOT_BREAKDOWN_INSTRUCTIONS = """\
You are breaking one paragraph of a story into storyboard shots.
 
A shot is one visual beat — one moment, framing, and arrangement of
characters that a single storyboard panel could show. Most paragraphs are
a single shot. Only split a paragraph into more than one shot when it
genuinely contains multiple distinct visual moments — for example, a
character crossing a room and then turning to face someone is two shots;
a character simply speaking a line while standing still is one.
 
You are given the fixed cast of this story below, each with an id, name,
and appearance. You may only reference characters from this list by their
id. If the paragraph describes someone not in this list (an unnamed
extra, a stranger, a crowd), do not create a region for them at all —
leave them out rather than inventing an id for them. Character orientations should reflect their actions and interactions in the paragraph — do not assume they all face towards the camera.
 
You are also given the last shot from the previous paragraph, if any, for
continuity. Keep a character's position and orientation similar to their
last known position unless the text describes them moving. You must also keep the position and orientation of characters consistent across shots in the same paragraph, unless the text describes them moving.
"""

def build_shot_breakdown_prompt(
    paragraph: str,
    cast: dict[str,LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
) -> str:
    """Builds a prompt for breaking a paragraph into storyboard shots"""
    cast_lines = "\n".join(
        f"- id: {cast_id}, name: {char.name}, description: {char.description}"
        for cast_id, char in cast.items()
    )

    if previous_shot is not None:
        previous_shot_text = f"Previous shot: {previous_shot.model_dump_json()}"
    else:
        previous_shot_text = "Previous shot: none — this is the first shot of the story."

    return (
        f"{SHOT_BREAKDOWN_INSTRUCTIONS}\n\n"
        f"CAST:\n{cast_lines}\n\n"
        f"{previous_shot_text}\n\n"
        f"PARAGRAPH:\n{paragraph}"
    )