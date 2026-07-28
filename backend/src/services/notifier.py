import asyncio
import json
import logging
import os
import re
from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo
from html import escape
from urllib.parse import urlencode, urlparse, urlunparse, urljoin
from urllib.request import Request, urlopen

from scrapling import Fetcher
from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.models.domain import ScrapedTopic, TargetSite, AllowedDomain

logger = logging.getLogger(__name__)

_ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# Telegram channel link pattern — must never be shown to end users
_TELEGRAM_URL_RE = __import__("re").compile(r"^https?://t\.me/", __import__("re").IGNORECASE)

# Subdomain prefixes that are mobile short-link redirectors.
# sl.n11.com → opens Google Play store; stripping "sl." gives the real product page.
_MOBILE_REDIRECT_PREFIXES = ("sl.", "m.")

# Mobile User-Agent for fallback canonical-URL resolution
_MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

_CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_URL_RE = re.compile(
    r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _ai_enhanced_mode_enabled() -> bool:
    return _env_flag_enabled("AI_ENHANCED_MODE", default=False)


def _ai_enhanced_lookback_hours() -> int:
    raw = (os.getenv("AI_ENHANCED_LOOKBACK_HOURS", "24") or "24").strip()
    if not raw.isdigit():
        return 24
    return max(1, min(168, int(raw)))


def normalize_deal_url(url: str) -> str:
    """Strip known mobile-redirect subdomains so the link goes to the real product page."""
    if not url:
        return url
    try:
        cleaned_url = re.sub(r"^[*_`\s]+|[*_`\s]+$", "", url.strip())
        cleaned_url = cleaned_url.strip("<>'\"")
        cleaned_url = cleaned_url.rstrip("*.,;:!?)\\]")
        parsed = urlparse(cleaned_url)
        if not parsed.scheme and not parsed.netloc:
            return cleaned_url
        hostname = parsed.hostname or ""
        netloc = parsed.netloc
        for prefix in _MOBILE_REDIRECT_PREFIXES:
            if hostname.startswith(prefix):
                new_host = hostname[len(prefix):]
                # Rebuild netloc preserving port if any
                netloc = new_host if not parsed.port else f"{new_host}:{parsed.port}"
                hostname = new_host
                parsed = parsed._replace(netloc=netloc)
                break
        parsed = parsed._replace(query="", fragment="")
        return urlunparse(parsed)
    except Exception:
        return url


def _sanitize_outgoing_text(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    cleaned = re.sub(r"^[*_`\s]+|[*_`\s]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


_TRAILING_TITLE_PRICE_RE = re.compile(
    r"\s*(?:[-–—|:]\s*)?(?:(?:TL|₺)\s*\d[\d.,\s]*|\d[\d.,\s]*\s*(?:TL|₺))\s*$",
    re.IGNORECASE,
)


def normalize_deal_title(value: str | None) -> str:
    """Remove trailing currency prices without touching product model numbers."""
    original = _sanitize_outgoing_text(value)
    if not original:
        return ""

    cleaned = original
    while True:
        normalized = _TRAILING_TITLE_PRICE_RE.sub("", cleaned).rstrip(" -–—|:")
        if not normalized or normalized == cleaned:
            return cleaned if normalized else original
        cleaned = normalized


def normalize_deal_price(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _normalize_price_text(value)
    return normalized or value.strip()


class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self._resolved_chat_id = self.chat_id
        self._warned_missing_token = False
        self._warned_missing_chat = False

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _post_form(self, method: str, payload: dict[str, str]) -> dict:
        encoded = urlencode(payload).encode("utf-8")
        req = Request(self._api_url(method), data=encoded, method="POST")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get_json(self, method: str) -> dict:
        req = Request(self._api_url(method), method="GET")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    async def _resolve_chat_id(self) -> str | None:
        if self._resolved_chat_id:
            return self._resolved_chat_id
        try:
            updates = await asyncio.to_thread(self._get_json, "getUpdates")
        except Exception as exc:
            if not self._warned_missing_chat:
                logger.warning("Telegram chat_id could not be auto-resolved: %s", exc)
                self._warned_missing_chat = True
            return None

        results = updates.get("result") or []
        for item in reversed(results):
            message = item.get("message") or item.get("channel_post") or {}
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if chat_id is not None:
                self._resolved_chat_id = str(chat_id)
                return self._resolved_chat_id
        if not self._warned_missing_chat:
            logger.warning("Telegram chat_id not found in getUpdates. Message your bot once, then retry.")
            self._warned_missing_chat = True
        return None

    async def send_topic(
        self,
        topic: ScrapedTopic,
        site_name: str,
        override_title: str | None = None,
        override_link: str | None = None,
    ) -> bool:
        if not self.token:
            if not self._warned_missing_token:
                logger.warning("Telegram notifier disabled: TELEGRAM_BOT_TOKEN is missing.")
                self._warned_missing_token = True
            return False

        chat_id = await self._resolve_chat_id()
        if not chat_id:
            return False

        # Determine the link to show. Never expose source Telegram channel URLs.
        link_candidate = (override_link or "").strip() or (topic.clean_deal_url or topic.deal_url or topic.url)
        link_url = normalize_deal_url(link_candidate)
        if _TELEGRAM_URL_RE.match(link_url):
            # No usable external link — skip silently.
            return True  # mark as "sent" so we don't retry forever

        source_date = topic.source_date or topic.scraped_at or datetime.utcnow()
        source_date_local = source_date.replace(tzinfo=ZoneInfo("UTC")).astimezone(_ISTANBUL_TZ)
        preferred_title = (override_title or "").strip()
        if not preferred_title:
            candidate_deal_title = (topic.deal_title or "").strip()
            preferred_title = topic.title if _is_junk_title(candidate_deal_title) else candidate_deal_title
        if not preferred_title:
            preferred_title = topic.title
        outgoing_title = normalize_deal_title(preferred_title)
        outgoing_price = normalize_deal_price(getattr(topic, "deal_price", None))
        if not outgoing_price:
            outgoing_price = "-"

        text = (
            f"<b>{escape(outgoing_title)}</b>\n"
            f"💰 {escape(outgoing_price)}\n"
            f"🕒 {source_date_local.strftime('%d.%m.%Y %H:%M')}\n"
            f"📍 {escape(site_name)}\n"
            "#işbirliğideğildir"
        )

        inline_keyboard = [[{"text": "🔗 Ürüne Git", "url": link_url}]]

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
            "reply_markup": json.dumps({"inline_keyboard": inline_keyboard}),
        }
        try:
            result = await asyncio.to_thread(self._post_form, "sendMessage", payload)
        except Exception as exc:
            logger.warning("Telegram send failed for topic id=%s: %s", topic.id, exc)
            return False

        if not result.get("ok"):
            logger.warning("Telegram send rejected for topic id=%s: %s", topic.id, result)
            return False
        return True

    async def send_price_drop(
        self,
        title: str,
        link_url: str,
        store_name: str,
        initial_price: str,
        current_price: str,
    ) -> bool:
        if not self.token:
            if not self._warned_missing_token:
                logger.warning("Telegram notifier disabled: TELEGRAM_BOT_TOKEN is missing.")
                self._warned_missing_token = True
            return False

        chat_id = await self._resolve_chat_id()
        if not chat_id:
            return False

        text = (
            "<b>Fiyat düştü</b>\n\n"
            f"<b>{escape(normalize_deal_title(title))}</b>\n"
            f"Güncel fiyat: <b>{escape(current_price)}</b>\n"
            f"Takibe alınan fiyat: <s>{escape(initial_price)}</s>\n"
            f"Mağaza: {escape(store_name)}"
        )
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
            "reply_markup": json.dumps(
                {"inline_keyboard": [[{"text": "Ürünü Gör", "url": link_url}]]}
            ),
        }
        try:
            result = await asyncio.to_thread(self._post_form, "sendMessage", payload)
        except Exception as exc:
            logger.warning("Telegram price-drop notification failed for %s: %s", link_url, exc)
            return False

        if not result.get("ok"):
            logger.warning("Telegram price-drop notification rejected: %s", result)
            return False
        return True


telegram_notifier = TelegramNotifier()


_JUNK_TITLES = frozenset({
    "just a moment...",
    "attention required",
    "access denied",
    "503 - hizmet kullanılamıyor hatası",
    "503 service unavailable",
    "service unavailable",
    "hizmet kullanılamıyor hatası",
    "please wait",
    "checking your browser",
    "403 forbidden",
    "404 not found",
    "security check",
    "bot verification",
    "ddos protection",
    "you are being redirected",
    "pardon our interruption",
    "üzgünüz",
    "uzgunuz",
    "sorry",
})

_COUPON_OR_CAMPAIGN_PHRASES = (
    "kupon",
    "kuponmatik",
    "indirim kodu",
    "kampanya",
    "paraf para",
    "ilk alışverişe",
    "kazanma şansı",
    "kazı kazan",
    "alt limitsiz",
    "limitsiz",
    "hediye ediyor",
    "tık hızı",
    "banka kampanyaları",
    "bank kampanyaları",
)

_DISCUSSION_PHRASES = (
    "öneri",
    "yardım",
    "dar boğaz",
    "sizce",
    "alınır mı",
    "yapar mı",
    "nasıl",
    "karşılaştırma",
    "kıyas",
    "merhaba",
)

_SOCIAL_IMAGE_HOSTS = (
    "instagram.com",
    "imgur.com",
    "ibb.co",
    "i.hizliresim.com",
    "hizliresim.com",
    "resimlink.com",
)


def _is_junk_title(title: str) -> bool:
    """Return True if the title looks like a Cloudflare/bot-challenge, error page, or AI hallucination."""
    t = title.strip().lower()
    return t in _JUNK_TITLES or any(j in t for j in (
        "just a moment", "checking your browser", "captcha",
        "attention required", "cloudflare",
        "service unavailable", "hizmet kullanılamıyor",
        "bu bir başlık", "ürün adı içermiyor", "bulunamadı",
        "bu bir ürün adı değil", "resim yükle", "watch this story",
        "alışverişe devam etmek için", "alisverise devam etmek icin",
        "continue shopping", "üzgünüz",
    ))


def _is_coupon_or_campaign_title(title: str | None) -> bool:
    if not title:
        return False
    lowered = _sanitize_outgoing_text(title).lower()
    if not lowered:
        return False
    if any(phrase in lowered for phrase in _COUPON_OR_CAMPAIGN_PHRASES):
        return True
    return bool(re.search(r"\b\d{2,5}\s*/\s*\d{2,5}\b", lowered))


def _is_discussion_title(title: str | None) -> bool:
    if not title:
        return False
    lowered = _sanitize_outgoing_text(title).lower()
    if not lowered:
        return False
    if lowered.endswith("?") or "?" in lowered:
        return True
    return any(phrase in lowered for phrase in _DISCUSSION_PHRASES)


def _can_use_title_price_fallback(title: str | None) -> bool:
    return bool(title) and not _is_coupon_or_campaign_title(title) and not _is_discussion_title(title)


def _is_homepage_or_junk_url(url: str) -> bool:
    """Return True if the resolved URL is a homepage, search page, or otherwise not a product page."""
    if not url:
        return True
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        path = (parsed.path or "/").rstrip("/")
        # Pure homepage (no path)
        if path in ("", "/"):
            return True
        # Trendyol search results page
        if path == "/sr":
            return True
        if "amazon." in hostname and path == "/s":
            return True
        # Generic search/listing paths
        if path in ("/search", "/ara", "/arama"):
            return True
        if path.startswith("/magaza/") or path.startswith("/stores/"):
            return True
        if "n11.com" in hostname and path.startswith("/n/"):
            return True
        if any(hostname == host or hostname.endswith("." + host) for host in _SOCIAL_IMAGE_HOSTS):
            return True
        return False
    except Exception:
        return True


def _extract_product_url_from_redirect(redirect_url: str) -> str | None:
    """Extract a desktop product URL from a mobile deep-link / tracker redirect.

    Handles Adjust (adj.st), AppsFlyer, Branch.io and similar trackers that
    embed product identifiers in query parameters.
    """
    try:
        parsed = urlparse(redirect_url)
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)

        # --- Hepsiburada (adj.st deep links) ---
        hostname = parsed.hostname or ""
        if "adj.st" in hostname or "adjust.com" in hostname:
            # 1) Direct sku param → product page
            sku = (qs.get("sku") or [None])[0]
            if sku and sku.startswith("HB"):
                return f"https://www.hepsiburada.com/-p-{sku}"

            # 2) Parse adj_deep_link (hbapp://...)
            deep_link = (qs.get("adj_deep_link") or [None])[0]
            if deep_link:
                dl_parsed = urlparse(deep_link)
                dl_qs = parse_qs(dl_parsed.query)
                # hbapp://product?sku=HBxxx
                sku = (dl_qs.get("sku") or [None])[0]
                if sku and sku.startswith("HB"):
                    return f"https://www.hepsiburada.com/-p-{sku}"
                # hbapp://tag?tagId=xxx → store/tag page
                dl_type = dl_parsed.hostname or ""  # "product", "tag", "list", etc.
                tag_id = (dl_qs.get("tagId") or [None])[0]
                if dl_type == "tag" and tag_id:
                    # Strip the unique suffix after last dash to get store slug
                    store_slug = tag_id.rsplit("-", 1)[0] if "-" in tag_id else tag_id
                    return f"https://www.hepsiburada.com/magaza/{store_slug}"
                # hbapp://list?listId=xxx → list/campaign page
                list_id = (dl_qs.get("listId") or [None])[0]
                if dl_type == "list" and list_id:
                    return f"https://www.hepsiburada.com/liste/{list_id}"

        # --- Trendyol (ty.gl / adjust / appsflyer) ---
        # Pattern: url or deep_link containing boutiqueid/merchantid/contentid
        for key in ("url", "deep_link", "adj_deep_link", "af_dp"):
            raw = (qs.get(key) or [None])[0]
            if not raw:
                continue
            if "trendyol.com" in raw:
                return normalize_deal_url(raw)
            dl_parsed = urlparse(raw)
            dl_qs = parse_qs(dl_parsed.query)
            content_id = (dl_qs.get("contentId") or dl_qs.get("boutiqueId") or [None])[0]
            if content_id and ("trendyol" in raw.lower() or "ty" in hostname):
                return f"https://www.trendyol.com/p-{content_id}"

        # --- Generic: look for a fallback URL that is a product page ---
        for key in ("adj_fallback", "fallback_url", "af_web_dp", "url", "$fallback_url"):
            raw = (qs.get(key) or [None])[0]
            if raw and not _is_homepage_or_junk_url(raw):
                return normalize_deal_url(raw)

    except Exception as exc:
        logger.debug("Failed to extract product URL from redirect %s: %s", redirect_url, exc)
    return None


def _try_resolve_via_mobile(url: str) -> str | None:
    """Resolve a short/app link by following its redirect chain with a mobile UA.

    Many e-commerce apps use short links (app.hb.biz, ty.gl, etc.) that redirect
    to homepage on desktop but to a deep link with product identifiers on mobile.
    This function captures the mobile redirect and extracts a usable desktop URL.
    """
    import ssl
    from urllib.parse import parse_qs
    try:
        # Step 1: Follow one hop with mobile UA to get the tracking redirect
        req = Request(url, headers={"User-Agent": _MOBILE_USER_AGENT})
        ctx = ssl.create_default_context()
        # Use a custom opener that does NOT auto-follow redirects
        import urllib.request
        class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(
            _NoRedirectHandler,
            urllib.request.HTTPSHandler(context=ctx),
        )
        try:
            resp = opener.open(req, timeout=12)
            location = None
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location")
            resp = e

        if not location:
            location = getattr(resp, "headers", {}).get("Location") if hasattr(resp, "headers") else None

        # If we got a redirect, try to extract product info from it
        if location:
            product_url = _extract_product_url_from_redirect(location)
            if product_url:
                logger.info("Short-link mobile redirect extracted: %s → %s", url, product_url)
                return product_url

        # Step 2: Follow all redirects with mobile UA, read canonical from final page
        req2 = Request(url, headers={"User-Agent": _MOBILE_USER_AGENT})
        with urlopen(req2, timeout=15, context=ctx) as resp2:
            final_url = resp2.url
            if _is_homepage_or_junk_url(final_url):
                return None
            html = resp2.read(500_000).decode("utf-8", errors="replace")

        # Try canonical / OG URL from HTML
        match = _CANONICAL_RE.search(html[:80_000])
        if not match:
            match = _OG_URL_RE.search(html[:80_000])
        if match:
            canonical = match.group(1).strip()
            if canonical and not _is_homepage_or_junk_url(canonical):
                return normalize_deal_url(canonical)

        # Strip m. from the final resolved URL as last resort
        final_parsed = urlparse(final_url)
        final_host = final_parsed.hostname or ""
        if final_host.startswith("m."):
            desktop_host = final_host[2:]
            return normalize_deal_url(urlunparse(final_parsed._replace(
                netloc=desktop_host if not final_parsed.port else f"{desktop_host}:{final_parsed.port}"
            )))
        if not _is_homepage_or_junk_url(final_url):
            return normalize_deal_url(final_url)
    except Exception as exc:
        logger.debug("Mobile short-link fallback failed for %s: %s", url, exc)
    return None


def _is_domain_allowed(url: str, allowed_domains: list[str]) -> bool:
    """Check if URL's hostname ends with one of the allowed domains."""
    if not allowed_domains:
        return True  # No whitelist = allow all
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower().removeprefix("www.")
        return any(hostname == d or hostname.endswith("." + d) for d in allowed_domains)
    except Exception:
        return False


def _get_notification_block_reason(topic: ScrapedTopic, allowed_domains: list[str]) -> str | None:
    link_url = normalize_deal_url(topic.clean_deal_url or topic.deal_url or topic.url)
    if not link_url or _TELEGRAM_URL_RE.match(link_url):
        return "missing-external-link"
    if _is_homepage_or_junk_url(link_url):
        return "storefront-or-listing"

    candidate_title = topic.deal_title or topic.title
    if _is_non_product_title(candidate_title):
        return "non-product-title"

    if not _is_domain_allowed(link_url, allowed_domains):
        return "domain-not-allowed"
    return None


def _is_non_product_title(title: str | None) -> bool:
    """Heuristic filter for generic marketplace/site labels instead of real product names."""
    if not title:
        return True

    raw = _sanitize_outgoing_text(title)
    if not raw:
        return True

    if _is_junk_title(raw):
        return True
    if _is_coupon_or_campaign_title(raw):
        return True
    if _is_discussion_title(raw):
        return True

    lowered = raw.lower().strip(" .,-_:/")
    compact = re.sub(r"[^a-z0-9]", "", lowered)

    # Plain domain or hostname-like title
    if re.fullmatch(r"(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+", lowered):
        return True

    blocked_compact = {
        "n11",
        "trendyol",
        "hepsiburada",
        "amazon",
        "amazoncomtr",
        "mediamarkt",
        "teknosa",
        "vatanbilgisayar",
        "a101",
        "bim",
        "site",
        "website",
        "websitesi",
        "magaza",
        "store",
        "marketplace",
        "kupon",
        "indirim",
        "kampanya",
        "firsat",
        "aramasonuclari",
        "aramasonucu",
    }
    if compact in blocked_compact:
        return True

    words = [w for w in re.split(r"\s+", lowered) if w]
    if len(words) <= 3 and any(w in {"site", "web", "websitesi", "magaza", "store"} for w in words):
        return True

    # Known site slogans / homepage titles
    _BLOCKED_PHRASES = (
        "en cok tavsiye edilen e-ticaret",
        "turkiye'nin en cok tavsiye",
        "arama sonuclari",
        "arama sonucu",
        "search results",
        "ürünleri, indirimleri ve kampanyaları",
        "watch this story",
        "resim yükle",
        "alışverişe devam etmek için",
        "continue shopping",
        "üzgünüz",
    )
    if any(phrase in lowered for phrase in _BLOCKED_PHRASES):
        return True

    return False


async def send_unsent_topic_notifications(db: AsyncSession, batch_size: int = 100) -> int:
    if not telegram_notifier.enabled:
        return 0

    # Load active allowed domains
    domain_rows = (await db.execute(
        select(AllowedDomain.domain).where(AllowedDomain.is_active == True)
    )).scalars().all()
    allowed_domains = [d.lower() for d in domain_rows]

    stmt = (
        select(ScrapedTopic, TargetSite.name.label("site_name"))
        .join(TargetSite, TargetSite.id == ScrapedTopic.site_id)
        .where(ScrapedTopic.notification_sent == False)
        .where(ScrapedTopic.domain_skipped == False)
        .where(ScrapedTopic.is_sticky == False)
        .where(ScrapedTopic.deleted_by_user == False)
        .where(
            or_(
                TargetSite.source_type != "donanimhaber_thread",
                (ScrapedTopic.clean_deal_url.isnot(None)) & (ScrapedTopic.clean_deal_url != ""),
                (ScrapedTopic.deal_url.isnot(None)) & (ScrapedTopic.deal_url != ""),
            )
        )
        .where(
            or_(
                (ScrapedTopic.deal_title.isnot(None)) & (ScrapedTopic.deal_title != ""),
                (ScrapedTopic.deal_price.isnot(None)) & (ScrapedTopic.deal_price != ""),
                (ScrapedTopic.clean_deal_url.isnot(None)) & (ScrapedTopic.clean_deal_url != ""),
                (ScrapedTopic.deal_url.isnot(None)) & (ScrapedTopic.deal_url != ""),
            )
        )
        .order_by(func.coalesce(ScrapedTopic.source_date, ScrapedTopic.scraped_at).asc())
        .limit(batch_size)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        return 0

    sent_count = 0
    changed_count = 0
    for topic, site_name in rows:
        block_reason = _get_notification_block_reason(topic, allowed_domains)
        if block_reason:
            topic.domain_skipped = True
            topic.notification_block_reason = block_reason
            changed_count += 1
            logger.debug("Skipped topic id=%s: notification blocked (%s)", topic.id, block_reason)
            continue

        sent = await telegram_notifier.send_topic(topic, site_name)
        if sent:
            topic.notification_sent = True
            topic.notification_block_reason = None
            sent_count += 1
            changed_count += 1
    if changed_count:
        await db.commit()
    return sent_count


def _clean_page_title(raw_title: str) -> str:
    """Strip common e-commerce suffixes from page titles to get just the product name."""
    import re as _re
    title = raw_title.strip()
    _SUFFIX_PATTERNS = [
        r"\s*[-–—|:]\s*Fiyat[ıi].*$",
        r"\s+Fiyat[ıi].*$",
        r"\s+Özellikleri.*$",
        r"\s+Taksit Seçenekleri.*$",
        r"\s*[-–—|:]\s*Yorumlar[ıi].*$",
        r"\s*[-–—|:]\s*En Ucuz.*$",
        r"\s*[-–—|:]\s*Trendyol.*$",
        r"\s*[-–—|:]\s*Hepsiburada.*$",
        r"\s*[-–—|:]\s*n11\.com.*$",
        r"\s*[-–—|:]\s*Amazon\.com\.tr.*$",
        r"\s*[-–—|:]\s*A101.*$",
        r"\s*[-–—|:]\s*BIM.*$",
        r"\s*[-–—|:]\s*Teknosa.*$",
        r"\s*[-–—|:]\s*MediaMarkt.*$",
        r"\s*[-–—|:]\s*Vatan Bilgisayar.*$",
        r"\s*[-–—|:]\s*Ücretsiz Kargo.*$",
        r"\s*[-–—|]\s*[A-Za-z0-9]+\.[a-z]{2,}.*$",
    ]
    for pattern in _SUFFIX_PATTERNS:
        title = _re.sub(pattern, "", title, flags=_re.IGNORECASE).strip()
    title = _re.sub(r"\s*[-–—|]+\s*$", "", title).strip()
    return normalize_deal_title(title)


def _format_int_with_thousands(value: str) -> str:
    chunks = []
    while value:
        chunks.append(value[-3:])
        value = value[:-3]
    return ".".join(reversed(chunks)) if chunks else "0"


def _is_zero_price_text(value: str | None) -> bool:
    if not value:
        return False
    numeric = value.strip().replace(".", "").replace(",", ".")
    if not numeric:
        return False
    try:
        return float(numeric) == 0.0
    except ValueError:
        return False


def _normalize_price_text(raw_price: str) -> str | None:
    if not raw_price:
        return None
    cleaned = raw_price.strip().replace("\xa0", " ")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"[^0-9,\.]", "", cleaned).strip()
    if not re.search(r"\d", cleaned):
        return None

    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")
    decimal_sep: str | None = None

    if last_comma != -1 and last_dot != -1:
        decimal_sep = "," if last_comma > last_dot else "."
    else:
        sep = "," if last_comma != -1 else "." if last_dot != -1 else None
        if sep:
            if cleaned.count(sep) == 1:
                after = cleaned.split(sep, 1)[1]
                if 1 <= len(after) <= 2:
                    decimal_sep = sep

    if decimal_sep:
        integer_part, decimal_part = cleaned.rsplit(decimal_sep, 1)
        integer_digits = re.sub(r"[^0-9]", "", integer_part)
        decimal_digits = re.sub(r"[^0-9]", "", decimal_part)
        if not integer_digits:
            integer_digits = "0"
        formatted_int = _format_int_with_thousands(integer_digits)
        if decimal_digits:
            decimal_digits = decimal_digits[:2]
            normalized = f"{formatted_int},{decimal_digits}"[:100]
            return None if _is_zero_price_text(normalized) else normalized
        normalized = formatted_int[:100]
        return None if _is_zero_price_text(normalized) else normalized

    integer_digits = re.sub(r"[^0-9]", "", cleaned)
    if not integer_digits:
        return None
    normalized = _format_int_with_thousands(integer_digits)[:100]
    return None if _is_zero_price_text(normalized) else normalized


def _extract_first_product_from_listing(html: str, base_url: str) -> tuple[str | None, str | None, str | None]:
    """For store/listing pages, pick first product card metadata (url, title, price)."""
    product_url_match = re.search(r'"url":"(/[^"\\]*?-p-[^"\\]+)"', html, flags=re.IGNORECASE)
    if not product_url_match:
        return None, None, None

    rel_url = product_url_match.group(1)
    rel_url = rel_url.replace("\\/", "/")
    abs_url = urljoin(base_url, rel_url)

    idx = product_url_match.start()
    window_start = max(0, idx - 4000)
    window = html[window_start: min(len(html), idx + 4000)]
    local_url_pos = idx - window_start

    name_matches = list(re.finditer(r'"name":"([^"\\]+)"', window, flags=re.IGNORECASE))
    raw_name = None
    if name_matches:
        preceding = [m for m in name_matches if m.start() <= local_url_pos]
        chosen_name = preceding[-1] if preceding else name_matches[0]
        raw_name = chosen_name.group(1).replace("\\u0026", "&")

    price_matches = list(re.finditer(r'"price":([0-9]+(?:\.[0-9]+)?)', window, flags=re.IGNORECASE))
    raw_price = None
    if price_matches:
        preceding_prices = [m for m in price_matches if m.start() <= local_url_pos]
        chosen_price = preceding_prices[-1] if preceding_prices else price_matches[0]
        raw_price = chosen_price.group(1)
    price = _normalize_price_text(raw_price) if raw_price else None

    return abs_url, (_clean_page_title(raw_name) if raw_name else None), price


def _extract_price_from_text(text: str) -> str | None:
    """Extract price from any text string (forum title, deal title, etc.)."""
    if not text:
        return None
    # Priority 1: digits followed by TL/₺ (highest confidence)
    patterns = [
        r'(\d[\d.,]*)\s*(?:TL|tl|₺)',
        r'₺\s*(\d[\d.,]*)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            normalized = _normalize_price_text(m.group(1))
            if normalized:
                return normalized

    # Priority 2: bare large numbers (≥5 digits or dot-separated thousands, likely prices)
    # Match: 33500, 44999, 89.999 but NOT 5060, 5070 (model numbers)
    for match in re.finditer(r'(?<!\w)(\d{1,3}(?:[.]\d{3})+|\d{5,6})(?!\w)', text):
        candidate = match.group(1)
        context = text[max(0, match.start() - 8): min(len(text), match.end() + 8)].lower()
        if re.search(r"(?:dpi|hz|khz|mhz|ghz|gb|tb|mb|mah|w|wh|ms|fps|inch|inç|cm)\b", context):
            continue
        normalized = _normalize_price_text(candidate)
        if normalized:
            digits_only = re.sub(r'[^0-9]', '', normalized)
            if digits_only and 500 <= int(digits_only) <= 500000:
                return normalized
    return None


def _to_price_number(value: str | None) -> float | None:
    if not value:
        return None
    numeric = value.strip().replace(".", "").replace(",", ".")
    try:
        return float(numeric)
    except ValueError:
        return None


def _pick_lowest_normalized_price(raw_candidates: list[str]) -> str | None:
    best_value = None
    best_price = None
    for raw in raw_candidates:
        normalized = _normalize_price_text(raw)
        number = _to_price_number(normalized)
        if not normalized or number is None or number <= 0:
            continue
        if best_value is None or number < best_value:
            best_value = number
            best_price = normalized
    return best_price


def _extract_price_from_n11_html(html: str) -> str | None:
    candidates: list[str] = []
    patterns = [
        r'"displayPrice"\s*:\s*"([0-9][0-9\., ]*)\s*TL"',
        r'"discountedPrice"\s*:\s*"([0-9][0-9\., ]*)\s*TL"',
        r'"displayPriceFloat"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"displayPriceNumber"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"disPrice"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',
        r'"productMeta"\s*:\s*\{[^{}]*?"price"\s*:\s*"([0-9]+(?:\.[0-9]+)?)"',
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))
    return _pick_lowest_normalized_price(candidates)


def _extract_price_from_hepsiburada_html(html: str) -> str | None:
    """Extract Hepsiburada price with strict priority: discounted/current > regular/list."""
    # Prefer explicit buybox winner price block when present.
    # On discounted pages non-segmented-price can be lower than finalPriceOnSale,
    # on non-discounted pages they are usually equal.
    buybox_primary_candidates: list[str] = []
    buybox_triplet_pattern = (
        r'buyboxOrder[^0-9]{0,20}([0-9]+)'
        r'.{0,2400}?finalPriceOnSale[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)'
        r'.{0,1800}?non-segmented-price[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)'
    )
    for buybox_order_raw, sale_raw, non_segmented_raw in re.findall(
        buybox_triplet_pattern,
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        if buybox_order_raw != "1":
            continue
        sale_normalized = _normalize_price_text(sale_raw)
        non_segmented_normalized = _normalize_price_text(non_segmented_raw)
        sale_value = _to_price_number(sale_normalized)
        non_segmented_value = _to_price_number(non_segmented_normalized)

        if sale_value is None and non_segmented_value is None:
            continue
        if sale_value is None:
            buybox_primary_candidates.append(non_segmented_raw)
            continue
        if non_segmented_value is None:
            buybox_primary_candidates.append(sale_raw)
            continue

        # If basket (non-segmented) is lower, use it; otherwise use the buybox sale price.
        if 0 < non_segmented_value <= sale_value:
            buybox_primary_candidates.append(non_segmented_raw)
        elif sale_value > 0:
            buybox_primary_candidates.append(sale_raw)

    picked_buybox_primary = _pick_lowest_normalized_price(buybox_primary_candidates)
    if picked_buybox_primary:
        return picked_buybox_primary

    discounted_candidates: list[str] = []
    current_candidates: list[str] = []
    regular_candidates: list[str] = []

    discounted_patterns = [
        r'"name"\s*:\s*"non-segmented-price"\s*,\s*"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"finalPriceOnSale"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"discountedPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"discountedPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"campaignPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"campaignPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
    ]
    current_patterns = [
        r'"finalPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"finalPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"currentPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"currentPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"salePrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"salePrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'data-test-id=["\']price-current-price["\'][^>]*>[^0-9]*([0-9][0-9\., ]*)',
    ]
    regular_patterns = [
        r'"finalPriceOnDisplay"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"originalPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"originalPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"listPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"listPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'"oldPrice"\s*:\s*"([0-9][0-9\., ]*)\s*(?:TL|₺)?"',
        r'"oldPrice"\s*:\s*\{[^{}]*?"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
        r'data-test-id=["\']price-old-price["\'][^>]*>[^0-9]*([0-9][0-9\., ]*)',
    ]

    for pattern in discounted_patterns:
        discounted_candidates.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))
    for pattern in current_patterns:
        current_candidates.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))
    for pattern in regular_patterns:
        regular_candidates.extend(re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL))

    # Business rule: prefer discounted price when present, then current/final price,
    # and only then fallback to original/list/old price.
    for candidates in (discounted_candidates, current_candidates, regular_candidates):
        picked = _pick_lowest_normalized_price(candidates)
        if picked:
            return picked

    return None


