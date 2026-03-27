from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from crawler import (
    get_latest_news,
    fetch_live_stock_quotes,
    get_stock_watchlist,
    get_stock_tracking_links,
    get_stock_market_news,
    fetch_article_content,
    persist_article_markdown,
    news_item_is_nav_noise,
)
import datetime
import os
import json
import re
import secrets
import requests
from pathlib import Path
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="Agriculture Price & News Monitor API")

# Hard-locked lightweight models for this app.
LOCKED_GEMINI_MODEL = "gemini-1.5-flash"
LOCKED_OPENAI_MODEL = "gpt-4o-mini"

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _normalize_ai_alert_json(raw_text: str):
    if not raw_text:
        return None
    m = re.search(r"(\[\s*\{.*\}\s*\])", raw_text, re.DOTALL)
    json_text = m.group(1) if m else raw_text
    parsed = json.loads(json_text)
    if not isinstance(parsed, list):
        return None
    alerts = []
    for item in parsed[:3]:
        level = str(item.get("level", "medium")).lower()
        if level not in {"high", "medium", "low"}:
            level = "medium"
        msg = str(item.get("text", "")).strip()
        if msg:
            alerts.append({"level": level, "text": msg[:220]})
    return alerts if alerts else None


def _safe_generate_ai_alerts(context_payload: dict):
    prompt = (
        "Ban la tro ly giam sat gia nong nghiep/thuy san. "
        "Duoc cap du lieu JSON, hay sinh 3 canh bao ngan bang tieng Viet. "
        "Tra ve CHI JSON array theo format: "
        "[{\"level\":\"high|medium|low\",\"text\":\"...\"}]. "
        "Khong markdown, khong giai thich.\n\n"
        f"DATA={json.dumps(context_payload, ensure_ascii=False)}"
    )

    # 1) Prefer Gemini
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{LOCKED_GEMINI_MODEL}:generateContent?key={gemini_key}"
            )
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            res = requests.post(url, json=payload, timeout=12)
            if res.status_code == 200:
                body = res.json()
                text = (
                    body.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                parsed = _normalize_ai_alert_json(text)
                if parsed:
                    return parsed
        except Exception:
            pass

    # 2) Backup key for OpenAI (support both OPENAI_API_KEY and OPENAPI_API_KEY)
    openai_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("OPENAPI_API_KEY", "").strip()
    if openai_key:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": LOCKED_OPENAI_MODEL,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "You return strict JSON only."},
                    {"role": "user", "content": prompt},
                ],
            }
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            }
            res = requests.post(url, headers=headers, json=payload, timeout=12)
            if res.status_code == 200:
                body = res.json()
                text = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = _normalize_ai_alert_json(text)
                if parsed:
                    return parsed
        except Exception:
            pass

    return None

@app.get("/")
def read_root():
    return {"message": "Welcome to Ag Monitor API"}

from database import SessionLocal
from models import (
    CommodityPrice,
    CrawlerSource,
    NewsArticle,
    StockPrice,
    PriceObservation,
    NormalizedNews,
    ExportMarketStat,
    NewsContentArchive,
    SubmitNewsLog,
)
from fastapi import Query
from database import Base, engine

Base.metadata.create_all(bind=engine)

_submit_basic = HTTPBasic(auto_error=False)


def _submit_basic_enabled() -> bool:
    return bool(os.getenv("SUBMIT_BASIC_PASSWORD", "").strip())


def verify_submit_basic(credentials: HTTPBasicCredentials | None = Depends(_submit_basic)):
    """
    Protect /api/submit/* when SUBMIT_BASIC_PASSWORD is set.
    n8n: HTTP Request node → Authentication → Basic Auth (same user/password).
    """
    expected_user = os.getenv("SUBMIT_BASIC_USER", "submit_admin").strip()
    expected_pass = os.getenv("SUBMIT_BASIC_PASSWORD", "").strip()
    if not expected_pass:
        return True
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Submit authentication required",
            headers={"WWW-Authenticate": 'Basic realm="argimonitor-submit"'},
        )
    user_ok = secrets.compare_digest(credentials.username or "", expected_user)
    pass_ok = secrets.compare_digest(credentials.password or "", expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid submit credentials",
            headers={"WWW-Authenticate": 'Basic realm="argimonitor-submit"'},
        )
    return True


