import requests
from bs4 import BeautifulSoup
from datetime import datetime
from datetime import timedelta
import feedparser
from urllib.parse import urljoin, urlparse
import re
from pathlib import Path
import hashlib
import json


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


def _safe_get(url: str, timeout: int = 10):
    return requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)


def _extract_float(value: str):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", raw)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_vnd_price(value: float):
    # VFA style: 5.450 == 5,450 VND/kg
    if value is None:
        return None
    if 0 < value < 100:
        return round(value * 1000, 2)
    return value


def _is_irrelevant_commodity_name(name: str):
    n = (name or "").strip().lower()
    return n in {"việt nam", "vietnam", "thế giới", "world", "trong nước", ""}


def _normalize_category(name: str):
    n = (name or "").lower()
    if "lúa" in n or "gạo" in n or "rice" in n:
        return "rice"
    if any(k in n for k in ["tôm", "cá", "seafood", "thủy"]):
        return "seafood"
    if any(k in n for k in ["heo", "thịt", "livestock"]):
        return "livestock"
    if any(k in n for k in ["cà phê", "hồ tiêu", "cao su", "sầu riêng", "nông"]):
        return "agriculture"
    return "other"


def _parse_vn_date(text: str):
    if not text:
        return None
    cleaned = text.strip()
    patterns = [
        r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})",
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
    ]
    for pattern in patterns:
        m = re.search(pattern, cleaned)
        if not m:
            continue
        try:
            if len(m.group(1)) == 4:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except Exception:
            continue
    return None


def _extract_dates_from_text(text: str):
    if not text:
        return []
    matches = re.findall(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}", text)
    dates = []
    for m in matches:
        dt = _parse_vn_date(m)
        if dt:
            dates.append(dt)
    return dates


def _is_probable_article(link: str, title: str):
    lowered_link = link.lower()
    lowered_title = title.lower()
    if len(title) < 25:
        return False
    reject_tokens = [
        "/category/",
        "/gioi-thieu",
        "/lien-he",
        "/default.aspx",
        ".jpg",
        ".png",
        "javascript:",
        "mailto:",
        "#",
    ]
    if any(t in lowered_link for t in reject_tokens):
        return False
    nav_titles = [
        "trang chủ",
        "giới thiệu",
        "sản phẩm",
        "liên hệ",
        "đặt mua",
        "xem tiếp",
        "tin tức",
        "hoạt động",
        "nhân sự",
    ]
    if any(t == lowered_title.strip() for t in nav_titles):
        return False
    nav_title_contains = [
        "sản phẩm & dịch vụ",
        "công nghệ - chuyển đổi số",
        "hiệp định thương mại tự do",
    ]
    if any(t in lowered_title for t in nav_title_contains):
        return False
    nav_link_contains = [
        "/san-pham",
        "/hiep-dinh-fta",
        "/kh-cn-doi-moi-sang-tao",
    ]
    if any(t in lowered_link for t in nav_link_contains):
        return False
    return True


# thongtincongthuong.vn: first path segment is often a *section* (not an article) but still has hyphens.
VITIC_SECTION_FIRST_SEGMENTS = frozenset(
    {
        "kh-cn-doi-moi-sang-tao",
        "san-pham-dich-vu-cua-trung-tam",
        "gioi-thieu",
        "lien-he",
        "lien-he-voi-chung-toi",
        "tag",
        "author",
        "video",
        "gallery",
        "english",
    }
)


def vitic_url_is_section_landing(url: str) -> bool:
    if not url or "thongtincongthuong.vn" not in url.lower():
        return False
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    if not parts:
        return True
    return parts[0].lower() in VITIC_SECTION_FIRST_SEGMENTS


def news_item_is_nav_noise(link: str, title: str) -> bool:
    """
    True = menu/section rows that should not appear as news (esp. VITIC category pages).
    Links like '#' are kept for system/placeholder rows.
    """
    if not title or not str(title).strip():
        return True
    if not link or link.strip() in ("", "#"):
        return False
    if vitic_url_is_section_landing(link):
        return True
    t = " ".join(str(title).lower().split())
    # Match en-dash or hyphen section headers
    noise_in_title = (
        "công nghệ - chuyển đổi số",
        "công nghệ – chuyển đổi số",
        "sản phẩm & dịch vụ",
        "hiệp định thương mại tự do",
    )
    if any(p in t for p in noise_in_title):
        return True
    nav_shout = (
        "công nghệ",
        "chuyển đổi số",
    )
    if t == "công nghệ" or t == "chuyển đổi số":
        return True
    if len(t) <= 50 and t.isupper() and (" - " in t or " – " in t) and any(k in t for k in nav_shout):
        return True
    return False


