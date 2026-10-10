"""
True end-to-end test: raw story text -> cast -> shots (Bedrock) -> rendered images (Together AI).

Nothing is hand-constructed between the story and the rendered PNGs. Makes real (paid) calls to both services and needs both sets of credentials. Run with: pytest -m integration

The whole pipeline runs ONCE per module (it's the expensive part), and every test below asserts against that single run. Every Bedrock token and Together AI call is recorded to output/e2e/run_log.json, so cost is measured, not guessed. Visual coherence can't be asserted -- review output/e2e/contact_sheet.png by eye.

Attributes:
    OUTPUT_DIR: Path - Folder the run's shots, references, logs and contact sheet are written to.
    MAX_TOGETHER_CALLS: int - Hard spend guard. The run aborts if it would exceed this many Together AI calls.
    FLUX_USD_PER_IMAGE: float - Together AI price per FLUX.2-dev image (in USD).
    HAIKU_USD_PER_M_INPUT: float - Claude Haiku 4.5 price per million input tokens (in USD).
    HAIKU_USD_PER_M_OUTPUT: float - Claude Haiku 4.5 price per million output tokens (in USD).
    STORY: str - Eight-paragraph test story.
    EXPECTED_PRESENCE: dict[int,set[str]] - Mapping of paragraph indices to the character IDs that must appear in that paragraph's shots.
"""

import json
from pathlib import Path
import shutil

import boto3
import pytest
from PIL import Image, ImageDraw

from taleboard.parsing.story_breakdown import break_down_story
from taleboard.rendering import together_caller
from taleboard.rendering.shot_renderer import render_shot

OUTPUT_DIR = Path(__file__).parent / "output" / "e2e"

MAX_TOGETHER_CALLS = 45  # Hard spend guard (~$0.70) -- aborts the run if exceeded
FLUX_USD_PER_IMAGE = 0.0154
HAIKU_USD_PER_M_INPUT = 1.00  # Anthropic list price; Bedrock regional pricing may differ slightly
HAIKU_USD_PER_M_OUTPUT = 5.00

# Deliberately exercises: an alias far from the introduction ("Elias Brandt" -> "the harbourmaster", 6 paragraphs later), a one-off named character (Lena),
# a character introduced late (Tomas), a paragraph with no visual referent (paragraph 5), and several setting changes
STORY = """\
Mara climbed the last of the spiral stairs into the lamp room of the lighthouse. She was a wiry woman in her thirties, her dark hair tied back under a knitted wool cap, wearing a heavy yellow oilskin coat. Through the salt-streaked windows she could see storm clouds massing over the sea.

Down at the harbour, Elias Brandt stood on the stone quay with his hands in his pockets. He was a broad, white-bearded old man in a navy peacoat and a flat cap. He watched the fishing boats straining at their ropes and frowned.

A girl named Lena ran along the quay towards him, her red scarf flying behind her. She stopped, out of breath, and pointed out to sea. "Tomas's boat isn't back," she said. Then she turned and ran home before he could answer.

Brandt hurried into the harbourmaster's office, a cramped room full of charts and a crackling radio set. He picked up the radio handset and called the lighthouse.

In the lamp room, Mara grabbed the radio and listened. Her brother Tomas was out there. She set the handset down, pulled on her gloves, and started down the stairs two at a time.

For a moment, everything felt very far away.

Out at sea, Tomas fought the tiller of his small wooden boat as waves broke over the bow. He was a lanky young man with a shaved head and a torn green fisherman's sweater. He looked up and saw the lighthouse beam sweep across the water towards him.

Hours later, the storm had passed. On the quay, the harbourmaster wrapped a blanket around Tomas's shoulders while Mara stood beside them, her arms crossed, looking out at the calm grey water.
"""

# Which characters MUST appear somewhere in each paragraph's shots (0-indexed)
EXPECTED_PRESENCE = {
    0: {"mara"},
    1: {"elias_brandt"},
    2: {"lena"},
    3: {"elias_brandt"},
    4: {"mara"},
    6: {"tomas"},
    7: {"elias_brandt", "tomas", "mara"},  # The far-apart alias check
}

