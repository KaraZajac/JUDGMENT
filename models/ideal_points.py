"""Dynamic ideal points: a penalized-ML variant of Martin–Quinn (2002).

Model (1-D dynamic IRT): justice j in term t has ideal point theta_jt; case i
has discrimination beta_i and location alpha_i;

    P(vote_ij = reverse) = sigmoid(beta_i * theta_j,t(i) - alpha_i)

MAP objective = Bernoulli log-likelihood
  - lam_rw  * sum_j sum_t (theta_jt - theta_j,t-1)^2      (random-walk smoothing)
  - lam0    * sum_j theta_j,first^2                        (initial-state prior)
  - lam_case* sum_i (beta_i^2 + alpha_i^2)                 (case ridge)

estimated by alternating Newton steps: per-case 2x2 solves given trajectories,
then per-justice tridiagonal (banded) solves given case parameters — the
justice step is exactly a Gaussian smoother on the trajectory. Identification:
location/scale normalized each sweep (mean 0, sd 1); sign oriented so that
conservative is positive (Republican-appointed mean > Democratic-appointed
mean, the Martin–Quinn convention). Differences from MQ: MAP point estimates
instead of a full MCMC posterior (no credible intervals), homogeneous
random-walk variance, and votes coded on the reverse/affirm axis.

Outputs:
  data/scores/ideal-points.yaml            smoothed full-history trajectories (site/story)
  models/output/cache/theta_filtered.pkl   leak-free lagged estimates for modeling:
    theta_lag(j, T) is estimated from votes in terms < T only (expanding refits
    every `stride` terms), so it is safe as a walk-forward feature.

Usage:
  .venv/bin/python -m models.ideal_points              # full history + YAML + checks
  .venv/bin/python -m models.ideal_points --filtered   # also build expanding estimates
"""

import argparse
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.linalg import solve_banded

from .features import load

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "output"
CACHE = OUT / "cache"
SCORES = ROOT / "data" / "scores"

LAM_RW = 5.0      # random-walk precision/2  (sigma_rw^2 = 0.1, per MQ)
LAM_0 = 0.5       # initial-state prior N(0,1)
LAM_CASE = 0.125  # case-parameter prior N(0,4)


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def prepare(df):
    d = df[["caseId", "justiceName", "term", "y_reverse", "prior_liberal",
            "appointer_party"]].dropna(subset=["y_reverse"]).copy()
    d["term"] = d["term"].astype(int)

    case_ids = {c: i for i, c in enumerate(d["caseId"].unique())}
    jt_pairs = d[["justiceName", "term"]].drop_duplicates().sort_values(
        ["justiceName", "term"]).reset_index(drop=True)
    jt_index = {(r.justiceName, r.term): i for i, r in jt_pairs.iterrows()}

    v_case = d["caseId"].map(case_ids).to_numpy()
    v_jt = np.array([jt_index[(jn, t)] for jn, t in zip(d["justiceName"], d["term"])])
    y = d["y_reverse"].to_numpy()

    # per-justice contiguous slices into the jt vector
    traj = {}
    for jn, g in jt_pairs.groupby("justiceName", sort=False):
        traj[jn] = g.index.to_numpy()  # ordered by term

    # warm start: conservative-positive from lagged behavioral lean
    lean = d.groupby([d["justiceName"], d["term"]])["prior_liberal"].mean()
    theta0 = np.zeros(len(jt_pairs))
    for i, r in jt_pairs.iterrows():
        lv = lean.get((r.justiceName, r.term), 0.5)
        theta0[i] = 1.0 - 2.0 * (lv if not np.isnan(lv) else 0.5)

    dem = d.groupby("justiceName")["appointer_party"].first()
    return d, jt_pairs, traj, v_case, v_jt, y, theta0, dem, len(case_ids)


