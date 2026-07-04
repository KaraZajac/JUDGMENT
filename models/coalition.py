"""Coalition-aware vote aggregation: replace the independence assumption.

The Poisson-binomial case aggregation treats the nine votes as independent
given their marginals, which understates unanimity and lopsided splits (the
documented limitation). This module adds a two-factor probit coalition
structure ON TOP of the deployed model's calibrated marginals, preserving
them exactly:

    vote_j | (u, v)  ~  Bernoulli( Phi( mu_j + lam0*u + lam1*s_j*v ) )
    u, v ~ N(0,1) shared within a case
    mu_j = sqrt(1 + lam0^2 + lam1^2 s_j^2) * Phi^{-1}(p_j)   (exact marginals)

u is case valence (clarity pulls everyone the same way); v is ideology, with
signed loadings s_j = 2*(0.5 - prior_liberal_j) (conservative positive,
leak-free — the same lagged feature the engine uses). Split distributions come
from 2-D Gauss-Hermite quadrature (no Monte Carlo). The two loadings are fit
by maximizing the log-likelihood of ACTUAL reverse-vote counts over the cached
walk-forward predictions on early terms, and evaluated out-of-sample on late
terms against independence.

  .venv/bin/python -m models.coalition          # fit, evaluate, write params
"""

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from numpy.polynomial.hermite_e import hermegauss
from scipy.stats import norm

from .features import load as load_features

OUT = Path(__file__).resolve().parent / "output"
CACHE = OUT / "cache"
PARAMS = Path(__file__).resolve().parent / "coalition-params.yaml"

FIT_THROUGH = 2010  # loadings fit on terms <= this; evaluated strictly after
N_NODES = 21


def quadrature():
    x, w = hermegauss(N_NODES)  # weight exp(-x^2/2): E[f(Z)] = sum w_i f(x_i)/sqrt(2pi)
    w = w / np.sqrt(2 * np.pi)
    return x, w


def split_distribution(p, s, lam0, lam1, nodes, z=None):
    """P(k reverse votes) for one case. p: (J,) marginals; s: (J,) signed leans.

    Vectorized: conditional vote probabilities on the flattened (u, v) grid,
    then a Poisson-binomial DP swept across all grid points at once.
    """
    x, w = nodes
    J = len(p)
    if z is None:
        z = norm.ppf(np.clip(p, 1e-4, 1 - 1e-4))
    scale = np.sqrt(1 + lam0 ** 2 + (lam1 * s) ** 2)
    mu = scale * z
    U = np.repeat(x, N_NODES)[:, None]           # (G,1) grid of u
    V = np.tile(x, N_NODES)[:, None]             # (G,1) grid of v
    q = norm.cdf(mu[None, :] + lam0 * U + lam1 * s[None, :] * V)  # (G,J)
    W = (w[:, None] * w[None, :]).reshape(-1)    # (G,)
    d = np.zeros((q.shape[0], J + 1))
    d[:, 0] = 1.0
    for j in range(J):
        pj = q[:, j:j + 1]
        d[:, 1:] = d[:, 1:] * (1 - pj) + d[:, :-1] * pj
        d[:, 0] *= (1 - pj[:, 0])
    dist = (W[:, None] * d).sum(axis=0)
    return dist / dist.sum()


def case_table():
    """Cached walk-forward predictions -> per-case arrays (p, s, k_actual)."""
    preds = pd.read_pickle(CACHE / "predictions-reverse-pending_config_lc_issue3t.pkl")
    feats = load_features()[["caseId", "justiceName", "prior_liberal"]]
    df = preds.merge(feats, on=["caseId", "justiceName"], how="left")
    df["s"] = 2.0 * (0.5 - df["prior_liberal"].fillna(0.5))
    cases = []
    for (cid, term), g in df.groupby(["caseId", "term"]):
        if len(g) < 5:
            continue
        p = g["p_model"].to_numpy()
        cases.append({"caseId": cid, "term": int(term),
                      "p": p,
                      "z": norm.ppf(np.clip(p, 1e-4, 1 - 1e-4)),
                      "s": g["s"].to_numpy(),
                      "k": int(g["y"].sum())})
    return cases


def mean_split_logloss(cases, lam0, lam1, nodes):
    ll = 0.0
    for c in cases:
        dist = split_distribution(c["p"], c["s"], lam0, lam1, nodes, z=c["z"])
        ll += -np.log(max(dist[c["k"]], 1e-12))
    return ll / len(cases)