def scrape_tepbac():
    news = []
    try:
        url = "https://tepbac.com/feed"
        response = _safe_get(url, timeout=8)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, features="xml")
            items = soup.find_all('item')
            for item in items[:15]: 
                title = item.find('title').text if item.find('title') else 'No title'
                link = item.find('link').text if item.find('link') else '#'
                pubDate = item.find('pubDate').text if item.find('pubDate') else datetime.now().strftime("%Y-%m-%d")
                
                desc = item.find('description')
                img_url = None
                if desc and '<img' in desc.text:
                    desc_soup = BeautifulSoup(desc.text, 'html.parser')
                    img = desc_soup.find('img')
                    if img and img.get('src'):
                        img_url = img.get('src')
                        
                news.append({
                    "source": "Tepbac",
                    "title": title,
                    "link": link,
                    "date": pubDate[:16] if len(pubDate) > 16 else pubDate,
                    "image": img_url,
                    "sentiment": "Neutral",
                    "ai_summary": ""
                })
    except Exception as e:
        print(f"Tepbac scrape failed: {e}")
    return news

def scrape_agriculture_vn():
    news = []
    try:
        feed = feedparser.parse("https://vnexpress.net/rss/kinh-doanh/hang-hoa.rss")
        for entry in feed.entries[:15]:
            title = entry.title
            link = entry.link
            pubDate = entry.published if hasattr(entry, 'published') else datetime.now().strftime("%Y-%m-%d")
            
            news.append({
                "source": "VNExpress (Hàng Hóa)",
                "title": title,
                "link": link,
                "date": pubDate[:16] if len(pubDate) > 16 else pubDate,
                "image": None,
                "sentiment": "Neutral",
                "ai_summary": ""
            })
    except Exception as e:
        print(f"Agriculture VN scrape failed: {e}")
    return news

def scrape_international():
    news = []
    feed_urls = [
        "https://www.intrafish.com/arc/outboundfeeds/rss/",
        "https://seafoodnews.com/feed" 
    ]
    try:
        feed = feedparser.parse(feed_urls[0])
        if len(feed.entries) == 0:
            return news
            
        for entry in feed.entries[:10]:
            title = entry.title
            link = entry.link
            pubDate = entry.published if hasattr(entry, 'published') else datetime.now().strftime("%Y-%m-%d")
            
            news.append({
                "source": "IntraFish",
                "title": title,
                "link": link,
                "date": pubDate[:16] if len(pubDate) > 16 else pubDate,
                "image": None,
                "sentiment": "Neutral",
                "ai_summary": ""
            })
    except Exception as e:
        print(f"International scrape failed: {e}")
    return news


def scrape_agromonitor_news():
    news = []
    try:
        url = "https://agromonitor.vn/category/47/tom"
        response = _safe_get(url)
        if response.status_code != 200:
            return news
        soup = BeautifulSoup(response.text, "html.parser")

        # Aggressive but bounded selector set for resilience to layout changes
        anchors = soup.select("a[href]")
        seen_links = set()
        for a in anchors:
            href = a.get("href", "").strip()
            title = " ".join(a.get_text(" ", strip=True).split())
            if not href or not title:
                continue
            full_link = urljoin(url, href)
            if not _is_probable_article(full_link, title):
                continue
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            news.append(
                {
                    "source": "AgroMonitor",
                    "title": title[:220],
                    "link": full_link,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "image": None,
                    "sentiment": "Neutral",
                    "ai_summary": "",
                }
            )
            if len(news) >= 15:
                break
    except Exception as e:
        print(f"AgroMonitor scrape failed: {e}")
    return news


