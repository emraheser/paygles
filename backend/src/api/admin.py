from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete

from src.database import get_db
from src.models.domain import TargetSite, AppSetting, ScrapedTopic, KeywordFilter, AllowedDomain
from src.schemas.admin import TargetSiteCreate, TargetSiteResponse, TargetSiteUpdate, AppSettingResponse, AppSettingUpdate, KeywordFilterCreate, KeywordFilterResponse, ManualLinkCreate, AllowedDomainCreate, AllowedDomainResponse
from src.services.scheduler import refresh_scheduler_interval
from src.services.notifier import normalize_deal_url

router = APIRouter(prefix="/admin", tags=["admin"])

DbDep = Annotated[AsyncSession, Depends(get_db)]

@router.get("/sites", response_model=list[TargetSiteResponse])
async def list_target_sites(db: DbDep):
    result = await db.execute(select(TargetSite))
    return result.scalars().all()

@router.post("/sites", response_model=TargetSiteResponse, status_code=status.HTTP_201_CREATED)
async def create_target_site(site: TargetSiteCreate, db: DbDep):
    new_site = TargetSite(**site.model_dump())
    db.add(new_site)
    await db.commit()
    await db.refresh(new_site)
    return new_site

@router.put("/sites/{site_id}", response_model=TargetSiteResponse)
async def update_target_site(site_id: int, site: TargetSiteUpdate, db: DbDep):
    result = await db.execute(select(TargetSite).where(TargetSite.id == site_id))
    db_site = result.scalar_one_or_none()
    if not db_site:
        raise HTTPException(status_code=404, detail="Site not found")
        
    for key, value in site.model_dump().items():
        setattr(db_site, key, value)
        
    await db.commit()
    await db.refresh(db_site)
    return db_site

@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target_site(site_id: int, db: DbDep):
    result = await db.execute(select(TargetSite).where(TargetSite.id == site_id))
    db_site = result.scalar_one_or_none()
    if not db_site:
        raise HTTPException(status_code=404, detail="Site not found")
        
    await db.execute(delete(ScrapedTopic).where(ScrapedTopic.site_id == site_id))
    await db.delete(db_site)
    await db.commit()

@router.get("/settings", response_model=list[AppSettingResponse])
async def list_settings(db: DbDep):
    result = await db.execute(select(AppSetting))
    return result.scalars().all()

@router.put("/settings/{key}", response_model=AppSettingResponse)
async def update_setting(key: str, setting_update: AppSettingUpdate, db: DbDep):
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    db_setting = result.scalar_one_or_none()
    
    if not db_setting:
        # Create it if it doesn't exist yet
        db_setting = AppSetting(key=key, **setting_update.model_dump())
        db.add(db_setting)
    else:
        for k, v in setting_update.model_dump().items():
            setattr(db_setting, k, v)
            
    await db.commit()
    await db.refresh(db_setting)

    if key == "scrape_interval_minutes":
        await refresh_scheduler_interval()

    return db_setting

# ── Keyword Filters ──────────────────────────────────────────────────────

@router.get("/keywords", response_model=list[KeywordFilterResponse])
async def list_keywords(db: DbDep):
    result = await db.execute(select(KeywordFilter))
    return result.scalars().all()

@router.post("/keywords", response_model=KeywordFilterResponse, status_code=status.HTTP_201_CREATED)
async def create_keyword(body: KeywordFilterCreate, db: DbDep):
    keyword_text = body.keyword.strip().lower()
    existing = await db.execute(
        select(KeywordFilter).where(KeywordFilter.keyword == keyword_text)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu keyword zaten mevcut")
    kw = KeywordFilter(keyword=keyword_text)
    db.add(kw)
    await db.commit()
    await db.refresh(kw)
    return kw

@router.delete("/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_keyword(keyword_id: int, db: DbDep):
    result = await db.execute(select(KeywordFilter).where(KeywordFilter.id == keyword_id))
    kw = result.scalar_one_or_none()
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    await db.delete(kw)
    await db.commit()

@router.patch("/keywords/{keyword_id}/toggle", response_model=KeywordFilterResponse)
async def toggle_keyword(keyword_id: int, db: DbDep):
    result = await db.execute(select(KeywordFilter).where(KeywordFilter.id == keyword_id))
    kw = result.scalar_one_or_none()
    if not kw:
        raise HTTPException(status_code=404, detail="Keyword not found")
    kw.is_active = not kw.is_active
    await db.commit()
    await db.refresh(kw)
    return kw

# ── Manual Link ───────────────────────────────────────────────────────────

@router.post("/manual-link", status_code=status.HTTP_201_CREATED)
async def create_manual_link(body: ManualLinkCreate, db: DbDep):
    """Manually create a deal entry that will be sent as a Telegram notification."""
    from datetime import datetime
    # Find or create the virtual 'Manuel' source
    result = await db.execute(
        select(TargetSite).where(TargetSite.name == "Admin", TargetSite.source_type == "manual")
    )
    site = result.scalar_one_or_none()
    if not site:
        site = TargetSite(
            name="Admin",
            url="manual://",
            source_type="manual",
            topic_list_selector="",
            title_selector="",
            link_selector="",
            is_active=True,
        )
        db.add(site)
        await db.flush()

    # Check if this URL already exists
    existing = await db.execute(
        select(ScrapedTopic).where(ScrapedTopic.url == body.deal_url.strip())
    )
    topic = existing.scalar_one_or_none()
    if topic:
        # Re-queue for notification
        topic.title = body.title.strip()
        topic.deal_url = body.deal_url.strip()
        topic.clean_deal_url = normalize_deal_url(body.deal_url.strip())
        topic.notification_sent = False
        topic.domain_skipped = False
        topic.notification_block_reason = None
        topic.deleted_by_user = False
        topic.scraped_at = datetime.utcnow()
    else:
        topic = ScrapedTopic(
            site_id=site.id,
            title=body.title.strip(),
            url=body.deal_url.strip(),
            deal_url=body.deal_url.strip(),
            clean_deal_url=normalize_deal_url(body.deal_url.strip()),
            notification_sent=False,
            domain_skipped=False,
            source_date=datetime.utcnow(),
            scraped_at=datetime.utcnow(),
        )
        db.add(topic)
    await db.commit()
    return {"message": "Link oluşturuldu, bildirim gönderilecek."}

# ── Allowed Domains ───────────────────────────────────────────────────────

@router.get("/domains", response_model=list[AllowedDomainResponse])
async def list_domains(db: DbDep):
    result = await db.execute(select(AllowedDomain))
    return result.scalars().all()

@router.post("/domains", response_model=AllowedDomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(body: AllowedDomainCreate, db: DbDep):
    domain_text = body.domain.strip().lower().removeprefix("www.")
    existing = await db.execute(
        select(AllowedDomain).where(AllowedDomain.domain == domain_text)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Bu domain zaten mevcut")
    d = AllowedDomain(domain=domain_text)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d

@router.delete("/domains/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(domain_id: int, db: DbDep):
    result = await db.execute(select(AllowedDomain).where(AllowedDomain.id == domain_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")
    await db.delete(d)
    await db.commit()

@router.patch("/domains/{domain_id}/toggle", response_model=AllowedDomainResponse)
async def toggle_domain(domain_id: int, db: DbDep):
    result = await db.execute(select(AllowedDomain).where(AllowedDomain.id == domain_id))
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Domain not found")
    d.is_active = not d.is_active
    await db.commit()
    await db.refresh(d)
    return d
