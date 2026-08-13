/**
 * Generate TypeScript types from the ActivityEvent JSON Schema.
 *
 * The Python model in apps/api/src/cairn_api/events/schema.py is the single
 * source of truth. This turns the schema it emits into TypeScript, so both
 * languages describe the same shape by construction rather than by discipline.
 *
 * The output is committed. A generated file in the repository makes a schema
 * change visible in the diff during review — which is precisely where a
 * breaking change should be noticed rather than at runtime.
 */
import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../schemas/activity-event.json");
const outputPath = resolve(here, "../src/generated/activity-event.ts");

const schema = JSON.parse(await readFile(schemaPath, "utf8"));

const banner = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source of truth: apps/api/src/cairn_api/events/schema.py
 * Regenerate with: make schema
 *
 * A test fails if this file is out of date, so drift between the Python model
 * and these types cannot reach production.
 */
`;

const compiled = await compile(schema, "ActivityEvent", {
  bannerComment: banner,
  style: { printWidth: 100, semi: true, singleQuote: false, trailingComma: "all" },
  additionalProperties: false,
  enableConstEnums: false,
});

await writeFile(outputPath, compiled, "utf8");
console.log(`Wrote ${outputPath}`);