@app.get("/api/submit/auth-config")
def submit_auth_config():
    """Public: whether Basic Auth is required for /api/submit/* (for UI + n8n setup)."""
    enabled = _submit_basic_enabled()
    return {
        "status": "success",
        "basic_auth_enabled": enabled,
        "username": os.getenv("SUBMIT_BASIC_USER", "submit_admin").strip() if enabled else None,
        "endpoints": {
            "price_options": "GET /api/submit/price-options",
            "price": "POST /api/submit/price",
            "news": "POST /api/submit/news",
            "news_history": "GET /api/submit/news/history",
            "news_history_delete": "DELETE /api/submit/news/history/{id}",
            "crawler_sources": "GET /api/submit/crawler-sources",
            "crawler_sources_patch": "PATCH /api/submit/crawler-sources/{slug}",
        },
    }


class SubmitPriceRequest(BaseModel):
    commodity_name: str = Field(..., min_length=2, max_length=220)
    category: str = Field(default="agriculture")
    market: str = Field(default="Vietnam")
    region: str = Field(default="Vietnam")
    price: float = Field(..., gt=0)
    currency: str = Field(default="VND")
    unit: str = Field(default="kg")
    price_type: str = Field(default="spot")
    source: str = Field(default="manual_submit")
    source_url: str = Field(default="manual://submit")


class SubmitNewsRequest(BaseModel):
    title: str = Field(..., min_length=4, max_length=300)
    link: str = Field(..., min_length=8, max_length=500)
    description: str = Field(default="", max_length=1500)
    source: str = Field(default="manual_submit")
    category: str = Field(default="")
    folder_type: str = Field(default="agriculture_news")


class CrawlerSourcePatch(BaseModel):
    enabled: bool


def _dt_naive_utc(dt: datetime.datetime | None) -> datetime.datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# Canonical dashboard names ↔ legacy crawler/submit aliases (merge in /api/prices + /api/history).
RICE_BENCHMARKS: tuple[tuple[str, frozenset[str]], ...] = (
    ("Giá lúa IR504", frozenset({"Giá lúa IR504", "Lúa Thường (IR50404)"})),
    ("Giá gạo 5%", frozenset({"Giá gạo 5%", "Gạo Xuất Khẩu 5%"})),
)


def _rice_skip_names() -> frozenset[str]:
    return frozenset(name for _, aliases in RICE_BENCHMARKS for name in aliases)


def _expand_rice_history_names(commodity: str) -> list[str]:
    c = (commodity or "").strip()
    for _, aliases in RICE_BENCHMARKS:
        if c in aliases:
            return list(aliases)
    return [c]


def _merge_cp_and_obs_history(
    cp_rows: list,
    obs_rows: list,
    range_key: str,
) -> tuple[list[str], list[float]]:
    """Merge CommodityPrice + PriceObservation series for charts (one point per day when not 1d)."""
    pairs: list[tuple[datetime.datetime, float]] = []
    for h in cp_rows:
        t = _dt_naive_utc(h.date_recorded) or h.date_recorded
        pairs.append((t, float(h.price)))
    for o in obs_rows:
        t = _dt_naive_utc(o.observed_at) or o.observed_at
        pairs.append((t, float(o.price)))
    pairs.sort(key=lambda x: x[0])
    if not pairs:
        return [], []
    if range_key == "1d":
        labels = [t.strftime("%H:%M") for t, _ in pairs]
        prices = [p for _, p in pairs]
        return labels, prices
    by_day: dict = {}
    for t, p in pairs:
        day = t.date()
        by_day[day] = (t, p)
    sorted_days = sorted(by_day.keys())
    labels = [by_day[d][0].strftime("%m-%d") for d in sorted_days]
    prices = [by_day[d][1] for d in sorted_days]
    return labels, prices


@app.get("/api/submit/price-options")
def get_submit_price_options(_auth: bool = Depends(verify_submit_basic)):
    db = SessionLocal()
    try:
        options_map = {}

        latest_obs = (
            db.query(PriceObservation)
            .order_by(PriceObservation.observed_at.desc())
            .limit(1200)
            .all()
        )
        for row in latest_obs:
            name = (row.commodity_name or "").strip()
            if not name or name in options_map:
                continue
            options_map[name] = {
                "commodity_name": name,
                "category": row.category or "agriculture",
                "market": row.market or "Vietnam",
                "region": row.region or row.market or "Vietnam",
                "currency": row.currency or "VND",
                "unit": row.unit or "kg",
                "price_type": row.price_type or "spot",
            }

        # Add legacy commodity table items if not found in observations.
        latest_legacy = (
            db.query(CommodityPrice)
            .order_by(CommodityPrice.date_recorded.desc())
            .limit(500)
            .all()
        )
        for row in latest_legacy:
            name = (row.name or "").strip()
            if not name or name in options_map:
                continue
            options_map[name] = {
                "commodity_name": name,
                "category": "agriculture",
                "market": row.region or "Vietnam",
                "region": row.region or "Vietnam",
                "currency": "VND",
                "unit": "kg",
                "price_type": "spot",
            }

        options = sorted(options_map.values(), key=lambda x: x["commodity_name"].lower())
        return {"status": "success", "data": options}
    finally:
        db.close()


