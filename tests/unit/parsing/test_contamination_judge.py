"""
Unit tests for contamination_judge, and for how get_shots_for_paragraph uses it.

Uses fake LLM call functions, so no LLM calls are made.
"""
import json

from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.contamination_judge import JudgeItem, judge_cast, judge_locations, judge_props, judge_texts
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMPropDraft
from taleboard.parsing.prompts import build_contamination_judge_prompt
from taleboard.parsing.shot_breakdown import MAX_RETRIES, get_shots_for_paragraph


def _make_cast() -> dict[str, LLMCharacterDraft]:
    """
    Builds a two-character cast (Alice and Bob).

    Returns:
        dict[str,LLMCharacterDraft] - Mapping of character IDs ("alice", "bob") to character drafts.
    """
    return assign_ids([
        LLMCharacterDraft(name="Alice", description="A woman in a green coat."),
        LLMCharacterDraft(name="Bob", description="A tall bearded man."),
    ])


def _verdicts(*flagged: tuple[str, str]) -> str:
    """
    Builds a judge response flagging the given items.

    Arguments:
        flagged: tuple[str,str] - (item ID, rewritten text) for each flagged item.

    Returns:
        str - Judge response (JSON).
    """
    return json.dumps({"texts": [
        {"id": item_id, "flagged": True, "reason": "test", "rewritten_text": text} for item_id, text in flagged
    ]})


def _shot(action: str, details: str = "") -> dict:
    """
    Builds a raw one-region shot for Alice, facing north.

    Arguments:
        action: str - Alice's action.
        details: str - The shot's details. Defaults to "" (none).

    Returns:
        dict - Raw shot, as the breakdown LLM returns it.
    """
    return {
        "description": action, "facing": "north", "details": details, "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
        "regions": [{"character_id": "alice", "position": "mid_center", "size": "medium", "orientation": "towards_camera", "action": action}],
    }


def test_judge_texts_returns_rewrites_only_for_flagged_known_items():
    """
    Verifies that only flagged items the judge was actually given come back as rewrites -- unflagged, unknown and empty rewrites are ignored.
    """
    items = [JudgeItem("a", "action", "hugging Bob", "Alice"), JudgeItem("b", "details", "rain on the window")]
    response = json.dumps({"texts": [
        {"id": "a", "flagged": True, "reason": "second person", "rewritten_text": "arms curved forward"},
        {"id": "b", "flagged": False, "reason": "", "rewritten_text": ""},
        {"id": "zzz", "flagged": True, "reason": "unknown id", "rewritten_text": "ignored"},
    ]})

    rewrites = judge_texts(items, _make_cast(), lambda prompt: response)

    assert rewrites == {"a": "arms curved forward"}


def test_judge_texts_fails_open_on_an_unusable_response():
    """
    Verifies that a judge response that doesn't fit the schema lets the text through unjudged, rather than failing.
    """
    rewrites = judge_texts([JudgeItem("a", "action", "waving", "Alice")], _make_cast(), lambda prompt: "not json")

    assert rewrites == {}


def test_the_judge_prompt_lists_the_cast_and_every_item():
    """
    Verifies that the judge is told who the cast is, and gets every item with its ID, kind and text.
    """
    prompt = build_contamination_judge_prompt([("s0.r0.action", "action", "hugging Bob", "Alice")], _make_cast())

    assert "Alice" in prompt and "Bob" in prompt
    assert 's0.r0.action' in prompt and '"hugging Bob"' in prompt


def test_a_flagged_action_is_rewritten_checked_again_and_keeps_its_place():
    """
    Verifies that the judge's rewrite replaces a flagged action without another breakdown call, is judged again, and the shot stays in its original place in the paragraph.
    """
    breakdown_calls: list[str] = []
    judge_responses = iter([_verdicts(("s0.r0.action", "arms curved forward at chest height")), _verdicts()])

    def call_llm(prompt: str) -> str:
        """
        Records the prompt and returns two shots, the first one leaky.

        Arguments:
            prompt: str - Prompt sent to the fake breakdown LLM.

        Returns:
            str - Breakdown response (JSON).
        """
        breakdown_calls.append(prompt)
        return json.dumps({"shots": [_shot("embracing someone tightly"), _shot("waving")]})

    results = get_shots_for_paragraph("Alice waves.", _make_cast(), None, call_llm, lambda prompt: next(judge_responses))

    assert len(breakdown_calls) == 1  # The rewrite needed no breakdown retry
    assert [r.shot.regions[0].action for r in results] == ["arms curved forward at chest height", "waving"]
    assert all(not r.needs_review for r in results)


