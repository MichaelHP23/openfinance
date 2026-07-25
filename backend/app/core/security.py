from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hash_: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
