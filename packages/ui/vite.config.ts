import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Dev server for the design system preview.
 *
 * A living style guide rather than a throwaway page: it is how components are
 * reviewed against all five user roles (md/05 §A.5) before they reach a screen,
 * and how the black/white direction is checked in both themes.
 */
export default defineConfig({
  root: "preview",
  plugins: [react()],
  server: { port: 6006, open: true },
});
