"""
Unit tests for project_store and the persistent caches.

Runs against moto's in-memory fakes of DynamoDB and S3, so no AWS calls are made and no credentials are needed.

Attributes:
    TABLE: str - Name of the fake DynamoDB table.
    BUCKET: str - Name of the fake S3 bucket.
    REGION: str - AWS Region of both.
"""
import io

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from taleboard.rendering.shot_renderer import render_shot
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Region, Shot
from taleboard.storage.caches import PersistentBackgroundCache, PersistentPoseCache, PersistentReferenceCache
from taleboard.storage.project_store import ProjectStore, background_cache_sk, image_s3_key, pose_cache_sk, project_pk, shot_sk

TABLE = "taleboard-test"
BUCKET = "taleboard-test-images"
REGION = "eu-west-2"


@pytest.fixture
def store(monkeypatch):
    """
    Creates a fake table and bucket, and yields a ProjectStore connected to them.

    Fake credentials are set so that nothing can ever reach a real AWS account.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to set fake AWS credentials.

    Returns:
        ProjectStore - A store backed by the fakes.
    """
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}, {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        yield ProjectStore(TABLE, BUCKET, REGION)


def _png(color: tuple[int, int, int, int] = (255, 0, 0, 255)) -> bytes:
    """
    Builds a small, solid-colour image.

    Arguments:
        color: tuple[int,int,int,int] - Colour of the image (RGBA). Defaults to opaque red.

    Returns:
        bytes - Image file (PNG, in bytes).
    """
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(index: int, regions: list[Region] | None = None) -> Shot:
    """
    Builds a shot whose description and setting carry its index.

    Arguments:
        index: int - Index used in the description and setting.
        regions: list[Region] - Character regions of the shot. Defaults to None (no regions).

    Returns:
        Shot - A Shot object.
    """
    return Shot(description=f"shot {index}", setting=f"setting {index}", regions=regions or [], paragraph_index=index,
                shot_size=ShotSize.MEDIUM, angle=CameraAngle.EYE_LEVEL, duration_s=2.5)


def _region(character_id: str = "alice") -> Region:
    """
    Builds a centred, camera-facing, standing region.

    Arguments:
        character_id: str - Character ID of the region. Defaults to "alice".

    Returns:
        Region - A Region object.
    """
    return Region(character_id=character_id, position=PositionCell.MID_CENTER, size=SizeInFrame.MEDIUM,
                  orientation=Orientation.LEFT, action="standing")


def _raw_items(store: ProjectStore, project_id: str) -> dict[str, dict]:
    """
    Reads every DynamoDB item in a project directly, bypassing ProjectStore.

    Arguments:
        store: ProjectStore - Store whose table is read.
        project_id: str - Unique project ID.

    Returns:
        dict[str,dict] - Mapping of sort keys to raw items.
    """
    response = store._table.query(KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(project_pk(project_id)))
    return {item["SK"]: item for item in response["Items"]}


def test_shot_sort_keys_are_zero_padded_so_they_sort_in_story_order():
    """
    Verifies that shot sort keys sort the same way as the shot indices they encode.
    """
    assert shot_sk(7) == "SHOT#0007"
    assert sorted([shot_sk(10), shot_sk(2), shot_sk(0)]) == [shot_sk(0), shot_sk(2), shot_sk(10)]


def test_cache_sort_keys_hash_free_form_text():
    """
    Verifies that cache sort keys hash the setting and action, are stable, and match the planned layout.
    """
    long_setting = "a narrow city alley at night, wet cobblestones, a single flickering streetlamp " * 5
    key = background_cache_sk(long_setting, "wide", "low")

    assert key == background_cache_sk(long_setting, "wide", "low")
    assert long_setting not in key and len(key) < 60
    assert key.startswith("BGCACHE#") and key.endswith("#wide#low")
    assert pose_cache_sk("alice", "waving", "left", "eye_level").startswith("POSECACHE#alice#")
    assert pose_cache_sk("alice", "waving", "left", "eye_level").endswith("#left#eye_level")


def test_project_round_trips_through_dynamodb(store):
    """
    Verifies that a saved project loads back with the same metadata, cast and shots, with shots in story order.

    Twelve shots are saved, so string ordering of unpadded indices (eg:- "10" before "2") would show up here.
    """
    project = store.create_project("Lighthouse")
    cast = {"alice": Character(name="Alice", description="A woman.", aliases=["Al"]), "bob": Character(name="Bob", description="A man.")}
    shots = [_shot(i, [_region()] if i % 2 else []) for i in range(12)]
    store.save_characters(project.project_id, cast)
    store.save_shots(project.project_id, shots)

    loaded = store.load_project(project.project_id)

    assert loaded.name == "Lighthouse"
    assert loaded.created_at == project.created_at
    assert loaded.cast == cast
    assert loaded.shots == shots


def test_load_project_rejects_an_unknown_id(store):
    """
    Verifies that loading a project that doesn't exist raises a KeyError.
    """
    with pytest.raises(KeyError):
        store.load_project("does-not-exist")


def test_save_shot_replaces_one_shot_in_place(store):
    """
    Verifies that saving one shot replaces it at its position, leaving the others alone.
    """
    project = store.create_project("Lighthouse")
    store.save_shots(project.project_id, [_shot(0), _shot(1)])

    store.save_shot(project.project_id, 1, _shot(1).model_copy(update={"needs_review": True}))

    loaded = store.load_project(project.project_id)
    assert [s.needs_review for s in loaded.shots] == [False, True]


def test_background_cache_misses_then_hits_across_separate_cache_objects(store):
    """
    Verifies that a cached background is found by a brand-new cache object -- as a later, stateless Lambda invocation would create.
    """
    project = store.create_project("Lighthouse")
    key = ("an empty hallway", "medium", "eye_level")

    assert PersistentBackgroundCache(store, project.project_id).get(key) is None
    PersistentBackgroundCache(store, project.project_id)[key] = _png()

    assert PersistentBackgroundCache(store, project.project_id).get(key) == _png()


def test_cached_image_lives_in_s3_with_dynamodb_pointing_at_it(store):
    """
    Verifies the storage split: the image bytes go to S3, and the DynamoDB item only holds the S3 key.
    """
    project = store.create_project("Lighthouse")
    key = ("alice", "waving", "left", "eye_level")
    PersistentPoseCache(store, project.project_id)[key] = _png()

    sort_key = pose_cache_sk(*key)
    item = _raw_items(store, project.project_id)[sort_key]
    assert set(item) == {"PK", "SK", "s3_key"}
    assert item["s3_key"] == image_s3_key(project.project_id, sort_key)
    assert store._read_s3(item["s3_key"]) == _png()


def test_caches_are_scoped_to_their_project(store):
    """
    Verifies that the same cache key in two projects never collides.
    """
    first = store.create_project("First")
    second = store.create_project("Second")
    key = ("alice", "waving", "left", "eye_level")
    PersistentPoseCache(store, first.project_id)[key] = _png()

    assert PersistentPoseCache(store, second.project_id).get(key) is None


def test_reference_image_is_stored_on_the_character_item(store):
    """
    Verifies that a reference image is recorded as the character's appearance_reference, leaving their other fields untouched.
    """
    project = store.create_project("Lighthouse")
    store.save_characters(project.project_id, {"alice": Character(name="Alice", description="A woman.", aliases=["Al"])})

    PersistentReferenceCache(store, project.project_id)["alice"] = _png()

    alice = store.load_project(project.project_id).cast["alice"]
    assert alice.appearance_reference == image_s3_key(project.project_id, "CHARACTER#alice#reference")
    assert (alice.name, alice.description, alice.aliases) == ("Alice", "A woman.", ["Al"])
    assert PersistentReferenceCache(store, project.project_id).get("alice") == _png()


def test_resaving_characters_never_wipes_a_reference_image(store):
    """
    Verifies that saving the cast again (eg:- after a description edit) keeps the reference image that was already paid for.
    """
    project = store.create_project("Lighthouse")
    store.save_characters(project.project_id, {"alice": Character(name="Alice", description="A woman.")})
    PersistentReferenceCache(store, project.project_id)["alice"] = _png()

    store.save_characters(project.project_id, {"alice": Character(name="Alice", description="A woman in a coat.")})

    assert PersistentReferenceCache(store, project.project_id).get("alice") == _png()


def test_reference_image_for_an_unsaved_character_is_rejected(store):
    """
    Verifies that storing a reference image for a character who isn't saved raises a KeyError, rather than creating a half-empty character item.
    """
    project = store.create_project("Lighthouse")

    with pytest.raises(KeyError, match="save the cast"):
        PersistentReferenceCache(store, project.project_id)["nobody"] = _png()

    assert "CHARACTER#nobody" not in _raw_items(store, project.project_id)


def test_rerendering_with_fresh_persistent_caches_makes_no_generation_calls(store):
    """
    Verifies the point of this whole module: re-rendering a shot in a new, stateless invocation costs nothing.

    The second render builds brand-new cache objects (as a new Lambda invocation would), and must still make zero generation calls.
    """
    project = store.create_project("Lighthouse")
    characters = {"alice": Character(name="Alice", description="A woman.")}
    store.save_characters(project.project_id, characters)
    shot = _shot(0, [_region()])
    calls = {"generate": 0}

    def fake_generate_image(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Counts the call and returns a solid image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Image file (in bytes).
        """
        calls["generate"] += 1
        return _png((200, 30, 30, 255))

    def render():
        """
        Renders the shot with brand-new persistent cache objects.

        Returns:
            RenderResult - The render result.
        """
        return render_shot(shot, characters,
                           character_cache=PersistentPoseCache(store, project.project_id),
                           background_cache=PersistentBackgroundCache(store, project.project_id),
                           reference_cache=PersistentReferenceCache(store, project.project_id),
                           generate_image=fake_generate_image, remove_background=lambda raw: _png())

    first = render()
    assert calls["generate"] == 3  # Background + reference + pose

    second = render()
    assert calls["generate"] == 3  # Unchanged: everything came from DynamoDB + S3
    assert second.image == first.image
