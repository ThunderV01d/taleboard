"""
Defines the prompts used to extract the cast and direct the shots from the story.

Acts as a 'director' -- building the prompts dynamically.

Attributes:
    CAST_EXTRACTION_INSTRUCTIONS: str - Instructions for the model to extract the cast from a story, placed into the prompt.
    PROP_EXTRACTION_INSTRUCTIONS: str - Instructions for the model to extract the props from a story, placed into the prompt.
    LOCATION_EXTRACTION_INSTRUCTIONS: str - Instructions for the model to extract the locations from a story, placed into the prompt.
    SCENE_BREAKDOWN_INSTRUCTIONS: str - Instructions for the model to split the story into scenes, placed into the prompt.
    SHOT_BREAKDOWN_INSTRUCTIONS: str - Instructions for the model to break one paragraph of a scene into shots, placed into the prompt.
    CONTAMINATION_JUDGE_INSTRUCTIONS: str - Instructions for the model to check text that is drawn on its own, and rewrite what would be drawn into the wrong image.
"""
import json

from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMPropDraft, LLMSceneDraft, LLMShotDraft

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
clothing, and any distinguishing visual features. Use every physical detail the story gives. Where it gives few or none, invent plausible, specific ones that suit the character (age, build, hair, clothing) -- never write that details are missing or unknown. Commit to one specific look: never offer alternatives ("a long dress or a work coat") or hedge ("likely", "perhaps", "suitable for"). This description will be
used directly to generate images of the character, alone, so keep it concrete and
visual. Do not include personality, demeanour, mood or facial expression (each shot gives the expression), backstory, or relationships to other
characters, and do not include anything they do, anywhere they go, anyone they are with, or how they change over the story -- only one fixed look. Never include anything they hold or carry (a bag, a lantern, a phone, a walking stick): those are drawn separately, so a character is always drawn empty-handed. Clothing and things worn (a hat, glasses, a scarf) belong in the description. Keep each description to one or two short sentences, under 250 characters. For example, write "a woman in her late thirties, slim, shoulder-length dark hair, cardigan over a long skirt", not "a woman who sings in the kitchen and watches the stars with her husband" -- anything else in the description gets drawn into every image of them.
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

For each location, give a short name that doesn't name any person (e.g. "the harbourmaster's office" or "the fishing boat", not "Tomas's boat"), and say whether it is an interior (indoors, under a roof: a room, a cabin, a cave) or an exterior (outdoors, open to the sky: a street, a quay, a forest).

Each location is drawn as four pictures, one looking at each of its four sides, so describe it in three parts, in this order:

- features: every fixed thing the story mentions in this place -- furniture, fixtures, machinery, stairs, doors, windows, hooks, the way characters come in or go out -- as short names of the things themselves, without where they are ("a great lens on a pedestal", "spiral stairs", "a hook", not "a hook by the window"). Leave out the story's props (listed below), people, and anything that changes. Use an empty list if the story mentions none.
- description: what the whole place has in common, seen from any side -- what kind of place it is, its size, its walls, floor and ceiling (or ground), its materials and style. No furniture or features that stand on one particular side. Keep it to one sentence, under 200 characters. For example, "a small wood-panelled office about four metres across, plain wooden floorboards".
- views: what the camera sees looking straight at each side -- north, east, south and west. Start each by saying in plain words which side it is, never by compass direction ("the back wall of the office: ...", "a side wall: ...", "the far end of the room: ..."), then list only what is on that side: furniture, fixtures, machinery, stairs, doors, windows, or for an exterior what lies that way ("the harbour: the edge of the quay, with fishing boats moored in the water and the open sea beyond"). Every fixed feature the story mentions in the place must appear in exactly one view, on the side where it stands -- including the way characters come in or go out (the top of a staircase, a doorway, a hatch); a feature in the middle of the place (a great lens on a pedestal, a table in the centre of the room) goes in the north view, seen in front of that side. Put the place's most important feature, or the side the story's action mostly faces, to the north. Every side must have a view, and each side should look different: give each a feature or two, inventing plausible ones where the story gives none (a window, a door, shelves, a cupboard, a radiator), and only if a side really must be empty say so ("the other side wall of the office, plain and mostly bare") -- never more than one bare side. Never repeat the description in a view, never put the same feature on two sides, and never offer alternatives ("steps or a ramp", "a balcony or stairs") -- commit to one. Keep each view under 180 characters.

