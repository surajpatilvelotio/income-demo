"""SQLAlchemy models for eKYC system."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def generate_member_id(auto_id: int) -> str:
    """
    Generate a member ID with format INS<year><padded_id>.
    
    Args:
        auto_id: The auto-increment ID of the user
        
    Returns:
        Member ID string like INS2025001, INS2025012, INS2025123
    """
    current_year = datetime.now().year
    # Pad the ID to at least 3 digits
    padded_id = str(auto_id).zfill(3)
    return f"INS{current_year}{padded_id}"


class User(Base):
    """User model for signup and authentication."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    auto_id: Mapped[int] = mapped_column(Integer, autoincrement=True, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True)
    kyc_status: Mapped[str] = mapped_column(String(20), default="pending")
    member_id: Mapped[Optional[str]] = mapped_column(String(20), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    kyc_applications: Mapped[list["KYCApplication"]] = relationship(
        "KYCApplication", back_populates="user", cascade="all, delete-orphan"
    )


class KYCApplication(Base):
    """KYC Application model for workflow tracking."""

    __tablename__ = "kyc_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="initiated")
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    decision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="kyc_applications")
    documents: Mapped[list["KYCDocument"]] = relationship(
        "KYCDocument", back_populates="application", cascade="all, delete-orphan"
    )
    stages: Mapped[list["KYCStage"]] = relationship(
        "KYCStage", back_populates="application", cascade="all, delete-orphan"
    )


class KYCDocument(Base):
    """KYC Document model for uploaded documents."""

    __tablename__ = "kyc_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kyc_applications.id"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ocr_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    application: Mapped["KYCApplication"] = relationship("KYCApplication", back_populates="documents")


class KYCStage(Base):
    """KYC Stage model for tracking processing stages."""

    __tablename__ = "kyc_stages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    application_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("kyc_applications.id"), nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    application: Mapped["KYCApplication"] = relationship("KYCApplication", back_populates="stages")


class MockGovernmentRecord(Base):
    """Mock Government Record model for simulating government database."""

    __tablename__ = "mock_government_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[datetime] = mapped_column(Date, nullable=False)
    address: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

