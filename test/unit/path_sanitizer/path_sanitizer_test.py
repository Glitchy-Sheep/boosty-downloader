from boosty_downloader.src.infrastructure.path_sanitizer import sanitize_string


def test_sanitize_string_removes_unsafe_characters():
    unsafe_input = 'test<file>name:with/unsafe\\chars|and?more*'
    result = sanitize_string(unsafe_input)

    assert result == 'testfilenamewithunsafecharsandmore'


def test_sanitize_string_preserves_safe_characters():
    safe_input = 'Valid_File-Name 123 (test)'
    result = sanitize_string(safe_input)

    assert result == safe_input


def test_sanitize_string_handles_empty_string():
    result = sanitize_string('')

    assert result == ''


def test_sanitize_string_handles_only_unsafe_characters():
    result = sanitize_string('<>:"/\\|?*')

    assert result == ''


def test_sanitize_string_truncates_long_strings():
    long_string = 'a' * 300
    result = sanitize_string(long_string)

    assert len(result.encode('utf-8')) <= 200
    assert len(result) == 200  # ASCII characters are 1 byte each


def test_sanitize_string_custom_max_bytes():
    long_string = 'a' * 150
    result = sanitize_string(long_string, max_bytes=100)

    assert len(result.encode('utf-8')) <= 100
    assert len(result) == 100


def test_sanitize_string_handles_utf8_multibyte_characters():
    cyrillic_text = 'Привет мир' * 20  # ~200 bytes
    result = sanitize_string(cyrillic_text, max_bytes=100)

    assert len(result.encode('utf-8')) <= 100
    result.encode('utf-8').decode('utf-8')


def test_sanitize_string_handles_emojis():
    emoji_text = '❤️' * 60  # ~240 bytes
    result = sanitize_string(emoji_text, max_bytes=100)

    assert len(result.encode('utf-8')) <= 100
    result.encode('utf-8').decode('utf-8')


def test_sanitize_string_mixed_multibyte_and_unsafe_chars():
    mixed_text = 'Это пример простого русского текста для демонстрации. ❤️'
    result = sanitize_string(mixed_text, max_bytes=50)

    assert '/' not in result
    assert len(result.encode('utf-8')) <= 50


def test_sanitize_string_preserves_utf8_character_boundaries():
    # Cyrillic 'Я' is 2 bytes (0xD0 0xAF in UTF-8)
    text = 'a' * 99 + 'Я' * 10  # 99 + 20 = 119 bytes
    result = sanitize_string(text, max_bytes=100)

    try:
        result.encode('utf-8').decode('utf-8')
        valid_utf8 = True
    except UnicodeDecodeError:
        valid_utf8 = False

    assert valid_utf8
    assert len(result.encode('utf-8')) <= 100


def test_sanitize_string_strips_trailing_whitespace_after_truncation():
    text = 'a' * 95 + '     ' + 'b' * 100  # 200+ bytes
    result = sanitize_string(text, max_bytes=100)

    assert not result.endswith(' ')


def test_sanitize_string_real_world_scenario():
    long_title = (
        'Это пример простого русского текста для демонстрации. '
        'Он содержит буквы, цифры 123 и знаки препинания и эмоджи. ❤️ '
        'Не несет никакой смысловой нагрузки (100%) 🔥'
    )
    full_path = f'2025-06-13 - {long_title} (12345f12)'
    result = sanitize_string(full_path, max_bytes=240)

    assert len(result.encode('utf-8')) <= 240
    result.encode('utf-8').decode('utf-8')
    assert len(result) > 0


def test_sanitize_string_short_string_not_truncated():
    short_text = 'Short Title'
    result = sanitize_string(short_text, max_bytes=200)

    assert result == short_text


def test_sanitize_string_exactly_at_limit():
    text = 'a' * 200
    result = sanitize_string(text, max_bytes=200)

    assert result == text
    assert len(result.encode('utf-8')) == 200


def test_sanitize_string_one_byte_over_limit():
    text = 'a' * 201
    result = sanitize_string(text, max_bytes=200)

    assert len(result) == 200
    assert len(result.encode('utf-8')) == 200


def test_sanitize_string_default_max_bytes():
    long_text = 'b' * 300
    result = sanitize_string(long_text)

    assert len(result.encode('utf-8')) <= 200
    assert len(result) == 200


def test_sanitize_string_handles_mixed_safe_and_unsafe():
    mixed = 'Valid<Text>Привет/World❤️|Test' * 10
    result = sanitize_string(mixed, max_bytes=100)

    assert '<' not in result
    assert '>' not in result
    assert '/' not in result
    assert '|' not in result
    result.encode('utf-8').decode('utf-8')
    assert len(result.encode('utf-8')) <= 100
