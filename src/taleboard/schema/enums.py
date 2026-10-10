"""
Defines the enums used in this application.
"""
from enum import Enum

class PositionCell(str,Enum):
    """
    Character positioning within a 3x3 grid over the frame.
    """
    # LLM picks between these 9 position cells, assigning one to the character region
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
    """
    Size of the character relative to the frame.
    """
    # LLM picks between these 3 sizes, assigning one to the character region
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

class Orientation(str,Enum):
    """
    Direction the character faces. Left and right are relative to the camera, not to the character.
    """
    # LLM picks between these 4 orientations, assigning one to the character region
    TOWARDS_CAMERA = "towards_camera"
    AWAY_FROM_CAMERA = "away_from_camera"
    LEFT = "left"
    RIGHT = "right"

class ShotSize(str,Enum):
    """
    Framing of the shot.
    """
    # LLM picks between these 3 shot sizes, assigning one to the shot
    CLOSE_UP = "close_up"
    MEDIUM = "medium"
    WIDE = "wide"

class CameraAngle(str,Enum):
    """
    Camera angle of the shot.
    """
    # LLM picks between these 3 camera angles, assigning one to the shot
    EYE_LEVEL = "eye_level"
    LOW = "low"
    HIGH = "high"