def fit(df, iters=20, verbose=True):
    d, jt_pairs, traj, v_case, v_jt, y, theta, dem, n_cases = prepare(df)
    beta = np.ones(n_cases)
    alpha = np.zeros(n_cases)

    case_rows = [np.where(v_case == i)[0] for i in range(n_cases)]
    jt_rows = [np.where(v_jt == k)[0] for k in range(len(jt_pairs))]

    for it in range(iters):
        # ---- case step: 2-param Newton per case -----------------------------
        th = theta[v_jt]
        for i in range(n_cases):
            rows = case_rows[i]
            t_i, y_i = th[rows], y[rows]
            b, a = beta[i], alpha[i]
            for _ in range(3):
                p = sigmoid(b * t_i - a)
                w = np.maximum(p * (1 - p), 1e-6)
                g_b = np.sum((y_i - p) * t_i) - 2 * LAM_CASE * b
                g_a = -np.sum(y_i - p) - 2 * LAM_CASE * a
                h_bb = np.sum(w * t_i * t_i) + 2 * LAM_CASE
                h_aa = np.sum(w) + 2 * LAM_CASE
                h_ba = -np.sum(w * t_i)
                det = h_bb * h_aa - h_ba * h_ba
                if det < 1e-9:
                    break
                db = (g_b * h_aa - g_a * h_ba) / det
                da = (h_bb * g_a - h_ba * g_b) / det
                b += 0.8 * db
                a += 0.8 * da
            beta[i], alpha[i] = np.clip(b, -8, 8), np.clip(a, -8, 8)

        # ---- justice step: banded Newton per trajectory ----------------------
        z = beta[v_case] * theta[v_jt] - alpha[v_case]
        p_all = sigmoid(z)
        grad_like = np.zeros(len(jt_pairs))
        hess_like = np.zeros(len(jt_pairs))
        np.add.at(grad_like, v_jt, beta[v_case] * (y - p_all))
        np.add.at(hess_like, v_jt,
                  np.maximum(p_all * (1 - p_all), 1e-6) * beta[v_case] ** 2)

        for jn, idx in traj.items():
            n = len(idx)
            th_j = theta[idx]
            g = grad_like[idx].copy()
            g[0] -= 2 * LAM_0 * th_j[0]
            g[:-1] -= 2 * LAM_RW * (th_j[:-1] - th_j[1:])
            g[1:] -= 2 * LAM_RW * (th_j[1:] - th_j[:-1])
            diag = hess_like[idx] + 2 * LAM_RW * np.r_[
                1.0, 2.0 * np.ones(max(n - 2, 0)), 1.0][:n]
            diag[0] += 2 * LAM_0
            if n == 1:
                theta[idx] = th_j + g / diag
                continue
            ab = np.zeros((3, n))
            ab[0, 1:] = -2 * LAM_RW
            ab[1] = diag
            ab[2, :-1] = -2 * LAM_RW
            step = solve_banded((1, 1), ab, g)
            theta[idx] = th_j + 0.9 * step

        # ---- identification --------------------------------------------------
        theta -= theta.mean()
        s = theta.std()
        if s > 1e-9:
            theta /= s
            beta *= s
        j_mean = pd.Series(theta, index=pd.MultiIndex.from_frame(jt_pairs)) \
            .groupby(level=0).mean()
        dems = j_mean[dem.reindex(j_mean.index) == 1.0]
        reps = j_mean[dem.reindex(j_mean.index) == 0.0]
        if len(dems) and len(reps) and dems.mean() > reps.mean():
            theta *= -1
            beta *= -1

        if verbose and (it % 5 == 0 or it == iters - 1):
            z = beta[v_case] * theta[v_jt] - alpha[v_case]
            p_ = np.clip(sigmoid(z), 1e-6, 1 - 1e-6)
            nll = -np.mean(y * np.log(p_) + (1 - y) * np.log(1 - p_))
            print(f"  iter {it:2d}  mean nll {nll:.4f}", flush=True)

    result = jt_pairs.copy()
    result["theta"] = theta
    return result, beta, alpha


def write_scores(result):
    SCORES.mkdir(parents=True, exist_ok=True)
    justices = {}
    for jn, g in result.groupby("justiceName"):
        justices[jn] = {int(r.term): round(float(r.theta), 3) for r in g.itertuples()}
    payload = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": ("dynamic 1-D IRT (Martin-Quinn-style), penalized-ML/MAP point "
                   "estimates; conservative positive, mean 0, sd 1; votes on the "
                   "reverse/affirm axis, modern era (1946+); see models/ideal_points.py"),
        "citation": "Martin & Quinn (2002), Political Analysis 10:134-153",
        "justices": justices,
    }
    with open(SCORES / "ideal-points.yaml", "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, width=100)
    print(f"wrote data/scores/ideal-points.yaml ({len(justices)} justices)")


def face_checks(result):
    """Sanity: known orderings the estimates must reproduce to be credible."""
    last = result[result["term"] == result["term"].max()]
    order = last.sort_values("theta")[["justiceName", "theta"]]
    print("\nnewest-term ordering (liberal -> conservative):")
    for r in order.itertuples():
        print(f"  {r.theta:+.2f}  {r.justiceName}")
    for jn in ("HABlackmun", "RBGinsburg"):
        g = result[result["justiceName"] == jn].sort_values("term")
        if len(g) > 5:
            drift = g["theta"].iloc[-1] - g["theta"].iloc[0]
            print(f"{jn}: theta first->last = {g['theta'].iloc[0]:+.2f} -> "
                  f"{g['theta'].iloc[-1]:+.2f} (drift {drift:+.2f})")


def build_filtered(df, stride=5, first_eval=1956):
    """theta_lag(j, T) from votes strictly before T, refit every `stride` terms."""
    last_term = int(df["term"].max())
    frames = []
    for refit in range(first_eval, last_term + 2, stride):
        train = df[df["term"] < refit]
        if train["caseId"].nunique() < 500:
            continue
        print(f"expanding refit @ {refit} (train terms {train['term'].min()}–{refit - 1})")
        result, _, _ = fit(train, iters=12, verbose=False)
        latest = result.sort_values("term").groupby("justiceName").tail(1)
        for T in range(refit, min(refit + stride, last_term + 1)):
            frames.append(pd.DataFrame({
                "justiceName": latest["justiceName"].to_numpy(),
                "term": T,
                "theta_lag": latest["theta"].to_numpy(),
            }))
    out = pd.concat(frames, ignore_index=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_pickle(CACHE / "theta_filtered.pkl")
    print(f"cached theta_filtered.pkl ({len(out):,} justice-term rows)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filtered", action="store_true",
                    help="also build leak-free expanding estimates for modeling")
    args = ap.parse_args()

    df = load()
    print("fitting full-history dynamic ideal points (modern era)")
    result, beta, alpha = fit(df)
    write_scores(result)
    face_checks(result)

    if args.filtered:
        build_filtered(df)


if __name__ == "__main__":
    main()
