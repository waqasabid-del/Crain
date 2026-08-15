/// <reference types="vite/client" />

/**
 * The environment variables this app reads.
 *
 * Vite's own `ImportMetaEnv` carries an `any` index signature, so every
 * `import.meta.env.X` would otherwise be `any` — which the strict type-aware
 * lint rules correctly refuse, and which would silently accept a misspelled
 * variable name. Declaring the two we use narrows them to `string | undefined`
 * and makes a typo a compile error instead of a blank screen.
 */
interface ImportMetaEnv {
  readonly VITE_CAIRN_API_URL?: string;
  readonly VITE_CAIRN_CONTENT_SOURCE?: string;
}
