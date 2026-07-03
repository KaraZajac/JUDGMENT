// Display helpers: SCDB stores case names in ALL CAPS and enums as kebab tokens.

const SMALL_WORDS = new Set([
  "a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or",
  "the", "to", "et", "al.", "al", "de", "la", "ex", "rel.",
]);

export function caseTitle(name) {
  if (!name) return "(untitled case)";
  return name
    .toLowerCase()
    .split(/\s+/)
    .map((w, i) => {
      if (w === "v." || w === "vs." || w === "versus") return "v.";
      if (/^([a-z]\.)+$/.test(w)) return w.toUpperCase(); // u.s., n.l.r.b.
      if (SMALL_WORDS.has(w) && i !== 0) return w;
      const cap = w.charAt(0).toUpperCase() + w.slice(1);
      return cap.replace(/^Mc(.)/, (_, c) => "Mc" + c.toUpperCase());
    })
    .join(" ");
}

export const pct = (x, digits = 0) =>
  x == null ? "—" : (x * 100).toFixed(digits) + "%";

export const label = (token) =>
  token == null ? null : String(token).replaceAll("-", " ");

export function fmtDate(iso) {
  if (!iso) return null;
  const [y, m, d] = String(iso).split("-").map(Number);
  if (!y || !m || !d) return String(iso);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
  });
}

export const num = (n) => (n == null ? "—" : n.toLocaleString("en-US"));