def _extract_price_from_amazon_html(html: str) -> str | None:
    """Extract Amazon buybox/current price with strict priority.

    We intentionally avoid generic first-price matches because Amazon pages contain
    many unrelated prices (variant cards, alternative offers, accessories).
    """
    # 1) Main core price block on desktop/mobile layouts.
    core_blocks: list[str] = []
    for match in re.finditer(r'id=["\']corePrice[^"\']*["\']', html, flags=re.IGNORECASE):
        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 12000)
        core_blocks.append(html[start:end])
    installment_markers = (
        "taksit",
        "aylık",
        "aylik",
        "/ay",
        " ay ",
        "aya varan",
        "monthly",
        "per month",
        "month",
    )

    def _filtered_block_prices(block: str) -> list[str]:
        values: list[str] = []
        for m in re.finditer(
            r'<span[^>]*class=["\'][^"\']*a-offscreen[^"\']*["\'][^>]*>\s*([0-9][0-9\., ]*)\s*(?:TL|₺)?\s*</span>',
            block,
            flags=re.IGNORECASE,
        ):
            context = block[max(0, m.start() - 220): min(len(block), m.end() + 220)].lower()
            if any(marker in context for marker in installment_markers):
                continue
            values.append(m.group(1))
        return values

    for block in core_blocks:
        candidates = _filtered_block_prices(block)
        picked = _pick_lowest_normalized_price(candidates)
        if picked:
            return picked

    # 2) Price-to-pay accessibility label used in modern Amazon DOM.
    price_to_pay_labels = re.findall(
        r'id=["\']apex-pricetopay-accessibility-label["\'][^>]*>\s*([0-9][0-9\., ]*)\s*(?:TL|₺)?\s*<',
        html,
        flags=re.IGNORECASE,
    )
    picked_price_to_pay = _pick_lowest_normalized_price(price_to_pay_labels)
    if picked_price_to_pay:
        return picked_price_to_pay

    # 3) Legacy ids still appear on some products.
    legacy_patterns = [
        r'id=["\']priceblock_ourprice["\'][^>]*>\s*([0-9][0-9\., ]*)\s*(?:TL|₺)?\s*<',
        r'id=["\']price_inside_buybox["\'][^>]*>\s*([0-9][0-9\., ]*)\s*(?:TL|₺)?\s*<',
        r'id=["\']priceblock_dealprice["\'][^>]*>\s*([0-9][0-9\., ]*)\s*(?:TL|₺)?\s*<',
    ]
    for pattern in legacy_patterns:
        values = re.findall(pattern, html, flags=re.IGNORECASE)
        picked = _pick_lowest_normalized_price(values)
        if picked:
            return picked

    # 4) Fallback: pick first visible offscreen price inside buybox-ish blocks.
    fallback_blocks = re.findall(
        r'(?:buybox|apex)[\s\S]{0,8000}',
        html,
        flags=re.IGNORECASE,
    )
    for block in fallback_blocks:
        values = _filtered_block_prices(block)
        picked = _pick_lowest_normalized_price(values)
        if picked:
            return picked

    return None


