import { defineConfig } from "astro/config";

// Static-output site over the YAML dataset in ../data.
// Dev mode renders pages on demand, so the ~29k case routes cost nothing
// until visited; a full `astro build` prerenders everything.
export default defineConfig({
  // Deployed at the root of judgment.karazajac.io — no base path needed.
  // PAGES_BASE/PAGES_SITE env overrides remain for any future subpath host;
  // internal links all go through url() in src/lib/format.js either way.
  site: process.env.PAGES_SITE || "https://judgment.karazajac.io",
  base: process.env.PAGES_BASE || undefined,
});
