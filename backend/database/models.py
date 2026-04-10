from sqlalchemy import Column, BigInteger, Boolean, Float, Numeric, DateTime, String, Text
from sqlalchemy.sql import func
from .connection import Base


class Factory(Base):
    __tablename__ = "factories"

    factory_id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(Text)
    status = Column(String(20), nullable=False, server_default="stopped")
    current_temp = Column(Float)
    current_humidity = Column(Float)
    is_human = Column(Boolean, server_default="false")
    is_light_on = Column(Boolean, server_default="false")
    door_open_count = Column(BigInteger, server_default="0")
    last_seen_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    max_quantity = Column(BigInteger)
    is_door_open = Column(Boolean, server_default="false")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factory_id = Column(BigInteger)
    priority = Column(String(20), nullable=False, server_default="medium")
    message = Column(Text)
    triggered_at = Column(DateTime(timezone=True))
    ack_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factory_id = Column(BigInteger)
    target_temp = Column(Float)
    mode = Column(Text)
    start_at = Column(DateTime(timezone=True))
    end_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factory_id = Column(BigInteger)
    target_units = Column(Text)
    status = Column(String(20), nullable=False, server_default="pending")
    deadline_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    quantity = Column(BigInteger)


class SensorLog(Base):
    __tablename__ = "sensor_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factory_id = Column(BigInteger, nullable=False)
    node_id = Column(String(20))
    temperature_c = Column(Numeric(5, 2))
    humidity_pct = Column(Numeric(5, 2))
    measured_at = Column(DateTime(timezone=True))
    logged_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
