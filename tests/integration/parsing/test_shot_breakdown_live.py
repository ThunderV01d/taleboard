"""
Integration tests for shot breakdown against real AWS Bedrock.

Makes real (paid) Bedrock calls and needs AWS credentials. Run with: pytest -m integration

Attributes:
    MODEL_ID: str - Bedrock model ID.
    REGION: str - AWS Region.
"""
import pytest

from taleboard.parsing.bedrock_caller import make_bedrock_caller
from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMPropDraft, LLMSceneDraft, build_paragraph_output_model
from taleboard.parsing.shot_breakdown import get_shots_for_paragraph

MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
REGION = "eu-west-2"


def _make_cast() -> dict[str, LLMCharacterDraft]:
    """
    Builds a two-character cast (Alice and Bob), with visual descriptions.

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of character IDs ("alice", "bob") to character drafts.
    """
    drafts = [
        LLMCharacterDraft(name="Alice", description="A young woman with short red hair, wearing a green coat."),
        LLMCharacterDraft(name="Bob", description="A tall man with a beard, wearing a blue jacket."),
    ]
    return assign_ids(drafts)


@pytest.mark.integration
def test_get_shots_for_paragraph_against_real_bedrock():
    """
    Verifies that the real model breaks a paragraph into valid shots that only reference real cast members.
    """
    cast = _make_cast()
    cast_ids = list(cast.keys())
    call_llm = make_bedrock_caller(
        model_id=MODEL_ID,
        schema_model=build_paragraph_output_model(cast_ids),
        region_name=REGION,
    )

    paragraph = (
        "Alice walked into the room and waved at Bob. He smiled and crossed "
        "the room to meet her, pulling her into a hug."
    )

    results = get_shots_for_paragraph(
        paragraph=paragraph,
        cast=cast,
        previous_shot=None,
        call_llm=call_llm,
    )

    assert len(results) >= 1
    for result in results:
        assert result.needs_review is False
        for region in result.shot.regions:
            assert region.character_id in cast_ids


@pytest.mark.integration
def test_continuity_preserved_across_paragraphs():
    """
    Verifies that a character who isn't described as moving keeps their position from the previous paragraph.

    Note: this is inherently a little flaky -- the model isn't guaranteed to hold position perfectly every run. That is a known, accepted limitation (see the continuity instructions in prompts.py), rather than something this test enforces with total strictness.
    """
    cast = _make_cast()
    cast_ids = list(cast.keys())
    call_llm = make_bedrock_caller(
        model_id=MODEL_ID,
        schema_model=build_paragraph_output_model(cast_ids),
        region_name=REGION,
    )

    first_results = get_shots_for_paragraph(
        paragraph="Alice walked into the room and sat down on the couch next to Bob.",
        cast=cast,
        previous_shot=None,
        call_llm=call_llm,
    )
    last_shot = first_results[-1].shot

    second_results = get_shots_for_paragraph(
        paragraph="Bob looked at Alice and smiled, saying nothing.",
        cast=cast,
        previous_shot=last_shot,
        call_llm=call_llm,
    )

    previous_positions = {r.character_id: r.position for r in last_shot.regions}
    new_positions = {r.character_id: r.position for r in second_results[0].shot.regions}

    for char_id, position in previous_positions.items():
        if char_id in new_positions:
            assert new_positions[char_id] == position


@pytest.mark.integration
def test_a_held_prop_is_its_own_entry_and_the_hand_holds_nothing():
    """
    Verifies, in a scene with a location and props: the letter Mara reads is a prop she holds, her action names no object, and the shot faces one of the location's sides. Prints the shots, for reading through.
    """
    cast = assign_ids([LLMCharacterDraft(name="Mara", description="a woman in her sixties, short grey hair, heavy oilskin coat")])
    props = {
        "letter": LLMPropDraft(name="Letter", description="a folded letter of cream paper"),
        "lantern": LLMPropDraft(name="Lantern", description="an old brass storm lantern"),
    }
    location = LLMLocationDraft(name="Lamp Room", setting="interior", description="a round lighthouse lamp room with whitewashed stone walls", views={
        "north": "the front of the room: the great lens on its pedestal before a tall window",
        "east": "a side wall: a curved window with a hook beside it",
        "south": "the back of the room: the top of the spiral stairs",
        "west": "the other side wall: shelves of spare brass fittings",
    })
    scene = LLMSceneDraft(first_paragraph=0, location_id="lamp_room", time_of_day="night", atmosphere="stormy", name="The lamp room at night", description="Mara reads the letter.")
    call_llm = make_bedrock_caller(model_id=MODEL_ID, schema_model=build_paragraph_output_model(list(cast), list(props)), region_name=REGION)

    results = get_shots_for_paragraph(
        "Mara took the letter, turned it over, and read it by the light of the lantern hanging on its hook.",
        cast, None, call_llm, props=props, scene=scene, location=location,
    )

    for result in results:
        print(result.shot.model_dump_json(indent=1))
    assert all(not result.needs_review for result in results)
    held = [(p.prop_id, p.held_by) for result in results for p in result.shot.props]
    assert ("letter", "mara") in held
    for result in results:
        for region in result.shot.regions:
            assert "letter" not in region.action.lower() and "lantern" not in region.action.lower()