def _extract_price_from_vatan_html(html: str) -> str | None:
    """Extract Vatan product price and ignore installment row amounts."""
    product_price_candidates = re.findall(
        r'"productPrice"\s*:\s*"?([0-9][0-9\.,]*)"?', html, flags=re.IGNORECASE
    )

    data_price_candidates = re.findall(
        r'data-price="([0-9][0-9\.,]*)"', html, flags=re.IGNORECASE
    )

    visible_price_candidates = re.findall(
        r'class="[^"]*(?:product-list__price|product-list__price-value|price)[^"]*"[^>]*>\s*([0-9][0-9\., ]*)',
        html,
        flags=re.IGNORECASE,
    )

    # Filter out obvious installment context (e.g. "2 x 12.998,00 TL").
    def _filter_installment(values: list[str]) -> list[str]:
        filtered_values: list[str] = []
        for value in values:
            pattern = re.escape(value)
            match = re.search(pattern, html, flags=re.IGNORECASE)
            if match:
                context = html[max(0, match.start() - 180): min(len(html), match.end() + 180)].lower()
                if any(marker in context for marker in ("taksit", "x ", " x", "aylık", "aylik", "toplam tutar")):
                    continue
            filtered_values.append(value)
        return filtered_values

    # Strict priority: productPrice json -> data-price on detail actions -> visible price blocks.
    for group in (
        _filter_installment(product_price_candidates),
        _filter_installment(data_price_candidates),
        _filter_installment(visible_price_candidates),
    ):
        if not group:
            continue
        picked = _pick_lowest_normalized_price(group)
        if picked:
            return picked

    # Final fallback if all filters removed candidates.
    for group in (product_price_candidates, data_price_candidates, visible_price_candidates):
        if not group:
            continue
        picked = _pick_lowest_normalized_price(group)
        if picked:
            return picked

    return None


