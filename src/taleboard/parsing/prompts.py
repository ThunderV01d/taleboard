"""
Defines the prompts used to extract the cast and direct the shots from the story.

Acts as a 'director' -- building the prompts dynamically.

Attributes:
    CAST_EXTRACTION_INSTRUCTIONS: str - Instructions for the model to extract the cast from a story, placed into the prompt.
    LOCATION_EXTRACTION_INSTRUCTIONS: str - Instructions for the model to extract the locations from a story, placed into the prompt.
    SHOT_BREAKDOWN_INSTRUCTIONS: str - Instructions for the model to break the story down into shots, placed into the prompt.
    CONTAMINATION_JUDGE_INSTRUCTIONS: str - Instructions for the model to check text that is drawn on its own, and rewrite what would be drawn into the wrong image.
"""
import json

from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMShotDraft

CAST_EXTRACTION_INSTRUCTIONS = """\
You are extracting a cast list from a short story, to be used as reference
material for illustrating the story as a storyboard.
 
Identify every character who is referred to by a proper name or a stable,
specific title (e.g. "the Captain") and who takes some action or is
described in the story. 

Only include people who physically appear in at least one scene of the
story's present action. Leave out anyone who appears only in a memory, a
thought, a dream, an account of the past, or only as a voice -- they can never be drawn in a shot.
 
If the same character is referred to by more than one name or description
in the text (e.g. "Ben" and "the old man"), treat them as one character and
use their most specific proper name. Only merge references that are clearly the same person. A relational description like "her mother" or "his friend" means a different person depending on who "her" or "his" is at that point in the story -- so one character's mother remembered in one scene and another character's mother appearing in a later scene are two separate characters. When in doubt, keep them seperate.

List every other way the story refers
to them in their aliases: short names, titles, roles, and descriptions (e.g.
"Brandt", "the harbourmaster", "the old man"). This includes roles the story
only implies, such as someone hurrying into "the harbourmaster's office"
being the harbourmaster. Only list an alias that always means this character
in this story -- never one the story also uses for somebody else, and if two characters could both be called the same thing (e.g. "the daughter"), list it for neither. Do include every short form the story uses, such as "the girl" for the "the girl in the yellow raincoat". Use an empty list if there are none.

For each character, write a short physical description: build, hair,
clothing, and any distinguishing visual features. Use every physical detail the story gives. Where it gives few or none, invent plausible, specific ones that suit the character (age, build, hair, clothing) -- never write that details are missing or unknown. This description will be
used directly to generate images of the character, alone, so keep it concrete and
visual. Do not include personality, backstory, or relationships to other
characters, and do not include anything they do, anywhere they go, anyone they are with, or how they change over the story -- only one fixed look. Keep each description to one or two short sentences, under 250 characters. For example, write "a woman in her late thirties, slim, shoulder-length dark hair, cardigan over a long skirt", not "a woman who sings in the kitchen and watches the stars with her husband" -- anything else in the description gets drawn into every image of them.
"""

def build_cast_extraction_prompt(story_text: str) -> str:
    """
    Builds a prompt for extracting the cast of characters from the story.
    
    Arguments:
        story_text: str - Story (in plain text).

    Returns:
        str - Full prompt to be passed to the LLM for cast extraction.
    """
    return f"{CAST_EXTRACTION_INSTRUCTIONS}\n\nSTORY:\n{story_text}"


