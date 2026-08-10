"""RFC 6238 TOTP from stdlib only — hmac/hashlib/base64/struct/time/os. The spec
(docs/superpowers/specs/2026-08-09-post-parity-roadmap-design.md §2.3) calls this out
explicitly against PLAN-CONSTRAINTS.md's "no new dependencies": pyotp is unnecessary,
this is HMAC-SHA1 over a 30-second counter in under 30 lines.
"""

import base64
import hashlib
import hmac
import os
import struct
import time

_PERIOD_SECONDS = 30
_DIGITS = 6


def generate_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode()


def provisioning_uri(secret: str, email: str, issuer: str = "OpenFinance") -> str:
    return (
        f"otpauth://totp/{issuer}:{email}"
        f"?secret={secret}&issuer={issuer}&algorithm=SHA1&digits={_DIGITS}&period={_PERIOD_SECONDS}"
    )


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper())
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    code = truncated % (10**_DIGITS)
    return f"{code:0{_DIGITS}d}"


def verify_totp(secret: str, code: str, *, at: int | None = None, window: int = 1) -> bool:
    """window=1 tolerates one 30s step of clock drift either direction, the
    conventional TOTP allowance."""
    step = (at if at is not None else int(time.time())) // _PERIOD_SECONDS
    return any(
        hmac.compare_digest(_hotp(secret, step + offset), code)
        for offset in range(-window, window + 1)
    )
