import pytest

from taleboard.parsing.bedrock_caller import make_bedrock_caller
from taleboard.parsing.cast_extraction import extract_cast
from taleboard.parsing.llm_schemas import LLMCastOutput

MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-2"

STORY = """\
Alice walked into the cafe, her short red hair catching the afternoon light
as she scanned the room. She wore a green coat against the autumn chill. A
waiter passed by carrying a tray of coffee cups, barely glancing at her.

In the corner, Bob sat reading a newspaper. He was tall, with a thick beard
and a battered blue jacket slung over the back of his chair. Alice spotted
him and waved. Bob looked up, smiled, and waved back.
"""


@pytest.mark.integration
def test_extract_cast_against_real_bedrock():
    call_llm = make_bedrock_caller(
        model_id=MODEL_ID,
        schema_model=LLMCastOutput,
        region_name=REGION,
    )

    cast = extract_cast(story_text=STORY, call_llm=call_llm)

    names = {c.name.lower() for c in cast.values()}
    assert "alice" in names
    assert "bob" in names
    # The unnamed waiter should be left out entirely, per the prompt's instruction -- not invented as a third character.
    assert len(cast) == 2