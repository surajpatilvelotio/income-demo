"""Password hashing utilities."""

import hashlib
import secrets


def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256 with salt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password with salt prefix
    """
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        password: Plain text password to verify
        hashed: Hashed password with salt prefix
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        salt, stored_hash = hashed.split(":", 1)
        computed_hash = hashlib.sha256((salt + password).encode()).hexdigest()
        return secrets.compare_digest(computed_hash, stored_hash)
    except ValueError:
        return False

