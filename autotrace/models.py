from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


INTERVALS = {5: 300, 15: 900, 60: 3600}


class SiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    interval_minutes: int | None = None
    check_interval_s: int | None = None

    @field_validator("interval_minutes")
    @classmethod
    def validate_interval(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in INTERVALS:
            raise ValueError("interval_minutes must be 5, 15, or 60")
        return value

    def interval_seconds(self) -> int:
        if self.interval_minutes is not None:
            return INTERVALS[self.interval_minutes]
        if self.check_interval_s in (300, 900, 3600):
            return int(self.check_interval_s)
        raise ValueError("check interval must be 300, 900, or 3600 seconds")


class AlertChannelCreate(BaseModel):
    site_id: str | None = None
    channel_type: Literal["email", "webhook"]
    config: dict[str, Any]

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any], info) -> dict[str, Any]:
        channel_type = info.data.get("channel_type")
        if channel_type == "email":
            email = value.get("email")
            if not isinstance(email, str) or "@" not in email:
                raise ValueError("config.email must be a valid email address")
        if channel_type == "webhook":
            url = value.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ValueError("config.url must start with https://")
        return value


class VerifyRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)