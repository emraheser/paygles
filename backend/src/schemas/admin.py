from datetime import datetime
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, model_validator


def _looks_like_donanimhaber_thread(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if "donanimhaber.com" not in host:
        return False
    path = (parsed.path or "").lower().rstrip("/")
    return "--" in path

class TargetSiteBase(BaseModel):
    name: str = Field(..., max_length=100)
    url: str = Field(..., max_length=500)
    source_type: str = Field("web", max_length=20)
    topic_list_selector: str = Field("", max_length=200)
    title_selector: str = Field("", max_length=200)
    link_selector: str = Field("", max_length=200)
    date_selector: str | None = Field(None, max_length=200)
    is_active: bool = True

    @model_validator(mode="after")
    def check_web_selectors(self):
        if self.source_type not in {"web", "telegram", "manual", "donanimhaber_thread"}:
            raise ValueError("Geçersiz kaynak türü")

        if self.source_type == "web":
            # Backward-compatible fallback: let DH thread URLs work even when source_type
            # is accidentally left as web in the UI.
            if _looks_like_donanimhaber_thread(self.url):
                return self
            if not self.topic_list_selector or not self.title_selector or not self.link_selector:
                raise ValueError("Web kaynakları için topic_list_selector, title_selector ve link_selector zorunludur")
        return self

class TargetSiteCreate(TargetSiteBase):
    pass

class TargetSiteUpdate(TargetSiteBase):
    pass

class TargetSiteResponse(TargetSiteBase):
    id: int
    source_type: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ScrapedTopicResponse(BaseModel):
    id: int
    site_id: int
    title: str
    url: str
    source_date: datetime | None = None
    scraped_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AppSettingResponse(BaseModel):
    key: str
    value: str
    description: str | None = None
    model_config = ConfigDict(from_attributes=True)
    
class AppSettingUpdate(BaseModel):
    value: str
    description: str | None = None

class KeywordFilterCreate(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100)

class KeywordFilterResponse(BaseModel):
    id: int
    keyword: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class ManualLinkCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    deal_url: str = Field(..., min_length=1, max_length=1000)

# Simple domain pattern: labels separated by dots, TLD at least 2 chars
_DOMAIN_RE = __import__("re").compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$"
)


class AllowedDomainCreate(BaseModel):
    domain: str = Field(..., min_length=3, max_length=200)

    @model_validator(mode="after")
    def sanitize_domain(self):
        d = self.domain.strip().lower()
        # Strip protocol, www, leading/trailing dots and slashes
        for prefix in ("https://", "http://"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        d = d.split("/")[0]  # remove path
        d = d.removeprefix("www.").strip(".")
        if not _DOMAIN_RE.match(d):
            raise ValueError("Geçersiz domain formatı. Örnek: hepsiburada.com")
        self.domain = d
        return self

class AllowedDomainResponse(BaseModel):
    id: int
    domain: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
