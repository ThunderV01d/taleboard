"""
Unit tests for contamination_judge, and for how get_shots_for_paragraph uses it.

Uses fake LLM call functions, so no LLM calls are made.
"""
import json

from taleboard.parsing.cast_extraction import assign_ids
from taleboard.parsing.contamination_judge import JudgeItem, judge_cast, judge_locations, judge_texts
from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft
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
    Builds a raw one-region shot for Alice, on a street.

    Arguments:
        action: str - Alice's action.
        details: str - The shot's details. Defaults to "" (none).

    Returns:
        dict - Raw shot, as the breakdown LLM returns it.
    """
    return {
        "description": action, "location_id": "street", "details": details, "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
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

    locations = {"office": LLMLocationDraft(name="Office", description="the office where Alice waits for the call")}

    judged = judge_locations(locations, _make_cast(), call_judge)

    assert judged["office"].description == "a small office with a desk and a telephone"
    assert "kind: location, place: Office" in judge_prompts[0]
