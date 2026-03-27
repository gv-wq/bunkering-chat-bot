import json
from datetime import datetime, timezone
from enum import Enum
from typing import Dict
from uuid import UUID

from pydantic import BaseModel, Field

class EventType(str, Enum):
    NEW_MESSAGE = "new_message"
    SEAROUTE_NEAREST = "searoute_nearest"
    SEAROUTE_PLAN = "searoute_plan"
    SEAROUTE_NEAREST_ERROR = "searoute_nearest_error"
    SEAROUTE_PLAN_ERROR = "searoute_plan_error"
    SEAROUTE_DATA_REUSE = "searoute_data_reuse"

    ROUTE_STARTED = "new_route_started"
    ROUTE_FINISHED = "new_route_finished"
    ROUTE_BUILT = "route_built"
    ROUTE_DELETED = "route_deleted"
    PDF_REQUESTED = "pdf_requested"
    PDF_GENERATED = "pdf_generated"
    PDF_DECLINED = "pdf_declined"
    PORT_SEARCHED = "port_searched"
    SUPPLIER_PRICES_REQUESTED = "supplier_prices_requested"
    SUPPLIER_PRICES_DECLINED = "supplier_prices_declined"
    VESSEL_NAME_ENTERED = "vessel_name_entered"
    VESSEL_IMO_ENTERED = "vessel_IMO_entered"
    EMAIL_ENTERED = "email_entered"
    COMPANY_NAME_ENTERED = "company_name_entered"

    ROUTES_LISTED = "route_listed"

    PORT_PRICE_REQUESTED = "port_price_requested"
    PORT_PRICE_ENTERED = "port_price_entered"

    SOS_REQUESTED = "sos_requested"
    ERROR = "error"

    QUOTE_REQUEST_STARTED = "quote_request_started"





class Event(BaseModel):
    user_id: UUID = Field(..., description="User ID")
    type: EventType = Field(..., description="Event type")
    timestamp: datetime = Field(..., description="Event timestamp")
    j: Dict = Field(default_factory=dict, description="Event payload as j")

    @classmethod
    def _now(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def new_message(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.NEW_MESSAGE,
            timestamp=cls._now(),
            j=payload or {}
        )

    # --- Sea route events ---
    @classmethod
    def searoute_nearest(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SEAROUTE_NEAREST,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def searoute_plan(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SEAROUTE_PLAN,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def searoute_nearest_error(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SEAROUTE_NEAREST_ERROR,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def searoute_plan_error(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SEAROUTE_PLAN_ERROR,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def searoute_data_reuse(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SEAROUTE_DATA_REUSE,
            timestamp=cls._now(),
            j=payload or {}
        )

    # --- Route lifecycle ---
    @classmethod
    def route_started(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.ROUTE_STARTED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def route_finished(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.ROUTE_FINISHED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def route_built(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.ROUTE_BUILT,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def route_deleted(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.ROUTE_DELETED,
            timestamp=cls._now(),
            j=payload or {}
        )

    # --- PDF / port / vessel / email ---
    @classmethod
    def pdf_generated(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PDF_GENERATED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def pdf_requested(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PDF_REQUESTED,
            timestamp=cls._now(),
            j=payload or {}
        )

    #PDF_DECLINED
    @classmethod
    def pdf_declined(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PDF_DECLINED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def supplier_price_requested(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SUPPLIER_PRICES_REQUESTED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def supplier_price_declined(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SUPPLIER_PRICES_DECLINED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def port_searched(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PORT_SEARCHED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def vessel_name_entered(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.VESSEL_NAME_ENTERED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def vessel_imo_entered(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.VESSEL_IMO_ENTERED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def email_entered(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.EMAIL_ENTERED,
            timestamp=cls._now(),
            j=payload or {}
        )

    # --- Port price events ---
    @classmethod
    def port_price_requested(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PORT_PRICE_REQUESTED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def port_price_entered(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.PORT_PRICE_ENTERED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def company_name_entered(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.COMPANY_NAME_ENTERED,
            timestamp=cls._now(),
            j=payload or {}
        )

    # --- SOS / error ---
    @classmethod
    def sos_requested(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.SOS_REQUESTED,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def error(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.ERROR,
            timestamp=cls._now(),
            j=payload or {}
        )

    @classmethod
    def quote_request_started(cls, user_id: UUID, payload: Dict = None):
        return cls(
            user_id=user_id,
            type=EventType.QUOTE_REQUEST_STARTED,
            timestamp=cls._now(),
            j=payload or {}
        )

class EventDB(Event):
    id: UUID

    @classmethod
    def from_db_row(cls, row) -> "EventDB":
        """Create EventDB from database row"""
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            type=row["type"],
            timestamp=row["timestamp"],
            j=json.loads(row["json"]),
        )
