"""Fetch SCDB releases into sources/.

Probes scdb.wustl.edu brick files for the newest modern release (<year>_01) and
newest legacy release (Legacy_NN), downloads the Citation-unit case-centered and
justice-centered zips, extracts the CSVs, and writes sources/manifest.yaml for
pipeline.build.
"""

import datetime
import io
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "sources"
BASE = "http://scdb.wustl.edu/_brickFiles"
UNITS = ("caseCentered_Citation", "justiceCentered_Citation")
UA = "JUDGEMENT-pipeline/0.1 (academic research)"


def _exists(url: str) -> bool:
    try:
        with urlopen(Request(url, method="HEAD", headers={"User-Agent": UA}), timeout=30) as resp:
            return resp.status == 200
    except (HTTPError, URLError, TimeoutError):
        return False


def _probe_url(release: str, unit: str) -> str:
    return f"{BASE}/{release}/SCDB_{release}_{unit}.csv.zip"


def newest_modern_release() -> str:
    year = datetime.date.today().year
    for y in range(year, 2022, -1):
        release = f"{y}_01"
        if _exists(_probe_url(release, UNITS[0])):
            return release
    raise SystemExit("could not locate a modern SCDB release on scdb.wustl.edu")


def newest_legacy_release() -> str:
    for n in range(12, 5, -1):
        release = f"Legacy_{n:02d}"
        if _exists(_probe_url(release, UNITS[0])):
            return release
    raise SystemExit("could not locate a legacy SCDB release on scdb.wustl.edu")


def fetch_zip_csv(url: str, dest: Path) -> None:
    """Download a one-CSV zip and extract that CSV to dest."""
    print(f"  GET {url}")
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=300) as resp:
        payload = resp.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise SystemExit(f"expected exactly one CSV in {url}, found {members}")
        dest.write_bytes(zf.read(members[0]))
    print(f"  -> {dest.relative_to(ROOT)} ({dest.stat().st_size:,} bytes)")


def main() -> None:
    force = "--force" in sys.argv
    SOURCES.mkdir(exist_ok=True)

    modern = newest_modern_release()
    legacy = newest_legacy_release()
    print(f"SCDB releases: modern={modern} legacy={legacy}")

    manifest = {
        "downloaded": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "modern_release": modern,
        "legacy_release": legacy,
        "files": {},
    }
    for release, era in ((modern, "modern"), (legacy, "legacy")):
        for unit in UNITS:
            url = _probe_url(release, unit)
            dest = SOURCES / f"SCDB_{release}_{unit}.csv"
            key = f"{era}_{'case' if unit.startswith('case') else 'justice'}"
            manifest["files"][key] = dest.name
            if dest.exists() and not force:
                print(f"  cached {dest.relative_to(ROOT)} (use --force to re-download)")
                continue
            fetch_zip_csv(url, dest)

    with open(SOURCES / "manifest.yaml", "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    print("wrote sources/manifest.yaml")


if __name__ == "__main__":
    main()