def _extract_price_from_html(html: str, page_url: str | None = None) -> str | None:
    hostname = (urlparse(page_url).hostname or "").lower() if page_url else ""
    if "n11.com" in hostname:
        n11_price = _extract_price_from_n11_html(html)
        if n11_price:
            return n11_price

    if "vatanbilgisayar.com" in hostname:
        vatan_price = _extract_price_from_vatan_html(html)
        if vatan_price:
            return vatan_price

    if "amazon." in hostname:
        amazon_price = _extract_price_from_amazon_html(html)
        if amazon_price:
            return amazon_price

    if "hepsiburada.com" in hostname:
        hepsiburada_price = _extract_price_from_hepsiburada_html(html)
        if hepsiburada_price:
            return hepsiburada_price

    # Trendyol datalayer: product_discounted_price is the most accurate (actual checkout price)
    m = re.search(r'"product_discounted_price"\s*:\s*([0-9]+(?:\.[0-9]+)?)', html)
    if m:
        normalized = _normalize_price_text(m.group(1))
        if normalized:
            return normalized
    # Trendyol uses {"value":NNN} objects — fallback to discounted/selling price
    for key in ("discountedPrice", "sellingPrice"):
        m = re.search(rf'"{key}"\s*:\s*\{{\s*"value"\s*:\s*([0-9]+(?:\.[0-9]+)?)', html)
        if m:
            normalized = _normalize_price_text(m.group(1))
            if normalized:
                return normalized

    patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'"price"\s*:\s*"([0-9][0-9\.,]*)"',
        r'₺\s*([0-9][0-9\.,]*)',
        r'([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*(?:TL|₺)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1) if match.groups() else match.group(0)
        normalized = _normalize_price_text(candidate)
        if normalized:
            return normalized
    return None


