from app.core.security import generate_api_key, hash_api_key, sign_webhook, verify_webhook


def test_generate_then_hash_stable():
    raw, hashed = generate_api_key("sk_test")
    assert hash_api_key(raw) == hashed


def test_signature_roundtrip():
    body = b'{"hello":"world"}'
    sig = sign_webhook(body)
    assert verify_webhook(body, sig)
    assert not verify_webhook(body, "0" * len(sig))
    assert not verify_webhook(b"tampered", sig)
