"""人脸识别子系统独立数据库（与检测系统 web.db 分开）。"""
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# 定位到 web/data/（与运行 cwd 无关）
_WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_WEB, "data")
os.makedirs(DATA_DIR, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'face.db')}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
# 开启 WAL（提升并发读写；持久生效，启动时确认一次即可）
with engine.connect() as conn:
    conn.execute(text("PRAGMA journal_mode=WAL"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
