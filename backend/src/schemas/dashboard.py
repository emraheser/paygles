from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

class DashboardTopicResponse(BaseModel):
    id: int
    site_name: str
    title: str
    url: str
    deal_url: str | None = None
    clean_deal_url: str | None = None
    deal_title: str | None = None
    deal_price: str | None = None
    akakce_url: str
    notification_sent: bool = False
    domain_skipped: bool = False
    notification_block_reason: str | None = None
    source_date: datetime | None = None
    scraped_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class DashboardSyncStatusResponse(BaseModel):
    last_scrape_completed_at: datetime | None = None
    scrape_interval_minutes: int


class DashboardForceSendRequest(BaseModel):
    title: str | None = None
    link: str | None = None


class TrackedProductCreate(BaseModel):
    url: str = Field(..., min_length=10, max_length=1500)

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.lower().startswith(("http://", "https://")):
            raise ValueError("Bağlantı http:// veya https:// ile başlamalıdır.")
        return normalized


class TrackedProductResponse(BaseModel):
    id: int
    title: str
    url: str
    store_name: str
    initial_price_cents: int
    current_price_cents: int
    lowest_price_cents: int
    initial_price: str
    current_price: str
    lowest_price: str
    discount_percent: float
    akakce_url: str
    is_active: bool
    last_checked_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime


class TrackedProductSettingsResponse(BaseModel):
    check_interval_minutes: int
    last_check_completed_at: datetime | None = None


class TrackedProductSettingsUpdate(BaseModel):
    check_interval_minutes: int = Field(..., ge=1, le=1440)