def scrape_agro_gov_news():
    news = []
    try:
        url = "https://agro.gov.vn/vn/default.aspx"
        response = _safe_get(url)
        if response.status_code != 200:
            return news
        soup = BeautifulSoup(response.text, "html.parser")
        anchors = soup.select("a[href]")
        seen_links = set()
        for a in anchors:
            href = a.get("href", "").strip()
            title = " ".join(a.get_text(" ", strip=True).split())
            if not href or not title:
                continue
            full_link = urljoin(url, href)
            if "/tid" not in full_link.lower():
                continue
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            news.append(
                {
                    "source": "AGROINFO",
                    "title": title[:220],
                    "link": full_link,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "image": None,
                    "sentiment": "Neutral",
                    "ai_summary": "",
                }
            )
            if len(news) >= 12:
                break
    except Exception as e:
        print(f"AGROINFO scrape failed: {e}")
    return news


def scrape_vitic_news():
    news = []
    try:
        url = "https://thongtincongthuong.vn/"
        response = _safe_get(url)
        if response.status_code != 200:
            return news
        soup = BeautifulSoup(response.text, "html.parser")
        anchors = soup.select("a[href]")
        seen_links = set()
        for a in anchors:
            href = a.get("href", "").strip()
            title = " ".join(a.get_text(" ", strip=True).split())
            if not href or not title:
                continue
            full_link = urljoin(url, href)
            lowered = full_link.lower()
            if "/category/" in lowered or "/tag/" in lowered:
                continue
            # Most article links on this site are slug-based pages and not section pages.
            if "-" not in lowered.rsplit("/", 2)[-2]:
                continue
            if news_item_is_nav_noise(full_link, title):
                continue
            if not _is_probable_article(full_link, title):
                continue
            if full_link in seen_links:
                continue
            seen_links.add(full_link)
            news.append(
                {
                    "source": "VITIC",
                    "title": title[:220],
                    "link": full_link,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "image": None,
                    "sentiment": "Neutral",
                    "ai_summary": "",
                }
            )
            if len(news) >= 12:
                break
    except Exception as e:
        print(f"VITIC scrape failed: {e}")
    return news


def get_regional_prices():
    """Scrape a simple commodity price table from AGROINFO homepage."""
    data = []
    try:
        url = "https://agro.gov.vn/vn/default.aspx"
        response = _safe_get(url)
        if response.status_code != 200:
            return {"status": "error", "message": "Source unavailable", "data": []}
        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table tr")
        for row in rows:
            cols = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cols) < 4:
                continue
            # Expected columns usually: Tên mặt hàng | Thị trường | Ngày | Giá | ...
            if "Tên mặt hàng" in cols[0]:
                continue
            item = {
                "name": cols[0],
                "market": cols[1] if len(cols) > 1 else "",
                "date": cols[2] if len(cols) > 2 else "",
                "price": cols[3] if len(cols) > 3 else "",
                "currency": cols[4] if len(cols) > 4 else "",
                "price_type": cols[5] if len(cols) > 5 else "",
                "source": cols[6] if len(cols) > 6 else "AGROINFO",
                "unit": cols[7] if len(cols) > 7 else "",
            }
            # Skip non-price rows
            if len(item["name"]) < 2 or len(item["price"]) < 1:
                continue
            data.append(item)
            if len(data) >= 30:
                break
    except Exception as e:
        print(f"Regional price scrape failed: {e}")
    return {"status": "success", "data": data}


def scrape_agroinfo_price_observations():
    observations = []
    source_url = "https://agro.gov.vn/vn/default.aspx"
    regional_data = get_regional_prices().get("data", [])
    for item in regional_data:
        price_value = _extract_float(item.get("price", ""))
        if price_value is None:
            continue
        name = item.get("name", "").strip()
        if _is_irrelevant_commodity_name(name):
            continue
        market = item.get("market", "").strip()
        date_str = item.get("date", "").strip()
        observed_at = datetime.utcnow()
        try:
            observed_at = datetime.strptime(date_str, "%d-%m-%Y")
        except Exception:
            pass
        observations.append(
            {
                "commodity_code": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80],
                "commodity_name": name,
                "category": _normalize_category(name),
                "subcategory": item.get("price_type", "").strip() or "spot",
                "market": market,
                "region": market,
                "price": price_value,
                "currency": item.get("currency", "VND").strip() or "VND",
                "unit": item.get("unit", "kg").strip() or "kg",
                "price_type": item.get("price_type", "").strip() or "spot",
                "source": "AGROINFO",
                "source_url": source_url,
                "observed_at": observed_at,
                "raw_payload": str(item),
            }
        )
    return observations


