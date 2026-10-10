"""
Persists projects to AWS -- structured metadata and cache lookups in DynamoDB, all image bytes in S3.

Every project lives in one DynamoDB table, under the partition key PROJECT#<project_id>. The sort key says what each item is:

    METADATA                                                       - project name, created_at
    CHARACTER#<character_id>                                       - name, description, aliases, appearance_reference (S3 key)
    SHOT#<zero-padded index>                                       - the shot's fields
    BGCACHE#<hash(setting)>#<shot_size>#<angle>                    - S3 key of a cached background
    POSECACHE#<character_id>#<hash(action)>#<orientation>#<angle>  - S3 key of a cached cutout

Images are always written to S3 before the DynamoDB item that points at them, so an item never points at a missing image. S3 keys are derived from the cache keys, so re-writing the same cache entry overwrites the same object rather than leaving orphans behind.

Attributes:
    TEXT_HASH_LENGTH: int - Number of hex characters kept from a SHA-256 hash of free-form text (setting, action).
    SHOT_INDEX_WIDTH: int - Number of digits a shot index is zero-padded to, so shots sort in story order.
    DEFAULT_REGION: str - AWS Region used when none is given.
"""
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from taleboard.schema.models import Character, Project, Shot

TEXT_HASH_LENGTH = 16
SHOT_INDEX_WIDTH = 4
DEFAULT_REGION = "eu-west-2"


