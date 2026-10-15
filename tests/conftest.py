import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.modules.identity.models.user import CitizenProfile, User
from app.modules.identity.schemas.identity import UserRole

# Use an in-memory SQLite database for fast, isolated testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """Recreates database tables before every test run."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a fresh database session for a test."""
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Test client configured with test database session overrides."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def citizen_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="citizen.test@example.com",
        phone_number="+15550001",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    profile = CitizenProfile(
        user_id=user.id,
        full_name="Alice Citizen",
        address="100 Maple St",
        preferred_language="en",
        notification_preference="email",
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def officer_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="officer.test@example.com",
        phone_number="+15550002",
        password_hash=hash_password("Password123!"),
        role=UserRole.OFFICER.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def supervisor_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="supervisor.test@example.com",
        phone_number="+15550003",
        password_hash=hash_password("Password123!"),
        role=UserRole.SUPERVISOR.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def citizen_token(citizen_user: User) -> str:
    return create_access_token(subject=str(citizen_user.id), role=citizen_user.role)


@pytest.fixture
def officer_token(officer_user: User) -> str:
    return create_access_token(subject=str(officer_user.id), role=officer_user.role)


@pytest.fixture
def supervisor_token(supervisor_user: User) -> str:
    return create_access_token(subject=str(supervisor_user.id), role=supervisor_user.role)


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="admin.test@example.com",
        phone_number="+15550004",
        password_hash=hash_password("Password123!"),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return create_access_token(subject=str(admin_user.id), role=admin_user.role)


@pytest.fixture
async def lead_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="lead.test@example.com",
        phone_number="+15550005",
        password_hash=hash_password("Password123!"),
        role=UserRole.DEPARTMENT_LEAD.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def lead_token(lead_user: User) -> str:
    return create_access_token(subject=str(lead_user.id), role=lead_user.role)


@pytest.fixture
async def auditor_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="auditor.test@example.com",
        phone_number="+15550006",
        password_hash=hash_password("Password123!"),
        role=UserRole.AUDITOR.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auditor_token(auditor_user: User) -> str:
    return create_access_token(subject=str(auditor_user.id), role=auditor_user.role)
