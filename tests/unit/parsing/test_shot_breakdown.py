"""
Unit tests for shot_breakdown, plus the alias-related parts of prompts and llm_schemas.

Covers retries and fallbacks, what the prompt lists (cast, props, the scene and its location's views), props in shots, tidying up what the model returns, and the cast-name checks.

Uses fake LLM call functions, so no LLM calls are made.

Attributes:
    INVALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that fails validation, as its character ID is not in the cast.
    VALID_SHOT_RESPONSE: str - Fake shot breakdown response (JSON) that passes validation.
"""
import json

from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMPropDraft, LLMSceneDraft, build_shot_draft_model
from taleboard.parsing.prompts import build_shot_breakdown_prompt
from taleboard.parsing.shot_breakdown import find_cast_mentions, get_shots_for_paragraph


def _make_cast() -> dict[str, LLMCharacterDraft]:
    """
    Builds a two-character cast (Alice and Bob).

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of character IDs ("alice", "bob") to character drafts.
    """
    drafts = [
        LLMCharacterDraft(name="Alice", description="..."),
        LLMCharacterDraft(name="Bob", description="..."),
    ]
    return assign_ids(drafts)


_VIEWS = {"north": "the way ahead", "east": "a row of houses", "south": "the way back", "west": "a low wall"}


def _street() -> LLMLocationDraft:
    return LLMLocationDraft(name="Street", setting="exterior", description="a quiet street corner with a lamppost", views=_VIEWS)


def _scene() -> LLMSceneDraft:
    return LLMSceneDraft(first_paragraph=0, location_id="street", time_of_day="dusk", atmosphere="rainy", name="On the street", description="Alice meets Bob.")


def _make_props() -> dict[str, LLMPropDraft]:
    return {"umbrella": LLMPropDraft(name="Umbrella", description="a black folding umbrella"), "letter": LLMPropDraft(name="Letter", description="a folded letter")}


def _with_props(*props: dict) -> str:
    """
    VALID_SHOT_RESPONSE (Alice alone), with the given props in its shot.
    """
    response = json.loads(VALID_SHOT_RESPONSE)
    response["shots"][0]["props"] = list(props)
    return json.dumps(response)


def _prop(prop_id: str, held_by: str = "", position: str = "mid_right") -> dict:
    return {"prop_id": prop_id, "position": position, "size": "small", "orientation": "towards_camera", "held_by": held_by}


# Character ID "carol" is not in the cast built by _make_cast(), so this fails validation against the cast-constrained schema
INVALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at a stranger.",
            "facing": "north",
            "details": "",
            "shot_size": "medium",
            "angle": "eye_level",
            "duration_s": 2.0,
            "regions": [
                {
                    "character_id": "carol",
                    "position": "mid_left",
                    "size": "medium",
                    "orientation": "towards_camera",
                    "action": "waving",
                }
            ],
        }
    ]
})

VALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at Bob.",
            "facing": "north",
            "details": "",
            "shot_size": "medium",
            "angle": "eye_level",
            "duration_s": 2.0,
            "regions": [
                {
                    "character_id": "alice",
                    "position": "mid_left",
                    "size": "medium",
                    "orientation": "towards_camera",
                    "action": "waving",
                }
            ],
        }
    ]
})


