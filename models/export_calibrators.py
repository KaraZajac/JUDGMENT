"""Export the deployed calibrators as portable step functions.

sklearn's IsotonicRegression predicts by linear interpolation over its fitted
thresholds, so (X_thresholds_, y_thresholds_) written to YAML lets any
environment (e.g. CI without the prediction caches) reproduce calibrated
probabilities exactly via np.interp.

  .venv/bin/python -m models.export_calibrators
"""

from pathlib import Path

import pandas as pd
import yaml

from .report import fit_final_calibrator

OUT = Path(__file__).resolve().parent
CACHE = OUT / "output" / "cache"


def main():
    # single source of truth for both pins
    from .predict import CALIBRATOR_FILES, DEPLOY_CONFIG, STAGE2_CONFIG
    for stage, config in (("cert", DEPLOY_CONFIG),
                          ("post-argument", STAGE2_CONFIG)):
        payload = {"config": config, "stage": stage}
        for target in ("reverse", "liberal"):
            wf = pd.read_pickle(CACHE / f"predictions-{target}-{config}.pkl")
            iso = fit_final_calibrator(wf)
            payload[target] = {
                "fitted_on": f"walk-forward {config} predictions, "
                             f"terms {int(wf['term'].min())}-{int(wf['term'].max())}",
                "x": [float(v) for v in iso.X_thresholds_],
                "y": [float(v) for v in iso.y_thresholds_],
            }
        dest = OUT / CALIBRATOR_FILES[stage]
        with open(dest, "w") as f:
            yaml.safe_dump(payload, f, sort_keys=False)
        print(f"wrote {dest.name} (config {config}): "
              + ", ".join(f"{t} ({len(p['x'])} thresholds)"
                          for t, p in payload.items() if isinstance(p, dict)))


if __name__ == "__main__":
    main()
