import { createContext, useContext } from "react";

import type { ThemePreference } from "./theme.js";

export interface ThemeContextValue {
  preference: ThemePreference;
  // A function-valued property rather than a method, for the same reason as
  // `AuthContextValue`: every caller destructures it, and method syntax on
  // an interface promises a `this` that this function never uses.
  setPreference: (preference: ThemePreference) => void;
}

/** Null default for the same reason as `AuthContext` — see auth/context.ts. */
export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (value === null) {
    throw new Error("useTheme was called outside <ThemeProvider>");
  }
  return value;
}
