# app/auth.py
from passlib.context import CryptContext
import hashlib

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _prehash(password: str) -> str:
    """
    Pre-hash with SHA256 so bcrypt never receives >72 bytes.
    Returns a fixed-length hex string (64 chars).
    """
    if password is None:
        password = ""
    password = str(password)
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def hash_password(password: str) -> str:
    # bcrypt will hash this 64-char string
    return pwd_context.hash(_prehash(password))

def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verify using prehash.
    Backward compatible: if old users were stored without prehash,
    fallback to raw verify once.
    """
    try:
        # New method (prehash)
        if pwd_context.verify(_prehash(password), hashed_password):
            return True
    except Exception:
        pass

    # Fallback for old hashes (if you had stored raw bcrypt before)
    try:
        return pwd_context.verify(password or "", hashed_password)
    except Exception:
        return False