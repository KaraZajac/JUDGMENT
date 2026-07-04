// Read-only access to the YAML dataset at the repo root (../data).
// Small shared files are cached per server process; the ~29k case files are
// parsed on demand so no page pays for the whole corpus.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import YAML from "yaml";

const DATA = fileURLToPath(new URL("../../../data", import.meta.url));
const cache = new Map();

function loadCached(rel) {
  if (!cache.has(rel)) {
    cache.set(rel, YAML.parse(fs.readFileSync(path.join(DATA, rel), "utf8")));
  }
  return cache.get(rel);
}

function loadFresh(rel) {
  return YAML.parse(fs.readFileSync(path.join(DATA, rel), "utf8"));
}

export const meta = () => loadCached("meta.yaml");
export const justiceIndex = () => loadCached("justices/index.yaml");
export const justice = (slug) => loadCached(`justices/${slug}.yaml`);
export const courts = () => loadCached("courts/natural-courts.yaml");
export const termsAgg = () => loadCached("aggregates/terms.yaml").terms;

let mnemonic = null;
/** Map of SCDB mnemonic (e.g. "JGRoberts") -> justice index entry. */
export function byMnemonic() {
  if (!mnemonic) mnemonic = new Map(justiceIndex().map((j) => [j.scdb_name, j]));
  return mnemonic;
}

export function termList() {
  return fs
    .readdirSync(path.join(DATA, "cases"))
    .filter((d) => /^\d{4}$/.test(d))
    .map(Number)
    .sort((a, b) => a - b);
}

export function caseIdsForTerm(term) {
  return fs
    .readdirSync(path.join(DATA, "cases", String(term)))
    .filter((f) => f.endsWith(".yaml"))
    .map((f) => f.slice(0, -5))
    .sort();
}

export function caseById(id) {
  const term = String(id).slice(0, 4);
  return loadFresh(`cases/${term}/${id}.yaml`);
}

export function casesForTerm(term) {
  return caseIdsForTerm(term).map(caseById);
}

/** Model forecasts for pending cases (data/forecasts/, written by models.predict). */
export function forecasts() {
  const root = path.join(DATA, "forecasts");
  const out = new Map();
  if (!fs.existsSync(root)) return out;
  for (const t of fs.readdirSync(root).filter((d) => /^\d{4}$/.test(d))) {
    for (const f of fs.readdirSync(path.join(root, t)).filter((f) => f.endsWith(".yaml"))) {
      const fc = loadFresh(`forecasts/${t}/${f}`);
      out.set(fc.id, fc);
    }
  }
  return out;
}

/** Granted/argued cases awaiting decision (data/docket/, written by pipeline.interim). */
export function pendingCases() {
  const root = path.join(DATA, "docket");
  if (!fs.existsSync(root)) return [];
  const out = [];
  for (const t of fs.readdirSync(root).filter((d) => /^\d{4}$/.test(d)).sort()) {
    for (const f of fs
      .readdirSync(path.join(root, t))
      .filter((f) => f.endsWith(".yaml"))
      .sort()) {
      out.push(loadFresh(`docket/${t}/${f}`));
    }
  }
  return out;
}
