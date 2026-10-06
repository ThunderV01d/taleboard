from pydantic import BaseModel

from taleboard.schema.enums import PositionCell, SizeInFrame, Orientation, ShotSize, CameraAngle


class Character(BaseModel):
    """A character in the story, as the project stores and the user can
    edit."""
    name: str
    description: str
    appearance_reference: str | None = None  #path/URL to a reference image
    colour: str  #hex colour used for this character's paint mask


class Region(BaseModel):
    """A single character's placement within a shot."""
    character_id: str
    position: PositionCell
    size: SizeInFrame
    orientation: Orientation
    action: str
    image_file: str | None = None  #path to the user-painted mask for this region


class Shot(BaseModel):
    """One storyboard panel."""
    description: str
    setting: str
    regions: list[Region]
    paragraph_index: int  #which paragraph of the story this shot came from
    shot_size: ShotSize
    angle: CameraAngle
    duration_s: float
    generated_frame: str | None = None  #path to the rendered image
    needs_review: bool = False


class Project(BaseModel):
    """A full storyboard project."""
    title: str
    shots: list[Shot]
    cast: dict[str, Character]  #keyed by the same character_id used in Region