def scrape_vfa_rice_observations():
    observations = []
    source_pages = [
        "https://vietfood.org.vn/thi-truong/gia-noi-dia/",
        "https://e.vietfood.org.vn/market-update/export-price/",
    ]
    for page_url in source_pages:
        try:
            response = _safe_get(page_url, timeout=12)
            if response.status_code != 200:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("table tr")
            for row in rows:
                cols = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                if len(cols) < 3:
                    continue
                row_text = " | ".join(cols)
                lowered = row_text.lower()
                if not any(k in lowered for k in ["lúa", "gạo", "rice"]):
                    continue
                # Guess fields in flexible way
                name = cols[0]
                if _is_irrelevant_commodity_name(name):
                    continue
                market = "Vietnam"
                price_type = "spot"
                currency = "VND"
                unit = "kg"
                observed_at = datetime.utcnow()
                for col in cols[1:]:
                    if "usd" in col.lower():
                        currency = "USD"
                    if "/" in col and any(u in col.lower() for u in ["kg", "tấn", "ton", "lb"]):
                        unit = col.lower().replace("đvt", "").strip()
                    if any(k in col.lower() for k in ["fob", "cif", "xuất khẩu", "nội địa"]):
                        price_type = col
                    if any(m in col.lower() for m in ["đbscl", "mekong", "philippines", "ghana", "usa", "new york", "london"]):
                        market = col
                    dt = _extract_float(col)
                    if dt and dt > 19000000:  # yyyymmdd-like not used currently
                        pass
                price_candidates = [_extract_float(c) for c in cols]
                price_candidates = [p for p in price_candidates if p is not None and p > 0]
                if not price_candidates:
                    continue
                if currency == "USD":
                    unit = "ton"
                    valid = [p for p in price_candidates if 100 <= p <= 2000]
                else:
                    valid = [_normalize_vnd_price(p) for p in price_candidates]
                    valid = [p for p in valid if p is not None and 3000 <= p <= 20000]
                if not valid:
                    continue
                # Pick max valid as current quoted ceiling
                price_value = max(valid)
                observations.append(
                    {
                        "commodity_code": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80],
                        "commodity_name": name,
                        "category": "rice",
                        "subcategory": "vfa",
                        "market": market,
                        "region": market,
                        "price": price_value,
                        "currency": currency,
                        "unit": unit,
                        "price_type": price_type,
                        "source": "VFA",
                        "source_url": page_url,
                        "observed_at": observed_at,
                        "raw_payload": row_text,
                    }
                )
        except Exception as e:
            print(f"VFA scrape failed ({page_url}): {e}")
    return observations


