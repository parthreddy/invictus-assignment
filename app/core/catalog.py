"""Loads the shared service catalog and shop list.

The catalog is the single source of truth for which service codes exist and what
they cost. It is immutable and loaded once. The extractor reads it to constrain
which codes the model may pick; the pricing engine reads it to compute totals.
Nothing mutates it at runtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"


class UnknownServiceError(KeyError):
    """Raised when a service code is not in the catalog."""


@dataclass(frozen=True)
class Service:
    code: str
    name: str
    price: Decimal
    minutes: int
    requires_inspection: bool


@dataclass(frozen=True)
class Shop:
    id: str
    name: str


class Catalog:
    def __init__(self, currency: str, shops: list[Shop], services: list[Service]):
        self.currency = currency
        self._shops = {s.id: s for s in shops}
        self._services = {s.code: s for s in services}

    @property
    def shops(self) -> list[Shop]:
        return list(self._shops.values())

    @property
    def services(self) -> list[Service]:
        return list(self._services.values())

    def get(self, code: str) -> Service:
        try:
            return self._services[code]
        except KeyError as exc:
            raise UnknownServiceError(code) from exc

    def get_shop(self, shop_id: str) -> Shop | None:
        return self._shops.get(shop_id)

    def codes(self) -> set[str]:
        return set(self._services)

    def shop_ids(self) -> set[str]:
        return set(self._shops)

    def has_shop(self, shop_id: str) -> bool:
        return shop_id in self._shops


def _parse(raw: dict) -> Catalog:
    shops = [Shop(id=s["id"], name=s["name"]) for s in raw["shops"]]
    services = [
        Service(
            code=s["code"],
            name=s["name"],
            # Parse via str() so money is exact Decimal, never a binary float.
            price=Decimal(str(s["price"])),
            minutes=int(s["minutes"]),
            requires_inspection=bool(s["requires_inspection"]),
        )
        for s in raw["services"]
    ]
    return Catalog(currency=raw["currency"], shops=shops, services=services)


@lru_cache(maxsize=1)
def load_catalog(path: str | Path = CATALOG_PATH) -> Catalog:
    with open(path, encoding="utf-8") as fh:
        return _parse(json.load(fh))
