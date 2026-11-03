"""
Defines the LLM-side schemas to validate LLM output against.

Includes schema model classes and builder functions.
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from taleboard.schema.enums import Atmosphere, Facing, PositionCell, SizeInFrame, Orientation, ShotSize, CameraAngle, Setting, TimeOfDay
from typing import Literal

class LLMRegion(BaseModel):
    """
    Represents a region in a shot.
    """
    model_config = ConfigDict(extra="forbid") # Restricts extra fields from cropping up in the output and also signals to the LLM to NOT invent any extra fields
    character_id: str
    position: PositionCell
    size: SizeInFrame
    orientation: Orientation
    action: str = Field(max_length=200) # This needs to be concise, as we don't want the LLM to waffle on about the character's action in a shot (and risk inventing details that don't exist)

def _require_aliases(schema: dict) -> None:
    """
    Helper to set the 'aliases' field of the LLMCharacterDraft as a mandatory field.

    While it is mandatory for every LLMCharacterDraft to have an 'aliases' field, it defaults to [] -- this allows for characters with no aliases to be catalogued successfully.
    """
    schema.setdefault("required", []).append("aliases")

class LLMCharacterDraft(BaseModel):
    """
    Represents a character to be generated.
    """
    model_config = ConfigDict(extra="forbid", json_schema_extra=_require_aliases)
    name: str
    description: str = Field(max_length=300) # This needs to be concise, as we don't want the LLM to waffle on about the character's description (and risk inventing details that don't exist)
    aliases: list[str] = Field(default_factory=list) # Other ways the story refers to this character


class LLMCastOutput(BaseModel):
    """
    Represents the entire cast of characters to be generated.
    """
    model_config = ConfigDict(extra="forbid")
    characters: list[LLMCharacterDraft]

class LLMPropDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = Field(max_length=300) # Drawn on its own as the prop's reference

class LLMPropsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    props: list[LLMPropDraft] # A story may have none

class LLMViews(BaseModel):
    model_config = ConfigDict(extra="forbid")
    north: str = Field(max_length=200)
    east: str = Field(max_length=200)
    south: str = Field(max_length=200)
    west: str = Field(max_length=200)

def _require_features(schema: dict) -> None:
    schema.setdefault("required", []).append("features")

class LLMLocationDraft(BaseModel):
    """
    Represents a location to be generated.
    """
    model_config = ConfigDict(extra="forbid", json_schema_extra=_require_features)
    name: str
    setting: Setting
    features: list[str] = Field(default_factory=list) # Every fixed feature the story mentions in the place -- never drawn itself, only checked against the views
    description: str = Field(max_length=300) # What the whole place has in common -- drawn into every side's plate
    views: LLMViews

class LLMLocationsOutput(BaseModel):
    """
    Represents every location in the story.
    """
    model_config = ConfigDict(extra="forbid")
    locations: list[LLMLocationDraft] = Field(min_length=1) # Every shot needs a location, so a story with none can't be broken down

class LLMPropRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prop_id: str
    position: PositionCell
    size: SizeInFrame
    orientation: Orientation
    held_by: str # ID of the character holding it, or "" if nobody is

def _require_props(schema: dict) -> None:
    schema.setdefault("required", []).append("props")
    
class LLMShotDraft(BaseModel):
    """
    Represents a single shot to be generated.
    """
    model_config = ConfigDict(extra="forbid", json_schema_extra=_require_props)
    description: str
    facing: Facing
    details: str = Field(max_length=150) # Only small visible changes to the location -- anything longer is the LLM redescribing the place, which breaks consistency
    shot_size: ShotSize
    angle: CameraAngle
    duration_s: float # Shots realistically shouldn't last for longer than a minute
    regions: list[LLMRegion]
    props: list[LLMPropRegion] = Field(default_factory=list)

    # Validates shot duration
    @field_validator("duration_s")
    @classmethod
    def duration_in_range(cls, v: float) -> float:
        if not (0 < v <= 60):
            raise ValueError("duration_s must be greater than 0 and at most 60")
        return v

class LLMSceneDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_paragraph: int # The scene runs from here to the paragraph before the next scene's first
    location_id: str
    time_of_day: TimeOfDay
    atmosphere: Atmosphere
    name: str = Field(max_length=80)
    description: str = Field(max_length=300) # What happens -- never drawn

class LLMScenesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[LLMSceneDraft] = Field(min_length=1)

class LLMJudgedText(BaseModel):
    """
    The contamination judge's verdict on one piece of text.
    """
    model_config = ConfigDict(extra="forbid")
    id: str
    flagged: bool
    reason: str
    rewritten_text: str

class LLMJudgeOutput(BaseModel):
    """
    The contamination judge's verdicts, one per piece of text it was given.
    """
    model_config = ConfigDict(extra="forbid")
    texts: list[LLMJudgedText]

def build_region_model(cast_ids: list[str]) -> type[LLMRegion]:
    """
    Builds a subclass of LLMRegion whose character_id can only be one of the given cast_ids at runtime.

    Arguments:
        cast_ids: list[str] - Cast (List of character IDs).
    
    Returns:
        ConstrainedRegion - Constrained subclass of LLMRegion.
    """
    # To be revisited once character-less stories are supported
    if not cast_ids:
        raise ValueError("Cast is empty -- shot breakdown needs at least one character. Stories with no characters aren't supported yet.")
    class ConstrainedRegion(LLMRegion):
        character_id: Literal[tuple(cast_ids)] #pyright: ignore[reportInvalidTypeForm]
    return ConstrainedRegion

def build_prop_region_model(prop_ids: list[str], cast_ids: list[str]) -> type[LLMPropRegion]:
    class ConstrainedPropRegion(LLMPropRegion):
        prop_id: Literal[tuple(prop_ids)] #pyright: ignore[reportInvalidTypeForm]
        held_by: Literal[("", *cast_ids)] #pyright: ignore[reportInvalidTypeForm]
    return ConstrainedPropRegion

def build_shot_draft_model(cast_ids: list[str], prop_ids: list[str] | None = None) -> type[LLMShotDraft]:
    ConstrainedRegion = build_region_model(cast_ids)
    if prop_ids:
        ConstrainedPropRegion = build_prop_region_model(prop_ids, cast_ids)
        class ConstrainedShotDraft(LLMShotDraft):
            regions: list[ConstrainedRegion] #pyright: ignore[reportInvalidTypeForm]
            props: list[ConstrainedPropRegion] = Field(default_factory=list) #pyright: ignore[reportInvalidTypeForm]
    else:  # No props to choose from -- any the model invents are dropped before validation (see shot_breakdown)
        class ConstrainedShotDraft(LLMShotDraft):
            regions: list[ConstrainedRegion] #pyright: ignore[reportInvalidTypeForm]
    return ConstrainedShotDraft

def build_paragraph_output_model(cast_ids: list[str], prop_ids: list[str] | None = None) -> type[BaseModel]:
    ConstrainedShotDraft = build_shot_draft_model(cast_ids, prop_ids)
    class ParagraphOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        shots: list[ConstrainedShotDraft] #pyright: ignore[reportInvalidTypeForm]
    return ParagraphOutput

def build_scenes_output_model(location_ids: list[str]) -> type[LLMScenesOutput]:
    class ConstrainedSceneDraft(LLMSceneDraft):
        location_id: Literal[tuple(location_ids)] #pyright: ignore[reportInvalidTypeForm]
    class ScenesOutput(LLMScenesOutput):
        scenes: list[ConstrainedSceneDraft] = Field(min_length=1) #pyright: ignore[reportInvalidTypeForm]
    return ScenesOutput