def _is_out_of_stock_page(html: str, page_url: str | None = None) -> bool:
    """Detect clear out-of-stock pages for supported stores.

    This currently targets Amazon, where product pages can keep showing historical
    price-like values even when the item is not purchasable.
    """
    if not html or not page_url:
        return False

    hostname = (urlparse(page_url).hostname or "").lower()
    if "amazon." not in hostname:
        return False

    # Ignore script blobs while checking phrases; Amazon embeds translation maps
    # that may contain "mevcut değil" even for purchasable variants.
    no_script_html = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
    haystack = no_script_html.lower()

    has_real_purchase_cta = any(
        re.search(pattern, haystack, flags=re.IGNORECASE)
        for pattern in (
            r"<input[^>]+id=[\"']add-to-cart-button[\"']",
            r"<input[^>]+name=[\"']submit\.add-to-cart[\"']",
            r"<button[^>]+id=[\"']add-to-cart-button[\"']",
            r"<input[^>]+id=[\"']buy-now-button[\"']",
            r"<button[^>]+id=[\"']buy-now-button[\"']",
        )
    )

    unavailable_markers = (
        "currently unavailable",
        "temporarily out of stock",
        "this item is currently unavailable",
        "stokta yok",
        "gecici olarak stokta yok",
        "şu anda mevcut değil",
        "su anda mevcut degil",
    )
    has_unavailable_phrase = any(marker in haystack for marker in unavailable_markers)

    # Conservative rule for tracking accuracy:
    # if there is no real purchasable CTA in buybox, treat as unavailable.
    if not has_real_purchase_cta:
        return True

    # If both real CTA and unavailability phrase coexist, trust CTA.
    return has_unavailable_phrase and not has_real_purchase_cta


