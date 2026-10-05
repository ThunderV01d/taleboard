from pathlib import Path

import pytest

from taleboard.rendering.background_removal import remove_background
from taleboard.rendering.prompts import build_character_prompt
from taleboard.rendering.together_caller import generate_character_image
from taleboard.schema.enums import Orientation, PositionCell, SizeInFrame
from taleboard.schema.models import Character, Region

OUTPUT_DIR = Path(__file__).parent / "output"

def _test_character() -> Character:
    return Character(
        name="Test Character",
        description="A tall man with a beard, wearing a jacket.",
        colour="#0000ff",
    )
 
 
def _test_region() -> Region:
    return Region(
        character_id="test_character",
        position=PositionCell.MID_CENTER,
        size=SizeInFrame.MEDIUM,
        orientation=Orientation.TOWARDS_CAMERA,
        action="standing",
    )

@pytest.mark.integration
def test_generation_and_background_removal_against_real_services():
    """One real generation call, reused for both checks: that the
    Together API call works end-to-end, and that rembg can isolate the
    subject from whatever SDXL actually produced. Writes both images to
    output/ for visual inspection -- that's the real point of this test.
    """
    prompt = build_character_prompt(_test_character(), _test_region())
    image_bytes = generate_character_image(
        text=prompt.text,
        negative_text=prompt.negative_text,
    )
    assert len(image_bytes) > 0
    cutout_bytes = remove_background(image_bytes)
    assert len(cutout_bytes) > 0
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "generated_character.png").write_bytes(image_bytes)
    (OUTPUT_DIR / "generated_character_cutout.png").write_bytes(cutout_bytes)