Use every visual detail the story gives about a place, and invent plausible, specific ones where it gives few or none -- never write that details are missing or unknown. Each picture is drawn on its own as an empty place with nobody in it, and every shot in the location is drawn from them -- so describe only the place itself. Never mention any person, named or not, or anything anyone does there; never mention the mood or atmosphere, the story's events, or anything that changes during the story (time of day, weather, a door being opened) -- each shot adds those itself. Never include words that would have to be readable (signs, labels, writing). Never include any of the story's props, listed below -- they are drawn separately, and would appear twice.
"""

def build_location_extraction_prompt(story_text: str, props: dict[str,LLMPropDraft] | None = None) -> str:
    """
    Builds a prompt for extracting the locations from the story.

    Arguments:
        story_text: str - Story (in plain text).
        props: dict[str,LLMPropDraft] - Mapping between prop IDs and LLM prop drafts, which locations must leave out. Defaults to None (no props).

    Returns:
        str - Full prompt to be passed to the LLM for location extraction.
    """
    return f"{LOCATION_EXTRACTION_INSTRUCTIONS}\n\nPROPS:\n{_prop_lines(props)}\n\nSTORY:\n{story_text}"


PROP_EXTRACTION_INSTRUCTIONS = """\
You are listing the props of a short story, to be used as reference material
for illustrating the story as a storyboard.

A prop is a portable object that a character holds, carries, picks up, hands over or uses in the story's present action (a lantern, a letter, a phone, a knife, a suitcase), or a small object the story singles out on its own (a ring left on a table). Each prop is drawn on its own and placed into shots separately -- characters are always drawn empty-handed, so anything they hold must be a prop. Leave out what characters wear (clothing, hats, glasses -- part of how they look), vehicles, animals, and objects that appear only in a memory, a dream, or are only mentioned. Never list a fixture of a place, however important it is to the story: anything built in, bolted down, or too big for one person to carry (a lighthouse's lens, a fireplace, a ship's wheel, a bell, a statue) belongs to the place and is drawn with it. A prop must be something a character could pick up and carry off in one hand or both arms. If in doubt, leave it out -- it is part of the place. The same object is one prop however the story words it -- never list it twice. If the story has no such objects, return an empty list. List the props in the order the story first shows them.

For each prop, give a short name that doesn't name any person ("the brass lantern", not "Mara's lantern") and a short visual description of how it always looks: its shape, size, material, colour and any distinguishing features. Use every visual detail the story gives, and invent plausible, specific ones where it gives few or none -- never write that details are missing or unknown. This description is drawn as the object alone on a blank background, so describe only the object: never mention a person or a hand holding it, a place, a surface it sits on, other objects, or anything that happens to it in the story. Never include words that would have to be readable (writing on a letter, a label, a screen) -- describe the object itself ("a folded letter of cream paper"). Commit to one specific look: never offer alternatives ("cream or white paper") or hedge ("perhaps"). Keep each description to one short sentence, under 200 characters.
"""


def build_prop_extraction_prompt(story_text: str) -> str:
    """
    Builds a prompt for extracting the props from the story.

    Arguments:
        story_text: str - Story (in plain text).

    Returns:
        str - Full prompt to be passed to the LLM for prop extraction.
    """
    return f"{PROP_EXTRACTION_INSTRUCTIONS}\n\nSTORY:\n{story_text}"


def _prop_lines(props: dict[str,LLMPropDraft] | None) -> str:
    """
    The story's props, one per line, for a prompt that must leave them out (or "none").
    """
    return "\n".join(f"- {prop.name}: {prop.description}" for prop in (props or {}).values()) or "none"

SCENE_BREAKDOWN_INSTRUCTIONS = """\
You are splitting a short story into scenes, to be illustrated as a storyboard.

