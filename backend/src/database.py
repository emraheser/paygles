import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env deterministically from backend root (works regardless of current cwd)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_BACKEND_ROOT / ".env")

database_url_env = (os.getenv("DATABASE_URL", "") or "").strip()
if database_url_env:
    DATABASE_URL = database_url_env
    _is_sqlite = DATABASE_URL.startswith("sqlite")
else:
    sqlite_path = (os.getenv("SQLITE_PATH", "") or "./paygles.db").strip()
    sqlite_file = Path(sqlite_path)
    if not sqlite_file.is_absolute():
        sqlite_file = (_BACKEND_ROOT / sqlite_file).resolve()
    sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite+aiosqlite:///{sqlite_file}"
    _is_sqlite = True

connect_args: dict = {"check_same_thread": False} if _is_sqlite else {}

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
)

# Enable WAL mode for SQLite so external tools (DBeaver) can read while backend writes
if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_wal(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.close()

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
