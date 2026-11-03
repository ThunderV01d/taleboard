"""
Manages the prop-extraction part of the pipeline -- the objects the story's characters hold, carry or use.

Characters are always drawn empty-handed, so every object they hold is a prop: drawn on its own, from one fixed visual description, and placed into each shot as a layer of its own. Each prop gets an ID the same way each character does.

Props are extracted before locations, so that locations (and their views) can be told to leave them out -- otherwise a prop would be drawn twice, once in the background and once as its own layer.

Attributes:
    PROP_RETRIES: int - Number of times a prop list that fails validation is sent to the model with the error, before giving up.
"""
from pydantic import ValidationError

from taleboard.parsing.bedrock_caller import CallLLM
from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMPropDraft, LLMPropsOutput
from taleboard.parsing.prompts import build_prop_extraction_prompt

PROP_RETRIES = 1


def extract_props(story_text: str, call_llm: CallLLM) -> dict[str, LLMPropDraft]:
    """
    Extracts every prop from the story. A story may have none.

    Raises a ValueError if the story is empty.

    Arguments:
        story_text: str - Entire story (in plain text).
        call_llm: CallLLM - LLM caller function (usually comes from bedrock_caller or is mocked during testing).

    Returns:
        dict[str,LLMPropDraft] - Mapping of unique prop IDs to each prop catalogued by the LLM, in story order.
    """
    if not story_text.strip():
        raise ValueError("Story is empty -- there are no props to extract.")
    prompt = build_prop_extraction_prompt(story_text)
    for attempt in range(PROP_RETRIES + 1):
        response_text = call_llm(prompt)
        try:
            output = LLMPropsOutput.model_validate_json(response_text)
            return assign_ids(output.props)
        except ValidationError as e:
            if attempt == PROP_RETRIES:
                raise
            prompt = _build_props_retry_prompt(response_text, e)


def _build_props_retry_prompt(response_text: str, error: ValidationError) -> str:
    """
    Builds the prompt for the LLM to fix a prop list that failed validation (eg:- a description over the length limit).

    Arguments:
        response_text: str - The model's failing response.
        error: ValidationError - Why it failed.

    Returns:
        str - Prompt for the LLM to retry the props.
    """
    return (
        "The prop list you sent failed validation. Fix it and return the whole list again, in the same JSON shape, "
        "under a \"props\" key. Keep every prop; shorten any description that is too long, keeping only how the object "
        f"looks.\n\nProps you sent:\n{response_text}\n\nError:\n{error}"
    )