A scene is a run of consecutive paragraphs that happen in one location, at one time. Start a new scene whenever the story moves to a different location, or jumps forward in time (the next morning, hours later); keep continuous action in the same place as one scene, however many paragraphs it takes. The paragraphs are numbered from 0. Give each scene the number of its first paragraph: the first scene starts at paragraph 0, each scene starts after the one before it, and a scene runs until the next one starts -- so every paragraph belongs to exactly one scene. A paragraph that moves somewhere new belongs to the scene where most of it happens.

For each scene, give:
- first_paragraph: the number of its first paragraph.
- location_id: where it happens -- one of the locations listed below, by id.
- time_of_day: dawn, day, dusk or night. Use what the story says or implies (a lit lamp, the dark sea, stars); if it never says, keep the previous scene's, or day for the first.
- atmosphere: the weather -- clear, overcast, rainy, foggy, stormy or snowy -- outside, even when the scene is indoors. Use what the story says or implies; if it never says, keep the previous scene's, or clear for the first.
- name: a short label for the scene, such as "The lamp room at night". Under 60 characters.
- description: one sentence saying what happens in the scene. It is never drawn.
"""


def build_scene_breakdown_prompt(paragraphs: list[str], locations: dict[str,LLMLocationDraft]) -> str:
    """
    Builds a prompt for splitting the story into scenes.

    Arguments:
        paragraphs: list[str] - The story's paragraphs, in order (in plain text).
        locations: dict[str,LLMLocationDraft] - Mapping between location IDs and LLM location drafts.

    Returns:
        str - Full prompt to be passed to the LLM for the scenes pass.
    """
    location_lines = "\n".join(
        f"- id: {location_id}, name: {location.name} ({location.setting.value}), description: {location.description}"
        for location_id, location in locations.items()
    )
    paragraph_lines = "\n\n".join(f"[{index}] {paragraph}" for index, paragraph in enumerate(paragraphs))
    return f"{SCENE_BREAKDOWN_INSTRUCTIONS}\nLOCATIONS:\n{location_lines}\n\nPARAGRAPHS:\n{paragraph_lines}"


SHOT_BREAKDOWN_INSTRUCTIONS = """\
You are breaking one paragraph of a story into storyboard shots. The paragraph is part of a scene, which says where and when it happens.

A shot is one visual beat — one moment, framing, and arrangement of characters that a single storyboard panel could show. Most paragraphs are a single shot. Only split a paragraph into more than one shot when it genuinely contains multiple distinct visual moments — for example, a character crossing a room and then turning to face someone is two shots; a character simply speaking a line while standing still is one.

You are given the fixed cast of this story below, each with an id, name, and appearance. You may only reference characters from this list by their id. If the paragraph describes someone not in this list (an unnamed extra, a stranger, a crowd), do not create a region for them at all — leave them out rather than inventing an id for them; mention them in the shot's details instead if they're part of what the shot looks like (e.g. "crowded with unnamed vendors"). The paragraph may refer to a cast member by any of their aliases rather than their name -- that is still that cast member, so give them a region with their id. But only give a cast member a region when the paragraph really means that person: a description like "her mother" can match a cast member's alias and still mean someone else, depending on who "her" is. If the person the paragraph means is not in the cast, leave them out of the regions. Only give a region to a character who is physically present in that moment: a voice from a radio, phone or recording, a person being remembered or imagined, or a figure of speech ("someone was out there far away, running away") is never a region -- show what can actually be seen instead.

