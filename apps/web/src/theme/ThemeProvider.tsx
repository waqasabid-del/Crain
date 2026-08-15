"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { ThemeContext, type ThemeContextValue } from "./context.js";
import {
  applyPreference,
  readStoredPreference,
  storePreference,
  type ThemePreference,
} from "./theme.js";

export interface ThemeProviderProps {
  children: ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps): ReactNode {
  // `system`, not the stored value: first render also happens on the server,
  // where `localStorage` and `document` do not exist. The flash is prevented by
  // the blocking inline script in `app/layout.tsx`, not here.
  const [preference, setPreferenceState] = useState<ThemePreference>("system");

  useEffect(() => {
    const stored = readStoredPreference();
    setPreferenceState(stored);
    applyPreference(stored);
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    // The DOM write is here, not in an effect, so cause and consequence sit
    // together.
    applyPreference(next);
    storePreference(next);
    setPreferenceState(next);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ preference, setPreference }),
    [preference, setPreference],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
