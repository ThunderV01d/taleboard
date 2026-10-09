from pydantic import BaseModel, Field, ConfigDict, field_validator
from taleboard.schema.enums import PositionCell, SizeInFrame, Orientation, ShotSize, CameraAngle
from typing import Literal


class LLMRegion(BaseModel):
    """Represents a region in a shot."""
    model_config = ConfigDict(extra="forbid")
    character_id: str
    position: PositionCell
    size: SizeInFrame
    orientation: Orientation
    action: str = Field(max_length=200)

def _require_aliases(schema: dict) -> None:
    schema.setdefault("required", []).append("aliases")

class LLMCharacterDraft(BaseModel):
    """Represents a character to be generated."""
    #aliases is required in the JSON schema sent to the LLM (so it's always filled in), but defaults to [] in Python.
    model_config = ConfigDict(extra="forbid", json_schema_extra=_require_aliases)
    name: str
    description: str = Field(max_length=300)
    aliases: list[str] = Field(default_factory=list)  #other ways the story refers to this character


class LLMCastOutput(BaseModel):
    """Represents the entire cast of characters to be generated."""
    model_config = ConfigDict(extra="forbid")
    characters: list[LLMCharacterDraft]
    
class LLMShotDraft(BaseModel):
    """Represents a single shot to be generated."""
    model_config = ConfigDict(extra="forbid")
    description: str
    setting: str = Field(max_length=300)
    shot_size: ShotSize
    angle: CameraAngle
    duration_s: float = Field(gt=0,le=60)
    regions: list[LLMRegion]

class LLMParagraphOutput(BaseModel):
    """Represents a list of shots to be generated from a single paragraph."""
    model_config = ConfigDict(extra="forbid")
    shots: list[LLMShotDraft]

def build_region_model(cast_ids: list[str]) -> type[BaseModel]:
    """Builds a version of LLMRegion whose character_id can only be one of the given cast_ids at runtime."""
    if not cast_ids:
        raise ValueError("Cast is empty -- shot breakdown needs at least one character. Stories with no characters aren't supported yet.")
    CharacterId = Literal[tuple(cast_ids)]
    class ConstrainedRegion(BaseModel):
        model_config = ConfigDict(extra="forbid")
        character_id: CharacterId #pyright: ignore[reportInvalidTypeForm]
        position: PositionCell
        size: SizeInFrame
        orientation: Orientation
        action: str = Field(max_length=200)
    return ConstrainedRegion

def build_shot_draft_model(cast_ids: list[str]) -> type[BaseModel]:
    """Builds a version of LLMShotDraft whose regions are constrained to the real cast."""
    ConstrainedRegion = build_region_model(cast_ids)
    class ConstrainedShotDraft(BaseModel):
        model_config = ConfigDict(extra="forbid")
        description: str
        setting: str = Field(max_length=300)
        shot_size: ShotSize
        angle: CameraAngle
        duration_s: float
        regions: list[ConstrainedRegion] #pyright: ignore[reportInvalidTypeForm]

        @field_validator("duration_s")
        @classmethod
        def duration_in_range(cls, v: float) -> float:
            if not (0 < v <= 60):
                raise ValueError("duration_s must be greater than 0 and at most 60")
            return v
    return ConstrainedShotDraft

def build_paragraph_output_model(cast_ids: list[str]) -> type[BaseModel]:
    """Builds the full output model for one paragraph's shot-breakdown call, with a character_id constrained to the real cast."""
    ConstrainedShotDraft = build_shot_draft_model(cast_ids)
    class ConstrainedParagraphOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        shots: list[ConstrainedShotDraft] #pyright: ignore[reportInvalidTypeForm]
    return ConstrainedParagraphOutput