LOCATION_EXTRACTION_INSTRUCTIONS = """\
You are listing the locations of a short story, to be used as reference
material for illustrating the story as a storyboard.

A location is a distinct place where at least one scene of the story's present action happens: a room, a street, a ship's deck, a forest clearing. Different rooms are different locations (the kitchen and the hallway of the same house are two). The same place at a different time of day, in different weather, or with a door now open is still one location -- never list a place twice (the quay at night and the quay at dawn are one location, "the quay"); each shot adds the time of day and weather itself. Leave out places that appear only in a memory, a dream, a story someone tells, or that are only mentioned. If the story never says where a scene happens, invent one plausible location that suits it. List the locations in the order the story first visits them.

For each location, give a short name that doesn't name any person (e.g. "the harbourmaster's office" or "the fishing boat", not "Tomas's boat") and a short visual description of how the place always looks: its architecture, size, main furniture and fixtures, materials, and windows or openings. Use every visual detail the story gives about it, and invent plausible, specific ones where it gives few or none -- never write that details are missing or unknown. This description is drawn on its own as an empty place with nobody in it, and every shot in the location is drawn from it -- so describe only the place itself. Never mention any person, named or not, or anything anyone does there; never mention the mood or atmosphere, the story's events, or anything that changes during the story (time of day, weather, a door being opened) -- each shot adds those itself. Never include words that would have to be readable (signs, labels, writing). Keep each description to one or two short sentences, under 250 characters. For example, write "a small wood-panelled office, a large desk with a black telephone, a leather chair, a filing cabinet, a corkboard on the left wall, a two-pane window at the back", not "the cluttered office where Marcus waits anxiously for the call that will change everything".
"""

def build_location_extraction_prompt(story_text: str) -> str:
    """
    Builds a prompt for extracting the locations from the story.

    Arguments:
        story_text: str - Story (in plain text).

    Returns:
        str - Full prompt to be passed to the LLM for location extraction.
    """
    return f"{LOCATION_EXTRACTION_INSTRUCTIONS}\n\nSTORY:\n{story_text}"

