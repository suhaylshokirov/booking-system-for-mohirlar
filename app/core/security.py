"""Password hashing (and, from P2.1, tokens).

Passwords are hashed with Argon2 through pwdlib; the plain password is never
stored or logged. Only `hash_password` exists so far because the seed script
needs it (see the Deviations log); P2.1 adds verification and JWTs here.
"""

from pwdlib import PasswordHash

# `recommended()` is Argon2id with the library's current safe parameters.
_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a salted Argon2 hash of `password`."""
    return _hasher.hash(password)
