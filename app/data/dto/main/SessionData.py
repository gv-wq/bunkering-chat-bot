import json
from datetime import datetime, date
from typing import List, Optional
from pydantic import Field, BaseModel

from app.data.dto.main.PortFuelPrice import PortFuelPriceDB
from app.data.dto.main.SeaPort import SeaPortDB
from app.data.dto.main.TariffSelection import TariffSelection
from app.data.dto.main.MabuxPortFuelPrice import MabuxPortFuelPriceDB


class CheckFuelPrice(BaseModel):
    port: Optional[SeaPortDB] = Field(None)
    prices: List[MabuxPortFuelPriceDB] = Field([])
    port_alternatives: List[SeaPortDB] =  Field([])

    @classmethod
    def from_dict(cls, d: dict) -> Optional["CheckFuelPrice"]:
        if not d:
            return None

        port_obj = d.get("port")
        port_alternatives = d.get("port_alternatives", [])
        prices = d.get("prices", [])

        return cls(
            port=SeaPortDB.from_db_row(port_obj) if port_obj else None,
            prices=[MabuxPortFuelPriceDB.from_dict(r) for r in prices],
            port_alternatives=[SeaPortDB.from_db_row(p) for p in port_alternatives]
        )

    def to_dict(self) -> dict:
        return {
            "port": self.port.model_dump() if self.port else None,
            "prices": [p.to_dict() for p in self.prices],
            "port_alternatives": [p.model_dump() for p in self.port_alternatives]
        }

class RouteSearch(BaseModel):
    ids: List[str] = Field(default=[])
    offset: int = Field(default=0)
    date: Optional[datetime] = Field(default=None)
    id: Optional[str] = Field(default=None)
    total: Optional[int] = Field(default=None)

    @classmethod
    def from_dict(cls, d: dict) -> Optional["RouteSearch"]:
        date = d.get("date")

        return cls(
            ids=d.get("ids", []),
            offset=d.get("offset", 0),
            date=datetime.strptime(date, "%Y-%m-%d").date() if date else None,
            id=d.get("id"),
            total=d.get("total", None)
        )

    def to_dict(self) -> dict:
        return {
            "ids": self.ids,
            "offset": self.offset,
            "date": self.date.strftime("%Y-%m-%d") if self.date else None,
            "id": self.id,
            "total": self.total
        }


