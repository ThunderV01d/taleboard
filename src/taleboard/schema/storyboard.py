"""
Defines the documents a v0.2.0 project is made of: its registries (characters, props, locations), its scenes, and each scene's shots -- every shot being a layer graph (see layers.py).

The registries own what things look like; shots only refer to them by ID, and own where they are placed.
"""
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from taleboard.schema.base import Model
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.layers import GenerationContext, GroupLayer, Layer

# One side of a location, in words -- short, as it's drawn alongside the location's description
View = Annotated[str, Field(max_length=200)]

class Reference(Model):
    """
    One reference image of a character or prop, in one orientation. Every pose of them in that orientation is matched to it.

    Attributes:
        image: str - S3 key of the image.
        source: Literal["generated", "sketch"] - Whether it was generated, or sketched by the user (used as-is).
    """
    image: str
    source: Literal["generated", "sketch"]

class Character(Model):
    """
    A character in the project's registry -- who they are and what they look like, never where they stand in a shot.

    Attributes:
        id: str - Unique ID of the character, made from their name (eg:- "mara").
        name: str - Full name of the character.
        description: str - What they look like, in words.
        aliases: list[str] - Other ways the story refers to them. Defaults to [].
        references: dict[Orientation,Reference] - Reference image for each orientation needed so far -- added the first time a shot needs one. Defaults to {}.
    """
    id: str
    name: str
    description: str = Field(default="", max_length=300)
    aliases: list[str] = Field(default_factory=list)
    references: dict[Orientation, Reference] = Field(default_factory=dict)

class Prop(Model):
    """
    A prop in the project's registry. Composited into shots like a character, with references added per orientation as they are needed.

    Attributes:
        id: str - Unique ID of the prop, made from its name.
        name: str - Name of the prop.
        description: str - What it looks like, in words.
        references: dict[Orientation,Reference] - Reference image for each orientation needed so far. Defaults to {}.
    """
    id: str
    name: str
    description: str = Field(default="", max_length=300)
    references: dict[Orientation, Reference] = Field(default_factory=dict)

class Location(Model):
    """
    A place in the project's registry. Every scene set there is drawn from its plates.

    Its description covers what the whole place has in common (what it's built of, its size and feel), and each of its views what's on one side of it -- so each facing's plate shows only that side, and every facing still looks like the same place. A facing without a view shows the north plate, as there is nothing to say what's there.

    Attributes:
        id: str - Unique ID of the location, made from its name.
        name: str - Short name of the place.
        description: str - What the whole empty place has in common, in words. Defaults to "".
        setting: Setting - Whether the place is indoors or out. Defaults to INT.
        views: dict[Facing,str] - What's on each side of the place (eg:- north: "the back wall: a two-pane window behind a desk"). Defaults to {}.
        plates: dict[Facing,str] - S3 key of the plate for each facing needed so far -- added the first time a shot needs one. Defaults to {}.
    """
    id: str
    name: str
    description: str = Field(default="", max_length=300)
    setting: Setting = Setting.INT
    views: dict[Facing, View] = Field(default_factory=dict)
    plates: dict[Facing, str] = Field(default_factory=dict)


class Scene(Model):
    """
    A run of shots in one place, at one time of day and in one atmosphere. A change of any of these is a new scene.

    Attributes:
        id: str - Unique ID of the scene. Defaults to a new random ID.
        name: str - Name shown in the editor. Defaults to "".
        description: str - What happens in the scene. Defaults to "".
        order: int - Position of the scene in the project (0 first). Defaults to 0.
        location_id: str - The location (in the project's registry) every shot in the scene takes place in.
        time_of_day: TimeOfDay - Time of day of the scene. Defaults to DAY.
        atmosphere: Atmosphere - Weather and atmosphere of the scene. Defaults to CLEAR.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    description: str = ""
    order: int = Field(default=0, ge=0)
    location_id: str
    time_of_day: TimeOfDay = TimeOfDay.DAY
    atmosphere: Atmosphere = Atmosphere.CLEAR

class Shot(Model):
    """
    One storyboard panel: its framing, and the layer graph it is drawn from. Its location and lighting are its scene's.

    Attributes:
        id: str - Unique ID of the shot. Defaults to a new random ID.
        scene_id: str - The scene the shot belongs to.
        order: int - Position of the shot in its scene (0 first). Defaults to 0.
        description: str - What happens in the shot (never drawn). Defaults to "".
        duration_s: float - How long the shot lasts (in seconds). Defaults to 2.
        shot_size: ShotSize - Framing of the shot. Defaults to MEDIUM.
        angle: CameraAngle - Camera angle of the shot. Defaults to EYE_LEVEL.
        details: str - Small visible changes to the location in this shot. Defaults to "".
        layers: list[Layer] - The layer graph, bottom to top. Defaults to [].
        version: int - Bumped on every save, so a save made from an out-of-date copy can be refused. Defaults to 0.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scene_id: str
    order: int = Field(default=0, ge=0)
    description: str = ""
    duration_s: float = Field(default=2.0, gt=0, le=60)
    shot_size: ShotSize = ShotSize.MEDIUM
    angle: CameraAngle = CameraAngle.EYE_LEVEL
    details: str = Field(default="", max_length=150)
    layers: list[Layer] = Field(default_factory=list)
    version: int = Field(default=0, ge=0)

    def all_layers(self) -> list[Layer]:
        """
        Every layer in the shot, groups' children included, bottom to top.

        Returns:
            list[Layer] - The layers, flattened.
        """
        flat: list[Layer] = []
        stack = list(reversed(self.layers))
        while stack:
            layer = stack.pop()
            flat.append(layer)
            if isinstance(layer, GroupLayer):
                stack.extend(reversed(layer.children))
        return flat

    def generation_context(self, scene: "Scene") -> GenerationContext:
        """
        The shot- and scene-level values this shot's background depends on.

        Arguments:
            scene: Scene - The shot's scene.

        Returns:
            GenerationContext - For the generated layers' current_params / needs_regeneration.
        """
        return GenerationContext(location_id=scene.location_id, shot_size=self.shot_size, angle=self.angle, details=self.details, time_of_day=scene.time_of_day, atmosphere=scene.atmosphere)

    @model_validator(mode="after")
    def layer_ids_are_unique(self) -> "Shot":
        """
        Rejects a shot in which two layers (anywhere in the tree) share an ID -- regenerating or editing a layer finds it by ID.
        """
        ids = [layer.id for layer in self.all_layers()]
        if len(ids) != len(set(ids)):
            raise ValueError("Two layers in this shot have the same id")
        return self

class Project(Model):
    """
    A project's own details. Its registries, scenes and shots are stored and loaded separately.

    Attributes:
        project_id: str - Unique ID of the project. Defaults to a new random ID.
        name: str - Name of the project.
        owner_id: str - User ID of the user who owns the project (Cognito sub).
        created_at: datetime - When the project was created (UTC).
    """
    project_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(min_length=1, max_length=200)
    owner_id: str
    created_at: datetime