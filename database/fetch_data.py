"""Unpacks the source dataset into data/external/."""

import zipfile

from common import ROOT, log

DATASET_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
EXTERNAL = ROOT / "data" / "external"
ARCHIVE = EXTERNAL / "dataset.zip"

EXPECTED = [
    "olist_orders_dataset.csv",
    "olist_customers_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "product_category_name_translation.csv",
]


def unpack():
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        archive.extractall(EXTERNAL, members=names)
    for name in sorted(names):
        log(f"  {name:<48} {(EXTERNAL / name).stat().st_size / 1e6:7.1f} MB")
    log(f"unpacked {len(names)} CSV files into {EXTERNAL}")


def main():
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    missing = [n for n in EXPECTED if not (EXTERNAL / n).exists()]
    if not missing:
        log(f"all {len(EXPECTED)} source files already present in {EXTERNAL}")
        return
    if ARCHIVE.exists():
        unpack()
        return
    raise SystemExit(
        f"Source data not found in {EXTERNAL}.\n"
        f"Download the Brazilian E-Commerce Public Dataset by Olist from\n"
        f"  {DATASET_URL}\n"
        f"and save the archive as {ARCHIVE}, or extract its CSV files into that folder."
    )


if __name__ == "__main__":
    main()
