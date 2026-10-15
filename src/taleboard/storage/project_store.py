"""
Persists projects to AWS -- structured metadata and cache lookups in DynamoDB, all image bytes in S3.

Every project lives in one DynamoDB table, under the partition key PROJECT#<project_id>. The sort key says what each item is:

    METADATA                                                       - project name, created_at, render_job state, shot_count
    CHARACTER#<character_id>                                       - name, description, aliases, appearance_reference (S3 key)
    LOCATION#<location_id>                                         - name, description, master_plate (S3 key)
    SHOT#<zero-padded index>                                       - the shot's fields
    BGCACHE#<location_id>#<hash(details)>#<shot_size>#<angle>      - S3 key of a cached background
    POSECACHE#<character_id>#<hash(action)>#<orientation>#<angle>  - S3 key of a cached cutout

Images are always written to S3 before the DynamoDB item that points at them, so an item never points at a missing image. S3 keys are derived from the cache keys, so re-writing the same cache entry overwrites the same object rather than leaving orphans behind.

Projects broken down before locations existed keep their old BGCACHE#<hash(setting)>#<shot_size>#<angle> items; nothing reads them any more.

Attributes:
    TEXT_HASH_LENGTH: int - Number of hex characters kept from a SHA-256 hash of free-form text (details, action).
    SHOT_INDEX_WIDTH: int - Number of digits a shot index is zero-padded to, so shots sort in story order.
    DEFAULT_REGION: str - AWS Region used when none is given.
    PROJECTS_INDEX: str - Name of the sparse GSI that lists projects newest-first. Only METADATA items carry its keys.
    JOB_LEASE_SECONDS: int - How long a worker holds a job before another delivery may take it over. Longer than Lambda's 15-minute maximum.
"""
import hashlib
import json
import os
import uuid
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from taleboard.schema.enums import ProjectStatus
from taleboard.schema.models import Character, Location, Project, Shot

TEXT_HASH_LENGTH = 16
SHOT_INDEX_WIDTH = 4
DEFAULT_REGION = "eu-west-2"
PROJECTS_INDEX = "projects-by-created-at"
JOB_LEASE_SECONDS = 16 * 60

