from __future__ import annotations

import enum
from datetime import datetime, date, time, timedelta
from typing import List, Optional

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (
    UniqueConstraint,
    CheckConstraint,
    Index,
    func,
    ForeignKey,
    Boolean,
    Integer,
    String,
    Date,
    Time,
    DateTime
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

db = SQLAlchemy()

class CourseType(enum.Enum):
    BEGINNER = "BEGINNER" # 초급 60분 x 8회
    INTERMEDIATE = "INTERMEDIATE" # 중급 60분 x 4회
    ADVANCED = "ADVANCED" # 심화 120분 x 4회 (예약 시 연속 2회 슬롯 점유)

class EnrollementStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    FROZEN = "FROZEN"
    CANCELED = "CANCELED"

class ReservationStatus(enum.Enum):
    BOOKED = "BOOKED"
    CANCELED = "CANCELED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"

class User(db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(string(80), nullable=Fales)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), updated_at=func.now(), nullable=False)
    
    enrollments = Mapped[List["Enrollment"]] = relationship(back_populates="User", cascade="all, delete-orphan")

    reservations = Mapped[List["Reservation"]] = relationship(back_populates="User", cascade="a;;, delecte-orphan")

    def __repr__(self):
        return f"<User id={self.id} phone={self.phone}>"
    