def _generate_with_ai(prompt: str, max_tokens: int = 60) -> str | None:
    """Generate text via OpenRouter API. Returns None if not configured."""
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-27b-it:free").strip()
    if not api_key:
        return None
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    import time
    for attempt in range(3):
        req = Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = content.strip().strip('"').strip("'")
            return result[:500] if result else None
        except Exception as exc:
            if "429" in str(exc) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            logger.debug("AI generation failed: %s", exc)
            return None
    return None


def _extract_price_with_ai(raw_title: str | None, html: str) -> str | None:
    """Use AI to infer product price when regex-based extraction fails."""
    try:
        signals = re.findall(
            r'(?:₺\s*[0-9][0-9\.,]*|[0-9][0-9\.,]*\s*(?:TL|tl)|"price"\s*:\s*"?[0-9][0-9\.,]*"?)',
            html,
            flags=re.IGNORECASE,
        )
        compact_signals = "\n".join(signals[:40]) if signals else ""
        prompt = (
            "Aşağıdaki metinden ürün fiyatını bul. "
            "Sadece fiyat değerini yaz (örnek: 14999,90). "
            "Eğer fiyat yoksa sadece YOK yaz.\n\n"
            f"Başlık: {raw_title or '-'}\n"
            f"Fiyat sinyalleri:\n{compact_signals or '-'}"
        )
        result = _generate_with_ai(prompt, max_tokens=20)
        if not result or result.upper() == "YOK":
            return None
        return _normalize_price_text(result)
    except Exception as exc:
        logger.debug("AI price extraction failed: %s", exc)
        return None


