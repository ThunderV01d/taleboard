"""
Integration test for extracting a story's cast, props and locations (with their views), and judging them, against real AWS Bedrock.

Makes real (paid, about a cent) Bedrock calls and needs AWS credentials. Run with: pytest -m integration -s tests/integration/parsing/test_extraction_live.py -- -s prints everything extracted, for reading through.

Attributes:
    MODEL_ID: str - Bedrock model ID.
    REGION: str - AWS Region.
    STORY: str - A story with two characters, objects they hold (a lantern, a letter), and two places: a lighthouse lamp room (interior) and a quay (exterior).
"""
import pytest

from taleboard.parsing.bedrock_caller import make_bedrock_caller
from taleboard.parsing.cast_extraction import extract_cast
from taleboard.parsing.contamination_judge import judge_cast, judge_locations, judge_props
from taleboard.parsing.llm_schemas import LLMCastOutput, LLMJudgeOutput, LLMLocationsOutput, LLMPropsOutput
from taleboard.parsing.location_extraction import extract_locations
from taleboard.parsing.prop_extraction import extract_props

MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-2"

STORY = """\
Mara climbed the last turn of the spiral stairs into the lamp room, an old
brass storm lantern swinging from her hand. The great lens sat silent on its
pedestal. She hung the lantern on a hook by the window and looked out at the
dark sea.

Below, on the quay, Tomas waited by the bollards with a letter in his coat
pocket. The fishing boats knocked against the stone in the swell. When Mara
came down, he pulled out the letter and held it out to her without a word.

She took it, turned it over, and read it by the light of the lantern.
"""


def _caller(schema):
    return make_bedrock_caller(model_id=MODEL_ID, schema_model=schema, region_name=REGION)


@pytest.mark.integration
def test_extract_cast_props_and_locations_against_real_bedrock():
    """
    A smoke test: checks only what must always hold -- the lantern and the letter are props (and in no one's description and no place), the lens is not a prop, each place has a setting and a view for every side, and nothing hedges or names a compass direction. How good the views are (which features made it onto which side) varies from run to run, so it isn't asserted -- read the printout.

    Prints what each extraction returned before the judge, then after -- so a missing feature can be traced to one or the other.
    """
    call_judge = _caller(LLMJudgeOutput)
    raw_cast = extract_cast(STORY, _caller(LLMCastOutput))
    cast = judge_cast(raw_cast, call_judge)
    raw_props = extract_props(STORY, _caller(LLMPropsOutput))
    props = judge_props(raw_props, cast, call_judge)
    raw_locations = extract_locations(STORY, _caller(LLMLocationsOutput), props)
    locations = judge_locations(raw_locations, cast, call_judge, props)

    print("\n--- Before the judge ---")
    for location_id, location in raw_locations.items():
        print(f"LOCATION {location_id} ({location.setting.value}): {location.description}")
        print(f"    features: {location.features}")
        for side, view in location.views.model_dump().items():
            print(f"    {side}: {view}")
    for draft_id, draft in {**raw_cast, **raw_props}.items():
        print(f"{draft_id}: {draft.description}")
    print("--- After the judge ---")

    for character_id, character in cast.items():
        print(f"CHARACTER {character_id}: {character.description}")
    for prop_id, prop in props.items():
        print(f"PROP {prop_id}: {prop.description}")
    for location_id, location in locations.items():
        print(f"LOCATION {location_id} ({location.setting.value}): {location.description}")
        for side, view in location.views.model_dump().items():
            print(f"    {side}: {view}")

    prop_names = " ".join(prop.name.lower() for prop in props.values())
    assert "lantern" in prop_names and "letter" in prop_names
    assert "lens" not in prop_names  # A fixture of the lamp room, however important
    for character in cast.values():
        assert "lantern" not in character.description.lower() and "letter" not in character.description.lower()

    settings = {location.setting.value for location in locations.values()}
    assert settings == {"interior", "exterior"}  # The lamp room, and the quay
    for location in locations.values():
        texts = [location.description, *location.views.model_dump().values()]
        assert all(text.strip() for text in texts)
        assert not any("lantern" in text.lower() or "letter" in text.lower() for text in texts)
        assert not any(text.lower().startswith(("north", "east", "south", "west", "the north", "the east", "the south", "the west")) for text in texts)
        assert not any(" or " in text.lower() for text in texts)

    for character in cast.values():
        assert not any(word in character.description.lower() for word in ("demeanor", "demeanour", "expression", " or ", "likely", "perhaps"))
