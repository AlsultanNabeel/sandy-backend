"""Make the Atlas vector index ``entries_vector`` on the database in .env, if it is missing.

An index that is already there is left as it is. Boot does the same in the background;
this is for a new database you want ready before the server first starts.

    python3 scripts/ensure_vector_index.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloud"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


def main() -> int:
    from pymongo.errors import PyMongoError

    from app.blocks import vector_index
    from app.config import MONGODB_DB_NAME, MONGODB_URI
    from app.integrations.mongodb_store import init_mongo_connection

    _, mongo_db = init_mongo_connection(MONGODB_URI, MONGODB_DB_NAME)
    if mongo_db is None:
        print("no database (MONGODB_URI is not set)")
        return 1
    try:
        result = vector_index.ensure(mongo_db)
    except PyMongoError as exc:
        print(f"could not make {vector_index.NAME} on {MONGODB_DB_NAME}: {exc}")
        return 1
    print(f"{vector_index.NAME} on {MONGODB_DB_NAME}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
