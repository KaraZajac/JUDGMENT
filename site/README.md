# site/

Future home of the Astro frontend that visualizes the dataset over time:

- justice ideology trajectories (term-by-term directional voting, ideal points)
- vote alignment / agreement matrices per natural court
- case explorer (by term, issue area, vote split)
- forecasts for pending cases once the models exist

The site will read directly from the YAML in `data/` (aggregated to JSON at
build time — ~29k small files should be pre-bundled, not loaded per-page).

Not scaffolded yet on purpose: the dataset and models come first.