def _fetch_page_metadata(
    url: str,
    source_title: str | None = None,
    _depth: int = 0,
) -> tuple[str | None, str | None, str | None]:
    """Fetch a URL and extract cleaned page title, price and canonical/deep product URL."""
    import re as _re
    _TITLE_RE = _re.compile(r"<title[^>]*>(.*?)</title>", _re.IGNORECASE | _re.DOTALL)
    try:
        page = Fetcher.get(url, timeout=25)
        html = page.html_content or page.body or ""
        if isinstance(html, bytes):
            html = html.decode(page.encoding or "utf-8", errors="replace")
        if not isinstance(html, str) or not html.strip():
            return None, None, normalize_deal_url(url)

        final_url = str(getattr(page, "url", "") or url)

        # If the redirect landed on a homepage or search page, treat as failed resolution
        if _is_homepage_or_junk_url(final_url):
            logger.debug("Short link %s resolved to homepage/junk: %s", url, final_url)
            # Fallback: try fetching the mobile version to extract canonical URL
            if _depth == 0:
                canonical = _try_resolve_via_mobile(url)
                if canonical:
                    logger.info("Mobile fallback resolved %s → %s", url, canonical)
                    return _fetch_page_metadata(canonical, source_title=source_title, _depth=1)
            return None, None, None

        is_out_of_stock = _is_out_of_stock_page(html, final_url)
        if is_out_of_stock:
            logger.info("Out-of-stock page detected for %s", final_url)

        price = None if is_out_of_stock else _extract_price_from_html(html, final_url)
        match = _TITLE_RE.search(html)
        if match:
            from html import unescape
            title = unescape(match.group(1)).strip()
            # Reject Cloudflare/bot-challenge placeholder titles
            if title and _is_junk_title(title):
                logger.debug("Junk title detected for %s: %r", url, title)
                return None, None, normalize_deal_url(final_url)
            title = _clean_page_title(title)
            if source_title and (_is_coupon_or_campaign_title(source_title) or _is_discussion_title(source_title)):
                if _is_non_product_title(title) or _is_homepage_or_junk_url(final_url):
                    return None, None, normalize_deal_url(final_url)
            if not price and not is_out_of_stock:
                price = _extract_price_with_ai(title, html)
            if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", title or ""):
                return None, price, normalize_deal_url(final_url)
            return (title[:500] if title else None), price, normalize_deal_url(final_url)
    except Exception as exc:
        logger.debug("Failed to fetch title from %s: %s", url, exc)
    return None, None, normalize_deal_url(url)


def _extract_title_with_ai(raw_title: str) -> str | None:
    """Use AI to extract a clean product name from a messy page title."""
    try:
        prompt = (
            "Sadece ürün adını yaz. "
            "Fiyat, yorum, site adı, kampanya metni, kargo bilgisini çıkar. "
            "Cevap tek satır olsun ve ürün adını eksiksiz yaz, kısaltma yapma.\n\n"
            f"Başlık: {raw_title}"
        )
        return _generate_with_ai(prompt, max_tokens=60)
    except Exception as exc:
        logger.debug("AI title extraction failed: %s", exc)
        return None


def _pick_best_title(raw_title: str, ai_title: str | None) -> str:
    if not ai_title:
        return raw_title
    cleaned_ai = _sanitize_outgoing_text(ai_title)
    if not cleaned_ai:
        return raw_title
    # Reject AI hallucinations / refusals
    lower = cleaned_ai.lower()
    if any(phrase in lower for phrase in (
        "bu bir başlık", "ürün adı içermiyor", "ürün adı bulunamadı",
        "başlık yok", "ürün bulunamadı", "bir başlık değil",
        "içermiyor", "bulunamadı", "bilgi yok",
        "lütfen bana ürün adını içeren metni verin",
        "ürün adını içeren metni verin",
    )):
        return raw_title
    raw_words = raw_title.split()
    ai_words = cleaned_ai.split()
    if ai_words and ai_words[-1].lower() in {"ve", "veya", "ile", "&"}:
        return raw_title
    if len(ai_words) < max(3, int(len(raw_words) * 0.7)):
        return raw_title
    return cleaned_ai


def _should_replace_title(existing_title: str | None, candidate_title: str | None) -> bool:
    candidate = _sanitize_outgoing_text(candidate_title)
    if not candidate or _is_non_product_title(candidate):
        return False
    existing = _sanitize_outgoing_text(existing_title)
    if not existing:
        return True
    if existing.lower() == candidate.lower():
        return False
    if _is_junk_title(existing) or _is_non_product_title(existing):
        return True
    return False