SHOT_BREAKDOWN_INSTRUCTIONS = """\
You are breaking one paragraph of a story into storyboard shots.
 
A shot is one visual beat — one moment, framing, and arrangement of characters that a single storyboard panel could show. Most paragraphs are a single shot. Only split a paragraph into more than one shot when it genuinely contains multiple distinct visual moments — for example, a character crossing a room and then turning to face someone is two shots; a character simply speaking a line while standing still is one.

You are given the fixed cast of this story below, each with an id, name, and appearance. You may only reference characters from this list by their id. If the paragraph describes someone not in this list (an unnamed extra, a stranger, a crowd), do not create a region for them at all — leave them out rather than inventing an id for them; mention them in the shot's details instead if they're part of what the shot looks like (e.g. "crowded with unnamed vendors"). The paragraph may refer to a cast member by any of their aliases rather than their name -- that is still that cast member, so give them a region with their id. But only give a cast member a region when the paragraph really means that person: a description like "her mother" can match a cast member's alias and still mean someone else, depending on who "her" is. If the person the paragraph means is not in the cast, leave them out of the regions. Only give a region to a character who is physically present in that moment: a voice from a radio, phone or recording, a person being remembered or imagined, or a figure of speech ("someone was out there far away, running away") is never a region -- show what can actually be seen instead (the radio, the star).

Each region's action is used on its own to draw that one character, isolated on a blank background. Describe only what their body is doing: pose, gesture, and expression, plus any smaller object they are holding or physically interacting with (eg:-"gripping a radio handset, frowning" or "seated, smiling pleasantly") -- ensure, however, that objects that belong in the background of the scene are not mentioned in the action text at all. Never mention the location, the weather, the scenery, or other characters in an action -- those come from the shot's location and details, and the other characters get their own regions. For example, write "climbing, pausing with a focused expression", not "climbing into the lamp room, looking out of the windows"; and write "draping a blanket forward with both hands, attentive expression", not "wrapping a blanket around Tomas's shoulders".

Anything an action mentions gets drawn into that character's image. When a character touches or holds onto someone else (an embrace, an arm around someone, holding hands), describe only this character's own body as it would look with the other person removed -- write "one arm curved outward at shoulder height, warm expression", not "wrapping an arm around the child's shoulders". Never refer to another person in an action in any form, named or not ("the child", "her friend"). The same goes for fixed parts of the scene they lean on, look through or climb: write "leaning forward with palms raised at face height", not "pressing her face against the window glass", and "stepping up with one leg raised high", not "climbing through the window frame". Pronouns count too: "his", "her", "their" or "them" pointing at anyone other than this character reads as a second person to draw, so "forehead pressed against his" draws two people. Describe only this character's own body ("head bowed forward, arms curved in front at chest height, eyes closed"), and never use words that need a second person, such as "someone", "each other", "embracing", "hugging" or "kissing".

Every shot takes place in one of the story's locations, listed below with an id, name and appearance. Set location_id to the id of the place the shot happens in; you may only use ids from this list. Shots in the same place must use the same location_id, even when the camera moves, time passes or the paragraph describes the place differently -- the location's description is drawn the same way for every shot of it, so never repeat or reword it in the shot. Not every shot needs a character: a beat that's really about a place or an object (an establishing shot, a close-up on something in the scene) should have an empty regions list rather than forcing a character into it.

The details field says what looks different about the location in this shot, and is drawn with the location's description as the shot's background. Use it only for small, visible, physical changes: a door open or shut, a light on or off, rain on the window, papers scattered on the floor, or unnamed figures who are not in the cast ("crowded with unnamed shoppers"). Leave it empty ("") when the place looks as described -- most shots should. Never put a mood or atmosphere ("tense", "emotionally charged"), story or backstory ("where the accident happened"), anything already in the location's description, or anything that would need readable text ("a clock showing 11:59") in details. Keep it under 150 characters. Each region's character is drawn separately and placed on top of the background, so a cast member mentioned in details appears twice: never mention a cast member in details in any form -- not by name or alias, not by a description such as "the girl", not by a pronoun ("the door behind her"), and not through something they are holding or doing ("the glow of the sphere Eleanor is holding"). Place things relative to the frame or the room ("elevator doors open at the back of the frame"), not relative to a cast member ("the window beside him").

The images are drawn by a model that cannot render readable text. Never make words visible in details or an action: no speech or dialogue, sound effects, signs, labels, writing, or inscriptions ("a voice speaks from the radio", "a sentence carved into the desk"). Describe only the objects themselves ("an old radio on the desk", "a wooden desk with a carved surface"); what is said or written belongs in the shot's description, which is never drawn.

Choose each character's orientation from what they are doing, not as a default. Characters talking to or looking at each other should face each other (one left, one right). A character walking or running away faces away from the camera, and one moving across the frame faces the direction they are moving. Use towards_camera only when the character is actually facing the viewer.

Vary the camera to suit each beat rather than defaulting to a medium, eye-level shot. Use a low angle to make a character look powerful, determined, or looming; a high angle to make them look small, vulnerable, or overwhelmed, or to show a layout from above; and a wide shot when the story arrives somewhere new.

You are also given the last shot from the previous paragraph, if any, for continuity. Keep a character's position and orientation similar to their last known position unless the text describes them moving. You must also keep the position and orientation of characters consistent across shots in the same paragraph, unless the text describes them moving. The same applies to the location: keep the previous shot's location_id unless the text signals the location has changed, and copy its details word for word unless something visible in the place has changed.
"""