def scrape_vfa_rice_history(days: int = 30):
    """Backfill VFA rice observations from recent post pages within N days."""
    observations = []
    cutoff = datetime.now() - timedelta(days=days)
    list_url = "https://vietfood.org.vn/thi-truong/gia-noi-dia/"
    try:
        response = _safe_get(list_url, timeout=12)
        if response.status_code != 200:
            return observations
        soup = BeautifulSoup(response.text, "html.parser")
        candidate_links = []
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            text = " ".join(a.get_text(" ", strip=True).split()).lower()
            full_link = urljoin(list_url, href)
            if "gia-lua-gao-noi-dia" in full_link.lower() or "giá lúa gạo" in text:
                candidate_links.append(full_link)
        # de-dup keep order
        dedup = []
        seen = set()
        for link in candidate_links:
            if link not in seen:
                seen.add(link)
                dedup.append(link)
        for page_url in dedup[:20]:
            try:
                page = _safe_get(page_url, timeout=12)
                if page.status_code != 200:
                    continue
                page_soup = BeautifulSoup(page.text, "html.parser")
                page_text = page_soup.get_text(" ", strip=True)
                found_dates = _extract_dates_from_text(page_text)
                page_date = max(found_dates) if found_dates else datetime.now()
                if page_date < cutoff:
                    continue
                rows = page_soup.select("table tr")
                for row in rows:
                    cols = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
                    if len(cols) < 2:
                        continue
                    line = " | ".join(cols)
                    lowered = line.lower()
                    if not any(k in lowered for k in ["lúa", "gạo", "rice"]):
                        continue
                    price_candidates = [_extract_float(c) for c in cols]
                    price_candidates = [p for p in price_candidates if p is not None and p > 0]
                    if not price_candidates:
                        continue
                    name = cols[0]
                    if _is_irrelevant_commodity_name(name):
                        continue
                    valid = [_normalize_vnd_price(p) for p in price_candidates]
                    valid = [p for p in valid if p is not None and 3000 <= p <= 20000]
                    if not valid:
                        valid = [p for p in price_candidates if 100 <= p <= 2000]
                    if not valid:
                        continue
                    # pick largest number as upper bound of range if present
                    price_value = max(valid)
                    if price_value <= 0:
                        continue
                    currency = "VND" if price_value >= 3000 else "USD"
                    unit = "kg" if currency == "VND" else "ton"
                    market = "ĐBSCL"
                    for col in cols:
                        col_l = col.lower()
                        if any(k in col_l for k in ["tiền giang", "long an", "đồng tháp", "cần thơ", "an giang", "bạc liêu", "kiên giang"]):
                            market = col
                            break
                    observations.append(
                        {
                            "commodity_code": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80],
                            "commodity_name": name,
                            "category": "rice",
                            "subcategory": "vfa_historical",
                            "market": market,
                            "region": market,
                            "price": price_value,
                            "currency": currency,
                            "unit": unit,
                            "price_type": "spot",
                            "source": "VFA",
                            "source_url": page_url,
                            "observed_at": page_date,
                            "raw_payload": line,
                        }
                    )
            except Exception as e:
                print(f"VFA history scrape page failed ({page_url}): {e}")
                continue
    except Exception as e:
        print(f"VFA history scrape failed: {e}")
    return observations


def get_normalized_price_observations():
    observations = []
    observations.extend(scrape_agroinfo_price_observations())
    observations.extend(scrape_vfa_rice_observations())
    return observations


def get_normalized_price_observations_with_backfill(days: int = 30):
    observations = get_normalized_price_observations()
    observations.extend(scrape_vfa_rice_history(days=days))
    # keep only rows in range for backfill sources where observed_at exists
    cutoff = datetime.now() - timedelta(days=days)
    filtered = []
    for obs in observations:
        observed_at = obs.get("observed_at")
        if observed_at and observed_at < cutoff:
            continue
        filtered.append(obs)
    return filtered


