from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from database import Base
import datetime

class CommodityPrice(Base):
    __tablename__ = "commodity_prices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    price = Column(Float)
    unit = Column(String)
    region = Column(String, index=True)
    date_recorded = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    trend = Column(String, default="ổn định") # up, down, stable

class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String)
    title = Column(String)
    link = Column(String, unique=True, index=True)
    image_url = Column(String, nullable=True)
    date_published = Column(String)
    sentiment = Column(String)
    ai_summary = Column(String)
    date_scraped = Column(DateTime, default=datetime.datetime.utcnow)


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    name = Column(String)
    price = Column(Float)
    currency = Column(String)
    market = Column(String, index=True)
    date_recorded = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id = Column(Integer, primary_key=True, index=True)
    commodity_code = Column(String, index=True)
    commodity_name = Column(String, index=True)
    category = Column(String, index=True)  # rice, seafood, agriculture, livestock, other
    subcategory = Column(String, index=True)
    market = Column(String, index=True)
    region = Column(String, index=True)
    price = Column(Float, index=True)
    currency = Column(String, default="VND")
    unit = Column(String, default="kg")
    price_type = Column(String)
    source = Column(String, index=True)
    source_url = Column(String)
    observed_at = Column(DateTime, index=True)
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    raw_payload = Column(Text)


class NormalizedNews(Base):
    __tablename__ = "normalized_news"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, index=True)
    category = Column(String, index=True)  # rice, seafood, agriculture, logistics, fx, policy, other
    title = Column(String)
    summary = Column(Text, default="")
    link = Column(String, unique=True, index=True)
    published_at = Column(DateTime, nullable=True, index=True)
    impact_level = Column(String, default="medium", index=True)  # high, medium, low
    tags = Column(String, default="")
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class ExportMarketStat(Base):
    __tablename__ = "export_market_stats"

    id = Column(Integer, primary_key=True, index=True)
    period_label = Column(String, index=True)  # e.g. 03/2026
    market_name = Column(String, index=True)
    commodity = Column(String, index=True)
    volume = Column(Float, nullable=True)
    volume_unit = Column(String, default="ton")
    change_pct = Column(Float, nullable=True)
    source = Column(String, index=True)
    source_url = Column(String)
    observed_at = Column(DateTime, index=True)
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class NewsContentArchive(Base):
    __tablename__ = "news_content_archive"

    id = Column(Integer, primary_key=True, index=True)
    news_link = Column(String, unique=True, index=True)
    source = Column(String, index=True)
    title = Column(String)
    markdown_path = Column(String, index=True)
    content_text = Column(Text)
    content_hash = Column(String, index=True)
    metadata_json = Column(Text, default="{}")
    fetched_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class SubmitNewsLog(Base):
    """Audit/history rows for POST /api/submit/news (UI + n8n)."""

    __tablename__ = "submit_news_log"

    id = Column(Integer, primary_key=True, index=True)
    link = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    source = Column(String, index=True, default="manual_submit")
    category = Column(String, default="other", index=True)
    folder_type = Column(String, default="agriculture_news")
    description_preview = Column(String, default="")
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
