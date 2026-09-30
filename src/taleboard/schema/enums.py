from enum import Enum

class PositionCell(str,Enum):
    """A 3x3 grid over the frame. LLM picks a cell."""
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MID_LEFT = "mid_left"
    MID_CENTER = "mid_center"
    MID_RIGHT = "mid_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"

class SizeInFrame(str,Enum):
    """Size of the object in the frame."""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

class Orientation(str,Enum):
    """Orientation of the object in the frame."""
    TOWARDS_CAMERA = "towards_camera"
    AWAY_FROM_CAMERA = "away_from_camera"
    LEFT = "left" #Facing left with respect to the camera
    RIGHT = "right" #Facing right with respect to the camera

class ShotSize(str,Enum):
    """Shot framing."""
    CLOSE_UP = "close_up"
    MEDIUM = "medium"
    WIDE = "wide"

class CameraAngle(str,Enum):
    """Camera angle."""
    EYE_LEVEL = "eye_level"
    LOW = "low"
    HIGH = "high"