from sqlalchemy import Column, BigInteger, SmallInteger, Numeric, DateTime, String
from sqlalchemy.sql import func
from .connection import Base


class SensorLog(Base):
    __tablename__ = "sensor_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factory_id = Column(SmallInteger, nullable=False)
    node_id = Column(String(20))
    temperature_c = Column(Numeric(5, 2))
    humidity_pct = Column(Numeric(5, 2))
    logged_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