@app.get("/api/prices")
def get_prices():
    """Returns the latest commodity prices."""
    db = SessionLocal()
    try:
        data = []
        seafood_commodities = [
            "Tôm Sú (Black Tiger) 20 con/kg",
            "Tôm Sú (Black Tiger) 30 con/kg",
            "Tôm Sú (Black Tiger) 40 con/kg",
            "Tôm Thẻ (Vannamei)",
            "Cá Ba Sa (Pangasius)",
            "Cua Thịt (Mud Crab)",
            "Cua Gạch (Egg Crab)",
        ]
        seafood_set = frozenset(seafood_commodities)

        for c in seafood_commodities:
            records = (
                db.query(CommodityPrice)
                .filter(CommodityPrice.name == c)
                .order_by(CommodityPrice.date_recorded.desc())
                .limit(2)
                .all()
            )
            obs_rows = (
                db.query(PriceObservation)
                .filter(PriceObservation.commodity_name == c)
                .order_by(PriceObservation.observed_at.desc())
                .limit(2)
                .all()
            )
            leg_latest = records[0] if records else None
            leg_prev = records[1] if len(records) > 1 else None
            obs_latest = obs_rows[0] if obs_rows else None
            obs_prev = obs_rows[1] if len(obs_rows) > 1 else None
            leg_t = _dt_naive_utc(leg_latest.date_recorded) if leg_latest else None
            obs_t = _dt_naive_utc(obs_latest.observed_at) if obs_latest else None

            if obs_latest is None and leg_latest is None:
                continue
            if obs_latest is not None and (leg_latest is None or (obs_t and leg_t and obs_t >= leg_t)):
                prev_price = obs_prev.price if obs_prev else (leg_latest.price if leg_latest else obs_latest.price)
                price = obs_latest.price
                diff = price - prev_price
                diff_pct = (diff / prev_price * 100) if prev_price else 0
                data.append(
                    {
                        "name": obs_latest.commodity_name,
                        "price": price,
                        "unit": f"{obs_latest.currency}/{obs_latest.unit}",
                        "trend": "up" if diff >= 0 else "down",
                        "category": obs_latest.category,
                        "change_amt": round(diff, 2),
                        "change_pct": round(diff_pct, 2),
                    }
                )
            elif leg_latest:
                prev_price = leg_prev.price if leg_prev else leg_latest.price
                diff = leg_latest.price - prev_price
                diff_pct = (diff / prev_price * 100) if prev_price else 0
                data.append(
                    {
                        "name": leg_latest.name,
                        "price": leg_latest.price,
                        "unit": leg_latest.unit,
                        "trend": leg_latest.trend,
                        "change_amt": round(diff, 2),
                        "change_pct": round(diff_pct, 2),
                    }
                )

        rice_skip = _rice_skip_names()
        for canonical, aliases in RICE_BENCHMARKS:
            alias_list = list(aliases)
            records = (
                db.query(CommodityPrice)
                .filter(CommodityPrice.name.in_(alias_list))
                .order_by(CommodityPrice.date_recorded.desc())
                .limit(2)
                .all()
            )
            obs_rows = (
                db.query(PriceObservation)
                .filter(PriceObservation.commodity_name.in_(alias_list))
                .order_by(PriceObservation.observed_at.desc())
                .limit(2)
                .all()
            )
            leg_latest = records[0] if records else None
            leg_prev = records[1] if len(records) > 1 else None
            obs_latest = obs_rows[0] if obs_rows else None
            obs_prev = obs_rows[1] if len(obs_rows) > 1 else None
            leg_t = _dt_naive_utc(leg_latest.date_recorded) if leg_latest else None
            obs_t = _dt_naive_utc(obs_latest.observed_at) if obs_latest else None

            if obs_latest is None and leg_latest is None:
                continue
            if obs_latest is not None and (leg_latest is None or (obs_t and leg_t and obs_t >= leg_t)):
                prev_price = obs_prev.price if obs_prev else (leg_latest.price if leg_latest else obs_latest.price)
                price = obs_latest.price
                diff = price - prev_price
                diff_pct = (diff / prev_price * 100) if prev_price else 0
                data.append(
                    {
                        "name": canonical,
                        "price": price,
                        "unit": f"{obs_latest.currency}/{obs_latest.unit}",
                        "trend": "up" if diff >= 0 else "down",
                        "category": obs_latest.category,
                        "change_amt": round(diff, 2),
                        "change_pct": round(diff_pct, 2),
                    }
                )
            elif leg_latest:
                prev_price = leg_prev.price if leg_prev else leg_latest.price
                diff = leg_latest.price - prev_price
                diff_pct = (diff / prev_price * 100) if prev_price else 0
                data.append(
                    {
                        "name": canonical,
                        "price": leg_latest.price,
                        "unit": leg_latest.unit,
                        "trend": leg_latest.trend,
                        "change_amt": round(diff, 2),
                        "change_pct": round(diff_pct, 2),
                    }
                )

        # Pull rice/agriculture from normalized observations for richer coverage
        recent_obs = (
            db.query(PriceObservation)
            .filter(PriceObservation.category.in_(["rice", "agriculture", "livestock", "seafood", "other"]))
            .order_by(PriceObservation.observed_at.desc())
            .limit(500)
            .all()
        )
        grouped = {}
        for row in recent_obs:
            key = row.commodity_name
            if key in seafood_set or key in rice_skip:
                continue
            bucket = grouped.setdefault(key, [])
            if len(bucket) < 2:
                bucket.append(row)
        for name, rows in grouped.items():
            if (name or "").strip().lower() in {"việt nam", "vietnam", "thế giới", "world", "trong nước"}:
                continue
            latest = rows[0]
            prev_price = rows[1].price if len(rows) > 1 else latest.price
            diff = latest.price - prev_price
            diff_pct = (diff / prev_price * 100) if prev_price else 0
            data.append(
                {
                    "name": latest.commodity_name,
                    "price": latest.price,
                    "unit": f"{latest.currency}/{latest.unit}",
                    "trend": "up" if diff >= 0 else "down",
                    "category": latest.category,
                    "change_amt": round(diff, 2),
                    "change_pct": round(diff_pct, 2),
                }
            )
        return {"status": "success", "data": data}
    finally:
        db.close()


