from app.kb.chunker import chunk_text


def test_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_single_chunk():
    out = chunk_text("Hello world.")
    assert len(out) == 1
    assert out[0].text.startswith("Hello")


def test_long_text_splits_with_overlap():
    para = "Sentence about cats. " * 300
    out = chunk_text(para, target_chars=500, overlap_chars=80)
    assert len(out) > 1
    # Each chunk roughly bounded
    for c in out:
        assert len(c.text) <= 700