def test_get_shots_for_paragraph_retries_once_and_succeeds():
    """
    Verifies that a shot failing validation is retried, and accepted without a review flag once the retry passes.
    """
    cast = _make_cast()
    responses = [INVALID_SHOT_RESPONSE, VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns an invalid response, then a valid one.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 2  # Initial call + one retry
    assert len(results) == 1
    assert results[0].needs_review is False
    assert results[0].shot.regions[0].character_id == "alice"


def test_get_shots_for_paragraph_falls_back_after_max_retries():
    """
    Verifies that a shot still failing after every permitted retry is replaced by a flagged fallback shot with no regions.
    """
    cast = _make_cast()
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and always returns an invalid response.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Invalid shot breakdown response (JSON).
        """
        calls.append(prompt)
        return INVALID_SHOT_RESPONSE  # Always invalid, never recovers

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 3  # Initial call + MAX_RETRIES (2) retries
    assert len(results) == 1
    assert results[0].needs_review is True
    assert results[0].shot.regions == []

def test_get_shots_for_paragraph_handles_unparseable_response():
    """
    Verifies that a response that isn't JSON at all ends in a flagged fallback shot, not a crash.
    """
    cast = _make_cast()

    def fake_call_llm(prompt: str) -> str:
        """
        Always returns text that is not JSON.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Unparseable response.
        """
        return "this is not json at all"

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(results) == 1
    assert results[0].needs_review is True

def test_breakdown_prompt_lists_each_cast_members_aliases():
    """
    Verifies that the shot breakdown prompt lists each cast member's aliases next to their ID.

    This is what lets the LLM resolve a reference like "the harbourmaster" to the right character.
    """
    cast = {"elias_brandt": LLMCharacterDraft(name="Elias Brandt", description="A bearded old man.",
                                              aliases=["Brandt", "the harbourmaster"])}

    prompt = build_shot_breakdown_prompt("The harbourmaster frowned.", cast, previous_shot=None)

    assert "id: elias_brandt" in prompt
    assert "also called: Brandt, the harbourmaster" in prompt


def test_aliases_are_required_for_the_llm_but_optional_in_python():
    """
    Verifies that 'aliases' is a required field in the schema sent to the LLM, while still defaulting to [] in Python.
    """
    from taleboard.parsing.llm_schemas import LLMCastOutput
    schema = LLMCastOutput.model_json_schema()
    assert "aliases" in schema["$defs"]["LLMCharacterDraft"]["required"]
    assert LLMCharacterDraft(name="Alice", description="...").aliases == []

def test_find_cast_mentions_catches_names_possessives_and_aliases_but_not_common_words():
    """
    Verifies that details naming a cast member are caught by name (possessive included) or multi-word alias, and that a single-word name doesn't match an ordinary lowercase word.
    """
    cast = {
        "eleanor": LLMCharacterDraft(name="Eleanor", description="...", aliases=["the girl"]),
        "rose": LLMCharacterDraft(name="Rose", description="..."),
    }

    assert find_cast_mentions("golden light in Eleanor's hands", cast) == ["Eleanor"]
    assert find_cast_mentions("The girl's face is pressed against the glass", cast) == ["the girl"]
    assert find_cast_mentions("a garden of rose bushes", cast) == []
    assert find_cast_mentions("an empty hallway", cast) == []


def test_details_naming_a_cast_member_are_retried_with_the_reason():
    """
    Verifies that a schema-valid shot whose details name a cast member is sent back for a retry, with an error naming who was mentioned.
    """
    cast = _make_cast()
    leaky = json.loads(VALID_SHOT_RESPONSE)
    leaky["shots"][0]["details"] = "rain falling where Alice stands waiting"
    responses = [json.dumps(leaky), VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns a shot whose details name Alice, then a clean one.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(paragraph="Alice waits.", cast=cast, previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 2
    assert "'Alice'" in calls[1]  # The retry prompt says who was mentioned
    assert results[0].needs_review is False
    assert results[0].shot.details == ""

def test_an_action_naming_another_cast_member_is_retried_but_a_character_may_name_themselves():
    """
    Verifies that a region whose action names a different cast member is sent back for a retry, while one naming its own character passes.
    """
    cast = _make_cast()
    leaky = json.loads(VALID_SHOT_RESPONSE)
    leaky["shots"][0]["regions"][0]["action"] = "waving at Bob"
    clean = json.loads(VALID_SHOT_RESPONSE)
    clean["shots"][0]["regions"][0]["action"] = "waving, Alice's hand raised high"
    responses = [json.dumps(leaky), json.dumps(clean)]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns an action naming Bob, then one naming only Alice herself.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Next canned response (JSON).
        """
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(paragraph="Alice waves.", cast=cast, previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 2
    assert "'Bob'" in calls[1]
    assert results[0].needs_review is False
    assert results[0].shot.regions[0].action == "waving, Alice's hand raised high"


def test_a_character_given_two_regions_keeps_only_the_first_without_a_retry():
    """
    Verifies that a duplicate region for the same character is dropped (keeping the first), without another LLM call or a review flag.
    """
    duplicated = json.loads(VALID_SHOT_RESPONSE)
    first = duplicated["shots"][0]["regions"][0]
    duplicated["shots"][0]["regions"].append({**first, "position": "mid_right", "action": "waving again"})
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        """
        Records the prompt and returns a shot with Alice in it twice.

        Arguments:
            prompt: str - Prompt sent to the fake LLM.

        Returns:
            str - Shot breakdown response (JSON).
        """
        calls.append(prompt)
        return json.dumps(duplicated)

    results = get_shots_for_paragraph(paragraph="Alice waves.", cast=_make_cast(), previous_shot=None, call_llm=fake_call_llm)

    assert len(calls) == 1
    assert [(r.character_id, r.action) for r in results[0].shot.regions] == [("alice", "waving")]
    assert results[0].needs_review is False


def test_the_prompt_lists_the_props_the_scene_and_what_each_facing_shows():
    """
    Verifies that the shot prompt gives the model the props by ID, the scene with its time and weather, and the location's view for every facing.
    """
    prompt = build_shot_breakdown_prompt("Alice waves.", _make_cast(), None, _make_props(), _scene(), _street())

    assert "id: umbrella, name: Umbrella, description: a black folding umbrella" in prompt
    assert "SCENE: On the street -- Alice meets Bob. (dusk, rainy)" in prompt
    assert "LOCATION: Street (exterior) -- a quiet street corner with a lamppost" in prompt
    for side, view in _VIEWS.items():
        assert f"- facing {side}: {view}" in prompt
    assert "first shot of the scene" in prompt


def test_a_story_without_props_says_so():
    """
    Verifies that the prompt lists no props as "none".
    """
    assert "PROPS:\nnone" in build_shot_breakdown_prompt("Alice waves.", _make_cast(), None)


def test_a_shot_keeps_its_facing_and_props_held_or_standing():
    """
    Verifies that a shot's facing and props come through: one held by a character in the shot, one standing on its own.
    """
    response = json.loads(_with_props(_prop("umbrella", held_by="alice"), _prop("letter")))
    response["shots"][0]["facing"] = "east"

    [result] = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: json.dumps(response), props=_make_props())

    assert result.shot.facing == "east"
    assert [(p.prop_id, p.held_by) for p in result.shot.props] == [("umbrella", "alice"), ("letter", "")]


def test_unknown_and_duplicate_props_are_dropped_and_a_holder_not_in_the_shot_puts_theirs_down():
    """
    Verifies the tidy-up, with no retry or review flag: a prop that isn't the story's is dropped, a second entry for a prop is dropped, and a prop held by someone with no region in the shot (in the cast or not) stands on its own instead.
    """
    calls: list[str] = []
    response = _with_props(_prop("umbrella", held_by="bob"), _prop("umbrella", held_by="alice"), _prop("teapot"))

    [result] = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: calls.append(prompt) or response, props=_make_props())

    assert len(calls) == 1 and result.needs_review is False
    assert [(p.prop_id, p.held_by) for p in result.shot.props] == [("umbrella", "")]