@app.post("/api/submit/price")
def submit_price(payload: SubmitPriceRequest, _auth: bool = Depends(verify_submit_basic)):
    """
    Upsert by logical key: same commodity + source + market + region + price_type
    updates the latest matching row instead of inserting another (avoids duplicate manual rows).
    """
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.UTC)
        name = payload.commodity_name.strip()
        market = payload.market.strip()
        region = payload.region.strip()
        source = payload.source.strip()
        price_type = payload.price_type.strip().lower()
        commodity_code = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:80]

        existing = (
            db.query(PriceObservation)
            .filter(
                PriceObservation.commodity_name == name,
                PriceObservation.source == source,
                PriceObservation.market == market,
                PriceObservation.region == region,
                PriceObservation.price_type == price_type,
            )
            .order_by(PriceObservation.observed_at.desc())
            .first()
        )
        if existing:
            existing.commodity_code = commodity_code
            existing.category = (payload.category or "agriculture").strip().lower()
            existing.subcategory = "manual"
            existing.price = payload.price
            existing.currency = payload.currency.strip().upper()
            existing.unit = payload.unit.strip().lower()
            existing.source_url = payload.source_url.strip()
            existing.observed_at = now
            existing.ingested_at = now
            existing.raw_payload = json.dumps(payload.model_dump(), ensure_ascii=False)
            db.commit()
            db.refresh(existing)
            return {
                "status": "success",
                "message": "Price updated (existing observation)",
                "data": {"id": existing.id, "observed_at": now.isoformat(), "updated": True},
            }

        obs = PriceObservation(
            commodity_code=commodity_code,
            commodity_name=name,
            category=(payload.category or "agriculture").strip().lower(),
            subcategory="manual",
            market=market,
            region=region,
            price=payload.price,
            currency=payload.currency.strip().upper(),
            unit=payload.unit.strip().lower(),
            price_type=price_type,
            source=source,
            source_url=payload.source_url.strip(),
            observed_at=now,
            raw_payload=json.dumps(payload.model_dump(), ensure_ascii=False),
        )
        db.add(obs)
        db.commit()
        db.refresh(obs)
        return {
            "status": "success",
            "message": "Price submitted",
            "data": {"id": obs.id, "observed_at": now.isoformat(), "updated": False},
        }
    finally:
        db.close()