class UserSearch(BaseModel):
    """User search state for pagination and filtering"""
    offset: int = Field(0)
    total: int = Field(0)
    ids: List[str] = Field(default_factory=list)
    filter_status: Optional[str] = Field(None)  # 'active', 'blocked', 'all'
    filter_admin: Optional[bool] = Field(None)  # True for admins only, False for non-admins
    search_term: Optional[str] = Field(None)  # Last search term used
    last_update: Optional[datetime] = Field(None)
    # Optional: Add date filters if needed
    created_after: Optional[date] = Field(None)
    created_before: Optional[date] = Field(None)

    @classmethod
    def from_dict(cls, d: dict) -> Optional["UserSearch"]:
        """Create UserSearch from dictionary"""

        # Parse date fields
        last_update_str = d.get("last_update")
        created_after_str = d.get("created_after")
        created_before_str = d.get("created_before")

        last_update = None
        created_after = None
        created_before = None

        if last_update_str:
            try:
                last_update = datetime.fromisoformat(last_update_str)
            except (ValueError, TypeError):
                last_update = None

        if created_after_str:
            try:
                created_after = datetime.strptime(created_after_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                created_after = None

        if created_before_str:
            try:
                created_before = datetime.strptime(created_before_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                created_before = None

        # Parse filter_admin - handle string to boolean conversion
        filter_admin = d.get("filter_admin")
        if isinstance(filter_admin, str):
            if filter_admin.lower() == "true":
                filter_admin = True
            elif filter_admin.lower() == "false":
                filter_admin = False
            else:
                filter_admin = None

        return cls(
            offset=d.get("offset", 0),
            total=d.get("total", 0),
            ids=d.get("ids", []),
            filter_status=d.get("filter_status"),
            filter_admin=filter_admin,
            search_term=d.get("search_term"),
            last_update=last_update,
            created_after=created_after,
            created_before=created_before
        )

    def to_dict(self) -> dict:
        """Convert UserSearch to dictionary"""
        return {
            "offset": self.offset,
            "total": self.total,
            "ids": self.ids,
            "filter_status": self.filter_status,
            "filter_admin": self.filter_admin,
            "search_term": self.search_term,
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "created_after": self.created_after.strftime("%Y-%m-%d") if self.created_after else None,
            "created_before": self.created_before.strftime("%Y-%m-%d") if self.created_before else None
        }

    def to_json(self) -> str:
        """Convert UserSearch to JSON string"""
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> Optional["UserSearch"]:
        """Create UserSearch from JSON string"""
        if not json_str:
            return None
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def reset(self) -> None:
        """Reset search to default values"""
        self.offset = 0
        self.total = 0
        self.ids = []
        self.filter_status = None
        self.filter_admin = None
        self.search_term = None
        self.last_update = None
        self.created_after = None
        self.created_before = None

    def has_filters(self) -> bool:
        """Check if any filters are active"""
        return any([
            self.filter_status is not None,
            self.filter_admin is not None,
            self.search_term is not None,
            self.created_after is not None,
            self.created_before is not None
        ])

    def get_filter_summary(self) -> str:
        """Get human-readable summary of active filters"""
        filters = []

        if self.filter_status == "active":
            filters.append("active users only")
        elif self.filter_status == "blocked":
            filters.append("blocked users only")

        if self.filter_admin is True:
            filters.append("admins only")
        elif self.filter_admin is False:
            filters.append("non-admins only")

        if self.search_term:
            filters.append(f'search: "{self.search_term}"')

        if self.created_after:
            filters.append(f'created after: {self.created_after.strftime("%Y-%m-%d")}')

        if self.created_before:
            filters.append(f'created before: {self.created_before.strftime("%Y-%m-%d")}')

        if not filters:
            return "No filters applied"

        return "; ".join(filters)

class AdminUpdateTariff(BaseModel):
    user_id : Optional[str] = Field(None)
    target_tariff_id: Optional[str] = Field(None)

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            user_id=d.get("user_id"),
            target_tariff_id=d.get("target_tariff_id"),
        )


class SessionData(BaseModel):
    check_port_fuel_price: Optional[CheckFuelPrice] = Field(None)
    route_search: RouteSearch = Field()
    tariff_selection: TariffSelection = Field()
    user_search: UserSearch = Field()
    admin_update_tariff : AdminUpdateTariff = Field()

    @classmethod
    def from_dict(cls, d: dict) -> "SessionData":
        check_fuel_price_dict = d.get("check_port_fuel_price")
        route_search_dict = d.get("route_search", {})
        tariff_selection_dict = d.get("tariff_selection", {})

        return cls(
            check_port_fuel_price=CheckFuelPrice.from_dict(check_fuel_price_dict) if check_fuel_price_dict else None,
            route_search=RouteSearch.from_dict(route_search_dict),
            tariff_selection=TariffSelection.from_dict(tariff_selection_dict),
            user_search=UserSearch.from_dict(d.get("user_search", {})),
            admin_update_tariff=AdminUpdateTariff.from_dict(d.get("admin_update_tariff", {})),
        )

    def to_dict(self) -> dict:
        return {
            "check_port_fuel_price": self.check_port_fuel_price.to_dict() if self.check_port_fuel_price else None,
            "route_search": self.route_search.to_dict(),
            "tariff_selection" : self.tariff_selection.model_dump(),
            "user_search": self.user_search.to_dict(),
            "admin_update_tariff": self.admin_update_tariff.model_dump(),
        }