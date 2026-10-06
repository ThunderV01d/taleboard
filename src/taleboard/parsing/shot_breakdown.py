import json
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMShotDraft, build_shot_draft_model
from taleboard.parsing.prompts import build_shot_breakdown_prompt
from taleboard.schema.models import Region, Shot

MAX_RETRIES = 2

#Takes a prompt string, returns the model's raw text response.
CallLLM = Callable[[str], str]


@dataclass
class ShotResult:
    shot: BaseModel
    needs_review: bool


def get_shots_for_paragraph(
    paragraph: str,
    cast: dict[str, LLMCharacterDraft],
    previous_shot: LLMShotDraft | None,
    call_llm: CallLLM
) -> list[ShotResult]:
    """Break one paragraph into validated shots. Only the shots that fail
    validation get retried; a shot that already passed is never touched
    again.
    """
    cast_ids = list(cast.keys())
    ShotModel = build_shot_draft_model(cast_ids)

    prompt = build_shot_breakdown_prompt(paragraph, cast, previous_shot)
    pending = _get_raw_shots(call_llm(prompt))

    results: list[ShotResult] = []
    attempt = 0

    while pending:
        still_failing: list[dict] = []

        for raw_shot in pending:
            try:
                shot = ShotModel.model_validate(raw_shot)
                results.append(ShotResult(shot=shot, needs_review=False))
            except ValidationError as e:
                still_failing.append({"raw": raw_shot, "error": str(e)})

        if not still_failing:
            break
        if attempt >= MAX_RETRIES:
            for failure in still_failing:
                results.append(ShotResult(
                    shot=_fallback_shot(paragraph),
                    needs_review=True
                ))
            break

        retry_prompt = _build_retry_prompt(still_failing)
        pending = _get_raw_shots(call_llm(retry_prompt))
        attempt += 1

    return results


def _get_raw_shots(response_text: str) -> list[dict]:
    """Parse the model's response into a list of shot dicts.
    Real per-shot validation happens afterwards, one shot at a time.
    """
    try:
        data = json.loads(response_text)
        return list(data["shots"])
    except (json.JSONDecodeError, KeyError, TypeError):
        # Nothing usable to split into individual shots — treat the
        # whole paragraph as one failure to retry/fallback on.
        return [{"_unparseable": response_text}]


def _build_retry_prompt(failures: list[dict]) -> str:
    lines = ["The following shots failed validation. Fix only these and "
             "return them in the same JSON shape, under a \"shots\" key.\n"]
    for i, failure in enumerate(failures, start=1):
        lines.append(f"Shot {i} you sent:\n{json.dumps(failure['raw'])}")
        lines.append(f"Error:\n{failure['error']}\n")
    return "\n".join(lines)


def _fallback_shot(paragraph: str) -> LLMShotDraft:
    """A safe, generic shot used when a real one couldn't be produced.
    No regions as we don't trust the failed data enough to place anyone,
    so the user sees a blank panel to fill in by hand, not a wrong one.
    """
    return LLMShotDraft(
        description=paragraph[:200],
        setting="unknown -- needs manual review",
        shot_size="medium",
        angle="eye_level",
        duration_s=2.0,
        regions=[]
    )

def to_domain_shot(result: ShotResult, paragraph_index: int) -> Shot:
    """Converts a ShotResult to a domain Shot."""
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