STOCK_WATCHLIST = [
    {"symbol": "MPC", "name": "Thủy sản Minh Phú", "exchange": "UPCOM", "market": "VN"},
    {"symbol": "VHC", "name": "Vĩnh Hoàn", "exchange": "HOSE", "market": "VN"},
    {"symbol": "SEA", "name": "Tổng CTCP Thủy sản Việt Nam (Seaprodex)", "exchange": "HOSE", "market": "VN"},
    {"symbol": "FMC", "name": "Thực phẩm Sao Ta", "exchange": "HOSE", "market": "VN"},
    {"symbol": "ABT", "name": "XNK Thủy sản Bến Tre", "exchange": "HOSE", "market": "VN"},
    {"symbol": "AAM", "name": "Thủy sản Mê Kông", "exchange": "HOSE", "market": "VN"},
    {"symbol": "ACL", "name": "XNK Thủy sản Cửu Long", "exchange": "HOSE", "market": "VN"},
    {"symbol": "BLF", "name": "Thủy sản Bạc Liêu", "exchange": "HNX", "market": "VN"},
    {"symbol": "IDP", "name": "Giống cây trồng và vật nuôi TW", "exchange": "HNX", "market": "VN"},
    {"symbol": "BAF", "name": "Nông nghiệp BAF Việt Nam", "exchange": "HOSE", "market": "VN"},
    {"symbol": "PAN", "name": "Tập đoàn PAN", "exchange": "HOSE", "market": "VN"},
    {"symbol": "ANV", "name": "Nam Việt", "exchange": "HOSE", "market": "VN"},
    {"symbol": "DRC", "name": "Giống cây trồng Đắk Lắk", "exchange": "HOSE", "market": "VN"},
    {"symbol": "DBC", "name": "Tập đoàn Dabaco Việt Nam", "exchange": "HOSE", "market": "VN"},
    {"symbol": "SSC", "name": "Giống cây trồng Miền Nam", "exchange": "HOSE", "market": "VN"},
    {"symbol": "AAF", "name": "Nông nghiệp An Giang", "exchange": "HOSE", "market": "VN"},
    {"symbol": "DPM", "name": "Phân bón Dầu khí Cà Mau", "exchange": "UPCOM", "market": "VN"},
    {"symbol": "LAS", "name": "Supe phốt phát và Hóa chất Lâm Thao", "exchange": "HOSE", "market": "VN"},
    {"symbol": "LTG", "name": "Tập đoàn Lộc Trời", "exchange": "HOSE", "market": "VN"},
    {"symbol": "NSC", "name": "Giống cây trồng Nam Sông Hậu", "exchange": "UPCOM", "market": "VN"},
    {"symbol": "HAG", "name": "Hoàng Anh Gia Lai", "exchange": "HOSE", "market": "VN"},
    {"symbol": "AGM", "name": "XNK An Giang", "exchange": "HOSE", "market": "VN"},
    {"symbol": "TAR", "name": "Nông nghiệp CN cao Trung An", "exchange": "HNX", "market": "VN"},
    {"symbol": "SGC", "name": "XNK Sa Giang", "exchange": "HNX", "market": "VN"},
    {"symbol": "SAF", "name": "Lương thực Thực phẩm SAFOCO", "exchange": "HNX", "market": "VN"},
]


def get_stock_watchlist():
    return STOCK_WATCHLIST


def get_stock_tracking_links(symbol: str):
    s = symbol.upper()
    return {
        "fireant": f"https://fireant.vn/ma-chung-khoan/{s}",
        "vietstock": f"https://finance.vietstock.vn/{s}/overview.htm",
        "ssi": f"https://iboard.ssi.com.vn/bang-gia/{s}",
    }


def fetch_live_stock_quotes():
    """Fetch stock quotes via Yahoo Finance free quote endpoint."""
    watchlist = get_stock_watchlist()
    if not watchlist:
        return []
    yahoo_symbols = ",".join([f"{item['symbol']}.VN" for item in watchlist])
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={yahoo_symbols}"
    quote_map = {}
    try:
        response = _safe_get(url, timeout=10)
        if response.status_code == 200:
            payload = response.json()
            results = payload.get("quoteResponse", {}).get("result", [])
            for row in results:
                raw_symbol = row.get("symbol", "")
                symbol = raw_symbol.replace(".VN", "")
                price = row.get("regularMarketPrice")
                prev_close = row.get("regularMarketPreviousClose")
                if price is None:
                    continue
                if prev_close in (None, 0):
                    prev_close = price
                change_amt = float(price) - float(prev_close)
                change_pct = (change_amt / float(prev_close) * 100) if prev_close else 0.0
                quote_map[symbol] = {
                    "price": round(float(price), 2),
                    "change_amt": round(change_amt, 2),
                    "change_pct": round(change_pct, 2),
                }
    except Exception as e:
        print(f"Live stock quote fetch failed: {e}")

    data = []
    for item in watchlist:
        symbol = item["symbol"]
        quote = quote_map.get(symbol)
        if quote:
            data.append(
                {
                    "symbol": symbol,
                    "name": item["name"],
                    "price": quote["price"],
                    "currency": "VND",
                    "market": item["market"],
                    "exchange": item["exchange"],
                    "trend": "up" if quote["change_amt"] >= 0 else "down",
                    "change_amt": quote["change_amt"],
                    "change_pct": quote["change_pct"],
                    "links": get_stock_tracking_links(symbol),
                }
            )
    return data


