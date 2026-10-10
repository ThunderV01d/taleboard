[![CI](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml/badge.svg)](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml)
# TaleBoard

Turn a story into an editable storyboard! You, the user, have control of framing, blocking, and pacing.

**Status: in progress.** The full story → storyboard pipeline works end to end: a raw story goes in (cast extraction and shot breakdown, backed by AWS Bedrock) and a sequence of rendered shots comes out (per-character generation, background rendering, compositing, backed by Together AI). Both halves are tested together, with measured cost. The canvas editor and a persisted project data model are not yet built. See [Status](#status) below for exactly what works today.

## What this is

Most "AI storyboard" tools hand you a finished image and hope it's right. TaleBoard is built around a different idea: the model's job is to propose a starting point (who's in a shot, where they're positioned, how they're framed), not to be the final word on it. Each shot becomes a stack of editable layers: the background and each character cutout can be moved, resized, flipped, or skewed directly on the canvas, so fixing the blocking is free and instant. A generation is only redone when the user explicitly asks for it, one layer at a time, and it keeps that layer's placement.

A story is broken into paragraphs, each paragraph into one or more shots, and each shot into per-character regions (position, size, orientation) — all validated against a strict schema rather than trusted as free text.

## Status

**Working, tested against AWS Bedrock:**
- **Cast extraction** — reads a story, identifies named characters (and correctly excludes unnamed background figures), assigns each a stable, collision-safe ID, and records every other way the story refers to them (aliases, surnames etc.) so later references resolve to the right character. Descriptions are kept strictly visual, because they go straight into image prompts.
- **Shot breakdown** — splits a paragraph into one or more shots, each with per-character regions constrained to the real extracted cast. Handles multi-shot paragraphs, cross-paragraph continuity (a character's position/orientation carries forward unless the text says they moved), and within-paragraph consistency across multiple shots in one response.
- **Validation and recovery** — LLM output is validated per-item against a Pydantic schema; a failing item is retried with its specific validation error fed back to the model; anything still invalid after retries is replaced with a flagged, safe fallback rather than silently dropped or left invalid.
- **Whole-story breakdown** — `break_down_story()` splits a story into paragraphs, extracts the cast once, and breaks each paragraph down in order, passing each one the previous paragraph's last shot for continuity. An empty story is rejected with a clear error before any paid API call.

**Working, tested against Together AI:**
- **Character rendering** — each character region is turned into a monochrome, background-removed line-art cutout and composited onto the shot canvas at the position, size, and orientation the shot breakdown specified. Camera angle (eye-level/low/high) is reflected in the generation prompt, not just a label on the shot.
- **Background rendering** — every shot also renders its own setting as a standalone environment image (not just blank white), cached per `(setting, shot_size, angle)` so shots that share a scene reuse the same render. A shot with character regions composites those cutouts over this rendered background rather than plain white; a shot with no regions (an establishing/object-insert shot) *is* the background render, nothing to composite. The only consistency mechanism between a character and its background is that both prompts share the same camera-angle wording — no true perspective or scale matching is attempted, by design (see Known issues).
- **Shot size affects composited scale** — a close-up, medium, or wide shot size now actually changes how large a character reads on the canvas, on top of each region's own relative size.
- **Character consistency via reference conditioning** — each character gets one neutral reference pose (eye-level, facing camera), generated once per project and cached. Every subsequent pose of that character is conditioned on it through FLUX.2's `reference_images` input, so a character keeps the same look across different shots and poses.
- **Direct LEFT/RIGHT orientation** — FLUX.2-dev follows directional prompts reliably, so every orientation is its own real generation (with its own cache entry).
- **No duplicate generations via caching** — a generation is only ever produced once per unique `(character, action, orientation, camera angle)` combination; any later shot reusing that exact combination (anywhere in the project, not just the adjacent shot) reuses the cached cutout instead of paying for a new one. Backgrounds are cached separately, keyed on `(setting, shot_size, angle)`. Each character's reference image is cached once for the whole project.
- **Cutout validation** — a cutout that background removal leaves (nearly) empty is never cached. It is regenerated once, and if it still fails, that character is left out of the shot and the shot is flagged `needs_review` rather than silently rendering an invisible character.
- **Transient error handling** — FLUX.2-dev occasionally returns spurious 400 errors that succeed on an identical retry; these are retried automatically, on top of the SDK's own rate-limit/server-error retries.
- **Tested end to end** — an integration test runs a real 8-paragraph story through the whole pipeline with nothing hand-built in between, checking alias resolution, character presence per paragraph, one reference image per character, and that every shot renders. A run costs about **$0.50** (~30 FLUX images plus ~9 Bedrock calls, ~95% of it image generation), so roughly a dozen stories of that length a month fit the £5 budget.

**Known issues:**
- **Camera angle prompting is unreliable on character generation.** Camera angle prompting doesn't work great on characters (although it works on the background!)s
- **Character/background compositing has no perspective or scale matching.** A character cutout and its background are two independently generated images; the only thing tying them together is sharing the same camera-angle wording. This was an explicit, accepted trade-off rather than an oversight — true scene-consistent compositing would need real 3D scene reasoning neither generation call does. In practice, a receding hallway background makes characters look like flat cutouts pasted onto the side walls, since nothing accounts for the scene's vanishing point. This can be mitigated to some extent using the editor's skew control -- a cutout can be nudged towards a background's vanishing point when it's visibly off.
- **Scene details occasionally leak into character cutouts.** Each character is generated alone on a blank background from their action text. When that text implies a large prop or a place ("gripping the tiller of a boat"), FLUX draws it too, and background removal leaves it as a faint box behind the character. The breakdown prompt asks for pose-only actions, which makes this rare but doesn't eliminate it.
- **Close-ups can crop a character's head.** Close-up scaling uses the same anchoring as wider shots, so the top of a full-body cutout can fall outside the frame. Nothing is lost (the full cutout is kept), so the canvas editor will let the user simply reposition it.
- **The same location can look different across shots** when its setting text is reworded. There is no location-identity mechanism yet, the equivalent of reference images for characters.
- **Camera variety is limited.** Shots lean heavily towards medium, eye-level framing, even with the breakdown prompt asking for variety.

**Not yet built:**
- A persisted `Project` container tying validated shots together as an ordered, editable whole (the domain pieces individual shots are built from — `Character`, `Region` — exist and are used directly by rendering; the project-level container around them doesn't yet).
- The canvas editor (see [Planned: Canvas Editor](#planned-canvas-editor)).
- Deployment (S3/CloudFront frontend, Lambda API + worker, SQS, DynamoDB, S3 storage for generated/uploaded images).

## Planned: Canvas Editor

Each shot will be a persistent **layer graph** rather than a single flattened image, so editing or regenerating one layer never disturbs the rest. Layers stack bottom-to-top:

| Layer | Contents |
|---|---|
| `background` | FLUX-generated environment render |
| `character` | FLUX-generated cutout, one per character region |
| `freehand` | user drawing, stored as **vector strokes** (points, colour, width) so individual strokes stay editable, and rasterized only at composite/export time |
| `image` | a user-uploaded image |
| `group` | a nested container whose transform and opacity apply to its children |

Every layer, groups included, has an affine transform (position, scale, rotation, skew), opacity, visibility, and a name. That one transform covers move/resize/flip/skew uniformly. The compositor will walk this tree, applying group transforms and opacity hierarchically, and flatten it to one image for preview and export.

**Regeneration** applies only to generated layers (`background`, `character`). It replaces just that layer's source image and keeps the transform, opacity, group membership, and stack position. Each generated layer stores its own generation parameters, so it is regenerated from a comparable prompt, still conditioned on the character's reference image.

**Storage** is hybrid. Layer images are S3 object keys, cached under the same keys the renderer already uses in memory, and served to the frontend through presigned URLs so image bytes never pass through the API. Transforms, metadata, and freehand strokes stay inline in the shot JSON. This keeps shot documents small, stays within Lambda payload limits, and costs next to nothing at this scale. The trade-off is lifecycle cleanup: old objects have to be removed when a layer is regenerated or a shot is deleted.

## How it works

0. **Orchestration** — `break_down_story()` drives steps 1–3: it splits the story into paragraphs, runs cast extraction once, then breaks each paragraph down in order.

1. **Cast extraction** — the story text is sent to Claude Haiku 4.5 (via Bedrock) with a prompt asking it to identify named characters and give each a short, visual (not personality/backstory) description plus a list of aliases (other names, titles, or roles the story uses for them). The response is validated against a Pydantic schema, then each character is assigned a unique, slugified ID (`alice`, `sam_1`/`sam_2` for duplicate names, with a collision-safety net for edge cases like a duplicated "Sam" sharing a cast with literally-named "Sam 1"/"Sam 2").

2. **Shot breakdown** — each paragraph is sent to the model one at a time, along with the fixed cast (so it can only reference real character IDs, never invent one) alongside their aliases and the last shot from the previous paragraph (for position/orientation continuity). The model returns one or more shots, each with a camera size/angle, duration, a setting description, and a list of per-character regions (a 3×3 grid position, relative size, facing direction). Bedrock's native structured-output mode constrains the response to this exact schema at generation time, rather than hoping the model's free-text JSON happens to be well-formed. Each region's action describes only pose, gesture, and expression, because it's used to draw that character alone on a blank background.

3. **Validation and retry** — every shot is validated individually (not as part of one big list), so one malformed shot doesn't invalidate an entire paragraph's worth of otherwise-good output. A failing shot is retried with its specific Pydantic error fed back to the model; after a capped number of retries, it's replaced with a safe, flagged placeholder shot rather than silently dropped.

4. **Rendering** — a shot's setting is always rendered as a standalone background first (square-framed), then, if the shot has character regions, each region is turned into a prompt (style, orientation, camera angle, and the character's own description/action), sent to Together AI's FLUX.2-dev (portrait-framed, to give a standing figure room to fit head-to-toe) along with that character's cached reference image for consistency, then background-removed, checked for an empty result (regenerated once, else left out and flagged), and deterministically converted to monochrome. A cache keyed on `(character, action, orientation, angle)` means a pose already generated anywhere in the project is never paid for twice; backgrounds are cached separately on `(setting, shot_size, angle)`. Finished character cutouts are scaled (by the region's size and the shot's overall shot size) and composited onto the rendered background at the position the shot breakdown specified. A shot with no character regions is simply its background render.

## Tech stack

- **Python 3.13**, **Pydantic v2** for schema validation and JSON-schema generation
- **AWS Bedrock** (Claude Haiku 4.5, via `boto3`) for structured LLM output — chosen specifically to demonstrate real AWS usage on a tight budget (native structured outputs avoid unreliable free-text JSON parsing, and Haiku 4.5's pricing keeps this well under £5/month at expected usage)
- **Together AI** (FLUX.2-dev) for all image generation, both characters and backgrounds. This was chosen as it allows image-conditioned prompts -- an important feature to ensure character consistency across shots. It is also fairly cheap to run ($0.0154/image).
- **Pillow**, plus an isnet-anime-based background removal model (rembg, run on CPU), for turning a raw generation into a clean, background-free, monochrome cutout
- **pytest**, split into a fast/free **unit** tier (fake LLM/image calls, mocked `boto3`, runs in under a second) and a slower, real-cost **integration** tier (`pytest -m integration`) that actually calls Bedrock and Together AI

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
│   ├── story_breakdown.py # whole story -> cast + ordered shots (top-level parsing entry point)
│   └── bedrock_caller.py  # AWS Bedrock Converse API integration
└── rendering/
    ├── prompts.py          # builds FLUX prompts (style, orientation, camera angle, shot size) for a character or a background
    ├── together_caller.py  # Together AI FLUX.2-dev image generation (separate character/background aspect ratios, reference-image conditioning)
    ├── background_removal.py  # isnet-anime based background removal
    ├── shot_renderer.py    # orchestrates reference images, character + background generation, caching, and monochrome conversion
    ├── compositor.py       # pastes finished character cutouts onto a shot's canvas or rendered background
    └── layout.py           # PositionCell/SizeInFrame/ShotSize -> pixel geometry

tests/
├── conftest.py             # loads .env credentials before any test runs
├── unit/parsing/           # fast, free, no AWS calls
├── unit/rendering/         # fast, free, no Together AI calls
├── integration/parsing/    # real Bedrock calls — costs money, needs credentials
└── integration/rendering/  # real Together AI calls — costs money, needs an API key
├── integration/test_story_to_render_live.py  # full story -> rendered shots, with cost logging
```

## Running it

Requires an AWS account with Bedrock model access granted for Claude Haiku 4.5 in your chosen region, local AWS credentials boto3 can find (e.g. via `aws configure`), and a Together AI API key (`TOGETHER_API_KEY`) for image generation. Put `TOGETHER_API_KEY` in a `.env` file at the repo root; the tests load it automatically (see `tests/conftest.py`).

```bash
pip install -e ".[dev]"
python -m pytest -m "not integration"   # fast, free
python -m pytest -m integration         # real Bedrock + Together AI calls
python -m pytest tests/integration/test_story_to_render_live.py -m integration -s   # full pipeline, ~$0.50 per run
```
Output (rendered shots, shots.json, run_log.json with costs, and a contact sheet) is written to tests/integration/output/e2e/, which is git-ignored.