async def build_deal_metadata_for_new_record(
    deal_url: str,
    source_title: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Build deal metadata (title, price, final link) for newly created records only."""
    if not deal_url:
        return None, None, None
    url = normalize_deal_url(deal_url)
    found_title, found_price, resolved_url = await asyncio.to_thread(
        _fetch_page_metadata,
        url,
        source_title,
    )
    if found_title and (_is_junk_title(found_title) or _is_non_product_title(found_title)):
        found_title = None
    if found_price and _is_zero_price_text(found_price):
        found_price = None
    if source_title and (_is_coupon_or_campaign_title(source_title) or _is_discussion_title(source_title)):
        if not found_title or _is_non_product_title(found_title):
            found_price = None
    if not found_title:
        return None, found_price, resolved_url
    ai_title = await asyncio.to_thread(_extract_title_with_ai, found_title)
    return _pick_best_title(found_title, ai_title), found_price, resolved_url


async def fill_missing_deal_data(db: AsyncSession, batch_size: int = 10) -> int:
    """Fill missing deal_title, deal_price, and resolve unresolved short URLs.

    Picks up topics that have any of:
    - No deal_title or a junk/Cloudflare title
    - No deal_price (but title exists in forum post or deal_title)
    - Unresolved short URLs (app.hb.biz, ty.gl, etc.) in clean_deal_url
    """
    enhanced_mode = _ai_enhanced_mode_enabled()
    enhanced_cutoff = datetime.utcnow() - timedelta(hours=_ai_enhanced_lookback_hours())

    missing_or_junk_filter = or_(
        # Missing or junk deal_title
        ScrapedTopic.deal_title.is_(None),
        ScrapedTopic.deal_title == "",
        ScrapedTopic.deal_title.like("Just a moment%"),
        ScrapedTopic.deal_title.like("Attention Required%"),
        ScrapedTopic.deal_title.like("Access Denied%"),
        ScrapedTopic.deal_title.like("%503%"),
        ScrapedTopic.deal_title.ilike("%service unavailable%"),
        ScrapedTopic.deal_title.ilike("%hizmet kullanılamıyor%"),
        ScrapedTopic.deal_title.like("Bu bir başlık%"),
        ScrapedTopic.deal_title.ilike("%watch this story%"),
        ScrapedTopic.deal_title.ilike("%resim yükle%"),
        ScrapedTopic.deal_title.ilike("%ürünleri, indirimleri ve kampanyaları%"),
        # Missing deal_price
        ScrapedTopic.deal_price.is_(None),
        ScrapedTopic.deal_price == "",
        ScrapedTopic.deal_price == "0",
        ScrapedTopic.deal_price == "0,0",
        ScrapedTopic.deal_price == "0,00",
    )

    review_filter = missing_or_junk_filter
    if enhanced_mode:
        review_filter = or_(
            missing_or_junk_filter,
            and_(
                ScrapedTopic.notification_sent == False,
                ScrapedTopic.scraped_at >= enhanced_cutoff,
            ),
        )

    stmt = (
        select(ScrapedTopic)
        .where(ScrapedTopic.deal_url.isnot(None))
        .where(ScrapedTopic.deal_url != "")
        .where(ScrapedTopic.domain_skipped == False)
        .where(review_filter)
        .where(ScrapedTopic.is_sticky == False)
        .where(ScrapedTopic.deleted_by_user == False)
        .order_by(ScrapedTopic.id.desc())
        .limit(batch_size)
    )
    topics = (await db.execute(stmt)).scalars().all()
    if not topics:
        return 0

    has_ai = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
    if enhanced_mode and has_ai:
        logger.info(
            "fill_missing_deal_data: AI enhanced mode enabled (lookback=%sh, batch=%s)",
            _ai_enhanced_lookback_hours(),
            batch_size,
        )
    ai_failed = False

    fixed = 0
    for topic in topics:
        changed = False

        # Clear known junk titles so we re-attempt
        if topic.deal_title and (_is_junk_title(topic.deal_title) or _is_non_product_title(topic.deal_title)):
            topic.deal_title = None
            changed = True
        if topic.deal_price and _is_zero_price_text(topic.deal_price):
            topic.deal_price = None
            changed = True

        needs_title = not (topic.deal_title or "").strip()
        needs_price = not (topic.deal_price or "").strip()
        needs_url = _is_unresolved_short_url(topic.clean_deal_url or "")

        # Skip if nothing to do
        if not needs_title and not needs_price and not needs_url:
            if changed:
                fixed += 1
            continue

        force_ai_review = enhanced_mode and has_ai and not ai_failed

        # Attempt page fetch for missing fields, URL resolution, or enhanced AI review.
        if needs_title or needs_url or force_ai_review:
            url = normalize_deal_url(topic.deal_url)
            found_title, found_price, resolved_url = await asyncio.to_thread(
                _fetch_page_metadata, url, topic.title
            )

            # Update clean_deal_url if we resolved a better desktop URL
            if resolved_url:
                new_clean = normalize_deal_url(resolved_url)
                if new_clean != topic.clean_deal_url:
                    topic.clean_deal_url = new_clean
                    changed = True

            # Update price from HTML
            if found_price and needs_price:
                topic.deal_price = found_price
                needs_price = False
                changed = True

            # Update title
            if found_title and (needs_title or force_ai_review):
                selected_title = found_title
                if has_ai and not ai_failed:
                    ai_title = await asyncio.to_thread(_extract_title_with_ai, found_title)
                    if ai_title:
                        selected_title = _pick_best_title(found_title, ai_title)
                    else:
                        ai_failed = True

                if _should_replace_title(topic.deal_title, selected_title):
                    topic.deal_title = selected_title
                    changed = True
                needs_title = not bool((topic.deal_title or "").strip())

        # Fallback: use forum title if we still have no deal_title
        if needs_title and topic.title:
            topic.deal_title = topic.title
            changed = True

        # Fallback: extract price from forum title or deal_title
        if needs_price:
            price_source = topic.title or topic.deal_title or ""
            text_price = _extract_price_from_text(price_source) if _can_use_title_price_fallback(price_source) else None
            if text_price:
                topic.deal_price = text_price
                changed = True

        if changed:
            fixed += 1

    if fixed:
        await db.commit()
        logger.info("fill_missing_deal_data: fixed %d/%d topics", fixed, len(topics))
    return fixed


def _is_unresolved_short_url(url: str) -> bool:
    """Return True if the URL is a known mobile short-link that should be resolved."""
    if not url:
        return False
    try:
        host = urlparse(url).hostname or ""
        return any(s in host for s in (
            "app.hb.biz", "ty.gl", "sl.n11", "amzn.eu", "amzn.to",
            "adj.st", "adjust.com", "go.link", "branch.io",
        ))
    except Exception:
        return False
