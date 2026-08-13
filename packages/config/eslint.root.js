import tseslint from "typescript-eslint";

import base from "./eslint.config.js";

/**
 * Repo-root ESLint configuration.
 *
 * Identical to the shared config, plus an exemption for root-level tooling
 * files (`eslint.config.js`, `commitlint.config.js`) which are plain ESM with
 * no tsconfig project. Type-aware rules genuinely cannot run on those, so the
 * type-checked layer is switched off for them specifically rather than
 * weakened everywhere else.
 *
 * Lives here so that every ESLint dependency stays in one package.
 */
export default tseslint.config(...base, {
  files: ["*.js", "*.mjs", "*.cjs"],
  extends: [tseslint.configs.disableTypeChecked],
});
