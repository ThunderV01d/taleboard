"""
Unit tests for writing a story breakdown into a project.

Runs against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py), with a breakdown built in code -- so no LLM calls are made.

Covers the registries (with their IDs mapped across), scenes in order, and each shot's layers: background facing, characters, standing props, and props grouped with whoever holds them.
"""
import pytest

from taleboard.parsing.llm_schemas import LLMCharacterDraft, LLMLocationDraft, LLMPropDraft, LLMSceneDraft, LLMShotDraft
from taleboard.parsing.shot_breakdown import ShotResult
from taleboard.parsing.story_breakdown import SceneBreakdown, StoryBreakdown
from taleboard.parsing.story_import import write_breakdown
from taleboard.schema.enums import Facing
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer
from taleboard.schema.storyboard import Character, Location, Prop
from taleboard.storage.storyboard_store import StoryboardStore

OWNER = "mara-user"

_VIEWS = {"north": "the great lens", "east": "a window", "south": "the stairs", "west": "shelves"}


def _shot(facing: str = "north", regions: list | None = None, props: list | None = None, **fields) -> LLMShotDraft:
    return LLMShotDraft.model_validate({
        "description": "Mara reads.", "facing": facing, "details": "", "shot_size": "medium", "angle": "eye_level", "duration_s": 3.0,
        "regions": regions or [], "props": props or [], **fields,
    })


def _region(character_id: str, position: str = "mid_center", action: str = "reading") -> dict:
    return {"character_id": character_id, "position": position, "size": "medium", "orientation": "right", "action": action}


def _prop(prop_id: str, held_by: str = "", position: str = "mid_right") -> dict:
    return {"prop_id": prop_id, "position": position, "size": "small", "orientation": "towards_camera", "held_by": held_by}


def _scene(location_id: str, first: int = 0, name: str = "The lamp room") -> LLMSceneDraft:
    return LLMSceneDraft(first_paragraph=first, location_id=location_id, time_of_day="night", atmosphere="stormy", name=name, description="Mara reads.")


@pytest.fixture
def boards(aws):
    return StoryboardStore.from_env()


@pytest.fixture
def breakdown() -> StoryBreakdown:
    """
    A two-scene breakdown: the lamp room (Mara reading the letter she holds, then the lantern standing alone) and the quay (Tomas).
    """
    return StoryBreakdown(
        cast={
            "mara": LLMCharacterDraft(name="Mara", description="a woman in an oilskin coat", aliases=["the keeper"]),
            "tomas": LLMCharacterDraft(name="Tomas", description="a man in a wool coat"),
        },
        props={"letter": LLMPropDraft(name="Letter", description="a folded letter"), "lantern": LLMPropDraft(name="Lantern", description="a brass lantern")},
        locations={
            "lamp_room": LLMLocationDraft(name="Lamp Room", setting="interior", description="a round stone room", views=_VIEWS),
            "quay": LLMLocationDraft(name="Quay", setting="exterior", description="a stone quay", views=_VIEWS),
        },
        scenes=[
            SceneBreakdown(_scene("lamp_room"), [0, 1], [
                (0, ShotResult(_shot("east", [_region("mara")], [_prop("letter", held_by="mara")]), False)),
                (1, ShotResult(_shot("south", props=[_prop("lantern")], shot_size="close_up"), False)),
            ]),
            SceneBreakdown(_scene("quay", first=2, name="The quay"), [2], [(2, ShotResult(_shot(regions=[_region("tomas", "mid_left")]), False))]),
        ],
    )


def test_the_registries_are_written_with_everything_the_breakdown_says(boards, breakdown):
    """
    Verifies that each character, prop and location is written -- aliases, setting and every view included.
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id

    write_breakdown(boards, pid, breakdown)

    mara = boards.get_entry(pid, Character, "mara")
    assert (mara.description, mara.aliases) == ("a woman in an oilskin coat", ["the keeper"])
    assert {p.id for p in boards.list_entries(pid, Prop)} == {"letter", "lantern"}
    quay = boards.get_entry(pid, Location, "quay")
    assert quay.setting == "exterior"
    assert quay.views == {Facing(side): view for side, view in _VIEWS.items()}


def test_scenes_and_shots_are_written_in_story_order(boards, breakdown):
    """
    Verifies the scenes' order, location and lighting, and each scene's shots in order with their framing.
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id

    written = write_breakdown(boards, pid, breakdown)

    scenes = sorted(boards.list_scenes(pid), key=lambda s: s.order)
    assert [(s.name, s.location_id, s.time_of_day, s.atmosphere) for s in scenes] == [
        ("The lamp room", "lamp_room", "night", "stormy"), ("The quay", "quay", "night", "stormy"),
    ]
    lamp_shots = sorted(boards.list_shots(pid, scenes[0].id), key=lambda s: s.order)
    assert [(s.order, s.shot_size, s.duration_s) for s in lamp_shots] == [(0, "medium", 3.0), (1, "close_up", 3.0)]
    assert [shot.id for _, shot in written] == [*(s.id for s in lamp_shots), boards.list_shots(pid, scenes[1].id)[0].id]


def test_each_shot_is_laid_out_as_layers_with_its_facing(boards, breakdown):
    """
    Verifies a shot's layers: a background facing its way, then the character holding the letter -- grouped with it, at their hand -- and a standing prop on its own.
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id

    written = write_breakdown(boards, pid, breakdown)

    [(_, reading), (_, lantern), (_, quay)] = written
    background, group = reading.layers
    assert isinstance(background, BackgroundLayer) and background.facing == Facing.EAST
    assert isinstance(group, GroupLayer)
    mara, letter = group.children
    assert isinstance(mara, CharacterLayer) and (mara.character_id, mara.action, mara.orientation) == ("mara", "reading", "right")
    assert isinstance(letter, PropLayer) and letter.prop_id == "letter"
    assert [type(l) for l in lantern.layers] == [BackgroundLayer, PropLayer] and lantern.layers[0].facing == Facing.SOUTH
    assert quay.layers[1].character_id == "tomas"


def test_registry_ids_are_mapped_across_when_the_store_picks_its_own(boards, breakdown):
    """
    Verifies that when a name's ID is already taken in the registry (so the store gives "mara_2"), the shot's layers point at the entry actually written.
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id
    boards.create_entry(pid, Character, "Mara")  # Takes "mara"

    write_breakdown(boards, pid, breakdown)

    ids = {layer.character_id for shot in boards.list_all_shots(pid) for layer in shot.all_layers() if isinstance(layer, CharacterLayer)}
    assert "mara_2" in ids and "mara" not in ids
