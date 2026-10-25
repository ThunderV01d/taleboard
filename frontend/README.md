# TaleBoard frontend

The TaleBoard editor. Sign in, make a project, fill its registries (characters, locations and props), then lay out each scene's shots on a canvas: a layer graph of a background, characters, props, text and uploaded images, each one moved, resized, rotated, skewed, flipped, grouped, reordered or perspective-warped by hand. Shots save themselves as you work, and undo/redo covers every edit.

Built with React + Vite + TypeScript, Tailwind and shadcn/ui. Server state is handled by TanStack Query, and the API client is typed from the backend's own OpenAPI schema via `openapi-fetch`. Sign-in uses Amazon Cognito through Amplify's Auth library; the canvas is Konva (`react-konva`), and drag-and-drop lists use dnd-kit.

## Setup

Needs Node.js 22+. Create `frontend/.env.local` (git-ignored) with the values from the backend stack's outputs (`ApiUrl`, `UserPoolId`, `UserPoolClientId` and `AuthDomain`):

```
VITE_API_URL=https://<api-id>.execute-api.eu-west-2.amazonaws.com
VITE_COGNITO_USER_POOL_ID=eu-west-2_<pool-id>
VITE_COGNITO_CLIENT_ID=<app-client-id>
VITE_COGNITO_DOMAIN=<prefix>.auth.eu-west-2.amazoncognito.com
```

None of these are secrets -- they all end up in the built JavaScript. Every API route checks the Cognito access token sent with each request, and each user only ever sees their own projects.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-checks, then builds to dist/
npm run lint
npm test           # unit tests (vitest): the layer graph, the editor's state and the warp maths
```

Google sign-in sends the browser back to `/auth/callback`, so the origin you run on must be one of the app client's callback URLs. These come from `corsOrigin` in `infra/cdk.json` (see Deploying below); `http://localhost:5173` is already in it.

## Keeping the API types in sync

`src/api/schema.d.ts` is generated, never edited by hand. It's built straight from the FastAPI app (every deployed route, `openapi.json` included, needs a sign-in token), so it needs the backend's Python environment, as for its tests. After any backend API change, regenerate it and fix whatever no longer type-checks:

```bash
npm run gen:api
```

## Deploying (Vercel)

Import the repo into Vercel with the project's **Root Directory** set to `frontend`; Vercel detects Vite and runs `npm run build`. Set the four `VITE_` variables above as environment variables in the Vercel project settings. `vercel.json` sends every path to `index.html`, so links into the app (eg:- `/projects/<id>`) load on a refresh. Every push to `main` then redeploys.

Once the site has its domain, allow it to call the API and to finish a Google sign-in: add it to `corsOrigin` in `infra/cdk.json` (a comma-separated list, eg:- `https://<your-app>.vercel.app,http://localhost:5173` to keep local development working) and redeploy the backend. Each origin becomes a CORS origin, a callback URL (`/auth/callback`) and a sign-out URL. Google's OAuth client also needs the Cognito domain's `/oauth2/idpresponse` as an authorised redirect URI.

## Canvas conventions

The backend's compositor (which turns a shot's layers into one image) must draw exactly what the canvas shows, so both follow these:

- Shots are a 1024 x 1024 frame. A layer's transform places its **centre**, in its parent's space: the frame at the top level, or the group's centre (its pivot) inside a group.
- Transforms apply as translate, rotate, skew, scale (Konva's order); rotation and skew are stored in degrees.
- A background is stretched to fill the frame; any other picture is drawn at its image's own size, times its scale.
- A picture's `corners` (if any) warp it before its transform: each is a fraction of its own width and height, mapped by a perspective transform (homography) from its rectangle (see `src/lib/warp.ts`).

## Structure

```
src/
├── api/schema.d.ts            # generated API types (npm run gen:api)
├── assets/logo.svg
├── lib/
│   ├── api.ts                 # typed API client, with the sign-in token added to every request
│   ├── auth.ts, auth-state.ts # Amplify/Cognito setup; the signed-in user, for any component
│   ├── projects.ts, scenes.ts, shots.ts, registries.ts
│   │                          # queries and changes for each resource (reorders show at once, before the API answers)
│   ├── uploads.ts             # presigned browser uploads straight to S3
│   ├── layers.ts              # the layer graph: building, walking and editing the tree; transform maths
│   ├── shot-editor.ts         # the canvas editor's state: draft, saved baseline, undo/redo, selection
│   ├── warp.ts                # perspective warp: corner checks, the homography, drawing as a triangle mesh
│   ├── *.test.ts              # unit tests for the three above
│   └── labels.ts              # display names for every enum
├── pages/
│   ├── landing.tsx, login.tsx, sign-up.tsx, auth-callback.tsx, not-found.tsx
│   ├── projects.tsx           # your projects
│   ├── project-editor.tsx     # one project: scene picker, the open shot's editor, the shot deck
│   └── registry.tsx           # a project's characters, locations or props
├── components/
│   ├── app-header.tsx         # logo, the open project's name, account
│   ├── auth-provider.tsx, auth-card.tsx, google-button.tsx, route-guards.tsx
│   ├── editor/                # scene picker and dialog, shot deck and dialog
│   ├── canvas/
│   │   ├── shot-editor.tsx    # one shot: tools + layers + shot details | canvas | layer details; autosave and conflicts
│   │   ├── shot-canvas.tsx    # the Konva frame: layers, selection, transform box, Distort's corner handles
│   │   ├── layers-panel.tsx   # the layer tree: add, delete, show/hide, drag to reorder or group
│   │   ├── properties-panel.tsx # the selected layer's properties, and the shot's
│   │   └── tool-strip.tsx, number-field.tsx
│   ├── registry/              # registry entry editor and delete dialog
│   ├── sortable.tsx           # drag-to-reorder lists (scenes, shots)
│   ├── delete-dialog.tsx, name-dialog.tsx, enum-select.tsx, logo.tsx, theme-provider.tsx
│   └── ui/                    # shadcn/ui components (generated; add more with npx shadcn@latest add ...)
├── App.tsx                    # routes
└── main.tsx
```