def text_hash(text: str) -> str:
    """
    Hashes free-form text into a short, stable token for use in a sort key.

    Python's built-in hash() is randomised per process, so SHA-256 is used instead -- every Lambda invocation must compute the same key.

    Arguments:
        text: str - Free-form text (eg:- details or an action).

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


def location_sk(location_id: str) -> str:
    """
    Builds a location's sort key.

    Arguments:
        location_id: str - Unique location ID.

    Returns:
        str - Sort key, eg:- "LOCATION#harbourmasters_office".
    """
    return f"LOCATION#{location_id}"


def shot_sk(index: int) -> str:
    """
    Builds a shot's sort key, zero-padded so that shots sort in story order.

    Arguments:
        index: int - Position of the shot in the story (0-indexed).

    Returns:
        str - Sort key, eg:- "SHOT#0007".
    """
    return f"SHOT#{index:0{SHOT_INDEX_WIDTH}d}"


def background_cache_sk(location_id: str, details: str, shot_size: str, angle: str) -> str:
    """
    Builds a cached background's sort key. The details are hashed, as they are free-form and can be long.

    Arguments:
        location_id: str - Unique location ID.
        details: str - Details of the shot ("" if the location looks as described).
        shot_size: str - Shot size value (eg:- "medium").
        angle: str - Camera angle value (eg:- "eye_level").

    Returns:
        str - Sort key, eg:- "BGCACHE#office#9c1d...#medium#eye_level".
    """
    return f"BGCACHE#{location_id}#{text_hash(details)}#{shot_size}#{angle}"


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

def story_s3_key(project_id: str, job_id: str) -> str:
    """
    Builds the S3 key a submiited story is stored under. Keyed by job, so a story can never be overwritten mid-render.
    
    Arguments:
        project_id: str - Unique project ID.
        job_id: str - Unique render job ID.

    Returns:
        str - S3 key.
    """
    return f"projects/{project_id}/story/{job_id}.txt"

def _project_from_metadata(item: dict) -> Project:
    """
    Builds a Project (without shots or cast) from its METADATA item.

    Arguments:
        item: dict - The METADATA item.

    Returns:
        Project - The project's metadata and job state.
    """
    fields = {k: v for k,v in item.items() if k in Project.model_fields}
    return Project(project_id=item["PK"].removeprefix("PROJECT#"),**fields)


def _to_dynamo(data: dict) -> dict:
    """
    Converts JSON-ready data into a form boto3 accepts for DynamoDB -- floats become Decimals, as DynamoDB rejects Python floats.

    Arguments:
        data: dict - JSON-ready data (eg:- from model_dump(mode="json")).

    Returns:
        dict - The same data, with every float as a Decimal.
    """
    return json.loads(json.dumps(data), parse_float=Decimal)

def _item_fields(item: dict) -> dict:
    """
    Strips the table's key attributes from an item, leaving only the model's own fields.

    Arguments:
        item: dict - A DynamoDB item.

    Returns:
        dict - The item without PK and SK.
    """
    return {k: v for k, v in item.items() if k not in ("PK", "SK")}


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
            "status": project.status.value,
            "GSI1PK": "PROJECTS", # Sparse index key -- only METADATA items carry it, so the index lists projects and nothing else
            "GSI1SK": project.created_at.isoformat()
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

    def save_locations(self, project_id: str, locations: dict[str, Location]) -> None:
        """
        Saves (or updates) each location's name and description.

        Deliberately leaves master_plate alone -- re-saving a location must never wipe out a master plate that was already paid for.

        Arguments:
            project_id: str - Unique project ID.
            locations: dict[str,Location] - Mapping of location IDs to locations.
        """
        for location_id, location in locations.items():
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": location_sk(location_id)},
                UpdateExpression="SET #name = :name, description = :description",
                ExpressionAttributeNames={"#name": "name"},  # 'name' is a DynamoDB reserved word
                ExpressionAttributeValues={":name": location.name, ":description": location.description},
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
        Loads a whole project -- metadata, cast, locations and shots -- with a single (paginated) query.

        Raises a KeyError if no project with this ID exists.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            Project - The project, with shots in story order.
        """
        items = self._query(project_id)

        metadata = next((item for item in items if item["SK"] == "METADATA"), None)
        if metadata is None:
            raise KeyError(f"No project with ID {project_id!r}")

        cast = {}
        locations = {}
        shots = []
        for item in items:  # Items come back sorted by SK, so shots are already in story order
            fields = _item_fields(item)
            if item["SK"].startswith("CHARACTER#"):
                cast[item["SK"].removeprefix("CHARACTER#")] = Character.model_validate(fields)
            elif item["SK"].startswith("LOCATION#"):
                locations[item["SK"].removeprefix("LOCATION#")] = Location.model_validate(fields)
            elif item["SK"].startswith("SHOT#"):
                shots.append(Shot.model_validate(fields))

        return _project_from_metadata(metadata).model_copy(update={"shots":shots, "cast":cast, "locations":locations})

    def get_project(self, project_id: str) -> Project:
        """
        Gets a project's metadata and job state, without its shots or cast.

        Raises a KeyError if no project with this ID exists.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            Project - The project, with empty shots and cast.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": "METADATA"}).get("Item")
        if item is None:
            raise KeyError(f"No project with ID {project_id!r}")
        return _project_from_metadata(item)

    def list_projects(self) -> list[Project]:
        """
        Lists every project's metadata, newest first, through the sparse projects index.

        Returns:
            list[Project] - Every project, with empty shots and cast.
        """
        items = []
        query = {"IndexName": PROJECTS_INDEX, "KeyConditionExpression": Key("GSI1PK").eq("PROJECTS"), "ScanIndexForward": False}
        while True:
            response = self._table.query(**query)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                return [_project_from_metadata(item) for item in items]
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def submit_story(self, project_id: str, job_id: str, story_text: str) -> None:
        """
        Stores a story and marks the project's render job as pending. A project only ever takes one story, unless its job failed.

        Raises a ValueError if the project already has a story that hasn't failed (or the project doesn't exist).

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
            story_text: str - The story (in plain text).
        """
        self._s3.put_object(Bucket=self._bucket, Key=story_s3_key(project_id, job_id), Body=story_text.encode("utf-8"), ContentType="text/plain; charset=utf-8")
        try:
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": "METADATA"},
                UpdateExpression="SET #status = :pending, job_id = :job_id REMOVE shot_count, #error", # A resubmitted story gets a fresh breakdown -- but keeps every cached image
                ConditionExpression="#status IN (:created,:failed)",
                ExpressionAttributeNames={"#status": "status", "#error":"error"},  # 'status' and 'error' are DynamoDB reserved words
                ExpressionAttributeValues={":pending": ProjectStatus.PENDING.value, ":created": ProjectStatus.CREATED.value, ":failed": ProjectStatus.FAILED.value, ":job_id": job_id},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(f"Project {project_id!r} already has a story") from None

    def load_story(self, project_id: str, job_id: str) -> str:
        """
        Loads the story submitted for a render job.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.

        Returns:
            str - The story (in plain text).
        """
        return self._read_s3(story_s3_key(project_id, job_id)).decode("utf-8")

    def claim_job(self, project_id: str, job_id: str) -> bool:
        """
        Claims a render job for this worker, unless another delivery of the same job is still running.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.

        Returns:
            bool - True if the job was claimed; False if it's finished, superseded, or held by another worker.
        """
        now = int(time.time())
        try:
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": "METADATA"},
                UpdateExpression="SET #status = :in_progress, lease_until = :lease_until",
                ConditionExpression="job_id = :job_id AND #status IN (:pending, :in_progress) AND (attribute_not_exists(lease_until) OR lease_until < :now)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":in_progress": ProjectStatus.IN_PROGRESS.value, ":pending": ProjectStatus.PENDING.value,
                    ":job_id": job_id, ":now": now, ":lease_until": now + JOB_LEASE_SECONDS,
                },
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def release_job(self, project_id: str, job_id: str) -> None:
        """
        Gives up the lease on an unfinished job, so the next delivery can claim it straight away.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
        """
        self._table.update_item(
            Key={"PK": project_pk(project_id), "SK": "METADATA"},
            UpdateExpression="SET lease_until = :zero",
            ConditionExpression="job_id = :job_id",
            ExpressionAttributeValues={":zero": 0, ":job_id": job_id},
        )

    def lease_seconds_remaining(self, project_id: str) -> int:
        """
        Gets how long the current holder's lease on the project's render job still runs.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            int - Seconds until the lease expires (0 if there's no lease, or it has already expired).
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": "METADATA"}, ProjectionExpression="lease_until").get("Item") or {}
        return max(0, int(item.get("lease_until", 0)) - int(time.time()))


    def finish_job(self, project_id: str, job_id: str, status: ProjectStatus, error: str | None = None) -> None:
        """
        Marks a render job as complete or failed, and releases its lease.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
            status: ProjectStatus - COMPLETE or FAILED.
            error: str - Why the job failed. Defaults to None.
        """
        self._table.update_item(
            Key={"PK": project_pk(project_id), "SK": "METADATA"},
            UpdateExpression="SET #status = :status, #error = :error REMOVE lease_until",
            ConditionExpression="job_id = :job_id",
            ExpressionAttributeNames={"#status": "status", "#error": "error"},
            ExpressionAttributeValues={":status": status.value, ":error": error, ":job_id": job_id},
        )


    def fail_unfinished_job(self, project_id: str, job_id: str, error: str) -> bool:
        """
        Marks a render job as failed -- but only if it's still the project's current job and hasn't finished.

        A job that completed (or failed, or was replaced by a resubmitted story) is left exactly as it is.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
            error: str - Why the job failed.

        Returns:
            bool - True if the job was marked failed; False if it had already finished or been superseded.
        """
        try:
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": "METADATA"},
                UpdateExpression="SET #status = :failed, #error = :error REMOVE lease_until",
                ConditionExpression="job_id = :job_id AND #status IN (:pending, :in_progress)",
                ExpressionAttributeNames={"#status": "status", "#error": "error"},
                ExpressionAttributeValues={
                    ":failed": ProjectStatus.FAILED.value, ":error": error, ":job_id": job_id,
                    ":pending": ProjectStatus.PENDING.value, ":in_progress": ProjectStatus.IN_PROGRESS.value,
                },
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False


    def save_breakdown(self, project_id: str, characters: dict[str, Character], shots: list[Shot], locations: dict[str, Location] | None = None) -> None:
        """
        Saves a story's breakdown as the job's checkpoint -- the cast and locations, then every (unrendered) shot, then shot_count.

        shot_count is written last, so it only exists once the shot list is complete. Any shots left by an earlier, crashed attempt are deleted first, so a shorter breakdown can't leave stale extras behind.

        Arguments:
            project_id: str - Unique project ID.
            characters: dict[str,Character] - Mapping of character IDs to characters.
            shots: list[Shot] - Shots in story order.
            locations: dict[str,Location] - Mapping of location IDs to locations. Defaults to None (no locations).
        """
        with self._table.batch_writer() as batch:
            for item in self._query(project_id, "SHOT#"):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        self.save_characters(project_id, characters)
        self.save_locations(project_id, locations or {})
        self.save_shots(project_id, shots)
        self._table.update_item(
            Key={"PK": project_pk(project_id), "SK": "METADATA"},
            UpdateExpression="SET shot_count = :count",
            ExpressionAttributeValues={":count": len(shots)},
        )

    def list_shots(self, project_id: str) -> list[Shot]:
        """
        Lists a project's shots in story order -- including unrendered ones while a job is running.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            list[Shot] - Every saved shot, in story order.
        """
        return [Shot.model_validate(_item_fields(item)) for item in self._query(project_id, "SHOT#")]

    def list_characters(self, project_id: str) -> dict[str, Character]:
        """
        Lists a project's cast.
        
        Arguments:
            project_id: str - Unique project ID.

        Returns:
            dict[str,Character] - Mapping of character IDs to characters.
        """
        return {item["SK"].removeprefix("CHARACTER#"):Character.model_validate(_item_fields(item)) for item in self._query(project_id, "CHARACTER#")}

    def get_shot(self, project_id: str, index: int) -> Shot | None:
        """
        Gets one shot.

        Arguments:
            project_id: str - Unique project ID.
            index: int - Position of the shot in the story (0-indexed).

        Returns:
            Shot - The shot, or None if there's no shot at that position.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": shot_sk(index)}).get("Item")
        return None if item is None else Shot.model_validate(_item_fields(item))

    def save_rendered_shot(self, project_id: str, index: int, shot: Shot, image: bytes, needs_review: bool) -> Shot:
        """
        Stores a shot's composited image, then marks the shot as rendered by pointing its generated_frame at it.

        A set generated_frame is the only record that a shot is done -- both status polling and job resumption read it.

        Arguments:
            project_id: str - Unique project ID.
            index: int - Position of the shot in the story (0-indexed).
            shot: Shot - The shot that was rendered.
            image: bytes - Composited shot image (PNG, in bytes).
            needs_review: bool - Whether a human needs to review the shot (eg:- a character was left out).

        Returns:
            Shot - The shot, as saved.
        """
        s3_key = image_s3_key(project_id, shot_sk(index) + "#render")
        self._write_s3(s3_key, image)
        rendered = shot.model_copy(update={"generated_frame": s3_key, "needs_review": shot.needs_review or needs_review})
        self.save_shot(project_id, index, rendered)
        return rendered

    def presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """
        Builds a temporary URL that lets a browser download one image directly from S3.

        Arguments:
            s3_key: str - S3 key of the image.
            expires_in: int - How long the URL stays valid (in seconds). Defaults to 3600.

        Returns:
            str - The presigned URL.
        """
        return self._s3.generate_presigned_url("get_object", Params={"Bucket": self._bucket, "Key": s3_key}, ExpiresIn=expires_in)

    def _query(self, project_id: str, sort_key_prefix: str | None = None) -> list[dict]:
        """
        Gets every item in a project, or only those whose sort key starts with a prefix, following pagination.

        Arguments:
            project_id: str - Unique project ID.
            sort_key_prefix: str - Only return items whose sort key starts with this. Defaults to None (every item).

        Returns:
            list[dict] - Matching items, sorted by sort key.
        """
        condition = Key("PK").eq(project_pk(project_id))
        if sort_key_prefix is not None:
            condition = condition & Key("SK").begins_with(sort_key_prefix)
        items, query = [], {"KeyConditionExpression": condition}
        while True:
            response = self._table.query(**query)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                return items
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]


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

        Raises a KeyError if the character hasn't been saved to the project yet.

        Arguments:
            project_id: str - Unique project ID.
            character_id: str - Unique character ID.
            image: bytes - Reference image (PNG, in bytes).
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

    def get_master_plate(self, project_id: str, location_id: str) -> bytes | None:
        """
        Looks up a location's master plate through its master_plate.

        Arguments:
            project_id: str - Unique project ID.
            location_id: str - Unique location ID.

        Returns:
            bytes - The master plate (PNG, in bytes), or None if the location has none yet.
        """
        item = self._table.get_item(
            Key={"PK": project_pk(project_id), "SK": location_sk(location_id)},
            ProjectionExpression="master_plate",
        ).get("Item")
        if not item or not item.get("master_plate"):
            return None
        return self._read_s3(item["master_plate"])

    def put_master_plate(self, project_id: str, location_id: str, image: bytes) -> None:
        """
        Stores a location's master plate -- uploads it to S3 first, then points its master_plate at it.

        Raises a KeyError if the location hasn't been saved to the project yet.

        Arguments:
            project_id: str - Unique project ID.
            location_id: str - Unique location ID.
            image: bytes - Master plate (PNG, in bytes).
        """
        s3_key = image_s3_key(project_id, location_sk(location_id) + "#master")
        self._write_s3(s3_key, image)
        try:
            self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": location_sk(location_id)},
                UpdateExpression="SET master_plate = :plate",
                ConditionExpression="attribute_exists(PK)",  # Never create a half-empty location item
                ExpressionAttributeValues={":plate": s3_key},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise KeyError(f"Location {location_id!r} isn't saved in project {project_id!r} -- save the locations before rendering") from None

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
