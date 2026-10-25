"""
Defines a shot's layer graph: the stack of layers a shot is drawn from, so that editing or regerating one layer never disturbs the rest.

Every layers has the same transform, opacity, visibility and name.

Coordinates are in the 1024x1024 shot frame, with a layer's position at its centre, so it rotates, scales and flips around its middle.

Attributes:
    FRAME_SIZE: int - Width and height of the shot frame that layer coordinates are measured in.
"""
import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, Field, model_validator

from taleboard.schema.base import Model
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay

FRAME_SIZE = 1024

class Transform(Model):
    """
    Where a layer sits in the frame and how it is distorted -- one transform covers moving, resizing, flipping, rotating and skewing.

    Attributes:
        x: float - Horizontal position of the layer's centre (in frame pixels). Defaults to the centre of the frame.
        y: float - Vertical position of the layer's centre (in frame pixels). Defaults to the centre of the frame.
        scale_x: float - Horizontal scale; negative flips the layer horizontally. Defaults to 1.
        scale_y: float - Vertical scale; negative flips the layer vertically. Defaults to 1.
        rotation: float - Clockwise rotation (in degrees). Defaults to 0.
        skew_x: float - Horizontal skew (in degrees). Defaults to 0.
        skew_y: float - Vertical skew (in degrees). Defaults to 0.        
    """
    x: float = FRAME_SIZE / 2
    y: float = FRAME_SIZE / 2
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    skew_x: float = 0.0
    skew_y: float = 0.0

class Point(Model):
    """
    A point on a layer's picture, as fractions of the picture's width and height: (0, 0) is the top-left corner and (1, 1) the bottom-right corner.

    Attributes:
        x: float - Across, as a fraction of the picture's width.
        y: float - Down, as a fraction of the picture's width. 
    """
    x: float
    y: float

class Corners(Model):
    """
    Where a picture's four corners are pulled to, warping its perspective.

    Each corner is a Point measured on the undistorted picture, so it can sit outside it (0 to 1) to stretch it outwards. Being fractions, they hold their shape when the picture is regenerated at another size. The layer's transform applies on top, as for any layer.

    Attributes:
        top_left: Point - Where the top-left corner goes. Defaults to (0, 0).
        top_right: Point - Where the top-right corner goes. Defaults to (1, 0).
        bottom_left: Point - Where the bottom-left corner goes. Defaults to (0, 1).
        bottom_right: Point - Where the bottom-right corner goes. Defaults to (1, 1).
    """
    top_left: Point = Field(default_factory=lambda: Point(x=0,y=0))
    top_right: Point = Field(default_factory=lambda: Point(x=1,y=0))
    bottom_left: Point = Field(default_factory=lambda: Point(x=0,y=1))
    bottom_right: Point = Field(default_factory=lambda: Point(x=1,y=1))

    @model_validator(mode="after")
    def _convex(self) -> "Corners":
        """
        Checks that the corners, in order, turn the same way at every corner (a convex shape) -- so the warp can never fold the picture over itself or turn it inside out.

        Raises a ValueError if the shape is concave, crossed over, or flat.

        Returns:
            Corners - the same corners.
        """
        quad = [self.top_left, self.top_right, self.bottom_right, self.bottom_left]
        for i in range(4):
            a, b, c = quad[i], quad[(i+1)%4], quad[(i+2)%4]
            if (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x) <= 0: # The turn at b: positive is clockwise on screen
                raise ValueError("corners must make a convex shape, in order: top-left, top-right, bottom-right, bottom-left")
        return self

