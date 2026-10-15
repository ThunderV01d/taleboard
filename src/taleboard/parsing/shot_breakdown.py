"""
Manages the breakdown of paragraphs into shots.

Includes helper functions to convert from the LLM-side to the domain-side, as well as constructing fallback shots in case of failure.

Attributes:
    MAX_RETRIES: int - Number of extra rounds a shot gets -- LLM retries and judge rewrites alike -- before a fallback (or the judge's unchecked rewrite) is used.
"""
import json
import logging
import re

from dataclasses import dataclass

from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.contamination_judge import apply_shot_rewrites, judge_texts, shot_items
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMShotDraft, build_shot_draft_model
from taleboard.parsing.prompts import build_shot_breakdown_prompt
from taleboard.schema.models import Region, Shot

MAX_RETRIES = 2

@dataclass
class ShotResult:
    """
    Dataclass holding information about the shot result generated from the LLM.
    
    Attributes:
        shot: LLMShotDraft - LLMShotDraft object with all shot information from the LLM side.
        needs_review: bool - Flag for whether the shot needs to be reviewed by a human (set True in case of failure).
    """
    shot: LLMShotDraft
    needs_review: bool


def get_shots_for_paragraph(
    paragraph: str,
    cast: dict[str,LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
    call_llm: CallLLM,
    call_judge: CallLLM | None = None,
) -> list[ShotResult]:
    """
    Breaks one paragraph into shots that are then validated, and (with a judge) checked for text that would be drawn into the wrong image.

    Only the shots that fail get another round -- a shot that already passed is never touched again. A shot failing validation or the cast-name check is sent back to the breakdown LLM with the error; a shot the judge flags has the judge's rewrite applied directly and is checked again.
    Every shot keeps its place in the paragraph, however many rounds it takes. Rounds are capped at MAX_RETRIES: past that, a shot still failing validation becomes a flagged fallback, and a shot still flagged by the judge keeps the judge's latest rewrite unchecked.

    Arguments:
        paragraph: str - Paragraph (in plain text).
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.
        previous_shot: LLMShotDraft - Previous generated shot; used for context retention between shots. Defaults to None (for first shot).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).
        call_judge: CallLLM - LLM caller function for the contamination judge's output schema. Defaults to None (no judging).

    Returns:
        list[ShotResult] - List of LLM-drafted shots alongside review flags, in paragraph order.
    """
    cast_ids = list(cast.keys())
    ShotModel = build_shot_draft_model(cast_ids)
    prompt = build_shot_breakdown_prompt(paragraph, cast, previous_shot)
    pending = list(enumerate(_get_raw_shots(call_llm(prompt)))) # (slot, raw shot) -- the slot is the shot's place in the paragraph
    next_slot = len(pending)

    results: dict[int, ShotResult] = {}
    attempt = 0

    # Validation loop
    while pending:
        still_failing: list[tuple[int, dict, str]] = []
        passed: list[tuple[int, dict, LLMShotDraft]] = []
        for slot, raw_shot in pending:
            try:
                shot = ShotModel.model_validate(raw_shot)
            except ValidationError as e:
                still_failing.append((slot, raw_shot, str(e)))
                continue
            problems = _cast_leaks(shot, cast)
            if problems:
                logging.getLogger(__name__).info("Shot sent back for a retry: %s", " ".join(problems))
                still_failing.append((slot, raw_shot, " ".join(problems)))
                continue
            passed.append((slot, raw_shot, shot))

        # One judge call for every shot that passed this round
        rewrites = {}
        if call_judge is not None and passed:
            rewrites = judge_texts([item for slot, _, shot in passed for item in shot_items(slot, shot, cast)], cast, call_judge)

        next_pending: list[tuple[int, dict]] = []
        for slot, raw_shot, shot in passed:
            rewritten = apply_shot_rewrites(slot, raw_shot, rewrites)
            if rewritten is None:
                results[slot] = ShotResult(shot=shot, needs_review=False) # Since the shot succeeded this time, we don't need a human to review it
            elif attempt < MAX_RETRIES:
                next_pending.append((slot, rewritten)) # Checked again next round
            else:
                results[slot] = _accept_final_rewrite(ShotModel, rewritten, shot)

        if still_failing:
            # Retry timeout
            if attempt >= MAX_RETRIES:
                for slot, _, _ in still_failing:
                    results[slot] = ShotResult(shot=_fallback_shot(paragraph), needs_review=True) # Since the shot failed even after all permitted retries, we need a human to review it manually
            else:
                # Retry -- the LLM returns the fixed shots in the order they were sent, so each goes back to its slot
                retried = _get_raw_shots(call_llm(_build_retry_prompt([{"raw": raw, "error": error} for _, raw, error in still_failing])))
                failed_slots = [slot for slot, _, _ in still_failing]
                for index, raw_shot in enumerate(retried):
                    if index < len(failed_slots):
                        next_pending.append((failed_slots[index], raw_shot))
                    else:
                        next_pending.append((next_slot, raw_shot))
                        next_slot += 1

        pending = next_pending
        attempt += 1

    return [results[slot] for slot in sorted(results)]


def _accept_final_rewrite(ShotModel: type[LLMShotDraft], rewritten: dict, original: LLMShotDraft) -> ShotResult:
    """
    Takes the judge's rewrite of a shot when there are no rounds left to check it again.

    Arguments:
        ShotModel: type[LLMShotDraft] - The cast-constrained shot model.
        rewritten: dict - The shot with the judge's latest rewrite applied.
        original: LLMShotDraft - The last version of the shot that passed validation.

    Returns:
        ShotResult - The rewritten shot; or, if the rewrite fails validation (eg:- too long), the original flagged for review.
    """
    try:
        return ShotResult(shot=ShotModel.model_validate(rewritten), needs_review=False)
    except ValidationError:
        return ShotResult(shot=original, needs_review=True)


def find_cast_mentions(text: str, cast: dict[str,LLMCharacterDraft]) -> list[str]:
    """
    Finds cast members named in a piece of text (a shot's setting, or a region's action), by their name or any alias.
    Settings and actions are each drawn on their own -- so a cast member named in either gets drawn into the wrong image, on top of their own region.
    Single-word terms match case-sensitively, so a character called "Rose" doesn't match "rose bushes". Multi-word terms ("the old man") match in any case.
    Pronouns and plain descriptions ("the house looms before her", "the child's shoulders") can't be caught this way -- the breakdown prompt covers those.
    
    Arguments:
        text: str - Text to search.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.

    Returns:
        list[str] - The name or alias each mentioned cast member was found by (one per cast member), in cast order.
    """
    found = []
    for char in cast.values():
        for term in (char.name, *char.aliases):
            term = term.strip()
            if not term:
                continue
            flags = re.IGNORECASE if " " in term else 0
            if re.search(rf"\b{re.escape(term)}\b", text, flags):
                found.append(term)
                break # One hit per cast member is enough
    return found


def _cast_in_setting_error(mentioned: list[str]) -> str:
    """
    Builds the retry error for a setting that names cast members.

    Arguments:
        mentioned: list[str] - The names or aliases found in the setting.

    Returns:
        str - Error message, phrased as an instruction for the model.
    """
    names = ", ".join(f"'{term}'" for term in mentioned)
    return (
        f"The setting mentions cast member(s) {names}. The setting is drawn as an empty background and cast members are "
        "drawn on top from their regions, so they would appear twice. Rewrite the setting to describe only the place -- "
        "no cast members by any name, description or pronoun, and nothing they are holding or doing."
    )

def _cast_in_action_error(character_id: str, mentioned: list[str]) -> str:
    """
    Builds the retry error for a region whose action names other cast members.

    Arguments:
        character_id: str - ID of the region's own character.
        mentioned: list[str] - The other cast members' names or aliases found in the action.

    Returns:
        str - Error message, phrased as an instruction for the model.
    """
    names = ", ".join(f"'{term}'" for term in mentioned)
    return (
        f"The action for '{character_id}' mentions {names}. Each character is drawn alone on a blank background, so "
        "anyone else mentioned gets drawn into this character's image too. Rewrite the action to describe only this "
        "character's own pose as it looks with everyone else removed -- eg:- \"one arm curved outward at shoulder "
        "height\", not \"an arm around Tomas's shoulders\"."
    )


def _cast_leaks(shot: LLMShotDraft, cast: dict[str,LLMCharacterDraft]) -> list[str]:
    """
    Checks a schema-valid shot for cast members written into text that is drawn on its own -- the setting, or another character's action.

    Arguments:
        shot: LLMShotDraft - Shot to check.
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.

    Returns:
        list[str] - One retry error per problem found; empty if the shot is clean.
    """
    problems = []
    mentioned = find_cast_mentions(shot.setting, cast)
    if mentioned:
        problems.append(_cast_in_setting_error(mentioned))
    for region in shot.regions:
        others = {char_id: char for char_id, char in cast.items() if char_id != region.character_id} # A character naming themselves isn't a leak
        named = find_cast_mentions(region.action, others)
        if named:
            problems.append(_cast_in_action_error(region.character_id, named))
    return problems


def _get_raw_shots(response_text: str) -> list[dict]:
    """
    Parses the model's response into a list of shot dicts.
    
    Real per-shot validation happens afterwards, one shot at a time.

    On parsing failure, returns the raw response back -- it will be dealt with as a failure in get_shots_for_paragraph.

    Arguments:
        response_text: str - Model's response (in plain text).
    
    Returns:
        list[dict] - List of shot dicts parsed from the response text.
    """
    try:
        data = json.loads(response_text)
        return list(data["shots"])
    except (json.JSONDecodeError, KeyError, TypeError):
        return [{"_unparseable": response_text}] # Returns entire response


def _build_retry_prompt(failures: list[dict]) -> str:
    """
    Builds the prompt for the LLM to retry failed shots.

    Belongs here and not in prompts.py as it is an isolated piece run in this stage of the pipeline only -- and only in case of failure.

    Arguments:
        failures: list[dict] - List of failed shot dicts.
    
    Returns:
        str - Prompt for the LLM to retry failed shots.
    """
    lines = ["The following shots failed validation. Fix only these and "
             "return them in the same JSON shape, under a \"shots\" key.\n"]
    for i, failure in enumerate(failures, start=1):
        lines.append(f"Shot {i} you sent:\n{json.dumps(failure['raw'])}")
        lines.append(f"Error:\n{failure['error']}\n")
    return "\n".join(lines)


def _fallback_shot(paragraph: str) -> LLMShotDraft:
    """
    Builds a safe, generic shot to be used when a real one couldn't be produced even after permitted retries.

    No regions as we don't trust the failed data enough to place anyone,
    so the user sees a blank panel to fill in by hand, not a wrong one.

    Arguments:
        paragraph: str - Failing paragraph (in plain text).
    
    Returns:
        LLMShotDraft - Fallback shot draft with generic details.
    """
    # Realistically, none of these fields matter as a human will be reviewing them anyway.
    return LLMShotDraft(
        description=paragraph[:200], # Capped at our maximum description length
        setting="unknown -- needs manual review",
        shot_size="medium",
        angle="eye_level",
        duration_s=2.0,
        regions=[]
    )

def to_domain_shot(result: ShotResult, paragraph_index: int) -> Shot:
    """
    Converts a ShotResult to a domain Shot.

    Appends a paragraph index to the Shot as well -- useful bookkeeping.

    Arguments:
        result: ShotResult - ShotResult object generated by the LLM and validated in this module.
        paragraph_index: int - Index of the paragraph which the shot comes from. This is indexed against the entire story.

    Returns:
        Shot - Domain Shot object.    
    """
    draft = result.shot
    regions = [
        Region(
            character_id=r.character_id,
            position=r.position,
            size=r.size,
            orientation=r.orientation,
            action=r.action
        )
        for r in draft.regions
    ]
    return Shot(
        description=draft.description,
        setting = draft.setting,
        regions = regions,
        paragraph_index=paragraph_index,
        shot_size=draft.shot_size,
        angle=draft.angle,
        duration_s=draft.duration_s,
        needs_review=result.needs_review
    )