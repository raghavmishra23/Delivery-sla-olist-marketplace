"""Downloads and unpacks the source dataset from Kaggle into data/external/."""

import base64
import os
import urllib.error
import urllib.request
import zipfile

from common import ROOT, log

DATASET = "olistbr/brazilian-ecommerce"
EXTERNAL = ROOT / "data" / "external"
ARCHIVE = EXTERNAL / "dataset.zip"
API = f"https://www.kaggle.com/api/v1/datasets/download/{DATASET}"


def load_env():
    """Reads KEY=VALUE pairs from .env without adding a dependency; real env vars win."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_request():
    user, key = os.environ.get("KAGGLE_USERNAME"), os.environ.get("KAGGLE_KEY")
    cookie = os.environ.get("KAGGLE_COOKIE")
    req = urllib.request.Request(API)
    if user and key:
        token = base64.b64encode(f"{user}:{key}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        return req, "API token"
    if cookie:
        req.add_header("Cookie", cookie)
        req.add_header("User-Agent", "Mozilla/5.0")
        return req, "session cookie"
    raise SystemExit(
        "No Kaggle credentials found.\n"
        "Put either of these in a .env file at the repo root:\n"
        "  KAGGLE_USERNAME=... and KAGGLE_KEY=...   (from kaggle.json, preferred)\n"
        "  KAGGLE_COOKIE=...                        (full Cookie header value)\n"
        f"Or download {DATASET} manually and save the zip to {ARCHIVE}."
    )


def download():
    req, how = build_request()
    log(f"fetching {DATASET} using {how}")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        hint = " - credentials rejected" if err.code in (401, 403) else ""
        raise SystemExit(f"download failed: HTTP {err.code}{hint}")
    if body[:2] != b"PK":
        raise SystemExit("response was not a zip - the credentials are probably not being accepted")
    ARCHIVE.write_bytes(body)
    log(f"saved {ARCHIVE} ({len(body) / 1e6:.1f} MB)")


def unpack():
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        archive.extractall(EXTERNAL, members=[m for m in archive.namelist() if m in names])
    for name in sorted(names):
        size = (EXTERNAL / name).stat().st_size / 1e6
        log(f"  {name:<48} {size:7.1f} MB")
    log(f"unpacked {len(names)} CSV files into {EXTERNAL}")


def main():
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        log(f"using existing archive {ARCHIVE}")
    else:
        load_env()
        download()
    unpack()


if __name__ == "__main__":
    main()
