"""Entry point for the pocket-nutrition-data pipeline.

Usage:
  python main.py                    # run all loaders
  python main.py --loader ciqual    # run a single loader
  python main.py --force            # re-download even if file is cached
"""

import argparse
import logging

from loaders.ciqual import CiqualLoader
from loaders.efsa_drv import EfsaDrvLoader
from loaders.mccance import McCanceLoader
from loaders.off import OffLoader
from loaders.usda import UsdaLoader
from loaders.usda_foundation import UsdaFoundationLoader
from loaders.usda_sr import UsdaSrLoader
from loaders.usda_cooking_yields import UsdaCookingYieldsLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ALL_LOADERS = {
    "ciqual": CiqualLoader,
    "off": OffLoader,
    "mccance": McCanceLoader,
    "usda": UsdaLoader,
    "usda_foundation": UsdaFoundationLoader,
    "usda_sr": UsdaSrLoader,
    "usda_cooking_yields": UsdaCookingYieldsLoader,
    "efsa_drv": EfsaDrvLoader,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and load public nutrition datasets")
    parser.add_argument("--loader", choices=list(ALL_LOADERS), help="Run a single loader only")
    parser.add_argument("--force", action="store_true", help="Re-download even if file already cached")
    args = parser.parse_args()

    loaders = {args.loader: ALL_LOADERS[args.loader]} if args.loader else ALL_LOADERS

    for name, cls in loaders.items():
        log.info("=== Starting loader: %s ===", name)
        cls().run(force_download=args.force)

    log.info("All loaders finished successfully")


if __name__ == "__main__":
    main()
