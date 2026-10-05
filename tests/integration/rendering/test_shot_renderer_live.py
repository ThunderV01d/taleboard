from pathlib import Path

import pytest

from taleboard.rendering import together_caller
from taleboard.rendering.shot_renderer import CutoutCache, render_shot
from taleboard.schema.enums import Orientation, PositionCell, SizeInFrame
from taleboard.schema.models import Character, Region

OUTPUT_DIR = Path(__file__).parent / "output"

def _test_characters() -> dict[str, Character]:
    return {
        "alice": Character(
            name="Alice",
            description="A young woman with short red hair, wearing a green coat.",
            colour="#ff0000",
        ),
        "bob": Character(
            name="Bob",
            description="A tall man with a beard, wearing a jacket.",
            colour="#0000ff",
        ),
    }


def _test_regions() -> list[Region]:
    return [
        Region(
            character_id="alice",
            position=PositionCell.MID_LEFT,
            size=SizeInFrame.MEDIUM,
            orientation=Orientation.RIGHT,  #facing right, i.e. towards Bob
            action="standing",
        ),
        Region(
            character_id="bob",
            position=PositionCell.MID_RIGHT,
            size=SizeInFrame.MEDIUM,
            orientation=Orientation.LEFT,  #facing left, i.e. towards Alice
            action="standing",
        ),
    ]


@pytest.mark.integration
def test_render_shot_end_to_end_and_cache_reuse_against_real_services():
    """First call: a real two-character shot through the full pipeline
    (generation, background removal, compositing), written to disk for
    visual inspection. Second call, same regions/cache: confirms no
    further real generation calls happen -- the cache actually works
    against the real API, not just against fakes.
    """
    call_count = 0
    real_generate = together_caller.generate_character_image

    def counting_generate(text: str, negative_text: str) -> bytes:
        nonlocal call_count
        call_count += 1
        return real_generate(text, negative_text)

    characters = _test_characters()
    regions = _test_regions()
    cache: CutoutCache = {}

    first_result = render_shot(
        regions=regions,
        characters=characters,
        cache=cache,
        generate_image=counting_generate,
    )
    assert len(first_result) > 0
    assert call_count == 2 #one per character, nothing cached yet

    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "composited_shot.png").write_bytes(first_result)

    second_result = render_shot(
        regions=regions,
        characters=characters,
        cache=cache,
        generate_image=counting_generate,
    )
    assert call_count == 2 #unchanged: both regions reused from cache
    assert second_result == first_result