def test_a_story_without_props_drops_any_the_model_invents():
    """
    Verifies that a shot listing props in a story with none keeps its characters and loses the props, without a retry.
    """
    calls: list[str] = []

    [result] = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: calls.append(prompt) or _with_props(_prop("umbrella")))

    assert len(calls) == 1
    assert result.shot.props == [] and result.shot.regions[0].character_id == "alice"


def test_a_fallback_shot_faces_where_the_scene_last_did():
    """
    Verifies that a shot that never validates falls back to the scene's last facing (north for its first shot), with no characters or props.
    """
    previous = build_shot_draft_model(["alice", "bob"]).model_validate({**json.loads(VALID_SHOT_RESPONSE)["shots"][0], "facing": "south"})

    [first] = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: INVALID_SHOT_RESPONSE)
    [later] = get_shots_for_paragraph("Alice waves.", _make_cast(), previous, lambda prompt: INVALID_SHOT_RESPONSE)

    assert (first.shot.facing, later.shot.facing) == ("north", "south")
    assert later.needs_review and later.shot.regions == [] and later.shot.props == []


def test_props_are_required_for_the_llm_but_optional_in_python():
    """
    Verifies that 'props' is a required field of a shot in the schema sent to the LLM, while still defaulting to [] in Python.
    """
    model = build_shot_draft_model(["alice"], ["umbrella"])
    assert "props" in model.model_json_schema()["required"]
    assert model.model_validate({**json.loads(VALID_SHOT_RESPONSE)["shots"][0]}).props == []