Each region's action is used on its own to draw that one character, empty-handed, isolated on a blank background. Describe only what their body is doing: pose, gesture, and expression -- never any object at all. Objects are drawn separately and placed into the shot (see PROPS), so a hand that holds something is "fingers curled closed around nothing": write "one hand raised to the ear, fingers curled closed around nothing, frowning" for someone on the phone, not "holding a phone to her ear, frowning". Never mention the location, the weather, the scenery, or other characters in an action -- those come from the scene's location and the shot's details, and the other characters get their own regions. For example, write "climbing, pausing with a focused expression", not "climbing into the lamp room, looking out of the windows"; and write "both arms reaching forward at chest height, fingers curled closed around nothing, attentive expression", not "wrapping a blanket around Tomas's shoulders".

Anything an action mentions gets drawn into that character's image. When a character touches or holds onto someone else (an embrace, an arm around someone, holding hands), describe only this character's own body as it would look with the other person removed -- write "one arm curved outward at shoulder height, warm expression", not "wrapping an arm around the child's shoulders". Never refer to another person in an action in any form, named or not ("the child", "her friend"). The same goes for fixed parts of the scene they lean on, look through or climb: write "leaning forward with palms raised at face height", not "pressing her face against the window glass", and "stepping up with one leg raised high", not "climbing through the window frame". Pronouns count too: "his", "her", "their" or "them" pointing at anyone other than this character reads as a second person to draw, so "forehead pressed against his" draws two people. Describe only this character's own body ("head bowed forward, arms curved in front at chest height, eyes closed"), and never use words that need a second person, such as "someone", "each other", "embracing", "hugging" or "kissing".

The story's props -- objects characters hold, carry or use -- are listed below, each with an id. Give a shot a prop entry for each prop that can be seen in it. If a character in the shot is holding it, set held_by to that character's id: it is drawn in their hand (their action should say "fingers curled closed around nothing"), and its position is ignored. Otherwise set held_by to "" and give it its own position and size, like a character's -- a letter lying on a table, a lantern hanging on a hook. Props are always small next to a character: use small for anything handheld. Leave out props that aren't in the shot; never invent one that isn't listed.

The shot's location is the scene's, described below with what the camera sees facing each way (north, east, south and west). Set facing to the side the camera looks at in this shot: the side showing what the moment is about -- the view a character is looking at or walking towards, or the side behind them when they face the camera. Keep the previous shot's facing unless the camera turns; two characters talking can alternate between opposite facings, each looking towards the other. Not every shot needs a character: a beat that's really about a place or an object (an establishing shot, a close-up on something) should have an empty regions list rather than forcing a character into it.

The details field says what looks different about the location in this shot, and is drawn with the location's view as the shot's background. Use it only for small, visible, physical changes: a door open or shut, a light on or off, rain on the window, papers scattered on the floor, or unnamed figures who are not in the cast ("crowded with unnamed shoppers"). Leave it empty ("") when the place looks as described -- most shots should. Never put a mood or atmosphere ("tense", "emotionally charged"), story or backstory ("where the accident happened"), the time of day or the weather (the scene sets those), anything already in the location's description or views, or anything that would need readable text ("a clock showing 11:59") in details. Never mention one of the props in details -- props are drawn separately, on top, and would appear twice. Keep it under 150 characters. Each region's character is drawn separately and placed on top of the background, so a cast member mentioned in details appears twice: never mention a cast member in details in any form -- not by name or alias, not by a description such as "the girl", not by a pronoun ("the door behind her"), and not through something they are holding or doing. Place things relative to the frame or the room ("elevator doors open at the back of the frame"), not relative to a cast member ("the window beside him").

The images are drawn by a model that cannot render readable text. Never make words visible in details or an action: no speech or dialogue, sound effects, signs, labels, writing, or inscriptions ("a voice speaks from the radio", "a sentence carved into the desk"). Describe only the objects themselves; what is said or written belongs in the shot's description, which is never drawn.

Choose each character's orientation from what they are doing, not as a default. Characters talking to or looking at each other should face each other (one left, one right). A character walking or running away faces away from the camera, and one moving across the frame faces the direction they are moving. Use towards_camera only when the character is actually facing the viewer.

