from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMShotDraft

CAST_EXTRACTION_INSTRUCTIONS = """\
You are extracting a cast list from a short story, to be used as reference
material for illustrating the story as a storyboard.
 
Identify every character who is referred to by a proper name or a stable,
specific title (e.g. "the Captain") and who takes some action or is
described in the story.
 
If the same character is referred to by more than one name or description
in the text (e.g. "Ben" and "the old man"), treat them as one character and
use their most specific proper name. List every other way the story refers
to them in their aliases: short names, titles, roles, and descriptions (e.g.
"Brandt", "the harbourmaster", "the old man"). This includes roles the story
only implies, such as someone hurrying into "the harbourmaster's office"
being the harbourmaster. Use an empty list if there are none.
 
For each character, write a short physical description: build, hair,
clothing, and any distinguishing visual features. Keep it as accurate to details mentioned in the story as possible, inventing details only if absolutely necessary. This description will be
used directly to generate images of the character, so keep it concrete and
visual. Do not include personality, backstory, or relationships to other
characters, and do not include anything they do or anywhere they go in the story -- only how they look.
"""

def build_cast_extraction_prompt(story_text: str) -> str:
    """Builds a prompt for extracting the cast of characters from the story."""
    return f"{CAST_EXTRACTION_INSTRUCTIONS}\n\nSTORY:\n{story_text}"

SHOT_BREAKDOWN_INSTRUCTIONS = """\
You are breaking one paragraph of a story into storyboard shots.
 
A shot is one visual beat — one moment, framing, and arrangement of characters that a single storyboard panel could show. Most paragraphs are a single shot. Only split a paragraph into more than one shot when it genuinely contains multiple distinct visual moments — for example, a character crossing a room and then turning to face someone is two shots; a character simply speaking a line while standing still is one.

You are given the fixed cast of this story below, each with an id, name, and appearance. You may only reference characters from this list by their id. If the paragraph describes someone not in this list (an unnamed extra, a stranger, a crowd), do not create a region for them at all — leave them out rather than inventing an id for them; mention them in the setting description instead if they're part of what the shot looks like (e.g. a busy marketplace crowded with unnamed vendors). The paragraph may refer to a cast member by any of their aliases rather than their name -- that is still that cast member, so give them a region with their id. Never describe a cast member in the setting text, under any name; cast members appear only as regions.

Each region's action is used on its own to draw that one character, isolated on a blank background. Describe only what their body is doing: pose, gesture, and expression, plus any smaller object they are holding or physically interacting with (eg:-"gripping a radio handset, frowning" or "sitting on a chair, smiling pleasantly") -- ensure, however, that objects that belong in the background of the scene are not mentioned in the action text at all. Never mention the location, the weather, the scenery, or other characters in an action -- those belong in the setting, and the other characters get their own regions. For example, write "climbing, pausing with a focused expression", not "climbing into the lamp room, looking out of the windows"; and write "draping a blanket forward with both hands, attentive expression", not "wrapping a blanket around Tomas's shoulders".

Every shot needs a setting — a short description of the location and environment it takes place in. Not every shot needs a character: a beat that's really about a place or an object (an establishing shot, a close-up on something in the scene) should have an empty regions list rather than forcing a character into it. A setting can be as plain and empty as the story implies ("an empty hallway") or as populated with unnamed figures as it implies ("a crowded train platform") — neither is a region, both just belong in the setting text.

Choose each character's orientation from what they are doing, not as a default. Characters talking to or looking at each other should face each other (one left, one right). A character walking or running away faces away from the camera, and one moving across the frame faces the direction they are moving. Use towards_camera only when the character is actually facing the viewer.

Vary the camera to suit each beat rather than defaulting to a medium, eye-level shot. Use a low angle to make a character look powerful, determined, or looming; a high angle to make them look small, vulnerable, or overwhelmed, or to show a layout from above; and a wide shot when the story arrives somewhere new.

You are also given the last shot from the previous paragraph, if any, for continuity. Keep a character's position and orientation similar to their last known position unless the text describes them moving. You must also keep the position and orientation of characters consistent across shots in the same paragraph, unless the text describes them moving. The same applies to setting: keep it the same as the previous shot unless the text signals the location has changed.
"""

def build_shot_breakdown_prompt(
    paragraph: str,
    cast: dict[str,LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
) -> str:
    """Builds a prompt for breaking a paragraph into storyboard shots."""
    cast_lines = "\n".join(
        f"- id: {cast_id}, name: {char.name}, also called: {', '.join(char.aliases) or 'no other names'}, description: {char.description}"
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