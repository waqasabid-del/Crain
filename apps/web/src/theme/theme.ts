/** Decides what, if anything, goes in `data-theme`. `system` writes no attribute
 * at all: stamping a concrete value would freeze the choice at load. */

export const THEME_PREFERENCES = ["system", "light", "dark"] as const;

export type ThemePreference = (typeof THEME_PREFERENCES)[number];

export const THEME_STORAGE_KEY = "cairn.theme";

export const THEME_LABELS: Record<ThemePreference, string> = {
  system: "Match my system",
  light: "Light",
  dark: "Dark",
};

function isThemePreference(value: string | null): value is ThemePreference {
  return value !== null && (THEME_PREFERENCES as readonly string[]).includes(value);
}

/** Guarded: `localStorage` throws in Safari private mode. */
export function readStoredPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function storePreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // The theme still applies for this session; it just is not remembered.
  }
}

export function applyPreference(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") {
    root.removeAttribute("data-theme");
    return;
  }
  root.setAttribute("data-theme", preference);
}
