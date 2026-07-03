"""JUDGEMENT ETL pipeline: SCDB raw files -> YAML dataset under data/.

Run from the repo root:

    python3 -m pipeline.download   # fetch SCDB releases into sources/
    python3 -m pipeline.build      # regenerate data/ from sources/ + curated inputs
    python3 -m pipeline.validate   # structural checks over the generated dataset
"""
