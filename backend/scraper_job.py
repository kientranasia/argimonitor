from database import SessionLocal, engine, Base
from models import (
    CommodityPrice,
    NewsArticle,
    StockPrice,
    PriceObservation,
    NormalizedNews,
    ExportMarketStat,
    NewsContentArchive,
)
import crawler
import datetime
import random
from pathlib import Path
import json

def recreate_db():
    Base.metadata.create_all(bind=engine)

def seed_historical_prices():
    """Generates 30 days of synthetic historical data for commodities if empty."""
    db = SessionLocal()
    
    commodities = [
        {"name": "Tôm Sú (Black Tiger)", "base": 220000},
        {"name": "Tôm Thẻ (Vannamei)", "base": 145000},
        {"name": "Cá Ba Sa (Pangasius)", "base": 28500},
        {"name": "Cua Thịt (Mud Crab)", "base": 350000},
        {"name": "Cua Gạch (Egg Crab)", "base": 520000},
        {"name": "Lúa Thường (IR50404)", "base": 8500},
        {"name": "Gạo Xuất Khẩu 5%", "base": 16000},
        {"name": "Cà Phê (Robusta)", "base": 95000},
        {"name": "Hồ Tiêu (Đắk Lắk)", "base": 93000}
    ]
    
    # Check if we already seeded
    first_com = db.query(CommodityPrice).filter(CommodityPrice.name == commodities[0]["name"]).first()
    if not first_com:
        print("Seeding 30-day historical data for Agriculture & Seafood...")
        now = datetime.datetime.now(datetime.UTC)
        for com in commodities:
            current_price = com["base"]
            for i in range(30, -1, -1):
                variance = current_price * 0.02
                current_price = round(current_price + random.uniform(-variance, variance))
                trend = "up" if random.random() > 0.5 else "down"
                
                record_date = now - datetime.timedelta(days=i)
                price_record = CommodityPrice(
                    name=com["name"],
                    price=current_price,
                    unit="VND/kg",
                    trend=trend,
                    date_recorded=record_date
                )
                db.add(price_record)
        db.commit()
    db.close()


def seed_historical_stocks():
    """Generates 30 days of synthetic historical data for tracked stocks if empty."""
    db = SessionLocal()
    watchlist = crawler.get_stock_watchlist()
    stocks = []
    for item in watchlist:
        base_price = random.uniform(12, 80)
        stocks.append(
            {
                "symbol": item["symbol"],
                "name": item["name"],
                "price": round(base_price, 2),
                "currency": "VND",
                "market": item["market"],
            }
        )

    missing_stocks = []
    for stock in stocks:
        exists = db.query(StockPrice).filter(StockPrice.symbol == stock["symbol"]).first()
        if not exists:
            missing_stocks.append(stock)

    if missing_stocks:
        print("Seeding 30-day historical data for aquaculture equities...")
        now = datetime.datetime.now(datetime.UTC)
        for stock in missing_stocks:
            current_price = stock["price"]
            for i in range(30, -1, -1):
                variance = current_price * 0.02
                current_price = round(current_price + random.uniform(-variance, variance), 2)
                record_date = now - datetime.timedelta(days=i)
                db.add(
                    StockPrice(
                        symbol=stock["symbol"],
                        name=stock["name"],
                        price=current_price,
                        currency=stock["currency"],
                        market=stock["market"],
                        date_recorded=record_date,
                    )
                )
        db.commit()
    db.close()