def test_rewrites_stop_after_max_retries_and_keep_the_last_rewrite():
    """
    Verifies that a judge that flags every rewrite is called at most MAX_RETRIES + 1 times, and its last rewrite is kept.
    """
    judge_calls: list[str] = []

    def call_judge(prompt: str) -> str:
        """
        Records the prompt and flags Alice's action again, with a new rewrite each time.

        Arguments:
            prompt: str - Prompt sent to the fake judge.

        Returns:
            str - Judge response (JSON).
        """
        judge_calls.append(prompt)
        return _verdicts(("s0.r0.action", f"pose {len(judge_calls)}"))

    results = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: json.dumps({"shots": [_shot("hugging")]}), call_judge)

    assert len(judge_calls) == MAX_RETRIES + 1
    assert results[0].shot.regions[0].action == f"pose {MAX_RETRIES + 1}"
    assert results[0].needs_review is False


def test_flagged_details_are_rewritten_even_to_nothing():
    """
    Verifies that flagged details are replaced by the judge's rewrite -- including an empty rewrite, when nothing visible was left (for every other kind of text, an empty rewrite is ignored).
    """
    judge_responses = iter([_verdicts(("s0.details", "")), _verdicts()])
    raw = json.dumps({"shots": [_shot("waving", details="an emotionally charged silence")]})

    results = get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: raw, lambda prompt: next(judge_responses))

    assert results[0].shot.details == ""
    assert judge_texts([JudgeItem("a", "action", "hugging Bob", "Alice")], _make_cast(), lambda prompt: _verdicts(("a", ""))) == {}


def test_empty_details_are_not_sent_to_the_judge():
    """
    Verifies that a shot with no details only has its actions judged.
    """
    judge_prompts: list[str] = []

    def call_judge(prompt: str) -> str:
        """
        Records the prompt and flags nothing.

        Arguments:
            prompt: str - Prompt sent to the fake judge.

        Returns:
            str - Judge response (JSON).
        """
        judge_prompts.append(prompt)
        return _verdicts()

    get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: json.dumps({"shots": [_shot("waving")]}), call_judge)

    assert "s0.r0.action" in judge_prompts[0] and "s0.details" not in judge_prompts[0]


def test_judge_cast_rewrites_a_flagged_description_and_ignores_an_invalid_rewrite():
    """
    Verifies that a flagged description is replaced (and judged again), while a rewrite that fails validation (here, over 300 characters) leaves the original in place.
    """
    judge_calls: list[str] = []
    responses = iter([
        _verdicts(("alice.description", "A woman in her thirties in a green coat."), ("bob.description", "x" * 301)),
        _verdicts(),
    ])

    def call_judge(prompt: str) -> str:
        """
        Records the prompt and returns the next canned verdicts.

        Arguments:
            prompt: str - Prompt sent to the fake judge.

        Returns:
            str - Judge response (JSON).
        """
        judge_calls.append(prompt)
        return next(responses)

    cast = judge_cast(_make_cast(), call_judge)

    assert cast["alice"].description == "A woman in her thirties in a green coat."
    assert cast["bob"].description == "A tall bearded man."
    assert len(judge_calls) == 2
    assert "alice.description" in judge_calls[1] and "bob.description" not in judge_calls[1]  # Only the rewrite is judged again


def test_judge_locations_rewrites_a_flagged_location_description_labelled_as_a_place():
    """
    Verifies that a flagged location description is replaced, and that the judge is told which place (not character) the description belongs to.
    """
    judge_prompts: list[str] = []
    responses = iter([_verdicts(("office.description", "a small office with a desk and a telephone")), _verdicts()])

    def call_judge(prompt: str) -> str:
        """
        Records the prompt and returns the next canned verdicts.

        Arguments:
            prompt: str - Prompt sent to the fake judge.

        Returns:
            str - Judge response (JSON).
        """
        judge_prompts.append(prompt)
        return next(responses)

    locations = {"office": _office("the office where Alice waits for the call")}

    judged = judge_locations(locations, _make_cast(), call_judge)

    assert judged["office"].description == "a small office with a desk and a telephone"
    assert "kind: location, place: Office" in judge_prompts[0]