Vary the camera to suit each beat rather than defaulting to a medium, eye-level shot. Use a low angle to make a character look powerful, determined, or looming; a high angle to make them look small, vulnerable, or overwhelmed, or to show a layout from above; a wide shot when the story arrives somewhere new; and a close-up for a face, a hand or an object that matters.

You are also given the last shot of the scene so far, if any, for continuity. Keep a character's position and orientation similar to their last known position unless the text describes them moving, both from that shot and between shots of this paragraph. Copy its details word for word unless something visible in the place has changed.
"""

def build_shot_breakdown_prompt(
    paragraph: str,
    cast: dict[str,LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
    props: dict[str,LLMPropDraft] | None = None,
    scene: LLMSceneDraft | None = None,
    location: LLMLocationDraft | None = None,
) -> str:
    """
    Builds a prompt for breaking a paragraph of a scene into storyboard shots.

    Arguments:
        paragraph: str - Paragraph to be broken down (in plain text).
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and the LLM character draft.
        previous_shot: LLMShotDraft - The scene's last shot so far; used for continuity. None for a scene's first shot.
        props: dict[str,LLMPropDraft] - Mapping between prop IDs and LLM prop drafts. Defaults to None (the story has none).
        scene: LLMSceneDraft - The scene the paragraph is in. Defaults to None (not listed).
        location: LLMLocationDraft - The scene's location, with its views. Defaults to None (not listed).

    Returns:
        str - Full prompt to be passed to the LLM for shot breakdown.
    """
    cast_lines = "\n".join(
        f"- id: {cast_id}, name: {char.name}, also called: {', '.join(char.aliases) or 'no other names'}, description: {char.description}"
        for cast_id, char in cast.items()
    )
    prop_lines = "\n".join(f"- id: {prop_id}, name: {prop.name}, description: {prop.description}" for prop_id, prop in (props or {}).items()) or "none"

    scene_text = f"SCENE: {scene.name} -- {scene.description} ({scene.time_of_day.value}, {scene.atmosphere.value})" if scene else "SCENE: not given"
    if location is not None:
        view_lines = "\n".join(f"- facing {side}: {view}" for side, view in location.views.model_dump().items())
        location_text = f"LOCATION: {location.name} ({location.setting.value}) -- {location.description}\n{view_lines}"
    else:
        location_text = "LOCATION: not given"

    if previous_shot is not None:
        previous_shot_text = f"Previous shot: {previous_shot.model_dump_json()}"
    else:
        previous_shot_text = "Previous shot: none — this is the first shot of the scene."

    return (
        f"{SHOT_BREAKDOWN_INSTRUCTIONS}\n\n"
        f"CAST:\n{cast_lines}\n\n"
        f"PROPS:\n{prop_lines}\n\n"
        f"{scene_text}\n\n"
        f"{location_text}\n\n"
        f"{previous_shot_text}\n\n"
        f"PARAGRAPH:\n{paragraph}"
    )


CONTAMINATION_JUDGE_INSTRUCTIONS = """\
You are checking text that an image model will draw from, before any image is generated. Each item below is drawn on its own, and anything it mentions gets drawn:

