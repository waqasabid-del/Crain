import base from "@cairn/config/eslint";

/**
 * The shared config, plus the files Next generates.
 *
 * `next-env.d.ts` carries a "do not edit" banner and is rewritten on every
 * build; its triple-slash reference is required by the framework. The only
 * options are to lint a generated file nobody may change or to exclude it, and
 * excluding it is the honest one. `.next` and `.open-next` are build output.
 */
export default [{ ignores: ["next-env.d.ts", ".next/**", ".open-next/**"] }, ...base];
