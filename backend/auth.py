"""Authentication utilities for admin access."""
import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.db_models import Admin

# Load environment variables
load_dotenv()

# Password hashing - use passlib but with bcrypt directly as fallback
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings - load from environment or generate a random one
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    # Generate a random secret key if not set (for development only)
    # In production, you MUST set JWT_SECRET_KEY in your .env file
    SECRET_KEY = secrets.token_urlsafe(32)
    print("⚠️  WARNING: JWT_SECRET_KEY not set in environment. Using a random key (tokens will be invalid on restart).")
    print("   Set JWT_SECRET_KEY in your .env file for production use.")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# HTTP Bearer token scheme
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    # Truncate password to 72 bytes (same as hashing)
    password_bytes = _truncate_to_72_bytes(plain_password)
    
    # Use bcrypt directly for verification
    try:
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        # Fallback to passlib if bcrypt fails
        return pwd_context.verify(plain_password, hashed_password)


def _truncate_to_72_bytes(password: str) -> bytes:
    """
    Truncate password to exactly 72 bytes, handling UTF-8 safely.
    Returns bytes to ensure exact length control.
    """
    if isinstance(password, bytes):
        password_bytes = password
    else:
        password_bytes = password.encode('utf-8')
    
    if len(password_bytes) <= 72:
        return password_bytes
    
    # Truncate to 72 bytes
    truncated = password_bytes[:72]
    
    # Remove incomplete UTF-8 sequences
    while len(truncated) > 0 and (truncated[-1] & 0xC0) == 0x80:
        truncated = truncated[:-1]
    
    return truncated


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.
    
    IMPORTANT: Bcrypt has a hard 72-byte limit (not 72 characters).
    - For ASCII: 72 bytes = 72 characters
    - For non-ASCII (é, ñ, emojis): fewer characters fit in 72 bytes
    
    Passwords longer than 72 bytes are automatically truncated.
    """
    # Truncate to 72 bytes (as bytes for exact control)
    password_bytes = _truncate_to_72_bytes(password)
    
    # Use bcrypt directly to avoid passlib initialization issues
    # Generate salt and hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # Return as string (bcrypt hash is ASCII-safe)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Admin:
    """Get the current authenticated admin from the token."""
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    admin = db.query(Admin).filter(Admin.username == username).first()
    if admin is None or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return admin