_VIEWS = {
    "north": "the back wall: a window above a desk",
    "east": "a side wall: a filing cabinet",
    "south": "the front wall: a door",
    "west": "the other side wall, plain and mostly bare",
}


def _office(description: str = "a small wood-panelled office", **views: str) -> LLMLocationDraft:
    return LLMLocationDraft(name="Office", setting="interior", description=description, views={**_VIEWS, **views})


def _lantern() -> dict[str, LLMPropDraft]:
    return {"lantern": LLMPropDraft(name="Lantern", description="an old brass storm lantern")}


def _recording(responses):
    """
    A fake judge that records each prompt and returns the next canned verdicts.

    Returns:
        tuple[CallLLM,list[str]] - The fake judge, and the list its prompts are appended to.
    """
    prompts: list[str] = []
    responses = iter(responses)
    return (lambda prompt: prompts.append(prompt) or next(responses)), prompts


def test_judge_locations_checks_every_view_and_rewrites_a_flagged_one():
    """
    Verifies that each of a location's views is judged as a view of that place, and that a flagged view (here, one drawing a prop) is rewritten on its own.
    """
    call_judge, prompts = _recording([_verdicts(("office.views.east", "a side wall: a filing cabinet")), _verdicts()])
    locations = {"office": _office(east="a side wall: a filing cabinet with the lantern on top")}

    judged = judge_locations(locations, _make_cast(), call_judge, _lantern())

    assert judged["office"].views.east == "a side wall: a filing cabinet"
    assert judged["office"].views.north == _VIEWS["north"]
    for side in ("north", "east", "south", "west"):
        assert f"id: office.views.{side}, kind: view, place: Office" in prompts[0]
    assert "PROPS:\n- Lantern: an old brass storm lantern" in prompts[0]


def test_a_view_rewrite_that_is_too_long_is_ignored():
    """
    Verifies that a view rewritten past its 200-character limit leaves the location as it was.
    """
    call_judge, _ = _recording([_verdicts(("office.views.west", "x" * 201))])

    judged = judge_locations({"office": _office()}, _make_cast(), call_judge)

    assert judged["office"].views.west == _VIEWS["west"]


def test_judge_props_rewrites_a_flagged_prop_labelled_as_an_object():
    """
    Verifies that a flagged prop description is replaced, judged again, and labelled as an object.
    """
    call_judge, prompts = _recording([_verdicts(("lantern.description", "an old brass storm lantern")), _verdicts()])
    props = {"lantern": LLMPropDraft(name="Lantern", description="an old brass storm lantern in Alice's hand")}

    judged = judge_props(props, _make_cast(), call_judge)

    assert judged["lantern"].description == "an old brass storm lantern"
    assert "kind: prop, object: Lantern" in prompts[0]
    assert len(prompts) == 2


def test_the_judge_prompt_lists_the_props():
    """
    Verifies that the story's props are listed for the judge, and "none" when there are none.
    """
    assert "PROPS:\n- Lantern: an old brass storm lantern" in build_contamination_judge_prompt([], _make_cast(), _lantern())
    assert "PROPS:\nnone" in build_contamination_judge_prompt([], _make_cast())


def test_a_rewrite_that_drops_one_of_a_locations_features_is_ignored():
    """
    Verifies that the judge can't lose a location's listed feature while fixing something else in the same view -- that rewrite is ignored -- while a rewrite keeping every feature goes through.
    """
    office = _office(north="the back wall: a great lens on a pedestal, in gloomy shadow", south="the front wall: a door, ominous")
    office = office.model_copy(update={"features": ["a great lens on a pedestal", "a door"]})
    call_judge, _ = _recording([
        _verdicts(("office.views.north", "the back wall: plain stone"), ("office.views.south", "the front wall: a door")),
        _verdicts(),
    ])

    judged = judge_locations({"office": office}, _make_cast(), call_judge)

    assert judged["office"].views.north == "the back wall: a great lens on a pedestal, in gloomy shadow"
    assert judged["office"].views.south == "the front wall: a door"


def test_a_shots_texts_are_judged_knowing_the_props():
    """
    Verifies that the judge checking a paragraph's shots is told the story's props -- so it can flag one written into an action or the details.
    """
    call_judge, prompts = _recording([_verdicts()])

    get_shots_for_paragraph("Alice waves.", _make_cast(), None, lambda prompt: json.dumps({"shots": [_shot("waving")]}), call_judge, props=_lantern())

    assert "PROPS:\n- Lantern: an old brass storm lantern" in prompts[0]