class LayerBase(Model):
    """
    Attributes belonging to every layer, regardless of its type.

    Attributes:
        id: str - Unique ID of the layer within its shot. Defaults to a new random ID.
        name: str - Name shown in the layer list. Defaults to "".
        transform: Transform - Where the layer sits in the frame. Defaults to the identity transform at the centre of the frame.
        opacity: float - From 0 (invisible) to 1 (solid). Defaults to 1.
        visible: bool - Whether the layer is drawn at all. Defaults to True.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    transform: Transform = Field(default_factory=Transform)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    visible: bool = True

class TextLayer(LayerBase):
    """
    A caption or line of dialogue drawn on the shot. Never generated.
    
    Attributes:
        type: Literal["text"] - Layer type.
        text: str - What it says. Defaults to "".
        font: Literal["sans", "serif", "mono", "handwritten"] - Font family; the frontend maps each to a real font. Defaults to "sans".
        size: float - Font size (in frame pixels). Defaults to 32.
        colour: str - Text colour, as a hex code. Defaults to black.
        align: Literal["left", "center", "right"] - Alignment of the text around its position. Defaults to "center".
    """
    type: Literal["text"] = "text"
    text: str = ""
    font: Literal["sans", "serif", "mono", "handwritten"] = "sans"
    size: float = Field(default=32.0, gt=0)
    colour: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    align: Literal["left", "center", "right"] = "center"

class PictureLayer(LayerBase):
    """
    What every layer drawn from a picture shares -- uploaded images and the three generated types: the picture, and how it is warped.

    Attributes:
        image: str - S3 key of the picture. Defaults to None (none uploaded or generated yet).
        corners: Corners - Where the picture's corners are pulled to. Defaults to None (not warped).
    """
    image: str | None = None
    corners: Corners | None = None

class ImageLayer(PictureLayer):
    """
    An image the user uploaded. Never generated -- "Replace image" swaps the file.

    Attributes:
        type: Literal["image"] - Layer type.
    """
    type: Literal["image"] = "image"

class GenerationContext(Model):
    """
    The shot- and scene-level values a background's image also depends on, alongside its own facing.

    Attributes:
        location_id: str - The location the shot's scene takes place in.
        shot_size: ShotSize - Size of the shot.
        angle: CameraAngle - Camera angle of the shot.
        details: str - Small visible changes to the location in this shot. Defaults to "".
        time_of_day: TimeOfDay - Time of day of the shot's scene.
        atmosphere: Atmosphere - Weather and atmosphere of the shot's scene.
    """
    location_id: str
    shot_size: ShotSize
    angle: CameraAngle
    details: str = ""
    time_of_day: TimeOfDay
    atmosphere: Atmosphere

class BackgroundParams(Model):
    """
    Everything a background's image was generated from.
    """
    location_id: str
    facing: Facing
    shot_size: ShotSize
    angle: CameraAngle
    details: str
    time_of_day: TimeOfDay
    atmosphere: Atmosphere

class CharacterParams(Model):
    """
    Everything a character layer's image was generated from (besides the character's own registry entry).
    """
    orientation: Orientation
    action: str

class PropParams(Model):
    """
    Everything a prop layer's image was generated from (besides the prop's own registry entry).
    """
    orientation: Orientation

class GeneratedLayer(PictureLayer):
    """
    What the three generated layer types (background, character, prop) share: an image, and a record of exactly what produced it.

    Each subclass says which values its image depends on (current_params); comparing those with the values its image was actually made from (last_generated_params) is what enables or disables its Regenerate button. Transforms and corners are never part of either, so moving, resizing or warping a layer never makes it need regenerating.
    """
    def current_params(self, context: GenerationContext) -> BaseModel:
        """
        The values this layer's image would be generated from now.

        Arguments:
            context: GenerationContext - The shot- and scene-level values, for layers whose image depends on them.

        Returns:
            BaseModel - This layer type's params model.
        """
        raise NotImplementedError

    def needs_regeneration(self, context: GenerationContext) -> bool:
        """
        Whether Regenerate should be enabled: the layer has never been generated, or something its image depends on has changed since.

        Changing a value and then changing it back disables it again, as the comparison is with what the image was made from, not a one-way "edited" flag.

        Arguments:
            context: GenerationContext - The shot- and scene-level values.

        Returns:
            bool - True if the layer's image is out of date.
        """
        last = getattr(self, "last_generated_params", None)
        return last is None or last != self.current_params(context)

class BackgroundLayer(GeneratedLayer):
    """
    The shot's location, seen facing one way. Its location is the scene's, so it isn't stored here.

    Attributes:
        type: Literal["background"] - Layer type.
        facing: Facing - Which way the camera faces within the location. Defaults to NORTH.
        last_generated_params: BackgroundParams - What the image was generated from. Defaults to None (not generated yet).
    """
    type: Literal["background"] = "background"
    facing: Facing = Facing.NORTH
    last_generated_params: BackgroundParams | None = None

    def current_params(self, context: GenerationContext) -> BackgroundParams:
        return BackgroundParams(facing=self.facing, **context.model_dump())

class CharacterLayer(GeneratedLayer):
    """
    One character, posed for this shot.

    Attributes:
        type: Literal["character"] - Layer type.
        character_id: str - The character (in the project's registry) this layer shows.
        orientation: Orientation - Which way the character faces, relative to the camera. Defaults to TOWARDS_CAMERA.
        action: str - What the character is doing -- drawn as their pose. Defaults to "".
        last_generated_params: CharacterParams - What the image was generated from. Defaults to None (not generated yet).
    """
    type: Literal["character"] = "character"
    character_id: str
    orientation: Orientation = Orientation.TOWARDS_CAMERA
    action: str = Field(default="", max_length=200)
    last_generated_params: CharacterParams | None = None

    def current_params(self, context: GenerationContext) -> CharacterParams:
        return CharacterParams(orientation=self.orientation, action=self.action)

class PropLayer(GeneratedLayer):
    """
    One prop, drawn for this shot.

    Attributes:
        type: Literal["prop"] - Layer type.
        prop_id: str - The prop (in the project's registry) this layer shows.
        orientation: Orientation - Which way the prop faces, relative to the camera. Defaults to TOWARDS_CAMERA.
        last_generated_params: PropParams - What the image was generated from. Defaults to None (not generated yet).
    """
    type: Literal["prop"] = "prop"
    prop_id: str
    orientation: Orientation = Orientation.TOWARDS_CAMERA
    last_generated_params: PropParams | None = None

    def current_params(self, context: GenerationContext) -> PropParams:
        return PropParams(orientation=self.orientation)

class GroupLayer(LayerBase):
    """
    A container that moves and fades several layers together (eg:- a prop held in a character's hand). Never generated itself.

    Its transform and opacity apply on top of each child's own; children are listed bottom to top, as in a shot.

    Attributes:
        type: Literal["group"] - Layer type.
        children: list[Layer] - The layers inside the group, bottom to top. Defaults to [].
    """
    type: Literal["group"] = "group"
    children: list["Layer"] = Field(default_factory=list)

# Any one layer: Pydantic reads each layer's "type" field to pick which model to validate it as
Layer = Annotated[
    BackgroundLayer | CharacterLayer | PropLayer | TextLayer | ImageLayer | GroupLayer,
    Field(discriminator="type"),
]

GroupLayer.model_rebuild()  # Resolves the forward reference to Layer, now that it exists