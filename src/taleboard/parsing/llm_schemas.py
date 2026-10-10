"""
Defines the LLM-side schemas to validate LLM output against.

Includes schema model classes and builder functions.
"""
from pydantic import BaseModel, Field, ConfigDict, field_validator
from taleboard.schema.enums import PositionCell, SizeInFrame, Orientation, ShotSize, CameraAngle
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
    
class LLMShotDraft(BaseModel):
    """
    Represents a single shot to be generated.
    """
    model_config = ConfigDict(extra="forbid")
    description: str
    setting: str = Field(max_length=300) # This needs to be concise, as we don't want the LLM to waffle on about the setting of the shot (and risk inventing details that don't exist)
    shot_size: ShotSize
    angle: CameraAngle
    duration_s: float # Shots realistically shouldn't last for longer than a minute
    regions: list[LLMRegion]

    # Validates shot duration
    @field_validator("duration_s")
    @classmethod
    def duration_in_range(cls, v: float) -> float:
        if not (0 < v <= 60):
            raise ValueError("duration_s must be greater than 0 and at most 60")
        return v

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

def build_shot_draft_model(cast_ids: list[str]) -> type[LLMShotDraft]:
    """
    Builds a subclass of LLMShotDraft whose regions are constrained to the real cast.
    
    Arguments:
        cast_ids: list[str] - Cast (List of character IDs).
    
    Returns:
        ConstrainedShotDraft - Constrained subclass of LLMShotDraft.
    """
    ConstrainedRegion = build_region_model(cast_ids)
    class ConstrainedShotDraft(LLMShotDraft):
        regions: list[ConstrainedRegion] #pyright: ignore[reportInvalidTypeForm]
    return ConstrainedShotDraft

def build_paragraph_output_model(cast_ids: list[str]) -> type[BaseModel]:
    """
    Builds the full output model for one paragraph's shot-breakdown call, with a character_id constrained to the real cast.

    Arguments:
        cast_ids: list[str] - Cast (List of character IDs).
    
    Returns:
        ParagraphOutput - full output model, with constrained character IDs.
    """
    ConstrainedShotDraft = build_shot_draft_model(cast_ids)
    class ParagraphOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        shots: list[ConstrainedShotDraft] #pyright: ignore[reportInvalidTypeForm]
    return ParagraphOutput