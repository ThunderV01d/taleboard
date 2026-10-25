// Regenerates src/api/schema.d.ts from the backend's OpenAPI schema, built straight from the FastAPI app.
// Local rather than from the deployed API: every deployed route (openapi.json included) now needs a sign-in token.
// Run after any backend API change: npm run gen:api (needs the backend's Python environment, as for its tests)
import { execSync } from "node:child_process"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

const schema = execSync(
  'python -c "import json, sys; from taleboard.api.app import app; json.dump(app.openapi(), sys.stdout)"',
  { encoding: "utf8" }
)
const schemaFile = join(mkdtempSync(join(tmpdir(), "taleboard-")), "openapi.json")
writeFileSync(schemaFile, schema)
// npx, not a devDependency: openapi-typescript 7 still pins TypeScript 5, and this project uses 6
execSync(`npx -y openapi-typescript@7 "${schemaFile}" -o src/api/schema.d.ts`, {
  stdio: "inherit",
})