def text_hash(text: str) -> str:
    """
    Hashes free-form text into a short, stable token for use in a sort key.

    Python's built-in hash() is randomised per process, so SHA-256 is used instead -- every Lambda invocation must compute the same key.

    Arguments:
        text: str - Free-form text (eg:- a setting or an action).

    Returns:
        str - First TEXT_HASH_LENGTH hex characters of the text's SHA-256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:TEXT_HASH_LENGTH]


def project_pk(project_id: str) -> str:
    """
    Builds a project's partition key.

    Arguments:
        project_id: str - Unique project ID.

    Returns:
        str - Partition key, eg:- "PROJECT#3f2a...".
    """
    return f"PROJECT#{project_id}"


def character_sk(character_id: str) -> str:
    """
    Builds a character's sort key.

    Arguments:
        character_id: str - Unique character ID.

    Returns:
        str - Sort key, eg:- "CHARACTER#alice".
    """
    return f"CHARACTER#{character_id}"


def shot_sk(index: int) -> str:
    """
    Builds a shot's sort key, zero-padded so that shots sort in story order.

    Arguments:
        index: int - Position of the shot in the story (0-indexed).

    Returns:
        str - Sort key, eg:- "SHOT#0007".
    """
    return f"SHOT#{index:0{SHOT_INDEX_WIDTH}d}"


def background_cache_sk(setting: str, shot_size: str, angle: str) -> str:
    """
    Builds a cached background's sort key. The setting is hashed, as it is free-form and can be long.

    Arguments:
        setting: str - Setting of the shot.
        shot_size: str - Shot size value (eg:- "medium").
        angle: str - Camera angle value (eg:- "eye_level").

    Returns:
        str - Sort key, eg:- "BGCACHE#9c1d...#medium#eye_level".
    """
    return f"BGCACHE#{text_hash(setting)}#{shot_size}#{angle}"


def pose_cache_sk(character_id: str, action: str, orientation: str, angle: str) -> str:
    """
    Builds a cached cutout's sort key. The action is hashed, as it is free-form and can be long.

    Arguments:
        character_id: str - Unique character ID.
        action: str - Action of the region.
        orientation: str - Orientation value (eg:- "left").
        angle: str - Camera angle value (eg:- "eye_level").

    Returns:
        str - Sort key, eg:- "POSECACHE#alice#4b7e...#left#eye_level".
    """
    return f"POSECACHE#{character_id}#{text_hash(action)}#{orientation}#{angle}"


def image_s3_key(project_id: str, sort_key: str) -> str:
    """
    Derives the S3 key for an image from the DynamoDB sort key that points at it.

    Arguments:
        project_id: str - Unique project ID.
        sort_key: str - Sort key of the item pointing at the image.

    Returns:
        str - S3 key, eg:- "projects/3f2a.../bgcache/9c1d.../medium/eye_level.png".
    """
    return f"projects/{project_id}/{sort_key.replace('#', '/').lower()}.png"


def _to_dynamo(data: dict) -> dict:
    """
    Converts JSON-ready data into a form boto3 accepts for DynamoDB -- floats become Decimals, as DynamoDB rejects Python floats.

    Arguments:
        data: dict - JSON-ready data (eg:- from model_dump(mode="json")).

    Returns:
        dict - The same data, with every float as a Decimal.
    """
    return json.loads(json.dumps(data), parse_float=Decimal)


class ProjectStore:
    """
    Reads and writes projects, and their cached images, in DynamoDB and S3.

    Attributes:
        _table: Table - The DynamoDB table holding every project.
        _s3: S3.Client - S3 client.
        _bucket: str - Name of the S3 bucket holding every image.
    """
    def __init__(self, table_name: str, bucket_name: str, region_name: str = DEFAULT_REGION):
        """
        Connects to the table and bucket. Nothing is created -- both must already exist.

        Arguments:
            table_name: str - Name of the DynamoDB table.
            bucket_name: str - Name of the S3 bucket.
            region_name: str - AWS Region of both. Defaults to DEFAULT_REGION.
        """
        self._table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
        self._s3 = boto3.client("s3", region_name=region_name)
        self._bucket = bucket_name

    @classmethod
    def from_env(cls) -> "ProjectStore":
        """
        Connects using the TALEBOARD_TABLE, TALEBOARD_BUCKET and (optionally) AWS_REGION environment variables.

        Returns:
            ProjectStore - A connected ProjectStore.
        """
        return cls(os.environ["TALEBOARD_TABLE"], os.environ["TALEBOARD_BUCKET"], os.environ.get("AWS_REGION", DEFAULT_REGION))

    def create_project(self, name: str) -> Project:
        """
        Creates an empty project with a new, unique ID.

        Arguments:
            name: str - Name of the project.

        Returns:
            Project - The new project, with no shots or cast yet.
        """
        project = Project(project_id=uuid.uuid4().hex, name=name, created_at=datetime.now(timezone.utc))
        self._table.put_item(Item={
            "PK": project_pk(project.project_id),
            "SK": "METADATA",
            "name": project.name,
            "created_at": project.created_at.isoformat(),
        })
        return project

    def save_characters(self, project_id: str, characters: dict[str, Character]) -> None:
        """
        Saves (or updates) each character's name, description and aliases.

        Deliberately leaves appearance_reference alone -- re-saving a character must never wipe out a reference image that was already paid for.

        Arguments:
            project_id: str - Unique project ID.
            characters: dict[str,Character] - Mapping of character IDs to characters.
        """
        for character_id, character in characters.items():
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": character_sk(character_id)},
                UpdateExpression="SET #name = :name, description = :description, aliases = :aliases",
                ExpressionAttributeNames={"#name": "name"},  # 'name' is a DynamoDB reserved word
                ExpressionAttributeValues={":name": character.name, ":description": character.description, ":aliases": character.aliases},
            )

    def save_shots(self, project_id: str, shots: list[Shot]) -> None:
        """
        Saves every shot, keyed by its position in the list.

        Arguments:
            project_id: str - Unique project ID.
            shots: list[Shot] - Shots in story order.
        """
        with self._table.batch_writer() as batch:
            for index, shot in enumerate(shots):
                batch.put_item(Item=self._shot_item(project_id, index, shot))

    def save_shot(self, project_id: str, index: int, shot: Shot) -> None:
        """
        Saves (or replaces) one shot.

        Arguments:
            project_id: str - Unique project ID.
            index: int - Position of the shot in the story (0-indexed).
            shot: Shot - Shot to save.
        """
        self._table.put_item(Item=self._shot_item(project_id, index, shot))

    def load_project(self, project_id: str) -> Project:
        """
        Loads a whole project -- metadata, cast and shots -- with a single (paginated) query.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            Project - The project, with shots in story order.

        Raises:
            KeyError - If no project with this ID exists.
        """
        items = []
        query = {"KeyConditionExpression": Key("PK").eq(project_pk(project_id))}
        while True:
            response = self._table.query(**query)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                break
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        metadata = next((item for item in items if item["SK"] == "METADATA"), None)
        if metadata is None:
            raise KeyError(f"No project with ID {project_id!r}")

        cast = {}
        shots = []
        for item in items:  # Items come back sorted by SK, so shots are already in story order
            fields = {k: v for k, v in item.items() if k not in ("PK", "SK")}
            if item["SK"].startswith("CHARACTER#"):
                cast[item["SK"].removeprefix("CHARACTER#")] = Character.model_validate(fields)
            elif item["SK"].startswith("SHOT#"):
                shots.append(Shot.model_validate(fields))

        return Project(project_id=project_id, name=metadata["name"], created_at=metadata["created_at"], shots=shots, cast=cast)

    def get_image(self, project_id: str, sort_key: str) -> bytes | None:
        """
        Looks up a cached image by its sort key.

        Arguments:
            project_id: str - Unique project ID.
            sort_key: str - Sort key of the cache item (BGCACHE#... or POSECACHE#...).

        Returns:
            bytes - The cached image (PNG, in bytes), or None on a cache miss.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": sort_key}).get("Item")
        if item is None:
            return None
        return self._read_s3(item["s3_key"])

    def put_image(self, project_id: str, sort_key: str, image: bytes) -> None:
        """
        Caches an image -- uploads it to S3 first, then writes the DynamoDB item pointing at it.

        Arguments:
            project_id: str - Unique project ID.
            sort_key: str - Sort key of the cache item (BGCACHE#... or POSECACHE#...).
            image: bytes - Image to cache (PNG, in bytes).
        """
        s3_key = image_s3_key(project_id, sort_key)
        self._write_s3(s3_key, image)
        self._table.put_item(Item={"PK": project_pk(project_id), "SK": sort_key, "s3_key": s3_key})

    def get_reference(self, project_id: str, character_id: str) -> bytes | None:
        """
        Looks up a character's reference image through their appearance_reference.

        Arguments:
            project_id: str - Unique project ID.
            character_id: str - Unique character ID.

        Returns:
            bytes - The reference image (PNG, in bytes), or None if the character has none yet.
        """
        item = self._table.get_item(
            Key={"PK": project_pk(project_id), "SK": character_sk(character_id)},
            ProjectionExpression="appearance_reference",
        ).get("Item")
        if not item or not item.get("appearance_reference"):
            return None
        return self._read_s3(item["appearance_reference"])

    def put_reference(self, project_id: str, character_id: str, image: bytes) -> None:
        """
        Stores a character's reference image -- uploads it to S3 first, then points their appearance_reference at it.

        Arguments:
            project_id: str - Unique project ID.
            character_id: str - Unique character ID.
            image: bytes - Reference image (PNG, in bytes).

        Raises:
            KeyError - If the character hasn't been saved to the project yet.
        """
        s3_key = image_s3_key(project_id, character_sk(character_id) + "#reference")
        self._write_s3(s3_key, image)
        try:
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": character_sk(character_id)},
                UpdateExpression="SET appearance_reference = :ref",
                ConditionExpression="attribute_exists(PK)",  # Never create a half-empty character item
                ExpressionAttributeValues={":ref": s3_key},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise KeyError(f"Character {character_id!r} isn't saved in project {project_id!r} -- save the cast before rendering") from None

    def _shot_item(self, project_id: str, index: int, shot: Shot) -> dict:
        """
        Builds the DynamoDB item for one shot.

        Arguments:
            project_id: str - Unique project ID.
            index: int - Position of the shot in the story (0-indexed).
            shot: Shot - Shot to store.

        Returns:
            dict - DynamoDB item, with the shot's fields as top-level attributes.
        """
        return {"PK": project_pk(project_id), "SK": shot_sk(index), **_to_dynamo(shot.model_dump(mode="json"))}

    def _write_s3(self, s3_key: str, image: bytes) -> None:
        """
        Uploads a PNG to the bucket.

        Arguments:
            s3_key: str - S3 key to upload to.
            image: bytes - Image (PNG, in bytes).
        """
        self._s3.put_object(Bucket=self._bucket, Key=s3_key, Body=image, ContentType="image/png")

    def _read_s3(self, s3_key: str) -> bytes:
        """
        Downloads an object from the bucket.

        Arguments:
            s3_key: str - S3 key to download.

        Returns:
            bytes - The object's contents.
        """
        return self._s3.get_object(Bucket=self._bucket, Key=s3_key)["Body"].read()
