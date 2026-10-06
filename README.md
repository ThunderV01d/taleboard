[![CI](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml/badge.svg)](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml)
# TaleBoard

Turn a story into an editable storyboard! You, the user, have control of framing, blocking, and pacing.

**Status: in progress.** The story → shots pipeline (cast extraction and
shot breakdown, both backed by AWS Bedrock) and image rendering (per-character
generation, background rendering, compositing, both backed by Together AI) are
implemented and tested. The paint editor and a persisted project data model
are not yet built. See [Status](#status) below for exactly what works today.

## What this is

Most "AI storyboard" tools hand you a finished image and hope it's right.
TaleBoard is built around a different idea: the model's job is to propose
a starting point (who's in a shot, where they're positioned,
how they're framed), not to be the final word on it. The user can paint
directly onto a shot to fix a character's position, and only that shot
gets thrown away and regenerated, keeping everything else untouched.

A story is broken into paragraphs, each paragraph into one or more shots,
and each shot into per-character regions (position, size, orientation) —
all validated against a strict schema rather than trusted as free text.

## Status

**Working, tested against AWS Bedrock:**
- **Cast extraction** — reads a story, identifies named characters (and
  correctly excludes unnamed background figures), assigns each a stable,
  collision-safe ID.
- **Shot breakdown** — splits a paragraph into one or more shots, each
  with per-character regions constrained to the real extracted cast.
  Handles multi-shot paragraphs, cross-paragraph continuity (a character's
  position/orientation carries forward unless the text says they moved),
  and within-paragraph consistency across multiple shots in one response.
- **Validation and recovery** — LLM output is validated per-item against
  a Pydantic schema; a failing item is retried with its specific
  validation error fed back to the model; anything still invalid after
  retries is replaced with a flagged, safe fallback rather than silently
  dropped or left invalid.

**Working, tested against Together AI:**
- **Character rendering** — each character region is turned into a
  monochrome, background-removed line-art cutout and composited onto the
  shot canvas at the position, size, and orientation the shot breakdown
  specified. Camera angle (eye-level/low/high) is reflected in the
  generation prompt, not just a label on the shot.
- **Background rendering** — every shot also renders its own setting as a
  standalone environment image (not just blank white), cached per
  `(setting, shot_size, angle)` so shots that share a scene reuse the same
  render. A shot with character regions composites those cutouts over this
  rendered background rather than plain white; a shot with no regions (an
  establishing/object-insert shot) *is* the background render, nothing to
  composite. The only consistency mechanism between a character and its
  background is that both prompts share the same camera-angle wording —
  no true perspective or scale matching is attempted, by design (see Known
  issues).
- **Shot size affects composited scale** — a close-up, medium, or wide shot
  size now actually changes how large a character reads on the canvas, on
  top of each region's own relative size.
- **LEFT/RIGHT orientation via mirroring** — a sideways-facing region is
  never generated twice. One real generation is produced for a canonical
  direction, and the opposite-facing cutout is derived by mirroring it —
  cheaper than a second generation, and guarantees the two actually match
  (two independent generations have no reason to agree on pose, proportions,
  or clothing folds).
- **Partial regeneration via caching** — a generation is only ever produced
  once per unique `(character, action, orientation, camera angle)`
  combination; any later shot reusing that exact combination (anywhere in
  the project, not just the adjacent shot) reuses the cached cutout instead
  of paying for a new one. Backgrounds are cached separately, keyed on
  `(setting, shot_size, angle)`.

**Known issues:**
- **Full-body framing is unreliable.** SDXL doesn't consistently honour
  "full body shot, entire figure visible" from prompt text alone — a
  square generation frame made this worse by giving a standing figure no
  room to fit head-to-toe, so character generations now request a
  portrait frame (768×1024, the tallest ratio Together's hosted endpoint
  allows) instead of square. This helps but doesn't fully solve it; since
  the compositor scales a cutout by its full height to hit a region's
  target size, an under-framed cutout still reads as oversized relative to
  a correctly-framed one in the same shot.
- **Occasionally a generation includes an extra, unrequested person or
  shadow figure in frame**, generated as part of the same image as the
  intended character — not something background removal can clean up,
  since it looks like one connected subject. The negative prompt now
  explicitly discourages this ("duplicate figure, second person, twin,
  shadow...") but it's a reduction, not a guarantee.
- **Left/right orientation accuracy depends on prompt wording that's still
  being refined** — SDXL's compliance with directional ("facing
  left/right") instructions is inherently less reliable than other
  attributes, and an occasional wrong-direction generation is possible
  even with the current prompt.
- **No character consistency across shots.** Each generation of a given
  `(character, action, orientation, angle)` combination is independent —
  nothing conditions a new generation on how that character has looked in
  earlier shots, so the same character can drift in appearance across a
  story.
- **Character/background compositing has no perspective or scale
  matching.** A character cutout and its background are two independently
  generated images; the only thing tying them together is sharing the same
  camera-angle wording. This was an explicit, accepted trade-off rather
  than an oversight — true scene-consistent compositing would need real 3D
  scene reasoning neither generation call does.

**Not yet built:**
- A persisted `Project` container tying validated shots together as an
  ordered, editable whole (the domain pieces individual shots are built
  from — `Character`, `Region` — exist and are used directly by rendering;
  the project-level container around them doesn't yet).
- The paint-to-regenerate editor.
- Deployment (S3/CloudFront frontend, Lambda API + worker, SQS, DynamoDB).

## How it works

1. **Cast extraction** — the story text is sent to Claude Haiku 4.5 (via
   Bedrock) with a prompt asking it to identify named characters and give
   each a short, visual (not personality/backstory) description. The
   response is validated against a Pydantic schema, then each character is
   assigned a unique, slugified ID (`alice`, `sam_1`/`sam_2` for
   duplicate names, with a collision-safety net for edge cases like a
   duplicated "Sam" sharing a cast with literally-named "Sam 1"/"Sam 2").

2. **Shot breakdown** — each paragraph is sent to the model one at a time,
   along with the fixed cast (so it can only reference real character
   IDs, never invent one) and the last shot from the previous paragraph
   (for position/orientation continuity). The model returns one or more
   shots, each with a camera size/angle, duration, a setting description,
   and a list of per-character regions (a 3×3 grid position, relative
   size, facing direction). Bedrock's native structured-output mode
   constrains the response to this exact schema at generation time, rather
   than hoping the model's free-text JSON happens to be well-formed.

3. **Validation and retry** — every shot is validated individually
   (not as part of one big list), so one malformed shot doesn't invalidate
   an entire paragraph's worth of otherwise-good output. A failing shot is
   retried with its specific Pydantic error fed back to the model; after a
   capped number of retries, it's replaced with a safe, flagged
   placeholder shot rather than silently dropped.

4. **Rendering** — a shot's setting is always rendered as a standalone
   background first (square-framed), then, if the shot has character
   regions, each region is turned into a prompt (style, orientation,
   camera angle, and the character's own description/action), sent to
   Together AI's Stable Diffusion XL (portrait-framed, to give a standing
   figure room to fit head-to-toe), background-removed, and
   deterministically converted to monochrome. Sideways-facing regions reuse
   a single real generation via horizontal mirroring rather than generating
   both directions independently, and a cache keyed on
   `(character, action, orientation, angle)` means a pose already generated
   anywhere in the project is never paid for twice; backgrounds are cached
   separately on `(setting, shot_size, angle)`. Finished character cutouts
   are scaled (by the region's size and the shot's overall shot size) and
   composited onto the rendered background at the position the shot
   breakdown specified. A shot with no character regions is simply its
   background render.

## Tech stack

- **Python 3.13**, **Pydantic v2** for schema validation and JSON-schema
  generation
- **AWS Bedrock** (Claude Haiku 4.5, via `boto3`) for structured LLM
  output — chosen specifically to demonstrate real AWS usage on a tight
  budget (native structured outputs avoid unreliable free-text JSON
  parsing, and Haiku 4.5's pricing keeps this well under £5/month at
  expected usage)
- **Together AI** (Stable Diffusion XL) for image generation — chosen as
  the cheapest verified option at the scale a full screenplay needs, after
  checking Bedrock's own image models (Titan/Nova Canvas, both inactive on
  this account) and fal.ai's FLUX.1 Schnell (same price class but
  meaningfully more expensive per image).
- **Pillow**, plus an isnet-anime-based background removal model, for
  turning a raw generation into a clean, background-free, monochrome cutout
- **pytest**, split into a fast/free **unit** tier (fake LLM/image calls,
  mocked `boto3`, runs in under a second) and a slower, real-cost
  **integration** tier (`pytest -m integration`) that actually calls
  Bedrock and Together AI

## Project structure

```
src/taleboard/
├── schema/
│   ├── enums.py          # closed vocabularies fed to the LLM (shot size, camera angle, orientation, ...)
│   └── models.py         # Character, Region, and the rest of the domain model rendering builds on
├── parsing/
│   ├── llm_schemas.py     # Pydantic models for LLM input/output, including dynamic
│   │                      # cast-constrained schema builders
│   ├── prompts.py         # prompt templates for cast extraction and shot breakdown
│   ├── cast_extraction.py
│   ├── shot_breakdown.py
│   └── bedrock_caller.py  # AWS Bedrock Converse API integration
└── rendering/
    ├── prompts.py          # builds SDXL prompts (style, orientation, camera angle, shot size, negative) for a character or a background
    ├── together_caller.py  # Together AI SDXL image generation (separate character/background aspect ratios)
    ├── background_removal.py  # isnet-anime based background removal
    ├── shot_renderer.py    # orchestrates character + background generation, caching, mirroring, and monochrome conversion
    ├── compositor.py       # pastes finished character cutouts onto a shot's canvas or rendered background
    └── layout.py           # PositionCell/SizeInFrame/ShotSize -> pixel geometry

tests/
├── unit/parsing/           # fast, free, no AWS calls
├── unit/rendering/         # fast, free, no Together AI calls
├── integration/parsing/    # real Bedrock calls — costs money, needs credentials
└── integration/rendering/  # real Together AI calls — costs money, needs an API key
```

## Running it

Requires an AWS account with Bedrock model access granted for Claude
Haiku 4.5 in your chosen region, local AWS credentials boto3 can find
(e.g. via `aws configure`), and a Together AI API key (`TOGETHER_API_KEY`)
for image generation.

```bash
pip install -e .
python -m pytest -m "not integration"   # fast, free
python -m pytest -m integration         # real Bedrock + Together AI calls
```