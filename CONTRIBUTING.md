# Contributing

Thanks for helping improve Argimonitor.

## Quick start for contributors

1. Fork the repository and clone your fork.
2. Copy environment template: `cp .env.example .env` and fill in secrets locally (never commit `.env`).
3. Run the stack: `docker compose up --build -d` (see `README.md`).
4. Make changes on a branch: `git checkout -b feature/your-change`.

## Pull requests

- Keep changes focused on one topic.
- Ensure `docker compose` still builds if you touch Docker or dependencies.
- Do not commit `backend/agrimonitor.db`, `backend/content_store/`, API keys, or `node_modules/`.

## Data & scraping

Crawled markdown and SQLite are generated locally. New clones should run the crawler (see README) instead of bundling private datasets.

## License

By contributing, you agree your contributions are licensed under the same terms as the project ([MIT](LICENSE)).
