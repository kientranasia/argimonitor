# Argimonitor

Dashboard theo dõi giá nông sản + thủy sản, cổ phiếu liên quan, tin tức và dữ liệu insight.

<img width="2048" height="1272" alt="image" src="https://github.com/user-attachments/assets/ec1e4fe2-6535-4d4c-aeac-17e376531e9a" />


## Mã nguồn mở

- **Giấy phép:** [MIT](LICENSE)
- **Repository:** [github.com/kientranasia/argimonitor](https://github.com/kientranasia/argimonitor)
- **Đóng góp:** xem [CONTRIBUTING.md](CONTRIBUTING.md)
- **Bảo mật:** xem [SECURITY.md](SECURITY.md)

Clone nhanh:

```bash
git clone git@github.com:kientranasia/argimonitor.git
cd argimonitor
cp .env.example .env
```

> Không commit file `.env` hay API key. Chỉ dùng `.env.example` làm mẫu.

## 1) Kiến trúc

Project chay bang Docker Compose voi 3 service:

- `frontend`: React build static + Nginx (public port `8085:80` mac dinh)
- `backend`: FastAPI (noi bo, expose `8000` cho frontend/crawler)
- `crawler`: job thu thap du lieu dinh ky, chay moi 30 phut

Luong request:

- Trinh duyet -> `http://localhost:8085`
- Nginx frontend proxy `/api/*` -> `backend:8000/api/*`
- Crawler ghi du lieu vao SQLite `backend/agrimonitor.db`

## 2) Yeu cau

- Docker + Docker Compose plugin (`docker compose`)

## 3) Cau hinh moi truong

Tao file `.env` tai root:

```bash
cp .env.example .env
```

Bien quan trong:

- `FRONTEND_PORT=8085`
- `VITE_API_BASE=/api`
- `CRAWLER_INTERVAL_SECONDS=1800` (30 phut)
- `CRAWLER_INITIAL_BACKFILL_DAYS=90`
- `SUBMIT_BASIC_USER`, `SUBMIT_BASIC_PASSWORD`
- `GEMINI_API_KEY` (tuy chon)
- `OPENAI_API_KEY` (tuy chon — OpenAI khi khong dung Gemini; tao key tai [platform.openai.com/api-keys](https://platform.openai.com/api-keys))

## 4) Chay he thong

Build + run:

```bash
docker compose up --build -d
```

Truy cap:

- UI: `http://localhost:8085`
- API (qua UI proxy): `http://localhost:8085/api/...`

Theo doi log:

```bash
docker compose logs -f frontend
docker compose logs -f backend
docker compose logs -f crawler
```

## 5) Scheduler crawler 30 phut

Crawler service chay script `backend/run_crawler_loop.sh`:

1. Bootstrap DB + seed du lieu lich su + chay scrape lan dau
2. Sleep `CRAWLER_INTERVAL_SECONDS` (mac dinh 1800s)
3. Chay scrape tiep (khong backfill lich su), lap vo han

Chinh chu ky nhanh/cham:

```bash
# trong .env
CRAWLER_INTERVAL_SECONDS=900   # 15 phut
```

Sau do restart crawler:

```bash
docker compose up -d --build crawler
```

## 6) Cac lenh van hanh thuong dung

```bash
# Dung he thong
docker compose down

# Dung + xoa network/containers
docker compose down --remove-orphans

# Rebuild toan bo
docker compose build --no-cache

# Chay scraper thu cong trong crawler container
docker compose exec crawler python -c "import scraper_job as s; s.run_scraper(backfill_days=0)"
```

## 7) Cau truc thu muc chinh

- `frontend/`: React app + Dockerfile production + `nginx.conf`
- `backend/`: FastAPI, crawler, SQLite DB, Dockerfile python
- `docker-compose.yml`: orchestration 3 services
- `.env.example`: mau bien moi truong

## 8) Luu y bao mat

- Khong commit API key that (`GEMINI_API_KEY`) vao git.
- Neu da co key that trong file local, doi key moi truoc khi deploy production.
- Doi `SUBMIT_BASIC_PASSWORD` truoc khi mo internet.

## 9) SQLite — xoa ban ghi thu cong / reset du lieu

Gia submit nam trong bang `price_observations`; gia thuy san legacy con trong `commodity_prices`.

**Xoa tay (vi du Tôm Sú submit thua):**

```bash
sqlite3 backend/agrimonitor.db "DELETE FROM price_observations WHERE commodity_name = 'Tôm Sú (Black Tiger)' AND source = 'manual_submit';"
```

**Reset gan nhu moi (xoa DB + archive, crawler se tao lai):**

```bash
docker compose down
rm -f backend/agrimonitor.db backend/agrimonitor.db-journal
rm -rf backend/content_store/*
docker compose up -d --build
```

(Luu y: mat toan bo du lieu local; chay lai seed + crawler.)
