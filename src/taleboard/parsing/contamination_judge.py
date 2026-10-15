"""
Checks text that is drawn on its own -- region actions, shot details, and character and location descriptions -- and rewrites anything that would be drawn into the wrong image.

An action or description that mentions another person draws them into that character's cutout; one that mentions a bed or a window draws a ghost of it behind them; details or a location that mention a cast member draw them twice. The breakdown prompt's rules and the cast-name check catch some of this, but not pronouns, unnamed references or furniture -- so a second LLM call judges the text and rewrites what it flags, before any image is generated.

The judge fails open: if its response can't be used, the text goes through unjudged. It is a quality layer, never a reason to fail a job.

Attributes:
    MAX_DESCRIPTION_PASSES: int - How many times rewritten character and location descriptions are judged again before the last rewrite is kept unchecked.
"""
import copy
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.cast_extraction import Draft
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMJudgeOutput, LLMLocationDraft, LLMShotDraft
from taleboard.parsing.prompts import build_contamination_judge_prompt

MAX_DESCRIPTION_PASSES = 2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeItem:
    """
    One piece of text for the judge to check.

    Attributes:
        id: str - Unique ID for this text within one judge call, eg:- "s0.details" or "s0.r1.action".
        kind: str - What the text is drawn as: "action", "details", "description" or "location".
        text: str - The text itself.
        character_name: str - Name of the character (actions and descriptions) or place (locations) it belongs to. Defaults to None.
    """
    id: str
    kind: str
    text: str
    character_name: str | None = None


def judge_texts(items: list[JudgeItem], cast: dict[str,LLMCharacterDraft], call_judge: CallLLM) -> dict[str, str]:
    """
    Asks the judge about a batch of texts, in one call.

    Arguments:
        items: list[JudgeItem] - Texts to check.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts (tells the judge who the cast is).
        call_judge: CallLLM - LLM caller function for the judge's output schema.

    Returns:
        dict[str,str] - Rewritten text for each flagged item, keyed by item ID. Empty if nothing was flagged, or if the response couldn't be used. Details may be rewritten to "" (nothing visible left); every other kind needs some text.
    """
    if not items:
        return {}
    prompt = build_contamination_judge_prompt([(item.id, item.kind, item.text, item.character_name) for item in items], cast)
    try:
        output = LLMJudgeOutput.model_validate_json(call_judge(prompt))
    except ValidationError as e:
        logger.warning("Contamination judge response unusable, so this batch goes through unjudged: %s", e)
        return {}

    known = {item.id: item for item in items}
    rewrites = {}
    for judged in output.texts:
        rewritten = judged.rewritten_text.strip()
        if judged.flagged and judged.id in known and (rewritten or known[judged.id].kind == "details"):
            logger.info("Contamination judge rewrote %s (%s): %r -> %r", judged.id, judged.reason, known[judged.id].text, rewritten)
            rewrites[judged.id] = rewritten
    return rewrites


def shot_items(slot: int, shot: LLMShotDraft, cast: dict[str,LLMCharacterDraft]) -> list[JudgeItem]:
    """
    Lists a shot's texts that are drawn on their own: its details (if it has any), and each region's action.

    Arguments:
        slot: int - The shot's position within its paragraph, used to make the item IDs unique.
        shot: LLMShotDraft - A shot that has passed validation.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.

    Returns:
        list[JudgeItem] - The shot's details, then each region's action.
    """
    items = [JudgeItem(f"s{slot}.details", "details", shot.details)] if shot.details.strip() else []
    for index, region in enumerate(shot.regions):
        items.append(JudgeItem(f"s{slot}.r{index}.action", "action", region.action, cast[region.character_id].name))
    return items


