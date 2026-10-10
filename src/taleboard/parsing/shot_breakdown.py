"""
Manages the breakdown of paragraphs into shots.

Includes helper functions to convert from the LLM-side to the domain-side, as well as constructing fallback shots in case of failure.

Attributes:
    MAX_RETRIES: int - Number of retries before switching to a generic fallback shot.
"""
import json
from dataclasses import dataclass

from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
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
    call_llm: CallLLM
) -> list[ShotResult]:
    """
    Breaks one paragraph into shots that are then validated.
    
    Only the shots that fail validation get retried -- a shot that already passed is never touched again.

    Arguments:
        paragraph: str - Paragraph (in plain text).
        cast: dict[str,LLMCharacterDraft] - Mapping between character IDs and LLM character drafts.
        previous_shot: LLMShotDraft - Previous generated shot; used for context retention between shots. Defaults to None (for first shot).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        list[ShotResult] - List of LLM-drafted shots alongside review flags.
    """
    cast_ids = list(cast.keys())
    ShotModel = build_shot_draft_model(cast_ids)
    prompt = build_shot_breakdown_prompt(paragraph, cast, previous_shot)
    pending = _get_raw_shots(call_llm(prompt))

    results: list[ShotResult] = []
    attempt = 0

    # Validation loop
    while pending:
        still_failing: list[dict] = []
        for raw_shot in pending:
            try:
                shot = ShotModel.model_validate(raw_shot)
                results.append(ShotResult(shot=shot, needs_review=False)) # Since the shot succeeded this time, we don't need a human to review it
            except ValidationError as e:
                still_failing.append({"raw": raw_shot, "error": str(e)})

        if not still_failing:
            break # No shots failed after retry; free to exit the loop
        
        # Retry timeout 
        if attempt >= MAX_RETRIES:
            for failure in still_failing:
                results.append(ShotResult(
                    shot=_fallback_shot(paragraph), needs_review=True)) # Since the shot failed even after all permitted retries, we need a human to review it manually
            break # Because we handled the failed shots using our fallback; free to exit the loop

        # Retry
        retry_prompt = _build_retry_prompt(still_failing)
        pending = _get_raw_shots(call_llm(retry_prompt))
        attempt += 1

    return results


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