// Regenerates src/api/schema.d.ts from the deployed API's live OpenAPI schema.
// Run after any backend API change: npm run gen:api (reads VITE_API_URL from .env.local)
import { execSync } from "node:child_process"

const apiUrl = process.env.VITE_API_URL
if (!apiUrl) {
  throw new Error("Set VITE_API_URL in .env.local first")
}
// npx, not a devDependency: openapi-typescript 7 still pins TypeScript 5, and this project uses 6
execSync(
  `npx -y openapi-typescript@7 ${apiUrl.replace(/\/+$/, "")}/openapi.json -o src/api/schema.d.ts`,
  { stdio: "inherit" }
)
