"""
Unit tests for the schemas sent to Bedrock as structured output.

Bedrock rejects a whole call whose schema uses a keyword its structured output doesn't support (eg:- "minimum" on an integer) -- and every other test fakes the LLM, so nothing else would notice before a deploy.
"""
import pytest

from taleboard.parsing.llm_schemas import (
    LLMCastOutput, LLMJudgeOutput, LLMLocationsOutput, LLMPropsOutput, build_paragraph_output_model, build_scenes_output_model,
)

# Constraints Bedrock's structured output refuses (string maxLength and array minItems are accepted, and used)
UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "maxItems"}


def _keywords(schema) -> set[str]:
    """
    Every key used anywhere in a JSON schema.
    """
    if isinstance(schema, dict):
        return set(schema) | {key for value in schema.values() for key in _keywords(value)}
    if isinstance(schema, list):
        return {key for value in schema for key in _keywords(value)}
    return set()


@pytest.mark.parametrize("model", [
    LLMCastOutput, LLMPropsOutput, LLMLocationsOutput, LLMJudgeOutput,
    build_scenes_output_model(["lamp_room", "quay"]),
    build_paragraph_output_model(["mara", "tomas"], ["letter"]),
    build_paragraph_output_model(["mara"]),
], ids=["cast", "props", "locations", "judge", "scenes", "shots", "shots-without-props"])
def test_no_schema_sent_to_bedrock_uses_a_constraint_it_rejects(model):
    """
    Verifies that every output schema is free of the constraints Bedrock's structured output refuses.

    Arguments:
        model: type[BaseModel] - An output schema sent to Bedrock.
    """
    assert _keywords(model.model_json_schema()) & UNSUPPORTED == set()
