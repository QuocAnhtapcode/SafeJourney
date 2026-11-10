"""Validated inputs for deterministic tools. Units are part of every field name."""
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Route engines/PostGIS return binary floats with more than six decimal places.
# Preserve their Decimal(str(value)) representation; never round eligibility.
Distance = Annotated[Decimal, Field(ge=0, le=20_000_000)]
Duration = Annotated[Decimal, Field(ge=0, le=604_800)]
Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=16, decimal_places=6)]
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=10, decimal_places=6)]
MatrixNumber = Annotated[float, Field(ge=0, le=20_000_000)]


class ToolModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Coordinate(ToolModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class FareInput(ToolModel):
    distance_m: Distance
    duration_s: Duration
    waiting_s: Duration = Decimal(0)
    surcharge_vnd: Money = Decimal(0)
    discount_vnd: Money = Decimal(0)


class RefundInput(ToolModel):
    paid_vnd: Money
    expected_vnd: Money
    already_refunded_vnd: Money = Decimal(0)

    @model_validator(mode='after')
    def refund_cannot_exceed_payment(self):
        if self.already_refunded_vnd > self.paid_vnd:
            raise ValueError('Khoản đã hoàn không được vượt số tiền đã trả')
        return self


class EVProfile(ToolModel):
    capacity_kwh: Decimal = Field(gt=0, le=500, max_digits=12, decimal_places=6)
    soh_percent: Decimal = Field(default=Decimal(100), gt=0, le=100, max_digits=10, decimal_places=6)
    soc_percent: Percent
    reserve_percent: Percent = Decimal(15)
    consumption_wh_per_km: Decimal = Field(default=Decimal(160), gt=0, le=2000, max_digits=12, decimal_places=6)
    auxiliary_kw: Decimal = Field(default=Decimal('0.8'), ge=0, le=20, max_digits=12, decimal_places=6)


class EnergyInput(ToolModel):
    profile: EVProfile
    # Dispatch checks pickup plus passenger leg, each bounded independently.
    distance_m: Decimal = Field(ge=0, le=40_000_000)
    duration_s: Decimal = Field(ge=0, le=1_209_600)


class ChargeInput(ToolModel):
    profile: EVProfile
    target_soc_percent: Percent = Decimal(80)
    station_power_kw: Decimal = Field(gt=0, le=1000, max_digits=12, decimal_places=6)
    vehicle_max_power_kw: Decimal = Field(gt=0, le=1000, max_digits=12, decimal_places=6)
    efficiency: Decimal = Field(default=Decimal('0.9'), gt=0, le=1, max_digits=10, decimal_places=6)
    ports: int = Field(default=1, ge=1, le=100, strict=True)
    busy_remaining_minutes: list[Annotated[Decimal, Field(ge=0, le=1440)]] = Field(default_factory=lambda: [Decimal(0)], max_length=100)
    queue_length: int = Field(default=0, ge=0, le=1000, strict=True)
    queue_session_minutes: Decimal = Field(default=Decimal(30), gt=0, le=1440)

    @model_validator(mode='after')
    def validate_station_snapshot(self):
        if len(self.busy_remaining_minutes) != self.ports:
            raise ValueError('Cần một thời gian còn lại cho mỗi cổng sạc, kể cả cổng trống = 0')
        if self.target_soc_percent < self.profile.soc_percent:
            raise ValueError('Mức pin mục tiêu không được thấp hơn mức hiện tại')
        return self


class DispatchVehicle(ToolModel):
    id: str = Field(min_length=1, max_length=100)
    position: Coordinate
    profile: EVProfile
    seats: int = Field(default=4, ge=1, le=20, strict=True)
    available: bool = True


class DispatchRequest(ToolModel):
    id: str = Field(min_length=1, max_length=100)
    pickup: Coordinate
    destination: Coordinate
    distance_m: Distance
    duration_s: Duration
    max_wait_s: Duration = Decimal(600)
    passengers: int = Field(default=1, ge=1, le=20, strict=True)


class DispatchInput(ToolModel):
    vehicles: list[DispatchVehicle] = Field(max_length=100)
    requests: list[DispatchRequest] = Field(max_length=100)
    distance_matrix_m: list[list[MatrixNumber | None]] = Field(max_length=100)
    duration_matrix_s: list[list[Annotated[float, Field(ge=0, le=604_800)] | None]] = Field(max_length=100)
    routing_verified: bool = False

    @model_validator(mode='after')
    def validate_problem(self):
        nv, nr = len(self.vehicles), len(self.requests)
        if len({v.id for v in self.vehicles}) != nv or len({r.id for r in self.requests}) != nr:
            raise ValueError('Mã xe và mã yêu cầu phải duy nhất trong từng tập')
        for matrix in (self.distance_matrix_m, self.duration_matrix_s):
            if len(matrix) != nv or any(len(row) != nr for row in matrix):
                raise ValueError('Ma trận phải có số hàng = xe, số cột = yêu cầu')
        for row_d, row_t in zip(self.distance_matrix_m, self.duration_matrix_s):
            if any((d is None) != (t is None) for d, t in zip(row_d, row_t)):
                raise ValueError('Cạnh không đi được phải có cả khoảng cách và thời gian null')
        return self
