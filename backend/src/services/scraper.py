import logging
import re
from html import unescape
from datetime import datetime
from datetime import timedelta, timezone
from urllib.request import Request, urlopen
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse, unquote
from zoneinfo import ZoneInfo

from scrapling import Fetcher
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from src.models.domain import TargetSite, ScrapedTopic
from src.services.notifier import (
    normalize_deal_url,
    build_deal_metadata_for_new_record,
    _can_use_title_price_fallback,
    _extract_price_from_text,
    _is_coupon_or_campaign_title,
    _is_discussion_title,
    _is_non_product_title,
)

logger = logging.getLogger(__name__)
TOPIC_ID_REGEX = re.compile(r"\.(\d+)(?:/)?$")
DH_THREAD_PATH_REGEX = re.compile(r"^(?P<base>.+--\d+)(?:-(?P<page>\d+))?$")
DH_MAX_PAGE_REGEX = re.compile(r'data-max-page="(\d+)"')
DH_MESSAGE_ID_FROM_URL_REGEX = re.compile(r"#(\d{6,})")
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
TR_MONTHS = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}
TR_CHAR_MAP = str.maketrans("cCcgGiIoOsSuU", "cCcgGiIoOsSuU")
TR_CHAR_MAP.update(str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU"))


class ScraperService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def run_all_sites(self):
        """Scrape all active web sites"""
        result = await self.db.execute(
            select(TargetSite).where(
                TargetSite.is_active == True,
                TargetSite.source_type.in_(["web", "donanimhaber_thread"]),
            )
        )
        active_sites = result.scalars().all()
        logger.info(f"Starting scrape for {len(active_sites)} active sites.")

        for site in active_sites:
            try:
                await self.scrape_site(site)
            except Exception:
                logger.exception("Error scraping %s", site.name)

    async def scrape_site(self, site: TargetSite):
        """Fetch page and extract topics using configured CSS selectors"""
        if site.source_type == "donanimhaber_thread" or self._should_use_donanimhaber_thread_mode(site):
            await self.scrape_donanimhaber_thread(site)
            return

        site_name = site.name
        site_url = site.url
        fetch_url = self._normalized_listing_url(site_url)
        logger.info("Scraping %s at %s", site_name, fetch_url)
        site_topics = (
            await self.db.execute(
                select(ScrapedTopic).where(ScrapedTopic.site_id == site.id)
            )
        ).scalars().all()
        site_topic_by_url = {topic.url: topic for topic in site_topics}

        page = Fetcher.get(fetch_url, timeout=20)
        topic_nodes = page.css(site.topic_list_selector)
        logger.info("Found %s nodes on %s", len(topic_nodes), site_name)
        inserted_count = 0
        updated_count = 0
        run_started_at = datetime.utcnow()

        for idx, node in enumerate(topic_nodes):
            try:
                link_nodes = node.css(site.link_selector)
                link_node = self._pick_topic_link_node(link_nodes)
                title_nodes = node.css(site.title_selector)
                title_node = self._pick_title_node(title_nodes, link_node)

                if not title_node or not link_node:
                    continue

                title = title_node.text.strip()
                url = link_node.attrib.get("href", "")

                if not title or not url:
                    continue

                if url.startswith("#") or url.startswith("javascript:"):
                    continue

                url = urljoin(site_url, url)
                is_sticky = self._is_sticky_topic(node)
                observed_at = run_started_at - timedelta(microseconds=idx)

                source_date = self._extract_source_date(node, site.date_selector)
                if not source_date:
                    source_date = datetime.utcnow()
                is_future_date = source_date > datetime.utcnow() + timedelta(days=1)

                source_topic_id = None
                match = TOPIC_ID_REGEX.search(url)
                if match:
                    source_topic_id = match.group(1)

                existing_topic = site_topic_by_url.get(url)
                if existing_topic:
                    if existing_topic.deleted_by_user:
                        continue
                    changed = False
                    if (
                        not is_future_date
                        and (
                            existing_topic.source_date is None
                            or source_date < existing_topic.source_date
                        )
                    ):
                        existing_topic.source_date = source_date
                        changed = True
                    if source_topic_id and existing_topic.source_topic_id != source_topic_id:
                        existing_topic.source_topic_id = source_topic_id
                        changed = True
                    if existing_topic.is_sticky != is_sticky:
                        existing_topic.is_sticky = is_sticky
                        changed = True
                    if existing_topic.scraped_at != observed_at:
                        existing_topic.scraped_at = observed_at
                        changed = True
                    if changed:
                        updated_count += 1
                    continue

                if is_future_date:
                    continue

                topic = ScrapedTopic(
                    site_id=site.id,
                    title=title,
                    url=url,
                    source_topic_id=source_topic_id,
                    is_sticky=is_sticky,
                    notification_sent=False,
                    source_date=source_date,
                    scraped_at=observed_at,
                )
                deal_url = self._extract_deal_url(url, site_url)
                if deal_url:
                    cleaned_deal_url = normalize_deal_url(deal_url)
                    deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                        cleaned_deal_url,
                        title,
                    )
                    topic.deal_url = deal_url
                    topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url)
                    topic.deal_title = deal_title
                    topic.deal_price = deal_price
                    # Fallback: extract price from forum title if page didn't have one
                    if not deal_price and _can_use_title_price_fallback(title):
                        topic.deal_price = _extract_price_from_text(title)
                elif _is_discussion_title(title):
                    continue

                if (
                    (_is_coupon_or_campaign_title(title) or _is_discussion_title(title))
                    and not (topic.deal_url or topic.clean_deal_url)
                    and not topic.deal_title
                    and not topic.deal_price
                ):
                    continue
                self.db.add(topic)
                site_topic_by_url[url] = topic
                inserted_count += 1
            except Exception as e:
                logger.debug("Failed node on %s: %s", site_name, e)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.warning("Commit conflict while saving topics for %s", site_name)
        else:
            logger.info(
                "Saved %s new topics and updated %s topics for %s",
                inserted_count,
                updated_count,
                site_name,
            )

    @staticmethod
    def _looks_like_donanimhaber_thread_url(url: str) -> bool:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        if "donanimhaber.com" not in host:
            return False
        path = (parsed.path or "").rstrip("/")
        return bool(DH_THREAD_PATH_REGEX.match(path))

    def _should_use_donanimhaber_thread_mode(self, site: TargetSite) -> bool:
        if site.source_type != "web":
            return False
        if not self._looks_like_donanimhaber_thread_url(site.url):
            return False
        selectors = (
            (site.topic_list_selector or "").strip(),
            (site.title_selector or "").strip(),
            (site.link_selector or "").strip(),
        )
        return not any(selectors)

    async def scrape_donanimhaber_thread(self, site: TargetSite):
        """Scrape only the latest page of a DonanimHaber topic and import latest posts."""
        site_name = site.name
        configured_url = (site.url or "").strip()
        base_thread_url = self._normalize_donanimhaber_thread_url(configured_url)
        fetch_limit = self._parse_post_limit(configured_url)

        if not base_thread_url:
            logger.warning("Invalid DonanimHaber thread URL for site %s", site_name)
            return

        logger.info(
            "Scraping DonanimHaber thread %s at %s (latest %s posts)",
            site_name,
            base_thread_url,
            fetch_limit,
        )

        site_topics = (
            await self.db.execute(
                select(ScrapedTopic).where(ScrapedTopic.site_id == site.id)
            )
        ).scalars().all()
        site_topic_by_url = {topic.url: topic for topic in site_topics}

        first_page = Fetcher.get(base_thread_url, timeout=20)
        first_html = self._node_html(first_page)
        max_page = self._extract_donanimhaber_max_page(first_html)
        last_page_url = self._build_donanimhaber_page_url(base_thread_url, max_page)

        page = first_page if last_page_url == base_thread_url else Fetcher.get(last_page_url, timeout=20)
        post_nodes = page.css("div[id^='message_']")
        parsed_posts: list[dict[str, str]] = []
        if post_nodes:
            selected_nodes = post_nodes[-fetch_limit:]
            site_domain = (urlparse(base_thread_url).hostname or "").lower()
            for node in selected_nodes:
                message_id = (node.attrib.get("id") or "").removeprefix("message_").strip()
                if not message_id:
                    continue

                raw_text = " ".join((node.text or "").split())
                if not raw_text:
                    raw_text = self._extract_donanimhaber_message_text(node)
                if not raw_text:
                    continue

                deal_url = self._extract_first_external_link_from_message_node(node, site_domain)
                if not deal_url:
                    continue

                parsed_posts.append(
                    {
                        "message_id": message_id,
                        "title": raw_text[:500],
                        "deal_url": deal_url,
                        "post_url": f"{last_page_url}#{message_id}",
                    }
                )
        else:
            if not self._is_donanimhaber_captcha_page(first_html):
                logger.warning("No post nodes found for DonanimHaber thread %s", last_page_url)
                return

            logger.warning(
                "DonanimHaber captcha challenge detected on %s, switching to markdown fallback",
                base_thread_url,
            )
            fallback_page_url, parsed_posts = self._extract_donanimhaber_posts_via_markdown_fallback(
                base_thread_url,
                fetch_limit,
            )
            if fallback_page_url:
                last_page_url = fallback_page_url

            page_match = re.search(r"-(\d+)$", urlparse(last_page_url).path or "")
            if page_match:
                max_page = int(page_match.group(1))

        if not parsed_posts:
            logger.warning("No parseable DonanimHaber posts found for %s", last_page_url)
            return

        inserted_count = 0
        updated_count = 0
        run_started_at = datetime.utcnow()

        for idx, parsed_post in enumerate(parsed_posts):
            try:
                message_id = parsed_post["message_id"]
                title = parsed_post["title"]
                post_url = parsed_post["post_url"]
                observed_at = run_started_at - timedelta(microseconds=idx)
                source_date = observed_at

                deal_url = parsed_post["deal_url"]

                existing_topic = site_topic_by_url.get(post_url)
                if existing_topic:
                    if existing_topic.deleted_by_user:
                        continue

                    changed = False
                    if existing_topic.title != title:
                        existing_topic.title = title
                        changed = True
                    if existing_topic.source_topic_id != message_id:
                        existing_topic.source_topic_id = message_id
                        changed = True
                    if existing_topic.scraped_at != observed_at:
                        existing_topic.scraped_at = observed_at
                        changed = True
                    if deal_url and existing_topic.deal_url != deal_url:
                        existing_topic.deal_url = deal_url
                        changed = True
                    if changed:
                        updated_count += 1
                    continue

                topic = ScrapedTopic(
                    site_id=site.id,
                    title=title,
                    url=post_url,
                    source_topic_id=message_id,
                    is_sticky=False,
                    notification_sent=False,
                    source_date=source_date,
                    scraped_at=observed_at,
                )

                if deal_url:
                    cleaned_deal_url = normalize_deal_url(deal_url)
                    deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                        cleaned_deal_url,
                        title,
                    )
                    topic.deal_url = deal_url
                    topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url)
                    topic.deal_title = deal_title
                    topic.deal_price = deal_price
                    if not deal_price and _can_use_title_price_fallback(title):
                        topic.deal_price = _extract_price_from_text(title)
                elif _can_use_title_price_fallback(title):
                    topic.deal_price = _extract_price_from_text(title)

                if (
                    (_is_coupon_or_campaign_title(title) or _is_discussion_title(title))
                    and not (topic.deal_url or topic.clean_deal_url)
                    and not topic.deal_title
                    and not topic.deal_price
                ):
                    continue

                self.db.add(topic)
                site_topic_by_url[post_url] = topic
                inserted_count += 1
            except Exception as exc:
                logger.debug("Failed DonanimHaber post parse on %s: %s", site_name, exc)

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            logger.warning("Commit conflict while saving DonanimHaber posts for %s", site_name)
        else:
            logger.info(
                "Saved %s new posts and updated %s posts for %s (page %s)",
                inserted_count,
                updated_count,
                site_name,
                max_page,
            )

    @staticmethod
    def _is_donanimhaber_captcha_page(page_html: str) -> bool:
        lowered = (page_html or "").lower()
        return (
            "validatecaptcha" in lowered
            or "g-recaptcha" in lowered
            or "api2/globalapi/sessioninsert" in lowered
        )

    @staticmethod
    def _build_jina_proxy_url(target_url: str) -> str:
        normalized = target_url.strip()
        if normalized.startswith("https://"):
            normalized = normalized.removeprefix("https://")
        elif normalized.startswith("http://"):
            normalized = normalized.removeprefix("http://")
        return f"https://r.jina.ai/http://{normalized}"

    @staticmethod
    def _fetch_text_url(url: str, timeout: int = 30) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            },
        )
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
        return body.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_donanimhaber_max_page_from_markdown(markdown: str, base_thread_url: str) -> int:
        parsed = urlparse(base_thread_url)
        base_path = (parsed.path or "").rstrip("/")
        if not base_path:
            return 1
        matches = [
            int(value)
            for value in re.findall(rf"{re.escape(base_path)}-(\d+)", markdown or "")
            if value.isdigit()
        ]
        return max(matches) if matches else 1

    @classmethod
    def _extract_donanimhaber_posts_from_markdown(
        cls,
        markdown: str,
        last_page_url: str,
        site_domain: str,
        fetch_limit: int,
    ) -> list[dict[str, str]]:
        occurrences: list[tuple[int, str]] = []
        for match in DH_MESSAGE_ID_FROM_URL_REGEX.finditer(markdown or ""):
            occurrences.append((match.start(), match.group(1)))

        ordered: list[tuple[int, str]] = []
        seen_ids: set[str] = set()
        for position, message_id in occurrences:
            if message_id in seen_ids:
                continue
            seen_ids.add(message_id)
            ordered.append((position, message_id))

        if not ordered:
            return []

        posts: list[dict[str, str]] = []
        for idx, (position, message_id) in enumerate(ordered):
            end = ordered[idx + 1][0] if idx + 1 < len(ordered) else len(markdown)
            block = markdown[position:end]
            deal_url = cls._extract_first_external_link_from_markdown_block(block, site_domain)
            if not deal_url:
                continue

            title = cls._extract_markdown_post_title(block, message_id)
            posts.append(
                {
                    "message_id": message_id,
                    "title": title,
                    "deal_url": deal_url,
                    "post_url": f"{last_page_url}#{message_id}",
                }
            )

        return posts[-fetch_limit:]

    @staticmethod
    def _extract_first_external_link_from_markdown_block(block: str, site_domain: str) -> str | None:
        blocked_host_fragments = (
            "donanimhaber.com",
            "google.com",
            "gstatic.com",
            "virgul.com",
        )
        image_suffixes = (
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
        )

        for raw_url in re.findall(r"https?://[^\s\)\]\"']+", block or ""):
            parsed = urlparse(raw_url)
            hostname = (parsed.hostname or "").lower()
            if not hostname:
                continue
            if hostname.endswith(site_domain):
                continue
            if any(fragment in hostname for fragment in blocked_host_fragments):
                continue
            if parsed.path.lower().endswith(image_suffixes):
                continue
            return raw_url
        return None

    @staticmethod
    def _extract_markdown_post_title(block: str, message_id: str) -> str:
        text = block or ""
        text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", text)
        text = re.sub(r"\[[^\]]*\]\([^\)]*\)", " ", text)
        text = re.sub(r"https?://\S+", " ", text)
        text = re.sub(r"\b(Bug[uü]n|D[uü]n)\s+\d{1,2}:\d{2}:\d{2}\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(Mesaj Linkini Kopyala|Sikayet|Şikayet|Reklam)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"[`*_>#\-]+", " ", text)
        text = " ".join(text.split())
        if not text:
            return f"DonanimHaber mesaj {message_id}"
        return text[:500]

    def _extract_donanimhaber_posts_via_markdown_fallback(
        self,
        base_thread_url: str,
        fetch_limit: int,
    ) -> tuple[str, list[dict[str, str]]]:
        site_domain = (urlparse(base_thread_url).hostname or "").lower()
        try:
            first_markdown = self._fetch_text_url(self._build_jina_proxy_url(base_thread_url), timeout=30)
        except Exception as exc:
            logger.warning("DonanimHaber markdown fallback first page failed: %s", exc)
            return base_thread_url, []

        max_page = self._extract_donanimhaber_max_page_from_markdown(first_markdown, base_thread_url)
        last_page_url = self._build_donanimhaber_page_url(base_thread_url, max_page)
        last_markdown = first_markdown
        if last_page_url != base_thread_url:
            try:
                last_markdown = self._fetch_text_url(self._build_jina_proxy_url(last_page_url), timeout=30)
            except Exception as exc:
                logger.warning("DonanimHaber markdown fallback last page failed: %s", exc)
                return last_page_url, []

        posts = self._extract_donanimhaber_posts_from_markdown(
            last_markdown,
            last_page_url,
            site_domain,
            fetch_limit,
        )
        return last_page_url, posts

    async def fill_missing_deal_links(self, batch_size: int = 20) -> int:
        """Backfill missing deal links for existing web topics."""
        stmt = (
            select(ScrapedTopic, TargetSite)
            .join(TargetSite, TargetSite.id == ScrapedTopic.site_id)
            .where(TargetSite.source_type == "web")
            .where(TargetSite.is_active == True)
            .where(ScrapedTopic.deleted_by_user == False)
            .where(ScrapedTopic.is_sticky == False)
            .where(
                or_(
                    ScrapedTopic.deal_url.is_(None),
                    ScrapedTopic.deal_url == "",
                )
            )
            .order_by(ScrapedTopic.id.desc())
            .limit(batch_size)
        )
        rows = (await self.db.execute(stmt)).all()
        if not rows:
            return 0

        fixed = 0
        for topic, site in rows:
            deal_url = self._extract_deal_url(topic.url, site.url)
            if not deal_url:
                continue
            cleaned_deal_url = normalize_deal_url(deal_url)
            deal_title, deal_price, resolved_url = await build_deal_metadata_for_new_record(
                cleaned_deal_url,
                topic.title,
            )
            topic.deal_url = deal_url
            topic.clean_deal_url = normalize_deal_url(resolved_url or cleaned_deal_url)
            if deal_title:
                topic.deal_title = deal_title
            if deal_price:
                topic.deal_price = deal_price
            elif not (topic.deal_price or "").strip() and _can_use_title_price_fallback(topic.title):
                topic.deal_price = _extract_price_from_text(topic.title)
            fixed += 1

        if fixed:
            try:
                await self.db.commit()
            except IntegrityError:
                await self.db.rollback()
                logger.warning("Commit conflict while backfilling missing deal links")
                return 0
        return fixed

    @staticmethod
    def _normalize_text(value: str) -> str:
        cleaned = value.strip().translate(TR_CHAR_MAP).lower().replace(",", " ")
        return " ".join(cleaned.split())

    @staticmethod
    def _to_utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=ISTANBUL_TZ)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def _parse_source_text(self, value: str) -> datetime | None:
        normalized = self._normalize_text(value)
        if not normalized:
            return None

        now_tr = datetime.now(ISTANBUL_TZ)

        if normalized == "az once":
            return self._to_utc_naive(now_tr)

        minute_match = re.search(r"(\d+)\s+dakika\s+once", normalized)
        if minute_match:
            dt = now_tr - timedelta(minutes=int(minute_match.group(1)))
            return self._to_utc_naive(dt)

        hour_match = re.search(r"(\d+)\s+saat\s+once", normalized)
        if hour_match:
            dt = now_tr - timedelta(hours=int(hour_match.group(1)))
            return self._to_utc_naive(dt)

        day_match = re.search(r"(\d+)\s+gun\s+once", normalized)
        if day_match:
            dt = now_tr - timedelta(days=int(day_match.group(1)))
            return self._to_utc_naive(dt)

        today_match = re.search(r"bugun(?:\s+(\d{1,2}):(\d{2}))?", normalized)
        if today_match:
            hour = int(today_match.group(1) or now_tr.hour)
            minute = int(today_match.group(2) or now_tr.minute)
            dt = now_tr.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return self._to_utc_naive(dt)

        yesterday_match = re.search(r"dun(?:\s+(\d{1,2}):(\d{2}))?", normalized)
        if yesterday_match:
            hour = int(yesterday_match.group(1) or now_tr.hour)
            minute = int(yesterday_match.group(2) or now_tr.minute)
            dt = (now_tr - timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return self._to_utc_naive(dt)

        abs_match = re.search(
            r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?",
            normalized,
        )
        if abs_match:
            day = int(abs_match.group(1))
            month_name = abs_match.group(2)
            month = TR_MONTHS.get(month_name)
            if month:
                raw_year = abs_match.group(3)
                year = int(raw_year or now_tr.year)
                hour = int(abs_match.group(4) or 0)
                minute = int(abs_match.group(5) or 0)
                dt = datetime(year, month, day, hour, minute, tzinfo=ISTANBUL_TZ)
                if not raw_year and dt > now_tr + timedelta(days=1):
                    dt = dt.replace(year=dt.year - 1)
                return self._to_utc_naive(dt)

        return None

    def _parse_source_node(self, node) -> datetime | None:
        data_time = node.attrib.get("data-time")
        if data_time and data_time.isdigit():
            return datetime.fromtimestamp(int(data_time), tz=timezone.utc).replace(
                tzinfo=None
            )

        datetime_attr = node.attrib.get("datetime")
        if datetime_attr:
            try:
                return self._to_utc_naive(
                    datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
                )
            except ValueError:
                pass

        title_attr = node.attrib.get("title")
        if title_attr:
            parsed_title = self._parse_source_text(title_attr)
            if parsed_title:
                return parsed_title

        return self._parse_source_text(node.text)

    def _extract_source_date(self, node, date_selector: str | None) -> datetime | None:
        creation_selectors = []
        if date_selector:
            creation_selectors.append(date_selector)
        creation_selectors.extend(
            [
                ".structItem-startDate time",
                ".structItem-cell--main .structItem-startDate time",
                ".structItem-cell--main .structItem-minor .structItem-startDate time",
                ".structItem-cell--main .structItem-minor time.u-dt",
                ".structItem-cell--main .structItem-minor time[datetime]",
            ]
        )
        latest_selectors = [
            ".structItem-cell--latest time",
            ".structItem-latestDate",
            ".structItem-cell--latest .u-dt",
            ".structItem-cell--latest time[datetime]",
        ]

        def _collect_dates(selectors: list[str]) -> list[datetime]:
            candidates: list[datetime] = []
            for selector in selectors:
                nodes = node.css(selector)
                if not nodes:
                    continue

                for candidate in nodes:
                    parsed = self._parse_source_node(candidate)
                    if parsed:
                        candidates.append(parsed)
                        continue
                    if selector == date_selector:
                        parsed_from_text = self._parse_source_text(candidate.text)
                        if parsed_from_text:
                            candidates.append(parsed_from_text)
            return candidates

        creation_dates = _collect_dates(creation_selectors)
        if creation_dates:
            return min(creation_dates)

        latest_dates = _collect_dates(latest_selectors)
        return min(latest_dates) if latest_dates else None

    @staticmethod
    def _is_sticky_topic(node) -> bool:
        css_class = (node.attrib.get("class") or "").lower()
        if "sticky" in css_class or "pinned" in css_class or "locked" in css_class:
            return True
        sticky_badges = node.css(".label--sticky, .label--pinned, .structItem-status--locked")
        if sticky_badges:
            return True
        status_nodes = node.css(".structItem-status")
        for status in status_nodes:
            status_class = (status.attrib.get("class") or "").lower()
            if "locked" in status_class:
                return True
        return False

    @staticmethod
    def _normalized_listing_url(url: str) -> str:
        """
        Enforce topic-creation ordering on XenForo-like forum listing URLs.
        This keeps behavior stable even if site-side default filters change.
        """
        parsed = urlparse(url)
        path = parsed.path.lower()
        if "/konu/" in path:
            return url
        if "/forumlar/" not in path and "/forums/" not in path:
            return url

        query = parse_qs(parsed.query, keep_blank_values=True)
        query["order"] = ["post_date"]
        query["direction"] = ["desc"]
        normalized_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=normalized_query))

    @staticmethod
    def _node_html(node) -> str:
        html = getattr(node, "html_content", None)
        if html is None:
            html = getattr(node, "body", "")
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")
        return html or ""

    def _parse_post_limit(self, url: str, default: int = 30) -> int:
        """
        Optional per-source limit via URL query params:
        - ?fetch_last=20
        - ?last_posts=30
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        for key in ("fetch_last", "last_posts"):
            raw = (qs.get(key) or [""])[0].strip()
            if not raw:
                continue
            if raw.isdigit():
                return max(1, min(100, int(raw)))
        return default

    @staticmethod
    def _normalize_donanimhaber_thread_url(url: str) -> str:
        parsed = urlparse(url)
        path = (parsed.path or "").rstrip("/")
        match = DH_THREAD_PATH_REGEX.match(path)
        if not match:
            return ""

        qs = parse_qs(parsed.query, keep_blank_values=True)
        qs.pop("fetch_last", None)
        qs.pop("last_posts", None)
        query = urlencode(qs, doseq=True)
        base_path = match.group("base")
        return urlunparse(parsed._replace(path=base_path, query=query, fragment=""))

    @staticmethod
    def _extract_donanimhaber_max_page(page_html: str) -> int:
        pages = [int(value) for value in DH_MAX_PAGE_REGEX.findall(page_html or "") if value.isdigit()]
        return max(pages) if pages else 1

    @staticmethod
    def _build_donanimhaber_page_url(base_url: str, page_number: int) -> str:
        if page_number <= 1:
            return base_url
        parsed = urlparse(base_url)
        path = (parsed.path or "").rstrip("/")
        return urlunparse(parsed._replace(path=f"{path}-{page_number}"))

    @staticmethod
    def _extract_first_external_link_from_message_node(node, site_domain: str) -> str | None:
        links = node.css("a[href]")
        for link in links:
            href = (link.attrib.get("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            absolute = href
            if href.startswith("/"):
                absolute = f"https://{site_domain}{href}"

            parsed = urlparse(absolute)
            if not parsed.netloc:
                continue

            hostname = parsed.hostname.lower() if parsed.hostname else ""
            if hostname.endswith(site_domain):
                if "externallinkredirect" in parsed.path.lower():
                    qs = parse_qs(parsed.query, keep_blank_values=True)
                    redirect_val = (qs.get("url") or [""])[0]
                    if redirect_val:
                        decoded = unquote(unescape(redirect_val)).strip()
                        decoded_parsed = urlparse(decoded)
                        if decoded_parsed.scheme and decoded_parsed.netloc:
                            return decoded
                continue

            return absolute
        return None

    @staticmethod
    def _extract_donanimhaber_message_text(node) -> str:
        candidates: list[str] = []
        selectors = [
            "p",
            "strong",
            ".ql-og-description",
            "a.og-link",
        ]
        for selector in selectors:
            nodes = node.css(selector)
            for child in nodes:
                text = " ".join((child.text or "").split())
                if not text:
                    continue
                if text in candidates:
                    continue
                candidates.append(text)
                if len(candidates) >= 4:
                    break
            if candidates:
                break

        if not candidates:
            return ""
        return " | ".join(candidates)

    @staticmethod
    def _pick_topic_link_node(link_nodes):
        if not link_nodes:
            return None
        for candidate in link_nodes:
            href = candidate.attrib.get("href", "")
            if "/konu/" in href:
                return candidate
        for candidate in link_nodes:
            href = candidate.attrib.get("href", "")
            if "prefix_id=" not in href and href:
                return candidate
        return link_nodes[0]

    @staticmethod
    def _pick_title_node(title_nodes, link_node):
        if not title_nodes:
            return link_node
        if link_node:
            link_href = link_node.attrib.get("href", "")
            for candidate in title_nodes:
                if candidate.attrib.get("href", "") == link_href and candidate.text.strip():
                    return candidate
        for candidate in title_nodes:
            if candidate.text.strip():
                return candidate
        return link_node

    @staticmethod
    def _extract_deal_url(topic_url: str, site_url: str) -> str | None:
        """Visit a topic page and extract the first external link from the first post."""
        site_domain = urlparse(site_url).netloc.lower()
        try:
            page = Fetcher.get(topic_url, timeout=20)
        except Exception as exc:
            logger.debug("Failed to fetch topic page %s: %s", topic_url, exc)
            return None

        # XenForo first post content selectors (try in order)
        content_selectors = [
            ".message-body .bbWrapper",
            ".message-content .bbWrapper",
            ".messageText",
            "article .bbWrapper",
        ]
        content_node = None
        for sel in content_selectors:
            nodes = page.css(sel)
            if nodes:
                content_node = nodes[0]
                break

        if content_node is None:
            return None

        def _normalize_extracted_href(raw_href: str) -> str | None:
            href = (raw_href or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                return None
            parsed_href = urlparse(href)
            if parsed_href.scheme and parsed_href.netloc:
                return href
            if href.startswith("/") and site_url:
                return urljoin(site_url, href)
            return None

        def _decode_possible_redirect(href: str) -> str | None:
            parsed = urlparse(href)
            host = (parsed.hostname or "").lower()
            if not host.endswith(site_domain):
                return None
            qs = parse_qs(parsed.query, keep_blank_values=True)
            for key in ("url", "u", "to", "target", "redirect", "r"):
                values = qs.get(key) or []
                for value in values:
                    candidate = unquote((value or "").strip())
                    parsed_candidate = urlparse(candidate)
                    if parsed_candidate.scheme and parsed_candidate.netloc:
                        if parsed_candidate.netloc.lower().endswith(site_domain):
                            continue
                        return candidate
            return None

        links = content_node.css("a[href]")
        for link in links:
            href = _normalize_extracted_href(link.attrib.get("href", ""))
            if not href:
                continue
            parsed = urlparse(href)
            # Skip links pointing back to the same forum
            if parsed.netloc.lower().endswith(site_domain):
                redirected = _decode_possible_redirect(href)
                if redirected:
                    return redirected
                continue
            return href

        # Fallback: some posts include plain-text URLs instead of <a href>.
        raw_html = getattr(content_node, "html_content", "") or getattr(content_node, "body", "") or ""
        if isinstance(raw_html, bytes):
            raw_html = raw_html.decode("utf-8", errors="replace")
        text_blob = (raw_html or "") + " " + (content_node.text or "")
        for match in re.finditer(r"https?://[^\s<>'\"\\)\\]]+", text_blob, flags=re.IGNORECASE):
            candidate = match.group(0).rstrip("*.,;:!?)]")
            parsed = urlparse(candidate)
            if not parsed.scheme or not parsed.netloc:
                continue
            if parsed.netloc.lower().endswith(site_domain):
                redirected = _decode_possible_redirect(candidate)
                if redirected:
                    return redirected
                continue
            return candidate

        return None
