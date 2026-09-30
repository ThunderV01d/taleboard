# TaleBoard

Turn a story into an editable storyboard! You, the user, have control of framing, blocking, and pacing.

**Status: in progress.** The story → shots pipeline (cast extraction and
shot breakdown, both backed by AWS Bedrock) is implemented and tested. The
paint editor and image rendering are not yet built. See
[Status](#status) below for exactly what works today.

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

**Not yet built:**
- The domain data model tying validated shots into a persisted `Project`
  (characters, ordered shots, regions) — currently only the LLM-facing
  schemas exist.
- The paint-to-regenerate editor.
- Actual image generation/rendering for a shot.
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
   shots, each with a camera size/angle, duration, and a list of
   per-character regions (a 3×3 grid position, relative size, facing
   direction). Bedrock's native structured-output mode constrains the
   response to this exact schema at generation time, rather than hoping
   the model's free-text JSON happens to be well-formed.

3. **Validation and retry** — every shot is validated individually
   (not as part of one big list), so one malformed shot doesn't invalidate
   an entire paragraph's worth of otherwise-good output. A failing shot is
   retried with its specific Pydantic error fed back to the model; after a
   capped number of retries, it's replaced with a safe, flagged
   placeholder shot rather than silently dropped.

## Tech stack

- **Python 3.13**, **Pydantic v2** for schema validation and JSON-schema
  generation
- **AWS Bedrock** (Claude Haiku 4.5, via `boto3`) for structured LLM
  output — chosen specifically to demonstrate real AWS usage on a tight
  budget (native structured outputs avoid unreliable free-text JSON
  parsing, and Haiku 4.5's pricing keeps this well under £5/month at
  expected usage)
- **pytest**, split into a fast/free **unit** tier (fake LLM calls,
  mocked `boto3`, runs in under a second) and a slower, real-cost
  **integration** tier (`pytest -m integration`) that actually calls
  Bedrock

## Project structure

```
src/taleboard/
├── schema/
│   ├── enums.py        # closed vocabularies fed to the LLM (shot size, camera angle, ...)
│   └── models.py        # domain model (Project/Character/Shot/Region) — not yet written
└── parsing/
    ├── llm_schemas.py    # Pydantic models for LLM input/output, including dynamic
    │                     # cast-constrained schema builders
    ├── prompts.py        # prompt templates for cast extraction and shot breakdown
    ├── cast_extraction.py
    ├── shot_breakdown.py
    └── bedrock_caller.py # AWS Bedrock Converse API integration

tests/
├── unit/parsing/         # fast, free, no AWS calls
└── integration/parsing/  # real Bedrock calls — costs money, needs credentials
```

## Running it

Requires an AWS account with Bedrock model access granted for Claude
Haiku 4.5 in your chosen region, and local AWS credentials boto3 can find
(e.g. via `aws configure`).

```bash
pip install -e .
python -m pytest -m "not integration"   # fast, free
python -m pytest -m integration         # real Bedrock calls
```