@app.post("/api/submit/news")
def submit_news(payload: SubmitNewsRequest, _auth: bool = Depends(verify_submit_basic)):
    db = SessionLocal()
    try:
        now = datetime.datetime.now(datetime.UTC)
        link = payload.link.strip()
        title = payload.title.strip()
        source = payload.source.strip() or "manual_submit"
        description = (payload.description or "").strip()

        # Save main news record if missing
        exists = db.query(NewsArticle).filter(NewsArticle.link == link).first()
        if not exists:
            db.add(
                NewsArticle(
                    source=source,
                    title=title,
                    link=link,
                    date_published=now.strftime("%Y-%m-%d %H:%M"),
                    sentiment="Neutral",
                    ai_summary=description,
                )
            )

        selected_category = (payload.category or "").strip().lower()
        lowered = title.lower()
        allowed_cat = {"rice", "seafood", "agriculture", "fx", "logistics", "policy", "other"}
        resolved_category = selected_category if selected_category in allowed_cat else "other"
        if not selected_category:
            if "lúa" in lowered or "gạo" in lowered or "rice" in lowered:
                resolved_category = "rice"
            elif "tôm" in lowered or "cá" in lowered or "thủy sản" in lowered:
                resolved_category = "seafood"
            elif "tỷ giá" in lowered or "usd" in lowered:
                resolved_category = "fx"
            elif "vận chuyển" in lowered or "logistics" in lowered:
                resolved_category = "logistics"

        # Save normalized news if missing
        normalized_exists = db.query(NormalizedNews).filter(NormalizedNews.link == link).first()
        if not normalized_exists:
            db.add(
                NormalizedNews(
                    source=source,
                    category=resolved_category,
                    title=title,
                    summary=description,
                    link=link,
                    published_at=now,
                    impact_level="medium",
                    tags="manual_submit",
                )
            )

        # Try enrich from original URL and store markdown archive
        archive_exists = db.query(NewsContentArchive).filter(NewsContentArchive.news_link == link).first()
        if not archive_exists:
            fetched = fetch_article_content(link)
            archive_metadata = fetched.get("metadata", {}) if isinstance(fetched, dict) else {}
            if not fetched.get("ok"):
                archive_metadata = {
                    **archive_metadata,
                    "fetch_error": fetched.get("error", "content_extraction_failed"),
                    "fallback_mode": "metadata_only",
                    "manual_description": description,
                }
            archive_text = fetched.get("content_text", "") if fetched.get("ok") else description
            content_store_dir = Path(__file__).resolve().parent / "content_store"
            content_store_dir.mkdir(parents=True, exist_ok=True)
            md_path = persist_article_markdown(
                base_dir=str(content_store_dir),
                source=source,
                title=title,
                link=link,
                content_text=archive_text,
                metadata=archive_metadata,
                folder_type=payload.folder_type or "agriculture_news",
            )
            db.add(
                NewsContentArchive(
                    news_link=link,
                    source=source,
                    title=title,
                    markdown_path=md_path,
                    content_text=archive_text[:20000],
                    content_hash=fetched.get("content_hash", "") if fetched.get("ok") else "",
                    metadata_json=json.dumps(archive_metadata, ensure_ascii=False),
                    fetched_at=now,
                )
            )

        db.add(
            SubmitNewsLog(
                link=link,
                title=title,
                source=source,
                category=resolved_category,
                folder_type=(payload.folder_type or "agriculture_news").strip(),
                description_preview=(description or "")[:500],
                submitted_at=now,
            )
        )

        db.commit()
        return {"status": "success", "message": "News submitted and archived"}
    finally:
        db.close()


