"""
Manages the location-extraction part of the pipeline -- the places the story's shots take place in.

Each location gets an ID and one fixed visual description, the same way each character does. Shots then refer to a location by its ID, so every shot in the same place is drawn from the same description (and the same master plate), however the paragraph words it.

Attributes:
    LOCATION_RETRIES: int - Number of times a location list that fails validation is sent to the model with the error, before giving up.
"""
from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMLocationDraft, LLMLocationsOutput
from taleboard.parsing.prompts import build_location_extraction_prompt
from taleboard.schema.models import Location

LOCATION_RETRIES = 1


def extract_locations(story_text: str, call_llm: CallLLM) -> dict[str, LLMLocationDraft]:
    """
    Extracts every location from the story.

    Raises a ValueError if the story is empty.

    Arguments:
        story_text: str - Entire story (in plain text).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        dict[str,LLMLocationDraft] - Mapping of unique location IDs to each location catalogued by the LLM, in story order.
    """
    if not story_text.strip():
        raise ValueError("Story is empty -- there are no locations to extract.")
    prompt = build_location_extraction_prompt(story_text)
    for attempt in range(LOCATION_RETRIES + 1):
        response_text = call_llm(prompt)
        try:
            output = LLMLocationsOutput.model_validate_json(response_text)
            return assign_ids(output.locations)
        except ValidationError as e:
            if attempt == LOCATION_RETRIES:
                raise
            prompt = _build_locations_retry_prompt(response_text, e)


def _build_locations_retry_prompt(response_text: str, error: ValidationError) -> str:
    """
    Builds the prompt for the LLM to fix a location list that failed validation (eg:- a description over the length limit, or no locations at all).

    Arguments:
        response_text: str - The model's failing response.
        error: ValidationError - Why it failed.

    Returns:
        str - Prompt for the LLM to retry the locations.
    """
    return (
        "The location list you sent failed validation. Fix it and return the whole list again, in the same JSON shape, "
        "under a \"locations\" key. There must be at least one location; shorten any description that is too long, keeping "
        f"only how the place looks.\n\nLocations you sent:\n{response_text}\n\nError:\n{error}"
    )


def to_domain_location(draft: LLMLocationDraft) -> Location:
    """
    Converts an LLMLocationDraft to a domain Location, with no master plate yet.

    Arguments:
        draft: LLMLocationDraft - An LLMLocationDraft object.

    Returns:
        Location - A Location object.
    """
    return Location(name=draft.name, description=draft.description)