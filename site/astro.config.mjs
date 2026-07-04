import { defineConfig } from "astro/config";

// Static-output site over the YAML dataset in ../data.
// Dev mode renders pages on demand, so the ~29k case routes cost nothing
// until visited; a full `astro build` prerenders everything.
export default defineConfig({
  // GitHub Pages serves the project site under /JUDGMENT/ — CI sets PAGES_BASE.
  // Local dev and preview stay at the root.
  site: process.env.PAGES_SITE || "http://localhost:4321",
  base: process.env.PAGES_BASE || undefined,
});
