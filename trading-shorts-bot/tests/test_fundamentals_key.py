from fundamentals_key import looks_like_key, set_env_value


def test_replaces_an_empty_key_line():
    assert set_env_value("PORT=8766\nFMP_API_KEY=\nX=1\n", "FMP_API_KEY", "abc") == "PORT=8766\nFMP_API_KEY=abc\nX=1\n"


def test_adds_the_line_when_missing():
    assert set_env_value("PORT=8766", "FMP_API_KEY", "abc") == "PORT=8766\nFMP_API_KEY=abc\n"
    assert set_env_value("", "FMP_API_KEY", "abc") == "FMP_API_KEY=abc\n"


def test_key_shape():
    assert looks_like_key("a" * 32) and not looks_like_key("short") and not looks_like_key("has space in it 12345678")
