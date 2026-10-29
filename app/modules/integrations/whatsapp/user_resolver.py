import logging
import re
import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.identity.models.user import CitizenProfile, User
from app.modules.identity.repository.identity_repository import UserRepository

logger = logging.getLogger("app.integrations.whatsapp.resolver")


def normalize_phone_number(raw_phone: str) -> str:
    """
    Normalizes incoming WhatsApp or Twilio phone numbers to E.164 format.

    Examples:
        'whatsapp:+919876543210' -> '+919876543210'
        '919876543210'           -> '+919876543210'
        '+91 98765-43210'        -> '+919876543210'
        '+1 (555) 123-4567'      -> '+15551234567'
    """
    cleaned = raw_phone.strip()
    if cleaned.lower().startswith("whatsapp:"):
        cleaned = cleaned[9:].strip()

    # Remove non-digit characters except leading plus
    has_plus = cleaned.startswith("+")
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        raise ValueError(f"Invalid phone number provided: '{raw_phone}'")

    if has_plus:
        return f"+{digits}"
    return f"+{digits}"


async def resolve_or_create_whatsapp_citizen(
    session: AsyncSession,
    raw_phone: str,
) -> User:
    """
    Resolves an existing citizen User by normalized phone number or auto-provisions
    a new citizen with a surrogate email and citizen profile.
    """
    normalized_phone = normalize_phone_number(raw_phone)
    user_repo = UserRepository(session)

    # 1. Check if user already exists
    existing_user: Optional[User] = await user_repo.get_by_phone(normalized_phone)
    if existing_user is not None:
        logger.debug("Resolved existing user %s for phone %s", existing_user.id, normalized_phone)
        return existing_user

    # 2. Auto-provision new citizen
    digits = re.sub(r"\D", "", normalized_phone)
    surrogate_email = f"{digits}@wa.grievance.local"

    # Edge check: ensure surrogate email uniqueness if already used
    existing_by_email = await user_repo.get_by_email(surrogate_email)
    if existing_by_email is not None:
        return existing_by_email

    random_secret = secrets.token_urlsafe(32)
    pwd_hash = hash_password(random_secret)

    new_user = User(
        phone_number=normalized_phone,
        email=surrogate_email,
        password_hash=pwd_hash,
        role="citizen",
        is_active=True,
    )
    session.add(new_user)
    await session.flush()

    profile = CitizenProfile(
        user_id=new_user.id,
        full_name="WhatsApp Citizen",
        notification_preference="whatsapp",
        preferred_language="hi",
    )
    session.add(profile)
    await session.flush()

    new_user.citizen_profile = profile
    logger.info("Auto-provisioned new WhatsApp citizen %s for phone %s", new_user.id, normalized_phone)
    return new_user