def fit(cases_train, nodes):
    best = (0.0, 0.0, mean_split_logloss(cases_train, 0.0, 0.0, nodes))
    grid = [0.0, 0.3, 0.6, 0.9, 1.2, 1.6, 2.0]
    for lam0, lam1 in itertools.product(grid, grid):
        if lam0 == lam1 == 0.0:
            continue
        ll = mean_split_logloss(cases_train, lam0, lam1, nodes)
        if ll < best[2]:
            best = (lam0, lam1, ll)
        print(f"  lam0={lam0:.1f} lam1={lam1:.1f} -> train logloss {ll:.4f}"
              + ("  *" if (lam0, lam1) == best[:2] else ""), flush=True)
    # refine around the best cell
    l0c, l1c = best[0], best[1]
    for lam0 in np.clip(np.array([l0c - 0.15, l0c, l0c + 0.15]), 0, None):
        for lam1 in np.clip(np.array([l1c - 0.15, l1c, l1c + 0.15]), 0, None):
            ll = mean_split_logloss(cases_train, float(lam0), float(lam1), nodes)
            if ll < best[2]:
                best = (float(lam0), float(lam1), ll)
    return best


def split_frequencies(cases, lam0, lam1, nodes, n_target=9):
    """Predicted vs actual frequency of each split among n_target-member cases."""
    pred = np.zeros(n_target + 1)
    actual = np.zeros(n_target + 1)
    m = 0
    for c in cases:
        if len(c["p"]) != n_target:
            continue
        pred += split_distribution(c["p"], c["s"], lam0, lam1, nodes)
        actual[c["k"]] += 1
        m += 1
    if m == 0:
        return {}
    rows = {}
    for k in range(n_target, -1, -1):
        rows[f"{k}-{n_target - k}"] = {
            "predicted": float(round(pred[k] / m, 4)),
            "actual": float(round(actual[k] / m, 4))}
    return rows


def main():
    nodes = quadrature()
    cases = case_table()
    train = [c for c in cases if c["term"] <= FIT_THROUGH]
    test = [c for c in cases if c["term"] > FIT_THROUGH]
    print(f"cases: {len(train)} train (<= {FIT_THROUGH}), {len(test)} eval")

    lam0, lam1, train_ll = fit(train, nodes)
    ind_ll = mean_split_logloss(test, 0.0, 0.0, nodes)
    coal_ll = mean_split_logloss(test, lam0, lam1, nodes)
    print(f"\nfitted lam0={lam0:.2f} (valence) lam1={lam1:.2f} (ideology)")
    print(f"eval split log-loss: independence {ind_ll:.4f} -> coalition {coal_ll:.4f} "
          f"({(ind_ll - coal_ll) / ind_ll:+.1%})")

    freq_ind = split_frequencies(test, 0.0, 0.0, nodes)
    freq_coal = split_frequencies(test, lam0, lam1, nodes)
    print("\nsplit frequencies on eval cases (9-member):")
    print(f"{'split':>6} {'actual':>8} {'indep':>8} {'coalition':>10}")
    for k in freq_coal:
        print(f"{k:>6} {freq_coal[k]['actual']:>8.3f} "
              f"{freq_ind[k]['predicted']:>8.3f} {freq_coal[k]['predicted']:>10.3f}")

    # binary case-outcome quality under each aggregation (same eval cases)
    binary = {}
    for l0, l1, name in ((0.0, 0.0, "independence"), (lam0, lam1, "coalition")):
        pc, yc = [], []
        for c in test:
            dist = split_distribution(c["p"], c["s"], l0, l1, nodes, z=c["z"])
            need = len(c["p"]) // 2 + 1
            pc.append(dist[need:].sum())
            yc.append(1.0 if c["k"] >= need else 0.0)
        pc, yc = np.array(pc), np.array(yc)
        binary[name] = {
            "accuracy": float(round(((pc >= 0.5) == yc).mean(), 4)),
            "brier": float(round(((pc - yc) ** 2).mean(), 4)),
        }
    print(f"binary case outcome: {binary}")

    payload = {
        "lam0_valence": float(round(lam0, 3)),
        "lam1_ideology": float(round(lam1, 3)),
        "fit_through_term": FIT_THROUGH,
        "eval_split_logloss": {"independence": float(round(ind_ll, 4)),
                               "coalition": float(round(coal_ll, 4))},
        "eval_case_binary": binary,
        "eval_split_frequencies": {"independence": freq_ind, "coalition": freq_coal},
        "definition": "vote_j|(u,v) ~ Bern(Phi(mu_j + lam0*u + lam1*s_j*v)); "
                      "marginals preserved exactly; s_j = 2*(0.5 - prior_liberal_j)",
    }
    with open(PARAMS, "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    print(f"\nwrote {PARAMS.name}")


if __name__ == "__main__":
    main()
