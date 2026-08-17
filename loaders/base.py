"""Base class shared by all dataset loaders."""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/data/raw"))


class BaseLoader(ABC):
    """Download a dataset file if not already cached, then load into PostgreSQL."""

    name: str          # human-readable label used in logs
    filename: str      # local file name inside DOWNLOAD_DIR
    url: str           # upstream download URL

    def run(self, force_download: bool = False) -> None:
        path = self._download(force_download)
        log.info("[%s] loading into database", self.name)
        self.load(path)
        log.info("[%s] done", self.name)

    def _download(self, force: bool) -> Path:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = DOWNLOAD_DIR / self.filename
        if dest.exists() and not force:
            log.info("[%s] already cached at %s — skipping download", self.name, dest)
            return dest
        log.info("[%s] downloading %s → %s", self.name, self.url, dest)
        headers = {"User-Agent": "pocket-nutrition-data/1.0 (nutrition research; +https://pocketnutrition.org)"}
        with requests.get(self.url, stream=True, timeout=600, headers=headers) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
            mb = downloaded / 1e6
            log.info("[%s] saved %.1f MB to %s", self.name, mb, dest)
        return dest

    @abstractmethod
    def load(self, path: Path) -> None:
        """Parse the downloaded file and upsert rows into PostgreSQL."""
