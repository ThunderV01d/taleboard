# TaleBoard frontend

A read-only viewer for the TaleBoard API: submit a story, watch its shots render, then flick through the finished storyboard.

Built with React + Vite + TypeScript, Tailwind and shadcn/ui. Server state (polling included) is handled by TanStack Query, and the API client is typed from the deployed API's own OpenAPI schema via `openapi-fetch`.

## Setup

Needs Node.js 22+. Create `frontend/.env.local` (git-ignored) with:

```
VITE_API_URL=https://<api-id>.execute-api.eu-west-2.amazonaws.com
VITE_API_KEY=<the shared API key>
```

`VITE_API_KEY` is baked into the built JavaScript. That's deliberate: it keeps out casual visitors and bots that would otherwise run up image-generation costs, but it isn't real authentication, since anyone can read it from the bundle.

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-checks, then builds to dist/
```

## Keeping the API types in sync

`src/api/schema.d.ts` is generated from the live API's `/openapi.json`, never edited by hand. After any backend API change (and a deploy), regenerate it and fix whatever no longer type-checks:

```bash
npm run gen:api
```

## Deploying (Vercel)

Import the repo into Vercel with the project's **Root Directory** set to `frontend`; Vercel detects Vite and runs `npm run build`. Set `VITE_API_URL` and `VITE_API_KEY` as environment variables in the Vercel project settings. Every push to `main` then redeploys.

## Structure

```
src/
├── api/schema.d.ts          # generated API types (npm run gen:api)
├── lib/
│   ├── api.ts               # typed API client and calls
│   ├── navigation.ts        # open project ID, kept in the URL (?project=...)
│   └── labels.ts            # display names for shot sizes and camera angles
├── components/
│   ├── story-form.tsx       # title + story form that starts a render
│   ├── project-view.tsx     # polls a render job; shows progress, then the storyboard
│   ├── storyboard.tsx       # finished slideshow + shot grid
│   ├── shot-card.tsx        # one shot: image (or placeholder), description, framing
│   └── ui/                  # shadcn/ui components (generated; add more with npx shadcn@latest add ...)
├── App.tsx
└── main.tsx
```
