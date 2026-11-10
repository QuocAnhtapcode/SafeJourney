"""HTTP request contracts; add fields compatibly or version the endpoint."""
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field, AwareDatetime, ConfigDict


class TripView(BaseModel):
    """Stable public projection; Pydantic serializes fleet lists directly."""
    id: str
    label: str
    driver_id: str
    status: str
    last_lat: float | None
    last_lon: float | None
    last_seen: AwareDatetime | None
    version: int
    route: dict | None

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class Telemetry(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    event_id: UUID
    seq: int = Field(ge=0)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=10000)
    speed_kmh: float = Field(ge=0, le=350)
    event_time: AwareDatetime


class SOS(BaseModel):
    event_id: UUID


class OwnershipAction(BaseModel):
    # Missing versions are rejected by the ownership guard with a refreshable 409.
    assignment_version: int | None = Field(default=None, ge=1, strict=True)


class Decision(OwnershipAction):
    proposal_id: UUID
    approve: bool
    proposal_revision: int | None = Field(default=None, ge=1, strict=True)


class ProposalEdit(OwnershipAction):
    proposal_id: UUID
    proposal_revision: int = Field(ge=1, strict=True)
    message: str = Field(min_length=5, max_length=1500)


class FollowUp(OwnershipAction):
    proposal_id: UUID
    request_id: UUID
    outcome: Literal['no_response', 'needs_help']


class ContactReply(BaseModel):
    request_id: UUID
    outcome: Literal['safe', 'needs_help']


class Replan(OwnershipAction):
    proposal_id: UUID


class Resolve(OwnershipAction):
    reason: str | None = Field(default=None, min_length=5, max_length=500)
    reason_code: str | None = Field(default=None, max_length=50)