def get_stock_market_news():
    feeds = [
        ("Vietstock", "https://vietstock.vn/rss/chung-khoan.rss"),
        ("CafeF", "https://cafef.vn/thi-truong-chung-khoan.rss"),
    ]
    items = []
    for source, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if not title or not link:
                    continue
                items.append(
                    {
                        "source": source,
                        "title": title,
                        "link": link,
                        "date": getattr(entry, "published", datetime.now().strftime("%Y-%m-%d %H:%M")),
                    }
                )
        except Exception as e:
            print(f"Stock news feed failed ({source}): {e}")
    # de-dup by link
    dedup = []
    seen = set()
    for item in items:
        if item["link"] in seen:
            continue
        seen.add(item["link"])
        dedup.append(item)
    return dedup[:20]


def fetch_article_content(link: str):
    """Best-effort fetch of article body + metadata from URL."""
    try:
        res = _safe_get(link, timeout=12)
        if res.status_code != 200:
            return {"ok": False, "error": f"status_{res.status_code}"}
        soup = BeautifulSoup(res.text, "html.parser")

        title_node = soup.find("h1") or soup.find("title")
        title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""

        # Remove noisy nodes first.
        for noisy in soup.select("script, style, nav, header, footer, aside, form, noscript"):
            noisy.decompose()

        # Try common article containers.
        container = (
            soup.find("article")
            or soup.select_one("main")
            or soup.select_one(".article-content")
            or soup.select_one(".content")
            or soup.body
        )
        paragraphs = []
        if container:
            for p in container.find_all("p"):
                txt = " ".join(p.get_text(" ", strip=True).split())
                if len(txt) >= 40:
                    paragraphs.append(txt)
        if not paragraphs and container:
            # Fallback: split by lines
            raw = " ".join(container.get_text("\n", strip=True).split())
            if raw:
                paragraphs = [raw]

        content_text = "\n\n".join(paragraphs).strip()
        content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest() if content_text else ""

        return {
            "ok": bool(content_text),
            "title": title,
            "content_text": content_text,
            "content_hash": content_hash,
            "metadata": {
                "fetched_url": link,
                "paragraph_count": len(paragraphs),
                "fetched_at": datetime.utcnow().isoformat(),
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def persist_article_markdown(
    base_dir: str,
    source: str,
    title: str,
    link: str,
    content_text: str,
    metadata: dict,
    folder_type: str = "agriculture_news",
):
    """
    Store article as markdown file. Returns relative file path from base_dir parent.
    """
    source_slug = re.sub(r"[^a-z0-9]+", "-", (source or "unknown").lower()).strip("-") or "unknown"
    title_slug = re.sub(r"[^a-z0-9]+", "-", (title or "untitled").lower()).strip("-")[:80] or "untitled"
    link_hash = hashlib.md5((link or "").encode("utf-8")).hexdigest()[:10]
    now = datetime.utcnow()

    safe_folder_type = folder_type if folder_type in {"agriculture_news", "stock_news"} else "agriculture_news"
    target_dir = Path(base_dir) / safe_folder_type / now.strftime("%Y") / now.strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_{source_slug}_{title_slug}_{link_hash}.md"
    file_path = target_dir / filename

    front_matter = {
        "title": title,
        "source": source,
        "link": link,
        "fetched_at": now.isoformat(),
        "meta": metadata or {},
    }
    content = (
        "---\n"
        + json.dumps(front_matter, ensure_ascii=False, indent=2)
        + "\n---\n\n"
        + (content_text or "")
        + "\n"
    )
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)

def get_latest_news():
    news_items = []
    news_items.extend(scrape_tepbac())
    news_items.extend(scrape_agriculture_vn())
    news_items.extend(scrape_international())
    news_items.extend(scrape_agromonitor_news())
    news_items.extend(scrape_agro_gov_news())
    news_items.extend(scrape_vitic_news())
    
    news_items = [x for x in news_items if not news_item_is_nav_noise(x.get("link", ""), x.get("title", ""))]

    # Sort by time mock if we wanted, but appending sequentially is fine
    if not news_items:
        news_items = [
            {
                "source": "System Core",
                "title": "Data stream temporarily offline. Waiting for sync.",
                "link": "#",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "sentiment": "Warning",
                "image": None,
                "ai_summary": ""
            }
        ]

    return {"status": "success", "data": news_items}

if __name__ == "__main__":
    print(get_latest_news())
