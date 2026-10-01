"""Response models for GET /slots. Shape only; the times come from services/slot_query.py."""

import datetime as dt

from pydantic import BaseModel, Field

from app.core.timezones import utc_to_local
from app.services.slot_query import SlotsResult

_EXAMPLE = {
    "date": "2026-10-05",
    "timezone": "Asia/Tashkent",
    "service": {"id": 1, "name": "Haircut", "duration_minutes": 30, "price": 60000},
    "providers": [
        {
            "provider": {"id": 1, "name": "Jasur"},
            "slots": [
                {
                    "start_at": "2026-10-05T04:00:00Z",
                    "end_at": "2026-10-05T04:30:00Z",
                    "local_start": "2026-10-05T09:00:00+05:00",
                    "local_end": "2026-10-05T09:30:00+05:00",
                },
                {
                    "start_at": "2026-10-05T04:15:00Z",
                    "end_at": "2026-10-05T04:45:00Z",
                    "local_start": "2026-10-05T09:15:00+05:00",
                    "local_end": "2026-10-05T09:45:00+05:00",
                },
            ],
        },
        {"provider": {"id": 2, "name": "Aziz"}, "slots": []},
    ],
}


class SlotServiceInfo(BaseModel):
    id: int
    name: str
    duration_minutes: int
    price: int = Field(description="Whole UZS.")


class SlotProviderInfo(BaseModel):
    id: int
    name: str


class SlotResponse(BaseModel):
    start_at: dt.datetime = Field(description="UTC instant the appointment would start.")
    end_at: dt.datetime = Field(description="`start_at` plus the service duration (exclusive).")
    local_start: dt.datetime = Field(
        description="`start_at` on the business's clock, with its UTC offset."
    )
    local_end: dt.datetime = Field(description="`end_at` on the business's clock, with its offset.")


class ProviderSlotsResponse(BaseModel):
    provider: SlotProviderInfo
    slots: list[SlotResponse] = Field(description="Empty when the provider has no free time.")


class SlotsResponse(BaseModel):
    date: dt.date = Field(description="The local date in the business timezone.")
    timezone: str = Field(description="IANA name; show the slots on this clock.")
    service: SlotServiceInfo
    providers: list[ProviderSlotsResponse]

    model_config = {"json_schema_extra": {"examples": [_EXAMPLE]}}

    @classmethod
    def from_result(cls, result: SlotsResult) -> "SlotsResponse":
        length = dt.timedelta(minutes=result.service.duration_minutes)
        return cls(
            date=result.date,
            timezone=result.timezone,
            service=SlotServiceInfo(
                id=result.service.id,
                name=result.service.name,
                duration_minutes=result.service.duration_minutes,
                price=result.service.price,
            ),
            providers=[
                ProviderSlotsResponse(
                    provider=SlotProviderInfo(id=item.provider.id, name=item.provider.name),
                    slots=[
                        SlotResponse(
                            start_at=start,
                            end_at=start + length,
                            local_start=utc_to_local(start, result.timezone),
                            local_end=utc_to_local(start + length, result.timezone),
                        )
                        for start in item.starts
                    ],
                )
                for item in result.providers
            ],
        )
