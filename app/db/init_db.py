"""Database initialization and seed data."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import AsyncSessionLocal, init_db
from app.db.models import MockGovernmentRecord, User
from app.services.password import hash_password


async def seed_mock_government_records(session: AsyncSession) -> None:
    """Seed mock government records for testing."""
    
    # Check if records already exist
    result = await session.execute(select(MockGovernmentRecord).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # Already seeded
    
    # Positive cases - will pass verification
    positive_records = [
        MockGovernmentRecord(
            document_number="123456789",
            document_type="id_card",
            first_name="MARIE",
            last_name="JUMIO",
            date_of_birth=date(1975, 1, 1),
            address={"country": "SINGAPORE"},
            is_valid=True,
            is_flagged=False,
        ),
        MockGovernmentRecord(
            document_number="CJ3760864",
            document_type="visa",
            first_name="ANAND",
            last_name="KUMAR",
            date_of_birth=date(1985, 5, 24),
            address={"nationality": "INDIAN"},
            is_valid=True,
            is_flagged=False,
        ),
    ]
    
    # Negative cases - will fail verification
    negative_records = [
        MockGovernmentRecord(
            document_number="ID-EXPIRED-001",
            document_type="id_card",
            first_name="Bob",
            last_name="Fraud",
            date_of_birth=date(1988, 1, 1),
            address={"street": "999 Fake St", "city": "Nowhere", "state": "XX", "zip": "00000"},
            is_valid=False,
            is_flagged=False,
            flag_reason="Document expired",
        ),
        MockGovernmentRecord(
            document_number="ID-FLAGGED-002",
            document_type="id_card",
            first_name="Charlie",
            last_name="Suspicious",
            date_of_birth=date(1992, 5, 10),
            address={"street": "111 Alert Ave", "city": "Watchlist", "state": "WL", "zip": "11111"},
            is_valid=True,
            is_flagged=True,
            flag_reason="Identity theft report filed on 2024-01-15",
        ),
        MockGovernmentRecord(
            document_number="PASS-REVOKED-003",
            document_type="passport",
            first_name="David",
            last_name="Blocked",
            date_of_birth=date(1985, 11, 20),
            address={"street": "222 Banned Blvd", "city": "Restricted", "state": "RS", "zip": "22222"},
            is_valid=False,
            is_flagged=True,
            flag_reason="Passport revoked due to fraud investigation",
        ),
        MockGovernmentRecord(
            document_number="ID-MISMATCH-004",
            document_type="id_card",
            first_name="Eve",
            last_name="Discrepancy",
            date_of_birth=date(1991, 3, 15),
            address={"street": "333 Wrong Way", "city": "Mismatch", "state": "MM", "zip": "33333"},
            is_valid=False,
            is_flagged=False,
            flag_reason="Document data mismatch with government records",
        ),
    ]
    
    for record in positive_records + negative_records:
        session.add(record)
    
    await session.commit()


async def seed_initial_users(session: AsyncSession) -> None:
    """Seed initial user accounts for testing."""
    
    # Define seed user emails
    seed_emails = ["kopal.gupta@outlook.com", "anand@gmail.com"]
    
    # Check if seed users specifically exist
    result = await session.execute(
        select(User).where(User.email.in_(seed_emails)).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return  # Already seeded
    
    # Default password for initial users (they should change it after first login)
    default_password = hash_password("TestPass123")
    
    initial_users = [
        User(
            email="kopal.gupta@outlook.com",
            phone="1-5235-89282",
            password_hash=default_password,
            first_name="Kopal",
            last_name="Gupta",
            date_of_birth=date(1986, 10, 6),
            kyc_status="pending",
        ),
        User(
            email="anand@gmail.com",
            phone="91-8947293201",
            password_hash=default_password,
            first_name="Anand",
            last_name="Kumar",
            date_of_birth=date(1985, 5, 24),
            kyc_status="pending",
        ),
    ]
    
    for user in initial_users:
        session.add(user)
    
    await session.commit()


async def initialize_database() -> None:
    """Initialize database tables and seed data."""
    # Create all tables
    await init_db()
    
    # Seed mock data
    async with AsyncSessionLocal() as session:
        await seed_mock_government_records(session)
        await seed_initial_users(session)


if __name__ == "__main__":
    import asyncio
    asyncio.run(initialize_database())