def build_shot_breakdown_prompt(
    paragraph: str,
    cast: dict[str,LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
    locations: dict[str,LLMLocationDraft] | None = None,
) -> str:
    """
    Builds a prompt for breaking a paragraph into storyboard shots.

    Arguments:
        paragraph: str - Paragraph to be broken down (in plain text).
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and the LLM character draft.
        previous_shot: LLMShotDraft - Previous generated shot; used for context retention between shots. Defaults to None (for first shot).
        locations: dict[str,LLMLocationDraft] - Mapping between location IDs and LLM location drafts. Defaults to None (no locations listed).
  
    Returns:
        str - Full prompt to be passed to the LLM for shot breakdown.
    """
    cast_lines = "\n".join(
        f"- id: {cast_id}, name: {char.name}, also called: {', '.join(char.aliases) or 'no other names'}, description: {char.description}"
        for cast_id, char in cast.items()
    )

    location_lines = "\n".join(
        f"- id: {location_id}, name: {location.name}, description: {location.description}"
        for location_id, location in (locations or {}).items()
    )

    if previous_shot is not None:
        previous_shot_text = f"Previous shot: {previous_shot.model_dump_json()}"
    else:
        previous_shot_text = "Previous shot: none — this is the first shot of the story."

    return (
        f"{SHOT_BREAKDOWN_INSTRUCTIONS}\n\n"
        f"CAST:\n{cast_lines}\n\n"
        f"LOCATIONS:\n{location_lines}\n\n"
        f"{previous_shot_text}\n\n"
        f"PARAGRAPH:\n{paragraph}"
    )


CONTAMINATION_JUDGE_INSTRUCTIONS = """\
You are checking text that an image model will draw from, before any image is generated. Each item below is drawn on its own, and anything it mentions gets drawn:

- An action is drawn as one character alone on a blank background (the item names the character). Flag it if it refers to anyone else in any form: by name or description, by a pronoun that points at someone other than this character ("his", "her", "their", "them"), or by a word that needs a second person present ("someone", "each other", "embracing", "together"). Also flag it if it mentions a fixed part of a scene: furniture, beds, chairs, desks, stairs, walls, windows, doors, vehicles, rooms or landscape. Small objects the character holds or wears are fine ("holding a phone", "gripping a red balloon"), and so are gestures that need nobody else ("making a kissing motion with her lips", "arms crossed").
- A location is drawn as an empty place with nobody in it, and every shot in that place is drawn from it. Flag it if it mentions any person, named or not, or something anyone does there; a mood or atmosphere; the story's events; or something temporary (time of day, weather, a door being opened). Its architecture, furniture, fixtures, windows and doors are what a location is made of -- never flag those. The place's name is never drawn, so never flag an item because of its name.
- Details are drawn with their location as one shot's background, with nobody from the cast in it; cast members are drawn separately on top. Flag them if they mention or imply a cast member in any form -- name, description, pronoun, or something they are holding or doing. Also flag a mood or atmosphere ("tense", "emotionally charged"), story or backstory ("where it all began"), or anything that would need readable text ("a clock showing 11:59"). Unnamed background figures who are not in the cast are fine ("crowded with unnamed shoppers"), and so are parts of the place, weather and light ("rain on the windows", "storm clouds over the sea", "the lamp switched off") -- visible changes like these are what details are for. If nothing visible is left once the problem is removed, rewrite them as an empty string.
- A description is drawn as one character standing alone on a blank background. Flag it if it mentions anyone else, a place, or something the character does in the story -- it should say only how they look.
- Any item: flag visible words (signs, writing, speech).

For every flagged item, write rewritten_text: the same text with the problem removed and everything else kept. For an action, describe this character's own body as it would look with the other person or the furniture taken away -- "one arm curved outward at shoulder height, head tilted forward" for an embrace, "seated, knees bent, hands resting on thighs" for sitting on a bed. Keep rewritten actions under 200 characters, details under 150, and locations and descriptions under 300. For an item that is not flagged, set reason and rewritten_text to empty strings.

Return exactly one entry per item, using its id.
"""

_JUDGE_OWNER_LABELS = {"location": "place"} # What an item's name is labelled as in the judge prompt -- a character's, unless listed here

def build_contamination_judge_prompt(items: list[tuple[str, str, str, str | None]], cast: dict[str,LLMCharacterDraft]) -> str:
    """
    Builds a prompt for checking text that is drawn on its own (actions, details, locations, descriptions).
    
    Arguments:
        items: list[tuple[str,str,str,str|None]] - (id, kind, text, name of the character or place it belongs to, or None) for each item to check.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts. Names and aliases are listed so the judge knows who counts as a cast member.

    Returns:
        str - Full prompt to be passed to the LLM for judging.
    """
    cast_lines = "\n".join(
        f"- {char.name} (also called: {', '.join(char.aliases) or 'no other names'})"
        for char in cast.values()
    )
    item_lines = "\n".join(
        f"- id: {item_id}, kind: {kind}{f', {_JUDGE_OWNER_LABELS.get(kind, 'character')}: {name}' if name else ''}, text: {json.dumps(text)}"
        for item_id, kind, text, name in items
    )
    return f"{CONTAMINATION_JUDGE_INSTRUCTIONS}\nCAST:\n{cast_lines}\n\nITEMS:\n{item_lines}"