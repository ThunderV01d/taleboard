[![CI](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml/badge.svg)](https://github.com/ThunderV01d/taleboard/actions/workflows/ci.yml)
# TaleBoard

Turn a story into an editable storyboard! You, the user, have control of framing, blocking, and pacing.

**Status: release 0.2.0 in progress.** The live site runs release 0.1.0: a story goes in, and a finished storyboard comes out, generated end to end on AWS (Bedrock for the breakdown, Together AI for the images, DynamoDB + S3 for storage). Release 0.2.0, on `main`, turns that storyboard into something you edit: sign-in, projects with registries of characters, locations and props, scenes, and a canvas editor where every shot is a stack of layers -- each one generated, and redrawn, on its own. A project can start blank or from a story, which is broken down into scenes and shots and (by default) drawn. Regenerating a layer when what it depends on changes, and freehand sketching, are the last milestone before release. See [Status](#status) below for exactly what works today.

## What this is

Most "AI storyboard" tools hand you a finished image and hope it's right. TaleBoard is built around a different idea: the model's job is to propose a starting point (who's in a shot, where they're positioned, how they're framed), not to be the final word on it. Each shot is a stack of editable layers: the background, each character and each prop can be moved, resized, flipped, skewed or perspective-warped directly on the canvas, so fixing the blocking is free and instant. A generation is only redone when the user explicitly asks for it, one layer at a time, and it keeps that layer's placement.

A story is broken into scenes (each a run of paragraphs in one place, at one time), each paragraph into one or more shots, and each shot into a facing plus the characters and props in it (position, size, orientation, and who's holding what) -- all validated against a strict schema rather than trusted as free text.

## Status

**Working, tested against AWS Bedrock -- story import:**
- **Cast extraction** -- reads a story, identifies named characters who physically appear (unnamed background figures, and people who only appear in memories or as a voice, are left out), assigns each a stable, collision-safe ID, and records every other way the story refers to them (aliases, surnames etc.) so later references resolve to the right character. Descriptions are kept strictly visual and committed to one look -- no personality, no expression, nothing they hold -- because they go straight into image prompts.
- **Prop extraction** -- lists the portable objects characters hold, carry or use. Characters are always drawn empty-handed; whatever they hold is a prop, drawn on its own and placed at their hand. Fixtures, however important to the story (a lighthouse's lens), stay part of the place.
- **Location extraction** -- lists the distinct places the story's present action happens in, each with a setting (interior or exterior), a description of what the whole place has in common, and a view of what's on each of its four sides -- every fixed feature the story mentions placed on exactly one side. The same place at another time of day, or with a door now open, stays one location. Props are left out of every place, so nothing is drawn twice.
- **Scenes** -- the story is split into scenes: runs of consecutive paragraphs in one location, each with a time of day and atmosphere that light every shot in it.
- **Shot breakdown** -- splits each paragraph into one or more shots, knowing its scene and the views of its location. Each shot says which way the camera faces, its framing, small visible `details` for that shot ("rain on the window"), and the characters and props in it -- constrained to the real extracted cast and props, with each held prop naming its holder. Handles multi-shot paragraphs, and continuity within a scene (a character's position and orientation, and the facing, carry forward unless the text says otherwise).
- **Contamination judge** -- anything drawn on its own is checked by a second LLM call before any image is generated: each character's action (drawn alone and empty-handed, so another person, a piece of furniture or a held object in it would be drawn into their cutout), each shot's details and each location's description and views (drawn with nobody in them, so a cast member or prop mentioned there would appear twice), and each character's and prop's description. Flagged text is rewritten in place and checked again, within a capped number of rounds. The judge fails open: if its answer can't be used, the text goes through unjudged rather than failing the import.
- **Validation and recovery** -- LLM output is validated per-item against a Pydantic schema; a failing item is retried with its specific validation error fed back to the model; anything still invalid after retries is replaced with a flagged, safe fallback rather than silently dropped. Harmless slips are tidied without a retry: a character given two regions keeps the first, an invented prop is dropped, and a prop held by someone not in the shot is put down.
- **Layout** -- each shot's characters and props become layers, placed on a 3×3 grid read as depth (further back is higher up the floor and smaller), with figures sharing a cell spread side by side, facing each other. A held prop is grouped with its holder at their hand, so moving the character moves the prop. A close-up is laid out a little larger, then cropped to its figures by scaling every layer, the background too.

**Working, tested against Together AI -- generation:**
- **Locations, one side at a time** -- each facing of a location is its own plate: a wide, eye-level view of the empty place, drawn from what the whole place has in common plus what's on that side. Every side but north is drawn with the north plate as a reference, so the materials match all round. A side with no view shows the north plate.
- **Backgrounds as a chain** -- a shot's background is built one change per generation, so a place never drifts from shot to shot: the plate, then its framing (shot size and angle), then the shot's details, then its lighting. Lighting knows indoors from outdoors -- a night interior gets lamplight, not a night sky -- and each link is skipped when it would change nothing.
- **Character consistency via references** -- each character gets a reference per orientation (the front one from their description, the others drawn from it), and each pose is drawn from the reference for its orientation through FLUX.2's `reference_images` input, so a character keeps the same look across every shot.
- **Props** -- each prop gets a reference too, drawn alone on white.
- **Nothing generated twice** -- every image is stored under a key made from everything it was drawn from (prompt and source images), so asking for an image that already exists anywhere in the project just finds it. Plates and references are also recorded on their registry entries, where they can be seen.
- **Cutouts** -- characters are cut out of their white background by an isnet-anime model; props by flood-filling the white around them (the model can't tell where a lone pencil-drawn object ends, and leaves it see-through). A cutout left (nearly) empty or see-through is regenerated once, then the layer fails with the reason rather than drawing an invisible or ghostly figure. Every layer image is monochrome, trimmed to the figure and fitted to a standard size, so a layer's scale alone says how big it is in the frame.
- **Transient error handling** -- a spurious 400 from Together AI is retried with growing waits; a request it keeps rejecting, or a prompt refused under its safety policy, fails only that layer. Image-to-image requests get two minutes before they count as stalled.

**Working, deployed on AWS:**
- **Persistence** -- a project lives in a single DynamoDB table (metadata, registries, scenes, one item per shot holding its layer graph, and jobs), with every image in S3.
- **HTTP API** -- FastAPI on Lambda behind API Gateway, one router per resource: projects; their characters, locations and props (each delete reports what it takes with it first); scenes, each pinned to a location with a time of day and atmosphere; shots; drag-to-reorder for scenes and shots; presigned browser uploads straight to S3 (PNG or JPEG, up to 10 MB); generation; and story import. Shot saves are version-checked, so a save over someone else's newer one is refused (409) rather than lost. Images are returned as presigned S3 URLs, so image bytes never pass through the API.
- **Generation jobs** -- asking to generate a layer, a shot, a scene or the whole project first previews how many layers it would draw and, at most, how many images that takes; confirming saves a job with one task per layer and queues it. Jobs go on an SQS FIFO queue grouped by project, so a project's jobs run one at a time, in order, while different projects' run side by side. The worker draws each layer and saves it straight into its shot (a version-checked save, retried if the user saved meanwhile), and a job that needs longer than one Lambda run hands itself on to a fresh one, carrying on from its first unfinished layer.
- **Story imports** -- an import is a job too: the story is saved beside it, and the worker breaks it down (every LLM call happens before anything is written), writes the registries, scenes and shots, and -- if asked to draw everything -- queues a generation job for every layer behind itself. A story that can't be broken down (eg:- one with no characters) fails at once with the reason.
- **Failure handling** -- a layer that can't be drawn fails alone, and its job goes on. A failure a retry might fix fails the delivery, which is retried a minute later, for up to 5 attempts; a job that still can't finish lands on a dead-letter queue, where a recovery Lambda marks it failed (with a CloudWatch alarm).
- **Infrastructure as code** -- the whole backend is one AWS CDK (Python) stack with least-privilege IAM: each Lambda can reach only what it uses, and deploys run through CDK's bootstrap roles rather than an admin user. The Together AI key lives in SSM Parameter Store, the API is throttled, and the worker runs at most two jobs at once, as cost guards. Every request needs a Cognito access token, checked by an API Gateway JWT authorizer before the API runs, and each project belongs to the user who made it -- anyone else gets the same 404 as for a missing project. The app defines two stacks: `TaleboardStack` (the live 0.1.0 release) and `TaleboardStack-dev` (0.2.0 development). The worker image installs its dependencies before copying the code, so a code-only change rebuilds (and uploads) one small layer in seconds rather than the whole 2.4GB image.
- **Accounts** -- Amazon Cognito: sign up with an email and password (confirmed by an emailed code), or sign in with Google. A first Google sign-in is linked to an existing confirmed account with the same email, by a pre-sign-up Lambda, so one person never ends up with two accounts; a password sign-up for an email that already uses Google is refused.

**Working, web frontend** (`frontend/`):
- **Sign-in and projects** -- email and password or Google; each user sees only their own projects. A new project starts blank or from a pasted story, with "draw every layer" ticked by default; the editor shows the import's progress, then each shot fills in as its layers are drawn.
- **Registries** -- a project's characters, locations and props, each with a name and a description, a location's setting and the view on each of its sides, and the reference images (or, for a location, the plates) that every shot is drawn from. Deleting one first shows what goes with it (eg:- the layers a character appears in).
- **Scenes and shots** -- a scene picker (drag to reorder) and a deck of the scene's shots along the bottom (drag to reorder).
- **Canvas editor** -- each shot is a stack of layers: a background, characters, props, text, uploaded images and groups. Layers are moved, resized, rotated, skewed and flipped on the canvas or by number, dragged in the layer tree to reorder them or into groups, and shown, hidden or deleted (with a confirmation listing what a group takes with it). Pictures can be perspective-warped with the Distort tool, by dragging their corners.
- **Generation** -- generate one layer, the open shot, or everything in the project. Layers waiting or being drawn are marked as such, a failed layer says why, and drawn images are merged into whatever you're editing rather than overwriting it.
- **Saving** -- every edit is undoable, and the shot saves itself a moment after you stop. If the same shot was saved somewhere else in the meantime, you choose which version to keep.

**Known issues:**
- **Together AI is unreliable with image-to-image requests.** Drawing from a reference image takes 25-30 seconds, sometimes over a minute, and some days a large share of those requests come back as a spurious 400 ("Inference error") that works on a retry. Retries and per-layer failure keep a job going, but a long story draws slowly, and a few layers may need generating again.
- **A whole story costs real money to draw.** At $0.0154 an image, a long story's hundreds of layers (with the references and background chains behind them) can come to several dollars; the Generate dialog shows the most it could take before anything is drawn.
- **Props with a hole keep it white.** The flood fill can't reach a white area its outline encloses, so the inside of a mug's or a lantern's handle stays filled in.
- **Prop extraction sometimes oversteps.** Clothing or a door occasionally comes through as a prop, and a prop can be drawn as what's in it (a photograph of a cake drawn as a cake). Each is quick to fix in the registry.
- **Camera angle prompting is unreliable on character generation.** Camera angle prompting doesn't work great on characters (although it works on the background!).
- **Character/background compositing has no perspective or scale matching.** A character cutout and its background are two independently generated images; the only thing tying them together is sharing the same camera-angle wording. This was an explicit, accepted trade-off rather than an oversight -- true scene-consistent compositing would need real 3D scene reasoning neither generation call does. In practice, a receding hallway background makes characters look like flat cutouts pasted onto the side walls, since nothing accounts for the scene's vanishing point. This can be mitigated in the editor: a cutout can be skewed, or perspective-warped with the Distort tool, towards a background's vanishing point when it's visibly off.
- **Re-framed backgrounds can drift in small details.** A medium shot or a low/high angle of a location is a new generation from its plate, guided by generic camera wording. The room stays recognisably the same, but small details (a window's pane count, a desk's design) can differ from the plate. Close-ups are exact, since they're crops.
- **Close-ups are always full-body.** Every character image is a whole figure, so a close-up is a closer view of the scene, never a face filling the frame.
- **Cold starts are slow.** The first job after a quiet period waits about a minute for the worker to start, most likely Lambda loading the 2.4GB container image. Slimming the image is the planned fix.

**Not yet built:**
- Regenerating a layer when what it depends on has changed (the layers already record what they were drawn from), and replacing a registry entry's reference or plate with a sketch.
- Freehand drawing on the canvas (the brush and eraser tools are placeholders).
- Exporting a storyboard as an image or PDF.

## Canvas Editor

Each shot is a persistent **layer graph** rather than a single flattened image, so editing or regenerating one layer never disturbs the rest. Layers stack bottom-to-top:

| Layer | Contents |
|---|---|
| `background` | the scene's location, seen facing one way (generated) |
| `character` | a character from the registry, posed for this shot (generated) |
| `prop` | a prop from the registry (generated) |
| `text` | a caption or line of dialogue |
| `image` | a user-uploaded image |
| `group` | a nested container whose transform and opacity apply to its children (eg:- a character and the prop they hold) |

Every layer, groups included, has one transform (position, scale, rotation, skew), opacity, visibility and a name. That one transform covers move, resize, flip and skew uniformly; a picture can also be perspective-warped by moving its four corners. Coordinates are in a 1024 x 1024 frame, with a layer's position at its centre (see `frontend/README.md` for the exact conventions).

**Regeneration** applies only to generated layers. Each records the parameters its image was drawn from (facing, framing, angle, details, time of day, atmosphere, orientation, action), so a change to any of those marks it out of date, while moves, warps and restyles never do. Regenerating replaces just that layer's image and keeps its transform, corners, group and place in the stack.

**Storage** is hybrid. Layer images are S3 object keys, served to the frontend through presigned URLs so image bytes never pass through the API; the layer graph itself is stored inline in the shot's DynamoDB item.

**Still planned:** freehand drawing, stored as vector strokes (points, colour, width) so individual strokes stay editable, and rasterized only when the shot is flattened.

## How it works

**Importing a story** (`POST /projects/{id}/import`, into an empty project):

1. **Breakdown** -- the worker runs `break_down_story()`, all on Claude Haiku 4.5 via Bedrock. It extracts the cast, then the props, then the locations (props first, so the places can be told to leave them out), and the contamination judge checks every description and view. Each extraction is constrained to a Pydantic schema by Bedrock's native structured output, so the response always has the right shape, and a response that still fails validation is sent back once with the error.
2. **Scenes** -- one call splits the numbered paragraphs into scenes, each naming its first paragraph, its location (by ID, constrained to the real ones), its time of day and its atmosphere. A split that doesn't start at paragraph 0 and go forward is sent back; one that still fails becomes a single scene, to be split in the editor.
3. **Shots** -- each scene's paragraphs are broken into shots in order, each one given the scene, the four views of its location, the cast (with aliases), the props, and the scene's last shot so far for continuity. Every shot is validated on its own, so one malformed shot never sinks a paragraph; a failing one is retried with its error, a passing one has its actions and details judged (and rewritten, if flagged), and one still failing after the capped rounds becomes a flagged placeholder.
4. **Writing it** -- only now is anything stored: the registries, then each scene and its shots, each shot's characters and props laid out as layers (see Layout above). If the import was asked to draw everything, it queues a generation job for every layer, which runs right after it.

**Generating layers** (`POST /projects/{id}/generate`, for a layer, a shot, a scene or everything):

1. **Planning** -- the request is expanded into the layers that need drawing (no image yet, or drawn from settings that have since changed), in story order; a preview says how many, and at most how many images. Confirming saves them as a job's tasks and queues it.
2. **Drawing** -- the worker draws each task's layer in turn. A background walks its chain (plate, framing, details, lighting); a character finds or draws their reference for the orientation, then the pose; a prop finds or draws its reference. Every image is looked up by its content key first, so anything drawn before -- in this shot or any other -- costs nothing.
3. **Saving** -- each finished layer is saved straight into its shot with its image and the parameters it was drawn from, then its task is marked done, so the editor can show it at once. A retried or handed-over job carries on from its first unfinished task.

## Tech stack

- **Python 3.13**, **Pydantic v2** for schema validation and JSON-schema generation
- **AWS Bedrock** (Claude Haiku 4.5, via `boto3`) for structured LLM output -- chosen specifically to demonstrate real AWS usage on a tight budget (native structured outputs avoid unreliable free-text JSON parsing, and Haiku 4.5's pricing keeps this well under £5/month at expected usage)
- **Together AI** (FLUX.2-dev) for all image generation: characters, props and backgrounds. This was chosen as it allows image-conditioned prompts -- an important feature to ensure character and location consistency across shots. It is also fairly cheap to run ($0.0154/image).
- **Pillow**, **NumPy** and **SciPy**, plus an isnet-anime-based background removal model (rembg, run on CPU), for turning a raw generation into a clean, background-free, monochrome cutout
- **AWS Lambda**, **API Gateway** (HTTP API), **SQS** (a FIFO queue, with a dead-letter queue), **DynamoDB**, **S3**, **SSM Parameter Store** and **CloudWatch**, all defined in one **AWS CDK** (Python) stack
- **Amazon Cognito** for accounts (email and password, or Google), with an API Gateway JWT authorizer in front of every route
- **FastAPI** (served on Lambda via Mangum) for the API. The worker runs as a **Docker** container image, since the generation dependencies are too big for a zipped Lambda; the background-removal model and compiled code are baked in, so a cold start never downloads anything
- **React**, **Vite** and **TypeScript** for the frontend, with **Tailwind** and **shadcn/ui** for styling, **TanStack Query** for server state, **Konva** (`react-konva`) for the canvas, **dnd-kit** for drag-and-drop, **Amplify** for sign-in, **Vitest** for unit tests, and API types generated from the FastAPI app's OpenAPI schema
- **pytest**, split into a fast/free **unit** tier (fake LLM/image calls, with DynamoDB, S3, SQS and SSM faked by **moto**; runs in a few minutes) and a slower, real-cost **integration** tier (`pytest -m integration`) that actually calls Bedrock and Together AI

## Project structure

```
src/
├── requirements.txt          # runtime dependencies for the zipped API and dead-letter Lambdas
└── taleboard/
    ├── schema/
    │   ├── enums.py          # closed vocabularies fed to the LLM (shot size, camera angle, orientation, facing, ...)
    │   ├── base.py           # the base model: response schemas list fields with defaults as required, for exact frontend types
    │   ├── layers.py         # the layer graph: layer types, transforms, corners, and what each generated layer was drawn from
    │   ├── storyboard.py     # projects: registries, scenes and shots
    │   └── generation.py     # jobs: generation jobs and their tasks, and story imports
    ├── parsing/
    │   ├── llm_schemas.py     # Pydantic models for LLM input/output, including cast-, prop- and location-constrained schema builders
    │   ├── prompts.py         # prompt templates for extraction, scenes, shot breakdown and the judge
    │   ├── cast_extraction.py
    │   ├── prop_extraction.py
    │   ├── location_extraction.py  # locations, with a setting and a view of each side
    │   ├── scene_breakdown.py # paragraphs -> scenes
    │   ├── shot_breakdown.py  # one paragraph of a scene -> shots
    │   ├── contamination_judge.py  # checks and rewrites text that would be drawn into the wrong image
    │   ├── story_breakdown.py # whole story -> cast, props, locations, and scenes of shots (top-level parsing entry point)
    │   ├── placement.py       # a shot's characters and props -> layers: the depth grid, held props, close-ups
    │   ├── story_import.py    # a breakdown -> a project's registries, scenes and shots
    │   └── bedrock_caller.py  # AWS Bedrock Converse API integration
    ├── generation/
    │   ├── prompts.py          # FLUX prompts: plates, framings, details, lighting, character and prop references, poses
    │   ├── engine.py           # draws (or finds) a layer's image: the background chain, references and poses
    │   ├── cutouts.py          # cutting out, checking, monochrome, trimming and fitting; the flood fill for props
    │   ├── planning.py         # which layers a Generate request draws, and at most how many images that takes
    │   ├── together_caller.py  # Together AI FLUX.2-dev image generation (character and square sizes, reference images, retries)
    │   └── background_removal.py  # isnet-anime based background removal
    ├── storage/
    │   ├── storyboard_store.py # DynamoDB + S3: projects by owner, registries, scenes, version-checked shots, jobs, images, uploads
    │   └── cascades.py         # what deleting a character, prop or location takes with it
    ├── jobs/
    │   ├── queue.py            # the SQS FIFO job queue (one message group per project)
    │   ├── worker.py           # worker Lambda entry point: runs each message as a generation job or a story import
    │   ├── generation_worker.py  # draws a generation job's layers in order, hands over when time runs short
    │   ├── import_worker.py    # breaks a story down into a project, then queues its drawing
    │   └── dead_letters.py     # recovery Lambda: marks dead-lettered jobs failed
    ├── auth/
    │   └── link_accounts.py    # pre-sign-up Lambda: links a Google sign-in to an existing account with the same email
    └── api/
        ├── app.py              # FastAPI app (served on Lambda via Mangum)
        ├── deps.py             # the signed-in user, each project's ownership check, the job queue
        └── routes/             # projects, registries, scenes, shots, uploads, generation, imports

frontend/                       # React + Vite web app (see frontend/README.md)
└── src/
    ├── api/schema.d.ts         # API types, generated from the FastAPI app (npm run gen:api)
    ├── lib/                    # API client, sign-in, data hooks, generation, the layer graph, editor state, warp maths (+ tests)
    ├── pages/                  # landing, sign-in, projects, project editor, registries
    └── components/             # header, new-project dialog, scene picker, shot deck, canvas editor, registries, shared dialogs

docker/
├── worker.Dockerfile           # worker container image: generation stack + baked background-removal model
└── worker-entrypoint.sh        # copies the precompiled numba cache into /tmp before starting the Lambda runtime

infra/                          # AWS CDK app (Python): one stack for the whole backend
├── app.py
├── taleboard_stack.py
└── cdk.json                    # CDK settings, incl. the allowed CORS origin(s)

tests/
├── conftest.py                 # loads .env credentials before any test runs
├── unit/                       # fast, free, no real AWS or Together AI calls
│   ├── conftest.py             # moto-backed DynamoDB/S3/SQS fakes shared by the storage, jobs and API tests
│   └── parsing/  generation/  schema/  storage/  jobs/  auth/  api/
└── integration/                # real calls: costs money, needs credentials
    ├── parsing/                # real Bedrock calls: extraction and shot breakdown
    └── generation/             # real Together AI calls: the engine's prompts, and background removal compared
```

## Running it

### Locally
Requires an AWS account with Bedrock model access granted for Claude Haiku 4.5 in your chosen region, local AWS credentials boto3 can find (e.g. via `aws configure`), and a Together AI API key (`TOGETHER_API_KEY`) for image generation. Put `TOGETHER_API_KEY` in a `.env` file at the repo root; the tests load it automatically (see `tests/conftest.py`).

```bash
pip install -e ".[dev]"
python -m pytest -m "not integration"   # fast, free
python -m pytest tests/integration/parsing -m integration -s      # real Bedrock calls, about a cent a run
python -m pytest tests/integration/generation -m integration -s   # real Together AI calls, a few cents to a few tens of cents
```

The live tests print what the models returned, and the generation ones write labelled contact sheets to `tests/integration/generation/output/` (git-ignored) for judging the prompts by eye. Images already drawn are reused, so a rerun costs nothing.

### Deploying to AWS
Needs Docker running (the worker image and Lambda packages are built locally), Node.js for the CDK CLI, and Bedrock access to Claude Haiku 4.5 in eu-west-2. Set your own AWS account ID in `infra/app.py`, and store your Together AI key in SSM Parameter Store as the SecureString `/taleboard/together-api-key`. For Google sign-in, create an OAuth client in Google Cloud, put its client ID in `GOOGLE_CLIENT_ID` in `infra/taleboard_stack.py`, and store its client secret in Secrets Manager as `taleboard/google-client-secret`. `corsOrigin` in `infra/cdk.json` takes a comma-separated list of the frontend origins (eg:- the deployed frontend and `http://localhost:5173`); each becomes a CORS origin and a sign-in callback URL.

```bash
npm install -g aws-cdk
pip install -r infra/requirements.txt
cd infra
cdk bootstrap                  # once per account and region
cdk deploy TaleboardStack-dev  # prints the API URL, user pool, app client and sign-in domain
```

Then add the Cognito domain's `/oauth2/idpresponse` URL to the Google OAuth client's authorised redirect URIs. The API is meant to be used through the frontend: every route needs a Cognito access token as `Authorization: Bearer ...`.

On Windows, if a deploy fails with `EPERM: operation not permitted, rename ...` in `cdk.out`, something (usually antivirus scanning the fresh bundle) is holding the folder: delete `infra/cdk.out` and deploy again.

### The frontend
Needs Node.js 22+ and a deployed API. Create `frontend/.env.local` with `VITE_API_URL`, `VITE_COGNITO_USER_POOL_ID`, `VITE_COGNITO_CLIENT_ID` and `VITE_COGNITO_DOMAIN` (from the stack's outputs), then:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

See `frontend/README.md` for keeping the API types in sync and deploying to Vercel.
