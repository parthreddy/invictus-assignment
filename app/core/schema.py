"""The contract between the LLM and the rest of the system.

Every model output is parsed into `ExtractedOrder`. Anything that does not fit
this schema is never saved as a work order .

Note what is deliberately ABSENT: there is no price, total, or money field. The
model picks service `code`s and a `quantity`; it cannot express a price at all,
so it cannot invent one or be injected into setting one. Prices are computed
later by the pricing engine from the catalog.
"""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Urgency(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Intent(str, Enum):
    new_order = "new_order"        # a real repair request
    price_question = "price_question"  # asking cost only, no repair (#18)
    cancellation = "cancellation"      # cancel a prior request (#38) -> parked
    other = "other"                    # anything else / unclear


class ServiceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    # quantity carries per-wheel / multi-bike counts (e.g. 2 brake pads, 2 bikes).
    # Bounds are enforced in validator.py, not here: OpenAI structured-output strict
    # mode rejects numeric min/max keywords, and quantity bounds are a business rule.
    quantity: int = 1


class ExtractedOrder(BaseModel):
    """Structured result the model must produce for one inbound message."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    # True only when this should become a work order. price_question / cancellation
    # / unclear messages set this False and never produce a work order.
    is_work_order: bool

    bike_type: str | None = None
    reported_issues: list[str] = Field(default_factory=list)
    services: list[ServiceSelection] = Field(default_factory=list)
    urgency: Urgency | None = None
    requested_date: str | None = None  # ISO 'YYYY-MM-DD' or null

    # One follow-up question when a required field is missing/ambiguous (#3 flow).
    needs_followup: bool = False
    followup_question: str | None = None
    followup_field: str | None = None

    # Content addressed to a different shop than the tag says (#9). We still trust
    # the routing tag; this just flags it for staff review.
    wrong_shop_suspected: bool = False

    @field_validator("requested_date")
    @classmethod
    def _valid_iso_date(cls, v: str | None) -> str | None:
        if v is None:
            return v
        date.fromisoformat(v)  # raises ValueError -> schema validation fails
        return v
