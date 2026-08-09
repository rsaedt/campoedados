from __future__ import annotations

import os
import sys

from app.core.database import DATABASE_URL, database_is_ready
from app.services.media_storage import media_storage_backend, media_storage_is_configured


def _flag(name: str) -> bool:
    return bool(os.getenv(name))


def main() -> int:
    environment = os.getenv("CAMPOEDADOS_ENV", "development")
    failures: list[str] = []

    if environment == "staging" and DATABASE_URL.startswith("sqlite"):
        failures.append("staging não pode usar SQLite em DATABASE_URL")
    db_ready = database_is_ready()
    if not db_ready:
        failures.append("banco de dados indisponível")

    storage_backend = media_storage_backend()
    if environment == "staging" and storage_backend != "supabase":
        failures.append("staging deve usar CAMPOEDADOS_MEDIA_STORAGE=supabase")
    storage_ready = media_storage_is_configured()
    if not storage_ready:
        failures.append("storage de mídia não está configurado")

    print(f"environment={environment}")
    print(f"database={'ok' if db_ready else 'fail'}")
    print(f"media_storage={storage_backend}")
    print(f"openai={'configured' if _flag('OPENAI_API_KEY') else 'not_configured'}")
    print("tenant_data=database")
    print("channel_accounts=database")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("staging preflight: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
