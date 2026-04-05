from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://midas:midas@localhost:5432/midas")

engine = create_async_engine(DATABASE_URL, echo=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def create_all_tables():
    # 개발용: ORM 모델 기반으로 테이블 자동 생성
    # 프로덕션에서는 Alembic 마이그레이션 사용
    from database import models  # noqa: F401 — 모델 import로 메타데이터 등록
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
