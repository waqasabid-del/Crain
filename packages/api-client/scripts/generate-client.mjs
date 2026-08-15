/**
 * Generate TypeScript types from the API's OpenAPI schema.
 *
 * The FastAPI routes are the single source of truth. `make schema` renders them
 * to `openapi.json`; this turns that into TypeScript, so both ends of the
 * language boundary describe the same contract by construction rather than by
 * discipline.
 *
 * This is the mechanism behind Step 9's exit criterion — *a breaking backend
 * change fails the frontend build*. Rename a field in a Pydantic model and the
 * regenerated types no longer match the call sites, so `pnpm typecheck` fails
 * before anything reaches a user.
 *
 * The output is committed. A generated file in the repository makes a contract
 * change visible in the diff during review, which is precisely where a breaking
 * change should be noticed rather than at runtime.
 */
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../openapi.json");
const outputPath = resolve(here, "../src/generated/schema.ts");

const schema = JSON.parse(await readFile(schemaPath, "utf8"));

const banner = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source of truth: apps/api/src/cairn_api/api/ (FastAPI routes and Pydantic models)
 * Regenerate with: make schema
 *
 * A test fails if this file is out of date, so drift between the API and these
 * types cannot reach production.
 */

`;

const ast = await openapiTS(schema, {
  // Every response field is present or absent by design; `undefined` unions on
  // required fields would force null checks the API contract already rules out.
  emptyObjectsUnknown: true,
  // Dates cross the wire as ISO strings. Typing them as `Date` would be a lie
  // that only shows up when someone calls `.getTime()` on a string.
  defaultNonNullable: true,
});

await mkdir(dirname(outputPath), { recursive: true });
await writeFile(outputPath, banner + astToString(ast), "utf8");
console.log(`Wrote ${outputPath}`);
