from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from src.database import Base

class TargetSite(Base):
    __tablename__ = "target_sites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    source_type = Column(String(20), nullable=False, default="web")  # "web" or "telegram"
    
    # CSS Selectors for Scrapling (only used when source_type="web")
    topic_list_selector = Column(String(200), nullable=False, default="")
    title_selector = Column(String(200), nullable=False, default="")
    link_selector = Column(String(200), nullable=False, default="")
    date_selector = Column(String(200), nullable=True) # Optional if we rely on scrape time
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScrapedTopic(Base):
    __tablename__ = "scraped_topics"

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(Integer, ForeignKey("target_sites.id", ondelete="CASCADE"), nullable=False)
    
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False, unique=True)
    source_topic_id = Column(String(100), nullable=True, index=True)
    is_sticky = Column(Boolean, default=False, nullable=False, index=True)
    notification_sent = Column(Boolean, default=False, nullable=False, index=True)
    domain_skipped = Column(Boolean, default=False, nullable=False, index=True)
    notification_block_reason = Column(String(100), nullable=True)
    deleted_by_user = Column(Boolean, default=False, nullable=False, index=True)
    source_date = Column(DateTime, nullable=True)
    deal_url = Column(String(1000), nullable=True)
    clean_deal_url = Column(String(1000), nullable=True)
    deal_title = Column(String(500), nullable=True)
    deal_price = Column(String(100), nullable=True)
    
    scraped_at = Column(DateTime, default=datetime.utcnow)

class AppSetting(Base):
    """General parametric settings like scraping interval"""
    __tablename__ = "app_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(String(500), nullable=False) # Store as string, parse as needed
    description = Column(String(500), nullable=True)

class KeywordFilter(Base):
    """Keywords used to filter Telegram channel messages."""
    __tablename__ = "keyword_filters"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(100), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AllowedDomain(Base):
    """Whitelisted domains for deal URLs. Only links from these domains will be sent."""
    __tablename__ = "allowed_domains"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(200), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