def _contact_sheet(images, path):
    """
    Lays every rendered shot out on one image, captioned with its paragraph, framing, characters and setting.

    Arguments:
        images: list[tuple[Path,Shot]] - Rendered shot image paths, each alongside its Shot.
        path: Path - Where to save the contact sheet.
    """
    cols, cell, cap = 4, 384, 54
    rows = max(1, (len(images) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + cap)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (png_path, shot) in enumerate(images):
        x, y = (i % cols) * cell, (i // cols) * (cell + cap)
        sheet.paste(Image.open(png_path).convert("RGB").resize((cell, cell)), (x, y))
        who = ", ".join(f"{r.character_id}:{r.orientation.value}" for r in shot.regions) or "(no characters)"
        draw.text((x + 4, y + cell + 2), f"#{i} p{shot.paragraph_index} {shot.shot_size.value}/{shot.angle.value}", fill="black")
        draw.text((x + 4, y + cell + 18), who[:60], fill="black")
        draw.text((x + 4, y + cell + 34), shot.setting[:60], fill="gray")
    sheet.save(path)


@pytest.fixture(scope="module")
def pipeline_run():
    """
    Runs the whole pipeline once on STORY, recording every Bedrock token and Together AI call.

    Writes shots.json (right after the breakdown, before any rendering), every rendered shot, each character's reference image, run_log.json and the contact sheet to OUTPUT_DIR.

    Returns:
        dict - The run's cast, shots, images (path and Shot pairs), cost summary and Together AI calls.
    """
    bedrock_calls: list[dict] = []
    together_calls: list[dict] = []

    real_boto_client = boto3.client

    class CountingBedrock:
        """
        Wraps a real Bedrock client, recording the token usage of every Converse call.

        Attributes:
            _inner: BaseClient - The real boto3 Bedrock client.
        """
        def __init__(self, inner):
            """
            Wraps the client.

            Arguments:
                inner: BaseClient - The real boto3 Bedrock client.
            """
            self._inner = inner

        def converse(self, **kwargs):
            """
            Makes the real Converse call and records its token usage.

            Arguments:
                kwargs: dict - Keyword arguments of the Converse call.

            Returns:
                dict - The real Converse response.
            """
            response = self._inner.converse(**kwargs)
            usage = response.get("usage", {})
            bedrock_calls.append({"input_tokens": usage.get("inputTokens", 0),
                                  "output_tokens": usage.get("outputTokens", 0)})
            return response

        def __getattr__(self, name):
            """
            Passes any other attribute through to the real client.

            Arguments:
                name: str - Attribute name.

            Returns:
                Any - The real client's attribute.
            """
            return getattr(self._inner, name)

    def counting_boto_client(service, *args, **kwargs):
        """
        Builds a real boto3 client, wrapping Bedrock runtime clients so their usage is recorded.

        Arguments:
            service: str - AWS service name.
            args: tuple - Other positional arguments for boto3.client.
            kwargs: dict - Other keyword arguments for boto3.client.

        Returns:
            BaseClient - The real client, wrapped in CountingBedrock if it's for Bedrock runtime.
        """
        client = real_boto_client(service, *args, **kwargs)
        return CountingBedrock(client) if service == "bedrock-runtime" else client

    real_generate_character = together_caller.generate_character_image
    real_generate_background = together_caller.generate_background_image

    def guard():
        """
        Aborts the run once it reaches MAX_TOGETHER_CALLS, to protect the budget.
        """
        if len(together_calls) >= MAX_TOGETHER_CALLS:
            raise RuntimeError(f"Together call cap ({MAX_TOGETHER_CALLS}) hit -- aborting to protect budget")

    def counting_generate_character(text, negative_text, reference_images=None):
        """
        Records the call (as a reference or a pose) and passes it through to the real character generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.
            reference_images: list[bytes] - Reference images. Defaults to None (for a reference generation).

        Returns:
            bytes - Generated character image file (in bytes).
        """
        guard()
        together_calls.append({"kind": "reference" if reference_images is None else "pose", "prompt": text})
        return real_generate_character(text, negative_text, reference_images=reference_images)

    def counting_generate_background(text, negative_text):
        """
        Records the call and passes it through to the real background generation.

        Arguments:
            text: str - Prompt.
            negative_text: str - Negative prompt.

        Returns:
            bytes - Generated background image file (in bytes).
        """
        guard()
        together_calls.append({"kind": "background", "prompt": text})
        return real_generate_background(text, negative_text)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(boto3, "client", counting_boto_client)
        mp.setattr(together_caller, "generate_character_image", counting_generate_character)
        mp.setattr(together_caller, "generate_background_image", counting_generate_background)

        breakdown = break_down_story(STORY)
        cast, characters, shots = breakdown.cast, breakdown.characters, breakdown.shots
        shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "shots.json").write_text(json.dumps({
            "cast": {cid: d.model_dump() for cid, d in cast.items()},
            "shots": [s.model_dump(mode="json") for s in shots],
        }, indent=2)) # Writes the shots to output after shot breakdown -- for sanity check purposes
        character_cache, background_cache, reference_cache = {}, {}, {}
        images = []
        for n, shot in enumerate(shots):
            png = render_shot(shot, characters, character_cache, background_cache, reference_cache)
            path = OUTPUT_DIR / f"shot_{n:02d}_p{shot.paragraph_index}.png"
            path.write_bytes(png)
            images.append((path, shot))
        for character_id, reference in reference_cache.items():
            (OUTPUT_DIR / f"reference_{character_id}.png").write_bytes(reference)

    _contact_sheet(images, OUTPUT_DIR / "contact_sheet.png")

    input_tokens = sum(c["input_tokens"] for c in bedrock_calls)
    output_tokens = sum(c["output_tokens"] for c in bedrock_calls)
    cost = {
        "bedrock_calls": len(bedrock_calls),
        "bedrock_input_tokens": input_tokens,
        "bedrock_output_tokens": output_tokens,
        "bedrock_usd": input_tokens / 1e6 * HAIKU_USD_PER_M_INPUT + output_tokens / 1e6 * HAIKU_USD_PER_M_OUTPUT,
        "together_calls_by_kind": {k: sum(c["kind"] == k for c in together_calls)
                                   for k in ("reference", "pose", "background")},
        "together_usd": len(together_calls) * FLUX_USD_PER_IMAGE,
    }
    (OUTPUT_DIR / "run_log.json").write_text(json.dumps({
        "cast": {cid: d.model_dump() for cid, d in cast.items()},
        "shots": [s.model_dump(mode="json") for s in shots],
        "cost": cost,
        "together_calls": together_calls,
    }, indent=2))
    print(f"\nE2E cost summary: {json.dumps(cost, indent=2)}")

    return {"cast": cast, "shots": shots, "images": images, "cost": cost, "together_calls": together_calls}


@pytest.mark.integration
def test_cast_merges_alias_and_skips_nobody(pipeline_run):
    """
    Verifies that the cast is exactly the four named characters -- "the harbourmaster" must resolve to Elias Brandt, not become a fifth character.

    Arguments:
        pipeline_run: dict - The shared pipeline run (module-scoped fixture).
    """
    assert set(pipeline_run["cast"]) == {"mara", "elias_brandt", "lena", "tomas"}


@pytest.mark.integration
def test_characters_appear_in_the_paragraphs_they_act_in(pipeline_run):
    """
    Verifies that every character appears in the shots of each paragraph they act in.

    IDs can't drift structurally (character_id is an enum in the Bedrock schema), so the real risk is misattribution or omission -- most likely in the last paragraph, where Brandt is only called "the harbourmaster".

    Arguments:
        pipeline_run: dict - The shared pipeline run (module-scoped fixture).
    """
    present: dict[int, set[str]] = {}
    for shot in pipeline_run["shots"]:
        present.setdefault(shot.paragraph_index, set()).update(r.character_id for r in shot.regions)
    missing = {p: ids - present.get(p, set()) for p, ids in EXPECTED_PRESENCE.items()
               if ids - present.get(p, set())}
    assert not missing, f"characters missing from their paragraphs: {missing}"


@pytest.mark.integration
def test_exactly_one_reference_image_per_rendered_character(pipeline_run):
    """
    Verifies that exactly one reference image is generated per rendered character.

    A drifted or duplicated ID would show up here as an extra reference generation.

    Arguments:
        pipeline_run: dict - The shared pipeline run (module-scoped fixture).
    """
    rendered_ids = {r.character_id for s in pipeline_run["shots"] for r in s.regions}
    reference_calls = pipeline_run["cost"]["together_calls_by_kind"]["reference"]
    assert reference_calls == len(rendered_ids)


@pytest.mark.integration
def test_every_shot_rendered_and_none_fell_back(pipeline_run):
    """
    Verifies that every shot rendered and none needs human review.

    A shot needs review when its breakdown fell back after failed retries, or when a character was left out of it.

    Arguments:
        pipeline_run: dict - The shared pipeline run (module-scoped fixture).
    """
    shots = pipeline_run["shots"]
    assert len(pipeline_run["images"]) == len(shots)
    assert not [i for i, s in enumerate(shots) if s.needs_review], "some shots hit the fallback path"


@pytest.mark.integration
def test_empty_story_fails_cleanly():
    """
    Verifies that an empty story raises a clear ValueError, before any API call is made.
    """
    with pytest.raises(ValueError):
        break_down_story("")
