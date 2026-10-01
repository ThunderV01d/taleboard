import json

from taleboard.parsing.cast_extraction import assign_char_ids
from taleboard.parsing.llm_schemas import LLMCharacterDraft, build_shot_draft_model
from taleboard.parsing.shot_breakdown import get_shots_for_paragraph, ShotResult, to_domain_shot


def _make_cast() -> dict[str, LLMCharacterDraft]:
    drafts = [
        LLMCharacterDraft(name="Alice", description="..."),
        LLMCharacterDraft(name="Bob", description="..."),
    ]
    return assign_char_ids(drafts)


#character_id "carol" is not in the cast built by _make_cast(), so this fails validation against the cast-constrained schema.
INVALID_SHOT_RESPONSE = json.dumps({
    "shots": [
        {
            "description": "Alice waves at a stranger.",
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
    cast = _make_cast()
    responses = [INVALID_SHOT_RESPONSE, VALID_SHOT_RESPONSE]
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        calls.append(prompt)
        return responses[len(calls) - 1]

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 2  # initial call + one retry
    assert len(results) == 1
    assert results[0].needs_review is False
    assert results[0].shot.regions[0].character_id == "alice"


def test_get_shots_for_paragraph_falls_back_after_max_retries():
    cast = _make_cast()
    calls: list[str] = []

    def fake_call_llm(prompt: str) -> str:
        calls.append(prompt)
        return INVALID_SHOT_RESPONSE  #always invalid, never recovers

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(calls) == 3  #initial call + MAX_RETRIES (2) retries
    assert len(results) == 1
    assert results[0].needs_review is True
    assert results[0].shot.regions == []


def test_get_shots_for_paragraph_handles_unparseable_response():
    cast = _make_cast()

    def fake_call_llm(prompt: str) -> str:
        return "this is not json at all"

    results = get_shots_for_paragraph(
        paragraph="Alice waves.",
        cast=cast,
        previous_shot=None,
        call_llm=fake_call_llm,
    )

    assert len(results) == 1
    assert results[0].needs_review is True

def test_to_domain_shot_maps_fields():
    ShotModel = build_shot_draft_model(["alice", "bob"])
    draft = ShotModel.model_validate({
        "description": "Alice waves at Bob.",
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
    })
    result = ShotResult(shot=draft, needs_review=False)

    shot = to_domain_shot(result, paragraph_index=3)

    assert shot.description == "Alice waves at Bob."
    assert shot.paragraph_index == 3
    assert shot.needs_review is False
    assert len(shot.regions) == 1
    assert shot.regions[0].character_id == "alice"
    assert shot.regions[0].action == "waving"
    assert shot.regions[0].image_file is None


def test_to_domain_shot_carries_needs_review_flag():
    ShotModel = build_shot_draft_model(["alice"])
    draft = ShotModel.model_validate({
        "description": "fallback",
        "shot_size": "medium",
        "angle": "eye_level",
        "duration_s": 2.0,
        "regions": [],
    })
    result = ShotResult(shot=draft, needs_review=True)

    shot = to_domain_shot(result, paragraph_index=0)

    assert shot.needs_review is True
    assert shot.regions == []