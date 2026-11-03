"""
Manages the location-extraction part of the pipeline -- the places the story's shots take place in.

Each location gets an ID, a setting (interior or exterior), a description of what the whole place has in common, and a view of what's on each of its four sides -- each side is drawn as its own plate. The model first lists the fixed features the story puts in the place; one that ends up on no side is sent back to be placed (once -- after that the location is kept as it is, as a missing feature isn't worth failing a story over). Shots then refer to a location by its ID, so every shot in the same place is drawn from the same plates, however the paragraph words it.

Attributes:
    LOCATION_RETRIES: int - Number of times a location list that fails validation, or leaves a feature off every side, is sent back to the model before giving up (or, for a feature, keeping it as it is).
"""
import logging
import re

from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMLocationDraft, LLMLocationsOutput, LLMPropDraft
from taleboard.parsing.prompts import build_location_extraction_prompt

LOCATION_RETRIES = 1

logger = logging.getLogger(__name__)


def extract_locations(story_text: str, call_llm: CallLLM, props: dict[str, LLMPropDraft] | None = None) -> dict[str, LLMLocationDraft]:
    """
    Extracts every location from the story.

    Raises a ValueError if the story is empty.

    Arguments:
        story_text: str - Entire story (in plain text).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).
        props: dict[str,LLMPropDraft] - Mapping between prop IDs and LLM prop drafts, which the locations must leave out (they're drawn separately). Defaults to None (no props).

    Returns:
        dict[str,LLMLocationDraft] - Mapping of unique location IDs to each location catalogued by the LLM, in story order.
    """
    if not story_text.strip():
        raise ValueError("Story is empty -- there are no locations to extract.")
    prompt = build_location_extraction_prompt(story_text, props)
    for attempt in range(LOCATION_RETRIES + 1):
        response_text = call_llm(prompt)
        try:
            output = LLMLocationsOutput.model_validate_json(response_text)
        except ValidationError as e:
            if attempt == LOCATION_RETRIES:
                raise
            prompt = _build_locations_retry_prompt(response_text, e)
            continue
        unplaced = {location.name: missing for location in output.locations if (missing := unplaced_features(location))}
        if unplaced and attempt < LOCATION_RETRIES:
            prompt = _build_placement_retry_prompt(response_text, unplaced)
            continue
        if unplaced:
            logger.warning("Kept locations with features on no side: %s", unplaced)
        return assign_ids(output.locations)


def unplaced_features(location: LLMLocationDraft) -> list[str]:
    """
    The features a location lists that its description and views never mention -- matched on each feature's last word (its noun, so "a great lens on a pedestal" needs "pedestal", and "spiral stairs" needs "stair").

    Arguments:
        location: LLMLocationDraft - A location that has passed validation.

    Returns:
        list[str] - Its unplaced features, in the order it listed them. Empty if every feature is on some side.
    """
    text = " ".join([location.description, *location.views.model_dump().values()]).lower()
    return [feature for feature in location.features if feature_noun(feature) not in text]


def feature_noun(feature: str) -> str:
    """
    A feature's last word, without a plural "s" -- "" (always found) if it has no words.
    """
    words = re.findall(r"[a-z]+", feature.lower())
    word = words[-1] if words else ""
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _build_placement_retry_prompt(response_text: str, unplaced: dict[str, list[str]]) -> str:
    """
    Builds the prompt for the LLM to put features it listed for a location onto that location's sides.

    Arguments:
        response_text: str - The model's response.
        unplaced: dict[str,list[str]] - The features on no side, by location name.

    Returns:
        str - Prompt for the LLM to retry the locations.
    """
    missing = "\n".join(f"- {name}: {', '.join(features)}" for name, features in unplaced.items())
    return (
        "In the location list you sent, some features you listed are not in any view. Put each one into the view of the "
        "side where it stands (a feature in the middle of the place goes in the north view), keeping everything else, and "
        "return the whole list again, in the same JSON shape, under a \"locations\" key.\n\n"
        f"Features on no side:\n{missing}\n\nLocations you sent:\n{response_text}"
    )


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
        "under a \"locations\" key. There must be at least one location, each with a view for every side; shorten any "
        f"description or view that is too long, keeping only how the place looks.\n\nLocations you sent:\n{response_text}\n\nError:\n{error}"
    )