- An action is drawn as one character alone, empty-handed, on a blank background (the item names the character). Flag it if it refers to anyone else in any form: by name or description, by a pronoun that points at someone other than this character ("his", "her", "their", "them"), or by a word that needs a second person present ("someone", "each other", "embracing", "together"). Also flag it if it mentions any object at all -- something held, carried or used (a phone, a lantern, a cup), or a fixed part of a scene (furniture, beds, chairs, desks, stairs, walls, windows, doors, vehicles, rooms or landscape). Objects are drawn separately, so a hand that holds something is described as "fingers curled closed around nothing". Gestures that need nobody and nothing else are fine ("making a kissing motion with her lips", "arms crossed").
- A description is drawn as one character standing alone, empty-handed, on a blank background. Flag it if it mentions anyone else, a place, something the character does in the story, anything they hold or carry, or a personality, demeanour, mood or facial expression (each shot gives the expression) -- it should say only how they look, including what they wear. Also flag one that offers alternatives ("a dress or a coat") or hedges ("likely", "perhaps"), and rewrite it to commit to one look.
- A prop is drawn as one object alone on a blank background. Flag it if it mentions a person, a hand, a place, a surface it rests on, another object, or something that happens to it in the story -- it should say only how the object looks. Also flag one that offers alternatives ("cream or white paper"), and rewrite it to commit to one look.
- A location is what a place has in common on every side, and a view is what is on one side of it; each is drawn as part of an empty place with nobody in it, and every shot in that place is drawn from them. Flag either if it mentions any person, named or not, or something anyone does there; a mood or atmosphere; the story's events; something temporary (time of day, weather, a door being opened); or one of the story's props (listed below -- they are drawn separately, and would appear twice). Architecture, furniture, fixtures, machinery, stairs, windows and doors are what a place is made of -- never flag those, and never take one out when rewriting something else. Only the objects listed under PROPS are props: an object that merely looks like one, or does a similar job, is part of the place and stays. Also flag a location or view that offers alternatives ("steps or a ramp"), and rewrite it to commit to one. The place's name is never drawn, so never flag an item because of its name.
- Details are drawn with their location as one shot's background, with nobody from the cast in it; cast members and props are drawn separately on top. Flag them if they mention or imply a cast member in any form -- name, description, pronoun, or something they are holding or doing -- or one of the story's props. Also flag a mood or atmosphere ("tense", "emotionally charged"), story or backstory ("where it all began"), or anything that would need readable text ("a clock showing 11:59"). Unnamed background figures who are not in the cast are fine ("crowded with unnamed shoppers"), and so are parts of the place, weather and light ("rain on the windows", "storm clouds over the sea", "the lamp switched off") -- visible changes like these are what details are for. If nothing visible is left once the problem is removed, rewrite them as an empty string.
- Any item: flag visible words (signs, writing, speech).

For every flagged item, write rewritten_text: the same text with the problem removed and everything else kept. For an action, describe this character's own body as it would look with the other person, the object or the furniture taken away -- "one arm curved outward at shoulder height, head tilted forward" for an embrace, "one hand raised to the ear, fingers curled closed around nothing" for holding a phone, "seated, knees bent, hands resting on thighs" for sitting on a bed. For a view left with nothing on that side, say so ("the side wall, plain and mostly bare"). Keep rewritten actions under 200 characters, details under 150, views under 200, and locations, props and descriptions under 300. For an item that is not flagged, set reason and rewritten_text to empty strings.

Return exactly one entry per item, using its id.
"""

_JUDGE_OWNER_LABELS = {"location": "place", "view": "place", "prop": "object"} # What an item's name is labelled as in the judge prompt -- a character's, unless listed here

def build_contamination_judge_prompt(
    items: list[tuple[str, str, str, str | None]],
    cast: dict[str,LLMCharacterDraft],
    props: dict[str,LLMPropDraft] | None = None,
) -> str:
    """
    Builds a prompt for checking text that is drawn on its own (actions, details, descriptions, props, locations and views).

    Arguments:
        items: list[tuple[str,str,str,str|None]] - (id, kind, text, name of the character, object or place it belongs to, or None) for each item to check.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts. Names and aliases are listed so the judge knows who counts as a cast member.
        props: dict[str,LLMPropDraft] - Mapping between prop IDs and LLM prop drafts, listed so the judge knows which objects are drawn separately. Defaults to None (no props).

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
    return f"{CONTAMINATION_JUDGE_INSTRUCTIONS}\nCAST:\n{cast_lines}\n\nPROPS:\n{_prop_lines(props)}\n\nITEMS:\n{item_lines}"