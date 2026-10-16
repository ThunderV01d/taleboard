[![CI](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml/badge.svg)](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml)
# TaleBoard

Turn a story into an editable storyboard! You, the user, have control of framing, blocking, and pacing.

**Status: in progress.** The full story → storyboard pipeline works end to end and is deployed on AWS: a story submitted to the HTTP API is queued, broken down into shots (AWS Bedrock), rendered (Together AI) and persisted (DynamoDB + S3). A read-only web frontend lists projects, follows a render live, and shows the finished storyboard alongside each shot's details and the story's cast and locations. The canvas editor is not yet built. See [Status](#status) below for exactly what works today.

## What this is

Most "AI storyboard" tools hand you a finished image and hope it's right. TaleBoard is built around a different idea: the model's job is to propose a starting point (who's in a shot, where they're positioned, how they're framed), not to be the final word on it. Each shot becomes a stack of editable layers: the background and each character cutout can be moved, resized, flipped, or skewed directly on the canvas, so fixing the blocking is free and instant. A generation is only redone when the user explicitly asks for it, one layer at a time, and it keeps that layer's placement.

A story is broken into paragraphs, each paragraph into one or more shots, and each shot into a location plus per-character regions (position, size, orientation) — all validated against a strict schema rather than trusted as free text.

## Status

**Working, tested against AWS Bedrock:**
- **Cast extraction** — reads a story, identifies named characters who physically appear (unnamed background figures, and people who only appear in memories or as a voice, are left out), assigns each a stable, collision-safe ID, and records every other way the story refers to them (aliases, surnames etc.) so later references resolve to the right character. Descriptions are kept strictly visual, because they go straight into image prompts.
- **Location extraction** — lists the distinct places the story's present action happens in, each with an ID and one fixed visual description. The same place at another time of day, or with a door now open, stays one location; what changes from shot to shot is recorded per shot instead.
- **Shot breakdown** — splits a paragraph into one or more shots. Each shot names its location by ID (so every shot in the same place is drawn from the same description, however the paragraph words it), plus small visible `details` for that shot ("rain on the window", "the desk drawer open"), and per-character regions constrained to the real extracted cast. Handles multi-shot paragraphs, cross-paragraph continuity (a character's position/orientation, and the location, carry forward unless the text says otherwise), and within-paragraph consistency across multiple shots in one response.
- **Contamination judge** — anything drawn on its own is checked by a second LLM call before any image is generated: each character's action (drawn alone, so another person or a piece of furniture in it would be drawn into their cutout), each shot's details and each location's description (drawn with nobody in them, so a cast member mentioned there would appear twice), and each character's description. Flagged text is rewritten in place and checked again, within a capped number of rounds. The judge fails open: if its answer can't be used, the text goes through unjudged rather than failing the job.
- **Validation and recovery** — LLM output is validated per-item against a Pydantic schema; a failing item is retried with its specific validation error fed back to the model; anything still invalid after retries is replaced with a flagged, safe fallback rather than silently dropped or left invalid. A character given two regions in one shot keeps only the first.
- **Whole-story breakdown** — `break_down_story()` splits a story into paragraphs, extracts and judges the cast and locations once, and breaks each paragraph down in order, passing each one the previous paragraph's last shot for continuity. An empty story is rejected with a clear error before any paid API call.

**Working, tested against Together AI:**
- **Character rendering** — each character region is turned into a monochrome, background-removed line-art cutout and composited onto the shot canvas at the position, size, and orientation the shot breakdown specified. Camera angle (eye-level/low/high) is reflected in the generation prompt, not just a label on the shot.
- **Consistent locations via master plates** — the first time a location is needed, it gets a **master plate**: one wide, eye-level view of the empty place, generated from its description. Every other background of that location is generated with the master plate as a reference image, so every shot in a place shows the same room. Each generation changes one thing only: a different framing (medium shot, low or high angle) is drawn from the master plate with explicit wording for where the camera has moved, and a shot's `details` are drawn as an edit of that framing without them. Doing both at once let the room drift, so they're never combined. A wide, eye-level shot with no details is the master plate itself, at no extra cost.
- **Close-ups by cropping** — a close-up is never generated. It is composited like a wide shot (wide background, figures at a wide shot's scale), then cropped to the square around its figures and enlarged back to full size, up to 2×. Room and figures zoom together, so a close-up is a genuinely closer view of the same place rather than a new room or a giant figure in front of a distant one.
- **Character consistency via reference conditioning** — each character gets one neutral reference pose (eye-level, facing camera), generated once per project and cached. Every subsequent pose of that character is conditioned on it through FLUX.2's `reference_images` input, so a character keeps the same look across different shots and poses.
- **Direct LEFT/RIGHT orientation** — FLUX.2-dev follows directional prompts reliably, so every orientation is its own real generation (with its own cache entry).
- **Characters sharing a cell stand side by side** — the shot breakdown places characters on a 3×3 grid. Two characters given the same cell are spread side by side (the one facing right on the left, so they face each other) instead of being pasted exactly on top of each other.
- **No duplicate generations via caching** — a generation is only ever produced once per unique `(character, action, orientation, camera angle)` combination; any later shot reusing that exact combination (anywhere in the project, not just the adjacent shot) reuses the cached cutout instead of paying for a new one. Backgrounds are cached separately, keyed on `(location, details, framing, angle)`, each location's master plate once, and each character's reference image once, all for the whole project.
- **Cutout validation** — a cutout that background removal leaves (nearly) empty, or see-through (most of the figure only partly opaque, a threshold measured on real cutouts), is never cached. It is regenerated once, and if it still fails, that character is left out of the shot and the shot is flagged `needs_review` rather than silently rendering an invisible or ghostly character.
- **Transient error handling** — FLUX.2-dev occasionally returns spurious 400 errors that succeed on an identical retry; these are retried automatically, on top of the SDK's own rate-limit/server-error retries.
- **Tested end to end** — an integration test runs a real 8-paragraph story through the whole pipeline with nothing hand-built in between, checking alias resolution, character presence per paragraph, one reference image per character, one master plate per location, and that every shot renders. A run costs about **$0.50** (~30 FLUX images plus a few dozen Bedrock calls, ~95% of it image generation), so roughly a dozen stories of that length a month fit the £5 budget.

**Working, deployed on AWS:**
- **Persistence** — a project lives in a single DynamoDB table (metadata, cast, locations, and one item per shot), with every generated image in S3. All four render caches (backgrounds, poses, character references, location master plates) are persisted too, so nothing is paid for twice, even across separate render jobs on the same project.
- **HTTP API** — FastAPI on Lambda behind API Gateway: create and list projects, submit a story, poll render progress, and fetch shots, characters and locations. Images are returned as presigned S3 URLs, so image bytes never pass through the API.
- **Asynchronous render jobs** — submitting a story enqueues a job on SQS and returns immediately; a container-image worker Lambda breaks the story down and renders it. Jobs are safe to retry: a lease stops two workers rendering the same job, the breakdown is checkpointed so a retry never pays for it again, and a retry resumes from the first unrendered shot. A job that needs longer than one Lambda run (15 minutes) hands itself off to a fresh one.
- **Failure handling** — bad input fails a job immediately; a transient failure is retried, a minute apart, for up to 5 attempts; a job that still can't finish lands on a dead-letter queue, where a recovery Lambda marks it failed (with a CloudWatch alarm). A failed project can take a new story, reusing everything already cached.
- **Infrastructure as code** — the whole backend is one AWS CDK (Python) stack with least-privilege IAM: each Lambda can reach only what it uses, and deploys run through CDK's bootstrap roles rather than an admin user. The Together AI key lives in SSM Parameter Store, and the API is throttled as a cost guard. Every request needs a shared X-API-Key header, a cost guard rather than real authentication. The worker image installs its dependencies before copying the code, so a code-only change rebuilds (and uploads) one small layer in seconds rather than the whole 2.4GB image.
- **Tested end to end on AWS** — a real story renders completely through the deployed stack: a 58-shot story with six locations came out with each place recognisably the same room throughout, for 23 background generations (6 master plates + 17 framings) rather than one per shot.

**Working, web frontend** (`frontend/`, read-only):
- **Project list** — every storyboard made so far, newest first, with its status, so a project is never lost along with its link.
- **Live progress** — a submitted story's render is followed as it happens, with shots appearing as they finish.
- **Storyboard view** — a slideshow of every shot, each beside a panel of its details: shot size, angle and duration; its location and that shot's details; and each character's position, size, facing and action.
- **Cast & locations** — every character with their reference image, and every location with its master plate.

**Known issues:**
- **Camera angle prompting is unreliable on character generation.** Camera angle prompting doesn't work great on characters (although it works on the background!).
- **Character/background compositing has no perspective or scale matching.** A character cutout and its background are two independently generated images; the only thing tying them together is sharing the same camera-angle wording. This was an explicit, accepted trade-off rather than an oversight — true scene-consistent compositing would need real 3D scene reasoning neither generation call does. In practice, a receding hallway background makes characters look like flat cutouts pasted onto the side walls, since nothing accounts for the scene's vanishing point. This can be mitigated to some extent using the editor's skew control -- a cutout can be nudged towards a background's vanishing point when it's visibly off.
- **Scene details occasionally leak into character cutouts.** Each character is generated alone on a blank background from their action text. When that text implies a large prop or a place ("gripping the tiller of a boat"), FLUX draws it too, and background removal leaves it as a faint box behind the character. The breakdown prompt and the contamination judge both work against this, which makes it rare but doesn't eliminate it.
- **Re-framed backgrounds can drift in small details.** A medium shot or a low/high angle of a location is a new generation from its master plate, guided by generic camera wording. The room stays recognisably the same, but small details (a window's pane count, a desk's design) can differ from the master plate. Close-ups are exact, since they're crops.
- **Close-ups are always full-body.** Every cutout is a whole figure, so a close-up is a closer view of the scene, never a face filling the frame.
- **Camera variety is limited.** Shots lean heavily towards medium, eye-level framing, even with the breakdown prompt asking for variety.
- **Together AI sometimes doesn't respond.** Around one in five image requests from Lambda hang with no response. Each call gives up after 30 seconds and retries, so a hang costs about half a minute instead of failing the job, and hung requests aren't billed; it still makes a story slower than it should be.
- **Cold starts are slow.** The first job after a quiet period waits about a minute for the worker to start, most likely Lambda loading the 2.4GB container image. Slimming the image is the planned fix.

**Not yet built:**
- The canvas editor (see [Planned: Canvas Editor](#planned-canvas-editor)) — the frontend only displays storyboards for now.
- Deleting projects (there's no endpoint yet; it's done by hand in AWS for now).

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

**Regeneration** applies only to generated layers (`background`, `character`). It replaces just that layer's source image and keeps the transform, opacity, group membership, and stack position. Each generated layer stores its own generation parameters, so it is regenerated from a comparable prompt, still conditioned on the character's reference image (or the location's master plate).

**Storage** is hybrid. Layer images are S3 object keys, cached under the same keys the renderer already uses in memory, and served to the frontend through presigned URLs so image bytes never pass through the API. Transforms, metadata, and freehand strokes stay inline in the shot JSON. This keeps shot documents small, stays within Lambda payload limits, and costs next to nothing at this scale. The trade-off is lifecycle cleanup: old objects have to be removed when a layer is regenerated or a shot is deleted.

## How it works

0. **Orchestration** — `break_down_story()` drives steps 1–4: it splits the story into paragraphs, runs cast and location extraction once, then breaks each paragraph down in order.

1. **Cast extraction** — the story text is sent to Claude Haiku 4.5 (via Bedrock) with a prompt asking it to identify named characters and give each a short, visual (not personality/backstory) description plus a list of aliases (other names, titles, or roles the story uses for them). The response is validated against a Pydantic schema, then each character is assigned a unique, slugified ID (`alice`, `sam_1`/`sam_2` for duplicate names, with a collision-safety net for edge cases like a duplicated "Sam" sharing a cast with literally-named "Sam 1"/"Sam 2").

2. **Location extraction** — the same way, a second call lists the story's locations, each with a short name and one fixed visual description of the empty place (architecture, furniture, fixtures — never people, mood, or anything that changes during the story). Locations get IDs the same way characters do.

3. **Shot breakdown** — each paragraph is sent to the model one at a time, along with the fixed cast and locations (so it can only reference real character and location IDs, never invent one), the cast's aliases, and the last shot from the previous paragraph (for continuity). The model returns one or more shots, each with a camera size/angle, duration, a location ID, the shot's `details`, and a list of per-character regions (a 3×3 grid position, relative size, facing direction, and action). Bedrock's native structured-output mode constrains the response to this exact schema at generation time, rather than hoping the model's free-text JSON happens to be well-formed. Each region's action describes only pose, gesture, and expression, because it's used to draw that character alone on a blank background.

4. **Validation, judging and retry** — every shot is validated individually (not as part of one big list), so one malformed shot doesn't invalidate an entire paragraph's worth of otherwise-good output. A failing shot is retried with its specific Pydantic error fed back to the model; a shot that passes has its actions and details checked by the contamination judge (as are the cast's and locations' descriptions, once per story), and any rewrite is applied and checked again. After a capped number of rounds, a still-invalid shot is replaced with a safe, flagged placeholder rather than silently dropped.

5. **Rendering** — a shot's background comes first. A location's master plate is generated the first time it's needed; the shot's framing is drawn from it (or is the master plate itself, for a wide eye-level shot), and the shot's details, if any, are drawn as an edit of that framing. Then, if the shot has character regions, each region is turned into a prompt (style, orientation, camera angle, and the character's own description/action), sent to Together AI's FLUX.2-dev (portrait-framed, to give a standing figure room to fit head-to-toe) along with that character's cached reference image for consistency, then background-removed, checked for an empty or see-through result (regenerated once, else left out and flagged), and deterministically converted to monochrome. A cache keyed on `(character, action, orientation, angle)` means a pose already generated anywhere in the project is never paid for twice; backgrounds are cached separately on `(location, details, framing, angle)`. Finished character cutouts are scaled (by the region's size and the shot's overall shot size) and composited onto the background at the position the shot breakdown specified, with characters sharing a cell spread side by side. A close-up is then cropped around its figures as the last step.

6. **Persistence** — images are written to S3 before the DynamoDB item that points at them, so a crash never leaves a record pointing at a missing image. A shot's composite image key doubles as the job's progress marker: the status endpoint counts rendered shots by it, and a retried job resumes from the first shot without one. There's one source of truth, with no separate checkpoint to drift out of sync.

7. **Request flow** — `POST /projects/{id}/story` stores the story in S3, marks the project pending, enqueues a job and returns 202 straight away. The worker Lambda claims a lease on the job, runs the breakdown (steps 0–4) unless an earlier attempt already saved it, renders every unrendered shot (step 5), and marks the project complete. Clients poll `GET /projects/{id}/status` for progress.

## Tech stack

- **Python 3.13**, **Pydantic v2** for schema validation and JSON-schema generation
- **AWS Bedrock** (Claude Haiku 4.5, via `boto3`) for structured LLM output — chosen specifically to demonstrate real AWS usage on a tight budget (native structured outputs avoid unreliable free-text JSON parsing, and Haiku 4.5's pricing keeps this well under £5/month at expected usage)
- **Together AI** (FLUX.2-dev) for all image generation, both characters and backgrounds. This was chosen as it allows image-conditioned prompts -- an important feature to ensure character and location consistency across shots. It is also fairly cheap to run ($0.0154/image).
- **Pillow**, plus an isnet-anime-based background removal model (rembg, run on CPU), for turning a raw generation into a clean, background-free, monochrome cutout
- **AWS Lambda**, **API Gateway** (HTTP API), **SQS** (with a dead-letter queue), **DynamoDB**, **S3**, **SSM Parameter Store** and **CloudWatch**, all defined in one **AWS CDK** (Python) stack
- **FastAPI** (served on Lambda via Mangum) for the API. The worker runs as a **Docker** container image, since the rendering dependencies are too big for a zipped Lambda; the background-removal model and compiled code are baked in, so a cold start never downloads anything
- **React**, **Vite** and **TypeScript** for the frontend, with **Tailwind** and **shadcn/ui** for styling, **TanStack Query** for server state and polling, and API types generated from the live API's OpenAPI schema
- **pytest**, split into a fast/free **unit** tier (fake LLM/image calls, with DynamoDB, S3, SQS and SSM faked by **moto**; runs in seconds) and a slower, real-cost **integration** tier (`pytest -m integration`) that actually calls Bedrock and Together AI

## Project structure

```
src/
├── requirements.txt          # runtime dependencies for the zipped API and dead-letter Lambdas
└── taleboard/
    ├── schema/
    │   ├── enums.py          # closed vocabularies fed to the LLM (shot size, camera angle, orientation, ...)
    │   └── models.py         # Project, Character, Location, Shot, Region: the domain model everything builds on
    ├── parsing/
    │   ├── llm_schemas.py     # Pydantic models for LLM input/output, including dynamic
    │   │                      # cast- and location-constrained schema builders
    │   ├── prompts.py         # prompt templates for cast and location extraction, shot breakdown and the judge
    │   ├── cast_extraction.py
    │   ├── location_extraction.py
    │   ├── shot_breakdown.py
    │   ├── contamination_judge.py  # checks and rewrites text that would be drawn into the wrong image
    │   ├── story_breakdown.py # whole story -> cast + locations + ordered shots (top-level parsing entry point)
    │   └── bedrock_caller.py  # AWS Bedrock Converse API integration
    ├── rendering/
    │   ├── prompts.py          # builds FLUX prompts: characters, master plates, re-framings and detail edits
    │   ├── together_caller.py  # Together AI FLUX.2-dev image generation (separate character/background aspect ratios, reference-image conditioning)
    │   ├── background_removal.py  # isnet-anime based background removal
    │   ├── shot_renderer.py    # orchestrates reference images, master plates, character + background generation, caching, and monochrome conversion
    │   ├── compositor.py       # pastes finished character cutouts onto a shot's background, then crops close-ups
    │   └── layout.py           # PositionCell/SizeInFrame/ShotSize -> pixel geometry, shared-cell spreading and the close-up crop
    ├── storage/
    │   ├── project_store.py    # DynamoDB + S3 persistence: projects, cast, locations, shots, job leases, images, presigned URLs
    │   └── caches.py           # persistent versions of the four render caches
    ├── jobs/
    │   ├── queue.py            # SQS job queue (enqueue, delayed redelivery)
    │   ├── worker.py           # worker Lambda: claims a job, breaks the story down, renders shots, retries and resumes
    │   └── dead_letters.py     # recovery Lambda: marks dead-lettered jobs failed
    └── api/
        └── app.py              # FastAPI app (served on Lambda via Mangum)

frontend/                       # React + Vite web app (see frontend/README.md)
└── src/
    ├── api/schema.d.ts         # API types, generated from the live API (npm run gen:api)
    ├── lib/                    # typed API client, cast/location lookups, display labels
    └── components/             # story form, project list, live progress, storyboard, shot panel, gallery

docker/
├── worker.Dockerfile           # worker container image: rendering stack + baked background-removal model
└── worker-entrypoint.sh        # copies the precompiled numba cache into /tmp before starting the Lambda runtime

infra/                          # AWS CDK app (Python): one stack for the whole backend
├── app.py
├── taleboard_stack.py
└── cdk.json                    # CDK settings, incl. the allowed CORS origin(s)

tests/
├── conftest.py                 # loads .env credentials before any test runs
├── unit/                       # fast, free, no real AWS or Together AI calls
│   ├── conftest.py             # moto-backed DynamoDB/S3/SQS fakes shared by the storage, jobs and API tests
│   └── parsing/  rendering/  storage/  jobs/  api/
└── integration/                # real calls: costs money, needs credentials
    ├── parsing/                # real Bedrock calls
    ├── rendering/              # real Together AI calls
    └── test_story_to_render_live.py  # full story -> rendered shots, with cost logging
```

## Running it

### Locally
Requires an AWS account with Bedrock model access granted for Claude Haiku 4.5 in your chosen region, local AWS credentials boto3 can find (e.g. via `aws configure`), and a Together AI API key (`TOGETHER_API_KEY`) for image generation. Put `TOGETHER_API_KEY` in a `.env` file at the repo root; the tests load it automatically (see `tests/conftest.py`).

```bash
pip install -e ".[dev]"
python -m pytest -m "not integration"   # fast, free
python -m pytest -m integration         # real Bedrock + Together AI calls
python -m pytest tests/integration/test_story_to_render_live.py -m integration -s   # full pipeline, ~$0.50 per run
```

Output (rendered shots, master plates, shots.json, run_log.json with costs, and a contact sheet) is written to tests/integration/output/e2e/, which is git-ignored.

### Deploying to AWS
Needs Docker running (the worker image and Lambda packages are built locally), Node.js for the CDK CLI, and Bedrock access to Claude Haiku 4.5 in eu-west-2. Set your own AWS account ID in `infra/app.py`, and store two SecureStrings in SSM Parameter Store: your Together AI key as `/taleboard/together-api-key`, and a random API key as `/taleboard/api-key`. `corsOrigin` in `infra/cdk.json` takes a comma-separated list of the origins allowed to call the API from a browser (e.g. the deployed frontend and `http://localhost:5173`); `*` allows any.

```bash
npm install -g aws-cdk
pip install -r infra/requirements.txt
cd infra
cdk bootstrap # once per account and region
cdk deploy # prints the API URL
```

Then, with `$API` set to that URL, `$API_KEY` to your API key, and `$PROJECT_ID` to the ID the first call returns:

```bash
curl -X POST $API/projects -H "content-type: application/json" -d '{"name": "My story"}' -H "X-API-Key: $API_KEY"   # returns the project_id
curl -X POST $API/projects/$PROJECT_ID/story -H "content-type: application/json" -d '{"story": "..."}' -H "X-API-Key: $API_KEY"
curl $API/projects/$PROJECT_ID/status -H "X-API-Key: $API_KEY"      # poll until "complete"
curl $API/projects/$PROJECT_ID/shots -H "X-API-Key: $API_KEY"       # shots, with presigned image URLs
curl $API/projects/$PROJECT_ID/locations -H "X-API-Key: $API_KEY"   # locations, with presigned master plate URLs
```

### The frontend
Needs Node.js 22+ and a deployed API. Create `frontend/.env.local` with `VITE_API_URL` and `VITE_API_KEY`, then:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

See `frontend/README.md` for keeping the API types in sync and deploying to Vercel.
