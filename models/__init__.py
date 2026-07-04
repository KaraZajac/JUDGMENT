"""JUDGMENT prediction engine.

Run from the repo root with the modeling venv:

    .venv/bin/python -m models.features     # build + cache the feature table
    .venv/bin/python -m models.walkforward  # walk-forward evaluation vs baselines
    .venv/bin/python -m models.ideal_points # dynamic ideal points (MQ-style MAP)
    .venv/bin/python -m models.predict      # forecast the pending docket

Methodology and results: models/README.md and models/output/report-*.md.
"""