@app.get("/api/submit/crawler-sources")
def list_crawler_sources(_auth: bool = Depends(verify_submit_basic)):
    from crawler_sources import ensure_crawler_sources

    db = SessionLocal()
    try:
        ensure_crawler_sources(db)
        rows = (
            db.query(CrawlerSource)
            .order_by(CrawlerSource.category, CrawlerSource.sort_order, CrawlerSource.label)
            .all()
        )
        return {
            "status": "success",
            "data": [
                {
                    "slug": r.slug,
                    "label": r.label,
                    "category": r.category,
                    "description": r.description or "",
                    "enabled": bool(r.enabled),
                    "sort_order": r.sort_order,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@app.patch("/api/submit/crawler-sources/{slug}")
def patch_crawler_source(
    slug: str,
    body: CrawlerSourcePatch,
    _auth: bool = Depends(verify_submit_basic),
):
    db = SessionLocal()
    try:
        row = db.query(CrawlerSource).filter(CrawlerSource.slug == slug.strip()).first()
        if not row:
            raise HTTPException(status_code=404, detail="Unknown crawler source slug")
        row.enabled = bool(body.enabled)
        db.commit()
        return {"status": "success", "data": {"slug": row.slug, "enabled": row.enabled}}
    finally:
        db.close()


@app.get("/api/submit/news/history")
def list_submit_news_history(_auth: bool = Depends(verify_submit_basic), limit: int = Query(80, ge=1, le=200)):
    db = SessionLocal()
    try:
        rows = (
            db.query(SubmitNewsLog)
            .order_by(SubmitNewsLog.submitted_at.desc())
            .limit(limit)
            .all()
        )
        data = [
            {
                "id": r.id,
                "title": r.title,
                "link": r.link,
                "source": r.source,
                "category": r.category,
                "folder_type": r.folder_type,
                "description_preview": r.description_preview,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in rows
        ]
        return {"status": "success", "data": data}
    finally:
        db.close()


@app.delete("/api/submit/news/history/{log_id}")
def delete_submit_news_history(log_id: int, _auth: bool = Depends(verify_submit_basic)):
    db = SessionLocal()
    try:
        log_row = db.query(SubmitNewsLog).filter(SubmitNewsLog.id == log_id).first()
        if not log_row:
            raise HTTPException(status_code=404, detail="History record not found")
        link = log_row.link
        db.delete(log_row)

        db.query(NewsArticle).filter(NewsArticle.link == link).delete(synchronize_session=False)
        db.query(NormalizedNews).filter(NormalizedNews.link == link).delete(synchronize_session=False)

        arch = db.query(NewsContentArchive).filter(NewsContentArchive.news_link == link).first()
        if arch:
            md_path = arch.markdown_path
            db.delete(arch)
            try:
                if md_path:
                    p = Path(md_path)
                    if p.is_file():
                        p.unlink()
            except OSError:
                pass

        db.commit()
        return {"status": "success", "message": "Submit news record and linked data removed"}
    finally:
        db.close()

@app.get("/api/history/{commodity}")
def get_history(commodity: str, range_key: str = Query("7d", alias="range")):
    db = SessionLocal()
    try:
        days = 7
        if range_key == "30d":
            days = 30
        elif range_key == "6m":
            days = 180
        elif range_key == "1y":
            days = 365
        elif range_key == "1d":
            days = 1
        
        limit_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        names = _expand_rice_history_names(commodity)
        history = db.query(CommodityPrice).filter(
            CommodityPrice.name.in_(names),
            CommodityPrice.date_recorded >= limit_date,
        ).order_by(CommodityPrice.date_recorded.asc()).all()

        obs_history = (
            db.query(PriceObservation)
            .filter(
                PriceObservation.commodity_name.in_(names),
                PriceObservation.observed_at >= limit_date,
            )
            .order_by(PriceObservation.observed_at.asc())
            .all()
        )
        if not history and not obs_history:
            return {"status": "error", "message": "No data found"}
        labels, prices = _merge_cp_and_obs_history(history, obs_history, range_key)
        return {"status": "success", "data": {"labels": labels, "prices": prices, "name": commodity}}
    finally:
        db.close()

@app.get("/api/regional-prices")
def get_regional_prices_api():
    """Returns regional pricing breakdown."""
    from crawler import get_regional_prices
    return get_regional_prices()

@app.get("/api/news")
def get_news():
    """Returns the latest agriculture news purely dense."""
    db = SessionLocal()
    try:
        articles = db.query(NewsArticle).order_by(NewsArticle.date_scraped.desc()).limit(120).all()
        data = []
        for a in articles:
            if news_item_is_nav_noise(a.link, a.title):
                continue
            data.append({
                "source": a.source,
                "title": a.title,
                "link": a.link,
                "date": a.date_published,
            })
            if len(data) >= 35:
                break
        if not data:
            from crawler import get_latest_news
            from crawler_sources import get_enabled_crawler_slugs

            return get_latest_news(active_slugs=get_enabled_crawler_slugs(db))
        return {"status": "success", "data": data}
    finally:
        db.close()

@app.get("/api/stocks")
def get_stocks():
    db = SessionLocal()
    try:
        live_quotes = fetch_live_stock_quotes()
        live_map = {q["symbol"]: q for q in live_quotes}
        watchlist = get_stock_watchlist()
        symbols = [item["symbol"] for item in watchlist]
        meta_map = {item["symbol"]: item for item in watchlist}
        response = []
        for symbol in symbols:
            live = live_map.get(symbol)
            if live:
                response.append(live)
                continue

            records = (
                db.query(StockPrice)
                .filter(StockPrice.symbol == symbol)
                .order_by(StockPrice.date_recorded.desc())
                .limit(2)
                .all()
            )
            if not records:
                # Keep full watchlist visible even when no data yet
                meta = meta_map.get(symbol, {})
                response.append(
                    {
                        "symbol": symbol,
                        "name": meta.get("name", symbol),
                        "price": 0.0,
                        "currency": "VND",
                        "market": meta.get("market", "VN"),
                        "exchange": meta.get("exchange", "VN"),
                        "trend": "up",
                        "change_amt": 0.0,
                        "change_pct": 0.0,
                        "links": get_stock_tracking_links(symbol),
                    }
                )
                continue
            latest = records[0]
            prev_price = records[1].price if len(records) > 1 else latest.price
            change_amt = latest.price - prev_price
            change_pct = (change_amt / prev_price * 100) if prev_price else 0
            response.append(
                {
                    "symbol": latest.symbol,
                    "name": meta_map.get(latest.symbol, {}).get("name", latest.name),
                    "price": latest.price,
                    "currency": latest.currency,
                    "market": latest.market,
                    "exchange": meta_map.get(latest.symbol, {}).get("exchange", "VN"),
                    "trend": "up" if change_amt >= 0 else "down",
                    "change_amt": round(change_amt, 2),
                    "change_pct": round(change_pct, 2),
                    "links": get_stock_tracking_links(latest.symbol),
                }
            )
        return {"status": "success", "data": response}
    finally:
        db.close()


@app.get("/api/stocks/history/{symbol}")
def get_stock_history(symbol: str, range_key: str = Query("7d", alias="range")):
    db = SessionLocal()
    try:
        days = 7
        if range_key == "30d":
            days = 30
        elif range_key == "6m":
            days = 180
        elif range_key == "1y":
            days = 365
        elif range_key == "1d":
            days = 1
        limit_date = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        history = (
            db.query(StockPrice)
            .filter(
                StockPrice.symbol == symbol.upper(),
                StockPrice.date_recorded >= limit_date,
            )
            .order_by(StockPrice.date_recorded.asc())
            .all()
        )
        if not history:
            return {"status": "error", "message": "No data found"}
        labels = [h.date_recorded.strftime("%m-%d") if range_key != "1d" else h.date_recorded.strftime("%H:%M") for h in history]
        prices = [h.price for h in history]
        return {"status": "success", "data": {"labels": labels, "prices": prices, "symbol": symbol.upper()}}
    finally:
        db.close()


@app.get("/api/insights/dashboard")
def get_dashboard_insights():
    db = SessionLocal()
    try:
        # Latest normalized rice prices for alerts
        latest_rice = (
            db.query(PriceObservation)
            .filter(PriceObservation.category == "rice")
            .order_by(PriceObservation.observed_at.desc())
            .limit(50)
            .all()
        )

        rice_price = None
        for r in latest_rice:
            name = (r.commodity_name or "").lower()
            if "ir504" in name or "lúa" in name:
                rice_price = r
                break

        top_alerts = []
        if rice_price:
            if rice_price.price < 5200:
                top_alerts.append({"level": "high", "text": f"HIGH RISK: Giá lúa {rice_price.commodity_name} < 5,200 VND/kg (Break support)"})
            else:
                top_alerts.append({"level": "low", "text": f"LOW: Giá lúa {rice_price.commodity_name} duy trì {round(rice_price.price, 0):,.0f} VND/kg"})
        else:
            top_alerts.append({"level": "medium", "text": "MEDIUM: Chưa đủ dữ liệu lúa gạo để đánh giá risk theo ngưỡng"})

        # Add weather/logistics placeholders as operational alerts from latest news
        latest_news = (
            db.query(NormalizedNews)
            .order_by(NormalizedNews.ingested_at.desc())
            .limit(80)
            .all()
        )
        latest_news = [n for n in latest_news if not news_item_is_nav_noise(n.link, n.title)]
        weather_hit = next((n for n in latest_news if "mưa" in n.title.lower() or "thời tiết" in n.title.lower()), None)
        logistics_hit = next((n for n in latest_news if "vận chuyển" in n.title.lower() or "chi phí" in n.title.lower() or "logistics" in n.title.lower()), None)
        if weather_hit:
            top_alerts.append({"level": "medium", "text": f"MEDIUM: {weather_hit.title}"})
        if logistics_hit:
            top_alerts.append({"level": "medium", "text": f"MEDIUM: {logistics_hit.title}"})
        if len(top_alerts) < 3:
            top_alerts.append({"level": "low", "text": "LOW: Giá tôm sú ổn định, biên lợi nhuận duy trì tích cực"})
        top_alerts = top_alerts[:3]

        # News & alerts block
        news_alerts = []
        for n in latest_news[:8]:
            icon = "📰"
            if n.impact_level == "high":
                icon = "🔥"
            elif n.category == "fx":
                icon = "💹"
            elif n.category == "logistics":
                icon = "🛳️"
            news_alerts.append({"icon": icon, "text": n.title, "link": n.link, "source": n.source})

        # Export analytics from DB (derived + direct observations)
        period = datetime.datetime.utcnow().strftime("%m/%Y")
        top_markets_rows = (
            db.query(ExportMarketStat)
            .filter(ExportMarketStat.period_label == period)
            .order_by(ExportMarketStat.volume.desc())
            .limit(5)
            .all()
        )
        top_markets = []
        for idx, row in enumerate(top_markets_rows, 1):
            up_down = "↑" if (row.change_pct or 0) >= 0 else "↓"
            pct_val = abs(round(row.change_pct or 0.0, 1))
            vol = f"{row.volume:.0f} {row.volume_unit}" if row.volume is not None else "N/A"
            top_markets.append(f"{idx}. {row.market_name}: {vol} ({up_down}{pct_val}%)")
        if not top_markets:
            top_markets = [
                "1. Chưa có dữ liệu thị trường xuất khẩu đủ tin cậy",
                "2. Hệ thống đang chờ ingest thêm từ VFA/AGROINFO",
                "3. Vui lòng chạy backfill hoặc scraper định kỳ",
            ]

        # FOB/CIF spread from rice observations if available
        rice_obs = (
            db.query(PriceObservation)
            .filter(PriceObservation.category == "rice")
            .order_by(PriceObservation.observed_at.desc())
            .limit(200)
            .all()
        )
        fob_price = next((r for r in rice_obs if "fob" in (r.price_type or "").lower()), None)
        cif_price = next((r for r in rice_obs if "cif" in (r.price_type or "").lower()), None)
        fob_cif = []
        if fob_price and cif_price and fob_price.price:
            delta_pct = ((cif_price.price - fob_price.price) / fob_price.price) * 100
            fob_cif.append(
                {
                    "label": "Gạo (FOB → CIF)",
                    "from_price": fob_price.price,
                    "to_price": cif_price.price,
                    "unit": fob_price.unit or "USD/ton",
                    "delta_pct": round(delta_pct, 2),
                }
            )
        else:
            # fallback from most recent rice spot record (support lúa/gạo/rice naming)
            spot = next(
                (
                    r
                    for r in rice_obs
                    if any(k in (r.commodity_name or "").lower() for k in ["gạo", "lúa", "rice"])
                ),
                None,
            )
            if spot:
                fob_cif.append(
                    {
                        "label": "Gạo 5% (proxy spread)",
                        "from_price": round(spot.price * 0.96, 2),
                        "to_price": spot.price,
                        "unit": f"{spot.currency}/{spot.unit}",
                        "delta_pct": 4.17,
                    }
                )
            else:
                fob_cif.append(
                    {
                        "label": "FOB/CIF",
                        "from_price": "N/A",
                        "to_price": "N/A",
                        "unit": "",
                        "delta_pct": 0.0,
                    }
                )

        # Optional AI-generated alert enrichment (requires GEMINI_API_KEY in env)
        ai_alerts = _safe_generate_ai_alerts(
            {
                "rice_price": rice_price.price if rice_price else None,
                "recent_news": [n.title for n in latest_news[:8]],
                "top_markets": top_markets,
                "fob_cif_spread": fob_cif,
            }
        )
        if ai_alerts:
            top_alerts = ai_alerts

        return {
            "status": "success",
            "data": {
                "top_alerts": top_alerts,
                "news_alerts": news_alerts,
                "export_analytics": {
                    "period": period,
                    "top_markets": top_markets,
                    "fob_cif_spread": fob_cif,
                },
            },
        }
    finally:
        db.close()


@app.post("/api/backfill/prices")
def backfill_prices(days: int = Query(30, ge=1, le=90)):
    from scraper_job import run_scraper
    run_scraper(backfill_days=days)
    return {"status": "success", "message": f"Backfill completed for last {days} days"}


@app.get("/api/stocks/news")
def get_stock_news():
    db = SessionLocal()
    try:
        from crawler_sources import get_enabled_crawler_slugs

        data = get_stock_market_news(active_slugs=get_enabled_crawler_slugs(db))
        return {"status": "success", "data": data}
    finally:
        db.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
