"""
Persists v0.2.0 projects -- their registries, scenes and shots -- in the same DynamoDB table and S3 bucket as project_store.py.

Every item of a project shares the partition key PROJECT#{project_id}. The sort key says what each item is:

    METADATA                         - name, created_at
    CHARACTER#{character_id}         - a character's registry entry
    PROP#{prop_id}                   - a prop's registry entry
    LOCATION#{location_id}           - a location's registry entry
    SCENE#{scene_id}                 - a scene
    SHOT#{scene_id}#{shot_id}        - a shot, its layer graph included

A shot's sort key starts with its scene's ID, so one query loads a whole scene's shots.
"""
import itertools
import os
from datetime import datetime, timezone
from typing import TypeVar

import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Key

from taleboard.parsing.cast_extraction import slugify
from taleboard.schema.storyboard import Character, Location, Project, Prop, Scene, Shot
from taleboard.storage.project_store import DEFAULT_REGION, PROJECTS_INDEX, _item_fields, _to_dynamo, project_pk

Entry = TypeVar("Entry", Character, Prop, Location)

_REGISTRY_PREFIXES: dict[type, str] = {
    Character: "CHARACTER#",
    Prop: "PROP#",
    Location: "LOCATION#",
}

def registry_sk(model: type, entry_id: str) -> str:
    """
    Builds a registry entry's sort key.

    Arguments:
        model: type - Character, Prop or Location.
        entry_id: str - Unique ID of the entry.

    Returns:
        str - Sort key, eg:- "PROP#lamp".
    """
    return f"{_REGISTRY_PREFIXES[model]}{entry_id}"

class ShotConflictError(Exception):
    """
    Raised when a shot is saved from an out-of-date copy -- someone (or something) saved it in between, so saving would erase their changes.

    Attributes:
        current_version: int - The shot's version as now stored.
    """
    def __init__(self, shot_id: str, current_version: int):
        """
        Records which shot clashed, and its current version.

        Arguments:
            shot_id: str - Unique ID of the shot.
            current_version: int - The shot's version as now stored.
        """
        super().__init__(f"Shot {shot_id!r} has changed since it was loaded (now at version {current_version})")
        self.current_version = current_version

def scene_sk(scene_id: str) -> str:
    """
    Builds a scene's sort key.

    Arguments:
        scene_id: str - Unique ID of the scene.

    Returns:
        str - Sort key, eg:- "SCENE#3f2a...".
    """
    return f"SCENE#{scene_id}"

def shot_sk(scene_id: str, shot_id: str) -> str:
    """
    Builds a shot's sort key, under its scene's, so one query finds all of a scene's shots.

    Arguments:
        scene_id: str - Unique ID of the shot's scene.
        shot_id: str - Unique ID of the shot.

    Returns:
        str - Sort key, eg:- "SHOT#3f2a...#9c1d...".
    """
    return f"SHOT#{scene_id}#{shot_id}"

def owner_index_key(owner_id: str) -> str:
    """
    Builds the projects index's partition key for one user, so listing their projects is a single query.

    Arguments:
        owner_id: str - The user's ID.

    Returns:
        str - The index partition key.
    """
    return f"OWNER#{owner_id}"