def run_scraper(backfill_days: int = 0):
    print("Starting scraper job...")
    db = SessionLocal()
    try:
        # 1. Generate/Scraping new price for today dynamically
        # Since MVP uses synthetic random jumps from the latest day
        latest_prices_group = [
            "Tôm Sú (Black Tiger)", "Tôm Thẻ (Vannamei)", "Cá Ba Sa (Pangasius)", 
            "Cua Thịt (Mud Crab)", "Cua Gạch (Egg Crab)", 
            "Lúa Thường (IR50404)", "Gạo Xuất Khẩu 5%", "Cà Phê (Robusta)", "Hồ Tiêu (Đắk Lắk)"
        ]
        for name in latest_prices_group:
            latest = db.query(CommodityPrice).filter(CommodityPrice.name == name).order_by(CommodityPrice.date_recorded.desc()).first()
            if latest:
                variance = latest.price * 0.01
                new_price = round(latest.price + random.uniform(-variance, variance))
                trend = "up" if new_price > latest.price else "down"
                
                price_record = CommodityPrice(
                    name=name,
                    price=new_price,
                    unit="VND/kg",
                    trend=trend,
                    date_recorded=datetime.datetime.now(datetime.UTC)
                )
                db.add(price_record)
        
        db.commit()

        # 1.1 Create today's stock snapshot from latest value
        live_quotes = crawler.fetch_live_stock_quotes()
        if live_quotes:
            for quote in live_quotes:
                db.add(
                    StockPrice(
                        symbol=quote["symbol"],
                        name=quote["name"],
                        price=max(0.01, quote["price"]),
                        currency=quote["currency"],
                        market=quote["market"],
                        date_recorded=datetime.datetime.now(datetime.UTC),
                    )
                )
        else:
            tracked_symbols = [item["symbol"] for item in crawler.get_stock_watchlist()]
            for symbol in tracked_symbols:
                latest_stock = (
                    db.query(StockPrice)
                    .filter(StockPrice.symbol == symbol)
                    .order_by(StockPrice.date_recorded.desc())
                    .first()
                )
                if latest_stock:
                    variance = latest_stock.price * 0.015
                    new_price = round(latest_stock.price + random.uniform(-variance, variance), 2)
                    db.add(
                        StockPrice(
                            symbol=latest_stock.symbol,
                            name=latest_stock.name,
                            price=max(0.01, new_price),
                            currency=latest_stock.currency,
                            market=latest_stock.market,
                            date_recorded=datetime.datetime.now(datetime.UTC),
                        )
                    )
        db.commit()

        # 2. Scrape News (Now pulls 30-40 articles fast w/o Gemini)
        news_data = crawler.get_latest_news()["data"]
        content_store_dir = Path(__file__).resolve().parent / "content_store"
        content_store_dir.mkdir(parents=True, exist_ok=True)
        for article in news_data:
            if article.get("link") == "#":
                continue
            exists = db.query(NewsArticle).filter(NewsArticle.link == article["link"]).first()
            if not exists:
                news_record = NewsArticle(
                    source=article["source"],
                    title=article["title"],
                    link=article["link"],
                    date_published=article["date"],
                    sentiment=article["sentiment"],
                    image_url=article["image"],
                    ai_summary=article.get("ai_summary", "")
                )
                db.add(news_record)

            normalized_exists = db.query(NormalizedNews).filter(NormalizedNews.link == article["link"]).first()
            if not normalized_exists:
                title = article.get("title", "")
                category = "other"
                lowered = title.lower()
                if "lúa" in lowered or "gạo" in lowered or "rice" in lowered:
                    category = "rice"
                elif "tôm" in lowered or "cá" in lowered or "thủy sản" in lowered:
                    category = "seafood"
                elif "tỷ giá" in lowered or "usd" in lowered:
                    category = "fx"
                elif "vận chuyển" in lowered or "logistics" in lowered:
                    category = "logistics"

                impact_level = "medium"
                if any(k in lowered for k in ["tăng mạnh", "giảm mạnh", "rủi ro", "khủng hoảng"]):
                    impact_level = "high"
                elif any(k in lowered for k in ["ổn định", "duy trì", "tích cực"]):
                    impact_level = "low"

                db.add(
                    NormalizedNews(
                        source=article.get("source", "Unknown"),
                        category=category,
                        title=title,
                        summary=article.get("ai_summary", "") or "",
                        link=article["link"],
                        published_at=None,
                        impact_level=impact_level,
                        tags="",
                    )
                )

            # Archive full content in DB + markdown store (best-effort)
            archive_exists = db.query(NewsContentArchive).filter(NewsContentArchive.news_link == article["link"]).first()
            if not archive_exists:
                fetched = crawler.fetch_article_content(article["link"])
                if fetched.get("ok"):
                    title = article.get("title") or fetched.get("title") or "Untitled"
                    md_path = crawler.persist_article_markdown(
                        base_dir=str(content_store_dir),
                        source=article.get("source", "Unknown"),
                        title=title,
                        link=article["link"],
                        content_text=fetched.get("content_text", ""),
                        metadata=fetched.get("metadata", {}),
                        folder_type="agriculture_news",
                    )
                    db.add(
                        NewsContentArchive(
                            news_link=article["link"],
                            source=article.get("source", "Unknown"),
                            title=title,
                            markdown_path=md_path,
                            content_text=fetched.get("content_text", "")[:20000],
                            content_hash=fetched.get("content_hash", ""),
                            metadata_json=json.dumps(fetched.get("metadata", {}), ensure_ascii=False),
                            fetched_at=datetime.datetime.now(datetime.UTC),
                        )
                    )

        stock_news = crawler.get_stock_market_news()
        for article in stock_news:
            link = article.get("link")
            if not link:
                continue
            archive_exists = db.query(NewsContentArchive).filter(NewsContentArchive.news_link == link).first()
            if archive_exists:
                continue
            fetched = crawler.fetch_article_content(link)
            title = article.get("title") or fetched.get("title") or "Untitled"
            archive_metadata = fetched.get("metadata", {}) if isinstance(fetched, dict) else {}
            if not fetched.get("ok"):
                archive_metadata = {
                    **archive_metadata,
                    "fetch_error": fetched.get("error", "content_extraction_failed"),
                    "fallback_mode": "metadata_only",
                }
            archive_text = fetched.get("content_text", "") if fetched.get("ok") else ""
            md_path = crawler.persist_article_markdown(
                base_dir=str(content_store_dir),
                source=article.get("source", "Stock News"),
                title=title,
                link=link,
                content_text=archive_text,
                metadata=archive_metadata,
                folder_type="stock_news",
            )
            db.add(
                NewsContentArchive(
                    news_link=link,
                    source=article.get("source", "Stock News"),
                    title=title,
                    markdown_path=md_path,
                    content_text=archive_text[:20000],
                    content_hash=fetched.get("content_hash", "") if fetched.get("ok") else "",
                    metadata_json=json.dumps(archive_metadata, ensure_ascii=False),
                    fetched_at=datetime.datetime.now(datetime.UTC),
                )
            )
        
        db.commit()

        # 3. Scrape normalized price observations from VFA + AGROINFO
        if backfill_days and backfill_days > 0:
            normalized_prices = crawler.get_normalized_price_observations_with_backfill(days=backfill_days)
        else:
            normalized_prices = crawler.get_normalized_price_observations()
        for obs in normalized_prices:
            if obs.get("price") is None or obs.get("price") <= 0:
                continue
            # de-dup by source + item + market + price + day bucket
            observed_at = obs.get("observed_at") or datetime.datetime.now(datetime.UTC)
            day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + datetime.timedelta(days=1)
            exists = (
                db.query(PriceObservation)
                .filter(
                    PriceObservation.source == obs.get("source"),
                    PriceObservation.commodity_name == obs.get("commodity_name"),
                    PriceObservation.market == obs.get("market"),
                    PriceObservation.price == obs.get("price"),
                    PriceObservation.observed_at >= day_start,
                    PriceObservation.observed_at < day_end,
                )
                .first()
            )
            if exists:
                continue
            db.add(
                PriceObservation(
                    commodity_code=obs.get("commodity_code"),
                    commodity_name=obs.get("commodity_name"),
                    category=obs.get("category"),
                    subcategory=obs.get("subcategory"),
                    market=obs.get("market"),
                    region=obs.get("region"),
                    price=obs.get("price"),
                    currency=obs.get("currency", "VND"),
                    unit=obs.get("unit", "kg"),
                    price_type=obs.get("price_type"),
                    source=obs.get("source"),
                    source_url=obs.get("source_url"),
                    observed_at=obs.get("observed_at") or datetime.datetime.now(datetime.UTC),
                    raw_payload=obs.get("raw_payload", ""),
                )
            )
        db.commit()

        # 4. Derived export market stats from normalized news mentions (lightweight until dedicated feed)
        latest_news = (
            db.query(NormalizedNews)
            .order_by(NormalizedNews.ingested_at.desc())
            .limit(150)
            .all()
        )
        market_keywords = {
            "Philippines": ["philippines"],
            "Ghana": ["ghana"],
            "USA": ["usa", "hoa kỳ", "my "],
            "China": ["trung quốc", "china"],
            "Japan": ["nhật bản", "japan"],
            "EU": ["eu", "châu âu", "europe"],
        }
        market_counts = {k: 0 for k in market_keywords}
        for n in latest_news:
            text = f"{n.title} {n.summary}".lower()
            for market, keywords in market_keywords.items():
                if any(k in text for k in keywords):
                    market_counts[market] += 1
        top_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        for market_name, mention_count in top_markets:
            if mention_count <= 0:
                continue
            exists = (
                db.query(ExportMarketStat)
                .filter(
                    ExportMarketStat.period_label == datetime.datetime.now(datetime.UTC).strftime("%m/%Y"),
                    ExportMarketStat.market_name == market_name,
                    ExportMarketStat.source == "DERIVED_NEWS",
                )
                .first()
            )
            if exists:
                exists.volume = float(mention_count)
                exists.observed_at = datetime.datetime.now(datetime.UTC)
            else:
                db.add(
                    ExportMarketStat(
                        period_label=datetime.datetime.now(datetime.UTC).strftime("%m/%Y"),
                        market_name=market_name,
                        commodity="rice",
                        volume=float(mention_count),
                        volume_unit="mentions",
                        change_pct=0.0,
                        source="DERIVED_NEWS",
                        source_url="internal://normalized_news_mentions",
                        observed_at=datetime.datetime.now(datetime.UTC),
                    )
                )
        db.commit()
        print("Scraper job completed and DB updated.")
    except Exception as e:
        print(f"Scraper error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    recreate_db()
    seed_historical_prices()
    seed_historical_stocks()
    run_scraper(backfill_days=30)
