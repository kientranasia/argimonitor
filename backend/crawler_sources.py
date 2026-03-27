"""Registry + DB seed for crawler feed toggles (see /api/submit/crawler-sources)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models import CrawlerSource

DEFAULT_CRAWLER_SOURCES: tuple[dict, ...] = (
    {
        "slug": "price_agroinfo",
        "label": "AGROINFO — giá (agro.gov.vn)",
        "category": "price",
        "description": "Quan sát giá lúa/gạo và thị trường từ cổng AgroInfo.",
        "sort_order": 10,
    },
    {
        "slug": "price_vfa_latest",
        "label": "VFA — bảng giá lúa/gạo (vietfood.org.vn)",
        "category": "price",
        "description": "Giá hiện hành từ Hiệp hội Lương thực Việt Nam.",
        "sort_order": 20,
    },
    {
        "slug": "price_vfa_history",
        "label": "VFA — lịch sử giá (backfill)",
        "category": "price",
        "description": "Chỉ chạy khi crawler có tham số backfill_days > 0.",
        "sort_order": 30,
    },
    {
        "slug": "news_tepbac",
        "label": "Tepbac",
        "category": "news",
        "description": "Tin thủy sản / nông nghiệp (tepbac.com).",
        "sort_order": 110,
    },
    {
        "slug": "news_vnexpress",
        "label": "VNExpress (Hàng hóa)",
        "category": "news",
        "description": "Mục hàng hóa trên VnExpress.",
        "sort_order": 120,
    },
    {
        "slug": "news_intrafish",
        "label": "IntraFish",
        "category": "news",
        "description": "Tin thủy sản quốc tế.",
        "sort_order": 130,
    },
    {
        "slug": "news_agromonitor",
        "label": "AgroMonitor",
        "category": "news",
        "description": "Tin từ kênh AgroMonitor.",
        "sort_order": 140,
    },
    {
        "slug": "news_agroinfo",
        "label": "AGROINFO — tin (agro.gov.vn)",
        "category": "news",
        "description": "Tin trên cổng Bộ NN&PTNT.",
        "sort_order": 150,
    },
    {
        "slug": "news_vitic",
        "label": "VITIC",
        "category": "news",
        "description": "Tin từ VITIC.",
        "sort_order": 160,
    },
    {
        "slug": "stock_news_vietstock",
        "label": "Vietstock RSS (chứng khoán)",
        "category": "stock_news",
        "description": "RSS thị trường chứng khoán — lưu archive .md.",
        "sort_order": 210,
    },
    {
        "slug": "stock_news_cafef",
        "label": "CafeF RSS (chứng khoán)",
        "category": "stock_news",
        "description": "RSS CafeF — lưu archive .md.",
        "sort_order": 220,
    },
)


def ensure_crawler_sources(db: Session) -> None:
    """Insert missing rows; leave existing toggles as-is."""
    for row in DEFAULT_CRAWLER_SOURCES:
        exists = db.query(CrawlerSource).filter(CrawlerSource.slug == row["slug"]).first()
        if exists:
            continue
        db.add(
            CrawlerSource(
                slug=row["slug"],
                label=row["label"],
                category=row["category"],
                description=row.get("description") or "",
                enabled=True,
                sort_order=row.get("sort_order") or 0,
            )
        )
    db.commit()


def get_enabled_crawler_slugs(db: Session) -> frozenset[str]:
    ensure_crawler_sources(db)
    rows = db.query(CrawlerSource.slug).filter(CrawlerSource.enabled.is_(True)).all()
    return frozenset(r[0] for r in rows)