class StoryboardStore:
    """
    Reads and writes v0.2.0 projects in DynamoDB and S3.

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
        # The regional address, never the global one: a new bucket's global address can redirect for up to a day, which breaks browser uploads
        self._s3 = boto3.client("s3", region_name=region_name, endpoint_url=f"https://s3.{region_name}.amazonaws.com", config=Config(s3={"addressing_style": "virtual"}))
        self._bucket = bucket_name

    @classmethod
    def from_env(cls) -> "StoryboardStore":
        """
        Connects using the TALEBOARD_TABLE, TALEBOARD_BUCKET and (optionally) AWS_REGION environment variables.

        Returns:
            StoryboardStore - A connected StoryboardStore.
        """
        return cls(os.environ["TALEBOARD_TABLE"], os.environ["TALEBOARD_BUCKET"], os.environ.get("AWS_REGION", DEFAULT_REGION))

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

    def create_project(self, name: str, owner_id: str) -> Project:
        """
        Creates an empty project with a new, unique ID.

        Arguments:
            name: str - Name of the project.
            owner_id: str - The user who owns it.

        Returns:
            Project - The new project.
        """
        project = Project(name=name, owner_id=owner_id, created_at=datetime.now(timezone.utc))
        self._table.put_item(
            Item={
                "PK": project_pk(project.project_id),
                "SK": "METADATA",
                "name": project.name,
                "owner_id": owner_id,
                "created_at": project.created_at.isoformat(),
                "GSI1PK": owner_index_key(owner_id),  # Sparse index key -- only METADATA items carry it, so the index lists projects and nothing else
                "GSI1SK": project.created_at.isoformat(),
            },
            ConditionExpression="attribute_not_exists(PK)",  # Never overwrite an existing project, however unlikely an ID clash
        )
        return project

    def get_project(self, project_id: str) -> Project:
        """
        Gets a project's own details.

        Raises a KeyError if no project with this ID exists.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            Project - The project.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": "METADATA"}).get("Item")
        if item is None:
            raise KeyError(f"No project with ID {project_id!r}")
        return _project_from_item(item)

    def list_projects(self, owner_id: str) -> list[Project]:
        """
        Lists a user's projects, newest first, through the sparse projects index.

        Arguments:
            owner_id: str - The user.
        
        Returns:
            list[Project] - Every project they own.
        """
        items = []
        query = {"IndexName": PROJECTS_INDEX, "KeyConditionExpression": Key("GSI1PK").eq(owner_index_key(owner_id)), "ScanIndexForward": False}
        while True:
            response = self._table.query(**query)
            items.extend(response["Items"])
            if "LastEvaluatedKey" not in response:
                return [_project_from_item(item) for item in items]
            query["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    def rename_project(self, project_id: str, name: str) -> Project:
        """
        Renames a project.

        Raises a KeyError if no project with this ID exists.

        Arguments:
            project_id: str - Unique project ID.
            name: str - New name of the project.

        Returns:
            Project - The renamed project.
        """
        Project(name=name, owner_id="unchanged", created_at=datetime.now(timezone.utc))  # Validates the name the same way as at creation, before anything is written
        try:
            item = self._table.update_item(
                Key={"PK": project_pk(project_id), "SK": "METADATA"},
                UpdateExpression="SET #name = :name",
                ConditionExpression="attribute_exists(PK)",  # Never create a project by renaming one that doesn't exist
                ExpressionAttributeNames={"#name": "name"},  # 'name' is a DynamoDB reserved word
                ExpressionAttributeValues={":name": name},
                ReturnValues="ALL_NEW",
            )["Attributes"]
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise KeyError(f"No project with ID {project_id!r}") from None
        return _project_from_item(item)

    def delete_project(self, project_id: str) -> None:
        """
        Deletes a project entirely: every item in its partition, then every image under its S3 prefix.

        Items go first, so the project disappears from the list at once and nothing is ever left pointing at a deleted image.

        Arguments:
            project_id: str - Unique project ID.
        """
        with self._table.batch_writer() as batch:
            for item in self._query(project_id):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        pages = self._s3.get_paginator("list_objects_v2").paginate(Bucket=self._bucket, Prefix=f"projects/{project_id}/")
        for page in pages:
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self._s3.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})

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

    def presigned_upload(self, s3_key: str, content_type: str, max_bytes: int, expires_in: int = 600) -> dict:
        """
        Builds a temporary form that lets a browser upload one image directly to S3 -- only to this key, only of this type, and no bigger than max_bytes.

        Arguments:
            s3_key: str - S3 key the image will be stored at.
            content_type: str - The image's MIME type.
            max_bytes: int - Largest file S3 will accept (in bytes).
            expires_in: int - How long the form stays valid (in seconds). Defaults to 600.

        Returns:
            dict - The URL to POST to ("url"), and the form fields to send with the file ("fields").
        """
        return self._s3.generate_presigned_post(
            Bucket=self._bucket,
            Key=s3_key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_in,
        )

    def list_entries(self, project_id: str, model: type[Entry]) -> list[Entry]:
        """
        Lists every entry in one of a project's registries.

        Arguments:
            project_id: str - Unique project ID.
            model: type - Character, Prop or Location.

        Returns:
            list[Character|Prop|Location] - Every entry, sorted by ID.
        """
        prefix = _REGISTRY_PREFIXES[model]
        return [_entry_from_item(model, item, prefix) for item in self._query(project_id, prefix)]

    def get_entry(self, project_id: str, model: type[Entry], entry_id: str) -> Entry:
        """
        Gets one registry entry.

        Raises a KeyError if there is no such entry.

        Arguments:
            project_id: str - Unique project ID.
            model: type - Character, Prop or Location.
            entry_id: str - Unique ID of the entry.

        Returns:
            Character|Prop|Location - The entry.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": registry_sk(model, entry_id)}).get("Item")
        if item is None:
            raise KeyError(f"No {model.__name__.lower()} {entry_id!r} in project {project_id!r}")
        return _entry_from_item(model, item, _REGISTRY_PREFIXES[model])

    def create_entry(self, project_id: str, model: type[Entry], name: str, **fields) -> Entry:
        """
        Adds an entry to one of a project's registries, with an ID made from its name.

        If the name's ID is taken, "_2", "_3" and so on are tried until one is free -- so two "Sam"s become "sam" and "sam_2".

        Arguments:
            project_id: str - Unique project ID.
            model: type - Character, Prop or Location.
            name: str - Name of the entry (its ID is made from this).
            fields: dict - The entry's other fields (eg:- description, aliases).

        Returns:
            Character|Prop|Location - The new entry, with its ID.
        """
        base_id = slugify(name)
        for attempt in itertools.count(1):
            entry = model(id=base_id if attempt == 1 else f"{base_id}_{attempt}", name=name, **fields)
            try:
                self._table.put_item(Item=self._entry_item(project_id, entry), ConditionExpression="attribute_not_exists(PK)")
                return entry
            except self._table.meta.client.exceptions.ConditionalCheckFailedException:
                continue  # That ID is taken -- try the next suffix

    def save_entry(self, project_id: str, entry: Character | Prop | Location) -> None:
        """
        Replaces an existing registry entry with a new version of it (eg:- a changed description, or a new reference image).

        Raises a KeyError if the entry doesn't exist -- entries are only ever created through create_entry.

        Arguments:
            project_id: str - Unique project ID.
            entry: Character|Prop|Location - The entry, as it should now be.
        """
        try:
            self._table.put_item(Item=self._entry_item(project_id, entry), ConditionExpression="attribute_exists(PK)")
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise KeyError(f"No {type(entry).__name__.lower()} {entry.id!r} in project {project_id!r}") from None

    def delete_entry(self, project_id: str, model: type[Entry], entry_id: str) -> None:
        """
        Deletes one registry entry -- just the entry. Anything that uses it is dealt with separately (see the usage lookup).

        Arguments:
            project_id: str - Unique project ID.
            model: type - Character, Prop or Location.
            entry_id: str - Unique ID of the entry.
        """
        self._table.delete_item(Key={"PK": project_pk(project_id), "SK": registry_sk(model, entry_id)})

    def _entry_item(self, project_id: str, entry: Character | Prop | Location) -> dict:
        """
        Builds the DynamoDB item for one registry entry. Its ID lives in the sort key, so it isn't repeated as a field.

        Arguments:
            project_id: str - Unique project ID.
            entry: Character|Prop|Location - The entry.

        Returns:
            dict - DynamoDB item.
        """
        fields = _to_dynamo(entry.model_dump(mode="json", exclude={"id"}))
        return {"PK": project_pk(project_id), "SK": registry_sk(type(entry), entry.id), **fields}

    def list_scenes(self, project_id: str) -> list[Scene]:
        """
        Lists a project's scenes, in story order.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            list[Scene] - Every scene, sorted by order.
        """
        scenes = [_scene_from_item(item) for item in self._query(project_id, "SCENE#")]
        return sorted(scenes, key=lambda scene: scene.order)

    def get_scene(self, project_id: str, scene_id: str) -> Scene:
        """
        Gets one scene.

        Raises a KeyError if there is no such scene.

        Arguments:
            project_id: str - Unique project ID.
            scene_id: str - Unique ID of the scene.

        Returns:
            Scene - The scene.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": scene_sk(scene_id)}).get("Item")
        if item is None:
            raise KeyError(f"No scene {scene_id!r} in project {project_id!r}")
        return _scene_from_item(item)

    def create_scene(self, project_id: str, scene: Scene) -> None:
        """
        Adds a new scene to a project.

        Arguments:
            project_id: str - Unique project ID.
            scene: Scene - The new scene.
        """
        self._table.put_item(Item=self._scene_item(project_id, scene), ConditionExpression="attribute_not_exists(PK)")

    def save_scene(self, project_id: str, scene: Scene) -> None:
        """
        Replaces an existing scene with a new version of it (eg:- a new name, lighting or position).

        Raises a KeyError if the scene doesn't exist.

        Arguments:
            project_id: str - Unique project ID.
            scene: Scene - The scene, as it should now be.
        """
        try:
            self._table.put_item(Item=self._scene_item(project_id, scene), ConditionExpression="attribute_exists(PK)")
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise KeyError(f"No scene {scene.id!r} in project {project_id!r}") from None

    def delete_scene(self, project_id: str, scene_id: str) -> None:
        """
        Deletes a scene and every shot in it.

        Arguments:
            project_id: str - Unique project ID.
            scene_id: str - Unique ID of the scene.
        """
        with self._table.batch_writer() as batch:
            for item in self._query(project_id, f"SHOT#{scene_id}#"):
                batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
            batch.delete_item(Key={"PK": project_pk(project_id), "SK": scene_sk(scene_id)})

    def _scene_item(self, project_id: str, scene: Scene) -> dict:
        """
        Builds the DynamoDB item for one scene. Its ID lives in the sort key, so it isn't repeated as a field.

        Arguments:
            project_id: str - Unique project ID.
            scene: Scene - The scene.

        Returns:
            dict - DynamoDB item.
        """
        return {"PK": project_pk(project_id), "SK": scene_sk(scene.id), **_to_dynamo(scene.model_dump(mode="json", exclude={"id"}))}

    def list_shots(self, project_id: str, scene_id: str) -> list[Shot]:
        """
        Lists one scene's shots, in order -- with a single query, as they share their scene's sort-key prefix.

        Arguments:
            project_id: str - Unique project ID.
            scene_id: str - Unique ID of the scene.

        Returns:
            list[Shot] - The scene's shots, sorted by order.
        """
        shots = [_shot_from_item(item) for item in self._query(project_id, f"SHOT#{scene_id}#")]
        return sorted(shots, key=lambda shot: shot.order)

    def list_all_shots(self, project_id: str) -> list[Shot]:
        """
        Lists every shot in a project, across all its scenes -- with a single query, as every shot's sort key starts with SHOT#.

        Arguments:
            project_id: str - Unique project ID.

        Returns:
            list[Shot] - Every shot, grouped by scene and in order within each.
        """
        shots = [_shot_from_item(item) for item in self._query(project_id, "SHOT#")]
        return sorted(shots, key=lambda shot: (shot.scene_id, shot.order))

    def get_shot(self, project_id: str, scene_id: str, shot_id: str) -> Shot:
        """
        Gets one shot, its layer graph included.

        Raises a KeyError if there is no such shot.

        Arguments:
            project_id: str - Unique project ID.
            scene_id: str - Unique ID of the shot's scene.
            shot_id: str - Unique ID of the shot.

        Returns:
            Shot - The shot.
        """
        item = self._table.get_item(Key={"PK": project_pk(project_id), "SK": shot_sk(scene_id, shot_id)}).get("Item")
        if item is None:
            raise KeyError(f"No shot {shot_id!r} in scene {scene_id!r}")
        return _shot_from_item(item)

    def create_shot(self, project_id: str, shot: Shot) -> None:
        """
        Adds a new shot to its scene.

        Arguments:
            project_id: str - Unique project ID.
            shot: Shot - The new shot.
        """
        self._table.put_item(Item=self._shot_item(project_id, shot), ConditionExpression="attribute_not_exists(PK)")

    def save_shot(self, project_id: str, shot: Shot) -> Shot:
        """
        Saves an edited shot -- but only if nobody has saved it since this copy was loaded (its version still matches the stored one).

        Raises a KeyError if the shot doesn't exist, or a ShotConflictError if it has been saved since this copy was loaded.

        Arguments:
            project_id: str - Unique project ID.
            shot: Shot - The shot as edited, carrying the version it was loaded at.

        Returns:
            Shot - The shot as saved, with its version bumped by one.
        """
        saved = shot.model_copy(update={"version": shot.version + 1})
        try:
            self._table.put_item(
                Item=self._shot_item(project_id, saved),
                ConditionExpression="attribute_exists(PK) AND version = :loaded",  # The check and the write happen as one step
                ExpressionAttributeValues={":loaded": shot.version},
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            current = self.get_shot(project_id, shot.scene_id, shot.id)  # A KeyError here means it was deleted, not changed
            raise ShotConflictError(shot.id, current.version) from None
        return saved

    def delete_shot(self, project_id: str, scene_id: str, shot_id: str) -> None:
        """
        Deletes one shot.

        Arguments:
            project_id: str - Unique project ID.
            scene_id: str - Unique ID of the shot's scene.
            shot_id: str - Unique ID of the shot.
        """
        self._table.delete_item(Key={"PK": project_pk(project_id), "SK": shot_sk(scene_id, shot_id)})

    def _shot_item(self, project_id: str, shot: Shot) -> dict:
        """
        Builds the DynamoDB item for one shot -- its layer graph inline. Its scene and own IDs live in the sort key, so they aren't repeated as fields.

        Arguments:
            project_id: str - Unique project ID.
            shot: Shot - The shot.

        Returns:
            dict - DynamoDB item.
        """
        fields = _to_dynamo(shot.model_dump(mode="json", exclude={"id", "scene_id"}))
        return {"PK": project_pk(project_id), "SK": shot_sk(shot.scene_id, shot.id), **fields}

def _project_from_item(item: dict) -> Project:
    """
    Builds a Project from its METADATA item.

    Arguments:
        item: dict - The METADATA item.

    Returns:
        Project - The project.
    """
    return Project(project_id=item["PK"].removeprefix("PROJECT#"), name=item["name"], owner_id=item["owner_id"], created_at=item["created_at"])

def _entry_from_item(model: type[Entry], item: dict, prefix: str) -> Entry:
    """
    Builds a registry entry from its DynamoDB item, taking its ID back out of the sort key.

    Arguments:
        model: type - Character, Prop or Location.
        item: dict - The item.
        prefix: str - The model's sort-key prefix.

    Returns:
        Character|Prop|Location - The entry.
    """
    return model.model_validate({**_item_fields(item), "id": item["SK"].removeprefix(prefix)})

def _scene_from_item(item: dict) -> Scene:
    """
    Builds a scene from its DynamoDB item, taking its ID back out of the sort key.

    Arguments:
        item: dict - The item.

    Returns:
        Scene - The scene.
    """
    return Scene.model_validate({**_item_fields(item), "id": item["SK"].removeprefix("SCENE#")})

def _shot_from_item(item: dict) -> Shot:
    """
    Builds a shot from its DynamoDB item, taking its scene and own IDs back out of the sort key.

    Arguments:
        item: dict - The item.

    Returns:
        Shot - The shot.
    """
    _, scene_id, shot_id = item["SK"].split("#")
    return Shot.model_validate({**_item_fields(item), "scene_id": scene_id, "id": shot_id})
