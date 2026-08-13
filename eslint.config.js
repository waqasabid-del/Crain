/**
 * Root ESLint configuration.
 *
 * ESLint 9 resolves its config from the working directory, so this file runs
 * when linting from the repo root — which is how the pre-commit hook invokes it
 * against staged files. Packages keep their own config for `pnpm lint`, which
 * runs from inside each package.
 *
 * The real configuration lives in @cairn/config so that every ESLint
 * dependency stays in a single package.
 */
export { default } from "@cairn/config/eslint-root";
