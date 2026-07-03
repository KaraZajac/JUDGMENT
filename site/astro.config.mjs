import { defineConfig } from "astro/config";

// Static-output site over the YAML dataset in ../data.
// Dev mode renders pages on demand, so the ~29k case routes cost nothing
// until visited; a full `astro build` prerenders everything.
export default defineConfig({
  site: "http://localhost:4321",
});
