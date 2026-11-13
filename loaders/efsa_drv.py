"""EFSA dietary reference values loader.

Source: the JSON dataset behind EFSA's DRV Finder (https://multimedia.efsa.europa.eu/drvs/), one
object per (nutrient, population group, age band, sex), with one column per value kind: AI
(adequate intake), AR (average requirement, plus its kcal alternative for energy), PRI (population
reference intake), RI (reference intake range, in % of energy), UL (tolerable upper intake level)
and SSI (safe and sufficient intake). Each value has its unit, a link to the EFSA scientific
opinion it comes from, and an explanatory note.

Upstream conventions handled here:
- "(+) 70"   pregnancy / lactation increment on top of the non-pregnant value → is_increment
- "45–60"    a range (en dash or hyphen)                                       → value_min / value_max
- "ND", "NA." not determined / not applicable                                  → raw kept, no number
- ""          no value of that kind for the row                                 → no output row
- "… PAL=1.6" in the age label of energy rows                                   → pal

Reuse: EFSA content may be reproduced provided the source is acknowledged. Every stored value keeps
its scientific opinion link for that attribution.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, insert

from db.connection import engine
from db.models import EfsaDrvValue, init_db
from loaders.base import BaseLoader

log = logging.getLogger(__name__)

EFSA_DRV_URL = "https://multimedia.efsa.europa.eu/drvs/assets/data/languages/en/data.json"

# The generic link/note columns EFSA fills when a row has a single AR/PRI, AI or RI opinion.
_GENERIC_LINK = "Scientific Opinion AR/PRI or AI or RI LINK"
_GENERIC_NOTE = "Additional information related to AR/PRI or AI or RI results"

_NUMBER = r"\d+(?:\.\d+)?"
_RANGE_RE = re.compile(rf"^({_NUMBER})\s*[–-]\s*({_NUMBER})$")
_POINT_RE = re.compile(rf"^({_NUMBER})$")
_INCREMENT_PREFIX = "(+)"
_PAL_RE = re.compile(r"PAL\s*=\s*(" + _NUMBER + ")")


@dataclass(frozen=True)
class ValueKind:
    key: str            # stored in efsa_drv_values.value_kind
    source: str         # upstream column holding the value
    link_source: str    # upstream column prefix used for the link and note ("ARs" for "ARs alt")


VALUE_KINDS: tuple[ValueKind, ...] = (
    ValueKind("ssi", "SSI", "SSI"),
    ValueKind("ai", "AIs", "AIs"),
    ValueKind("ar", "ARs", "ARs"),
    ValueKind("ar_kcal", "ARs alt", "ARs"),
    ValueKind("pri", "PRIs", "PRIs"),
    ValueKind("ri", "RI", "RI"),
    ValueKind("ul", "UL", "UL"),
)


def parse_value(raw: Any) -> tuple[str, float | None, float | None, bool] | None:
    """Parse one upstream cell into (raw text, min, max, is_increment); None when the cell is empty."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        number = float(raw)
        return _format_number(raw), number, number, False
    text = str(raw).strip()
    if not text:
        return None

    body = text
    is_increment = body.startswith(_INCREMENT_PREFIX)
    if is_increment:
        body = body[len(_INCREMENT_PREFIX):].strip()

    if match := _POINT_RE.match(body):
        number = float(match.group(1))
        return text, number, number, is_increment
    if match := _RANGE_RE.match(body):
        return text, float(match.group(1)), float(match.group(2)), is_increment
    return text, None, None, False


def _format_number(value: int | float) -> str:
    """The raw text of a numeric cell, without a spurious ".0" on integers."""
    return str(int(value)) if float(value).is_integer() else str(value)


def parse_pal(age_label: str | None) -> float | None:
    """The physical activity level embedded in an energy row's age label ("18–29 years PAL=1.4")."""
    if not age_label:
        return None
    match = _PAL_RE.search(age_label)
    return float(match.group(1)) if match else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def explode_rows(rows: Iterable[dict]) -> list[dict]:
    """Turn wide upstream rows into one dict per present value kind, keyed like EfsaDrvValue."""
    out: list[dict] = []
    for index, row in enumerate(rows):
        population = _text(row.get("Target population")) or ""
        base = {
            "source_row": index,
            "classification": _text(row.get("Classification")) or "",
            "nutrient": _text(row.get("Name")) or "",
            "population": population,
            "population_description": _text(row.get("Target population Description")) or population,
            "age_from": _number(row.get("From Age")),
            "age_to": _number(row.get("To Age")),
            "age_unit": _text(row.get("Age Unit")),
            "age_label": _text(row.get("Age displayed")),
            "pal": parse_pal(_text(row.get("Age displayed"))),
            "sex": _text(row.get("Sex")),
            "is_male": bool(row.get("Male")),
            "is_female": bool(row.get("Female")),
        }
        for kind in VALUE_KINDS:
            parsed = parse_value(row.get(kind.source))
            if parsed is None:
                continue
            raw, value_min, value_max, is_increment = parsed
            out.append({
                **base,
                "value_kind": kind.key,
                "raw": raw,
                "value_min": value_min,
                "value_max": value_max,
                "is_increment": is_increment,
                "unit": _text(row.get(f"{kind.source} Unit")),
                "source_link": _text(row.get(f"Scientific Opinion {kind.link_source} LINK"))
                or _text(row.get(_GENERIC_LINK)),
                "note": _text(row.get(f"Additional information related to {kind.link_source} results"))
                or _text(row.get(_GENERIC_NOTE)),
            })
    return out


class EfsaDrvLoader(BaseLoader):
    name = "efsa_drv"
    filename = "efsa_drv_en.json"
    url = EFSA_DRV_URL

    def load(self, path: Path) -> None:
        init_db()
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"[efsa_drv] expected a non-empty JSON list in {path}")

        values = explode_rows(rows)
        if not values:
            raise ValueError("[efsa_drv] no value parsed: the upstream format may have changed")

        # Snapshot table: replace everything atomically, so a failed load leaves the previous data.
        with engine.begin() as conn:
            conn.execute(delete(EfsaDrvValue))
            conn.execute(insert(EfsaDrvValue), values)

        nutrients = len({v["nutrient"] for v in values})
        log.info("[efsa_drv] loaded %d values (%d nutrients, %d source rows)", len(values), nutrients, len(rows))
