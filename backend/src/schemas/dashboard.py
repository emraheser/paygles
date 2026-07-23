from datetime import datetime
from pydantic import BaseModel, ConfigDict

class DashboardTopicResponse(BaseModel):
    id: int
    site_name: str
    title: str
    url: str
    deal_url: str | None = None
    clean_deal_url: str | None = None
    deal_title: str | None = None
    deal_price: str | None = None
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
