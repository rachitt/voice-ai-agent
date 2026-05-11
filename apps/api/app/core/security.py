import hashlib
import hmac
import secrets

from .config import get_settings


def generate_api_key(prefix: str = "sk_live") -> tuple[str, str]:
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    pepper = get_settings().api_key_pepper.encode()
    return hmac.new(pepper, raw.encode(), hashlib.sha256).hexdigest()


def sign_webhook(body: bytes) -> str:
    secret = get_settings().webhook_hmac_secret.encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_webhook(body: bytes, signature: str) -> bool:
    expected = sign_webhook(body)
    return hmac.compare_digest(expected, signature)
