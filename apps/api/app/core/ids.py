import secrets
import time

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _b36(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = ALPHABET[r] + out
    return out or "0"


def prefixed_id(prefix: str) -> str:
    ts = _b36(int(time.time() * 1000))
    rnd = secrets.token_hex(6)
    return f"{prefix}_{ts}{rnd}"