def apply_shot_rewrites(slot: int, raw_shot: dict, rewrites: dict[str, str]) -> dict | None:
    """
    Applies the judge's rewrites for one shot to a copy of its raw (as-returned) form, so it can be validated again.

    Arguments:
        slot: int - The shot's position within its paragraph (matches the IDs from shot_items).
        raw_shot: dict - The shot as the breakdown LLM returned it.
        rewrites: dict[str,str] - Rewritten text by item ID, from judge_texts.

    Returns:
        dict | None - A rewritten copy of the shot, or None if nothing in it was flagged.
    """
    prefix = f"s{slot}."
    mine = {item_id[len(prefix):]: text for item_id, text in rewrites.items() if item_id.startswith(prefix)}
    if not mine:
        return None
    rewritten = copy.deepcopy(raw_shot)
    for field, text in mine.items():
        if field == "details":
            rewritten["details"] = text
        else:  # "r<index>.action"
            rewritten["regions"][int(field.split(".")[0][1:])]["action"] = text
    return rewritten


def judge_cast(cast: dict[str,LLMCharacterDraft], call_judge: CallLLM) -> dict[str,LLMCharacterDraft]:
    """
    Checks every character description, rewriting any that would draw something besides the character.

    A description feeds the character's reference image, which every later pose is matched against -- so anything wrong in it spreads to every image of that character.

    Arguments:
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.
        call_judge: CallLLM - LLM caller function for the judge's output schema.

    Returns:
        dict[str,LLMCharacterDraft] - The cast, with flagged descriptions rewritten.
    """
    return _judge_descriptions(cast, "description", cast, call_judge)


def judge_locations(locations: dict[str,LLMLocationDraft], cast: dict[str,LLMCharacterDraft], call_judge: CallLLM) -> dict[str,LLMLocationDraft]:
    """
    Checks every location description, rewriting any that would draw something besides the empty place.

    A description feeds the location's master plate, which every background of it is drawn from -- so anything wrong in it spreads to every shot in that location.

    Arguments:
        locations: dict[str,LLMLocationDraft] - Mapping between location IDs and LLM location drafts.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts (tells the judge who the cast is).
        call_judge: CallLLM - LLM caller function for the judge's output schema.

    Returns:
        dict[str,LLMLocationDraft] - The locations, with flagged descriptions rewritten.
    """
    return _judge_descriptions(locations, "location", cast, call_judge)


def _judge_descriptions(drafts: dict[str,Draft], kind: str, cast: dict[str,LLMCharacterDraft], call_judge: CallLLM) -> dict[str,Draft]:
    """
    Checks the description of every character (or location), rewriting the ones the judge flags.

    Rewritten descriptions are judged again, up to MAX_DESCRIPTION_PASSES times; a rewrite that breaks the description's validation (eg:- too long) is ignored.

    Arguments:
        drafts: dict[str,LLMCharacterDraft|LLMLocationDraft] - Mapping between IDs and the drafts whose descriptions are checked.
        kind: str - Judge item kind: "description" for characters, "location" for locations.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts (tells the judge who the cast is).
        call_judge: CallLLM - LLM caller function for the judge's output schema.

    Returns:
        dict[str,LLMCharacterDraft|LLMLocationDraft] - The drafts, with flagged descriptions rewritten.
    """
    judged = dict(drafts)
    to_check = list(judged)
    for _ in range(MAX_DESCRIPTION_PASSES):
        items = [JudgeItem(f"{draft_id}.description", kind, judged[draft_id].description, judged[draft_id].name) for draft_id in to_check]
        rewrites = judge_texts(items, cast, call_judge)
        to_check = []
        for draft_id in list(judged):
            new_description = rewrites.get(f"{draft_id}.description")
            if new_description is None:
                continue
            try:
                judged[draft_id] = type(judged[draft_id]).model_validate({**judged[draft_id].model_dump(), "description": new_description})
                to_check.append(draft_id)
            except ValidationError:
                logger.warning("Ignored the judge's rewrite of %s's description, as it failed validation", draft_id)
        if not to_check:
            break
    return judged