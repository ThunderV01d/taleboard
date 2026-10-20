"""
Defines a shot's layer graph: the stack of layers a shot is drawn from, so that editing or regerating one layer never disturbs the rest.

Every layers has the same transform, opacity, visibility and name.

Coordinates are in the 1024x1024 shot frame, with a layer's position at its centre, so it rotates, scales and flips around its middle.

Attributes:
    FRAME_SIZE: int - Width and height of the shot frame that layer coordinates are measured in.
"""
import uuid
from typing import Annotated, Literal
from pydantic import BaseModel, Field

from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay

FRAME_SIZE = 1024

class Transform(BaseModel):
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

class LayerBase(BaseModel):
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

class ImageLayer(LayerBase):
    """
    An image the user uploaded. Never generated -- "Replace image" swaps the file.
    Attributes:
        type: Literal["image"] - Layer type.
        image: str - S3 key of the uploaded image. Defaults to None (no image uploaded yet).    
    """
    type: Literal["image"] = "image"
    image: str | None = None

class GenerationContext(BaseModel):
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

class BackgroundParams(BaseModel):
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

class CharacterParams(BaseModel):
    """
    Everything a character layer's image was generated from (besides the character's own registry entry).
    """
    orientation: Orientation
    action: str

class PropParams(BaseModel):
    """
    Everything a prop layer's image was generated from (besides the prop's own registry entry).
    """
    orientation: Orientation

class GeneratedLayer(LayerBase):
    """
    What the three generated layer types (background, character, prop) share: an image, and a record of exactly what produced it.

    Each subclass says which values its image depends on (current_params); comparing those with the values its image was actually made from (last_generated_params) is what enables or disables its Regenerate button. Transforms are never part of either, so moving or resizing a layer never makes it need regenerating.

    Attributes:
        image: str - S3 key of the generated image. Defaults to None (not generated yet).
    """
    image: str | None = None

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