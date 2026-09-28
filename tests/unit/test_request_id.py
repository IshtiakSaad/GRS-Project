from apps.common.request_id import accept_or_new


def test_keeps_a_plain_caller_id():
    assert accept_or_new("abc12345-def") == "abc12345-def"


def test_replaces_missing_id():
    generated = accept_or_new(None)
    assert len(generated) == 32


def test_replaces_unsafe_id():
    # Anything that could inject into logs or headers is discarded, not echoed back.
    for bad in ["short", "x" * 65, "abc12345\nforged: header", "abc 12345678", "<script>abc"]:
        assert accept_or_new(bad) != bad
