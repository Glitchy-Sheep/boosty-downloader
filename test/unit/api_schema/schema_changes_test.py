"""The warning list: what fresh answers add to the committed schema."""

from __future__ import annotations

from api_schema.schema_changes import SchemaChange, find_changes


def _document(**schemas: dict[str, object]) -> dict[str, object]:
    return {'components': {'schemas': schemas}}


def _post(**properties: dict[str, object]) -> dict[str, object]:
    return {'type': 'object', 'properties': properties}


def _chunk(kind: str) -> dict[str, object]:
    return {'type': 'object', 'properties': {'type': {'type': 'string', 'const': kind}}}


def test_the_same_schema_has_no_changes():
    document = _document(Post=_post(title={'type': 'string'}), ChunkText=_chunk('text'))

    assert find_changes(document, document) == []


def test_a_key_missing_from_fresh_answers_is_not_a_change():
    """One page of one blog rarely holds every key the schema knows."""
    committed = _document(
        Post=_post(title={'type': 'string'}, teaser={'type': 'array'})
    )
    live = _document(Post=_post(title={'type': 'string'}))

    assert find_changes(committed, live) == []


def test_a_new_key_names_its_path_and_type():
    committed = _document(Post=_post(title={'type': 'string'}))
    live = _document(
        Post=_post(title={'type': 'string'}, hasAIContent={'type': 'boolean'})
    )

    assert find_changes(committed, live) == [
        SchemaChange('new_key', 'Post.hasAIContent', 'boolean')
    ]


def test_a_new_key_inside_a_nested_object_and_a_list_item():
    committed = _document(
        Post=_post(
            user=_post(name={'type': 'string'}),
            tags={'type': 'array', 'items': _post(id={'type': 'integer'})},
        )
    )
    live = _document(
        Post=_post(
            user=_post(name={'type': 'string'}, isOfficial={'type': 'boolean'}),
            tags={
                'type': 'array',
                'items': _post(id={'type': 'integer'}, title={'type': 'string'}),
            },
        )
    )

    assert find_changes(committed, live) == [
        SchemaChange('new_key', 'Post.user.isOfficial', 'boolean'),
        SchemaChange('new_key', 'Post.tags[].title', 'string'),
    ]


def test_a_new_type_shows_before_and_after():
    committed = _document(Post=_post(price={'type': 'integer'}))
    live = _document(Post=_post(price={'type': ['integer', 'number']}))

    assert find_changes(committed, live) == [
        SchemaChange('new_type', 'Post.price', 'integer → integer|number')
    ]


def test_new_vocabulary_values_one_by_one():
    committed = _document(
        ChunkOkVideo=_post(status={'type': 'string', 'x-seen-values': ['ok']})
    )
    live = _document(
        ChunkOkVideo=_post(
            status={'type': 'string', 'x-seen-values': ['ok', 'processing', 'failed']}
        )
    )

    assert find_changes(committed, live) == [
        SchemaChange('new_value', 'ChunkOkVideo.status', 'failed'),
        SchemaChange('new_value', 'ChunkOkVideo.status', 'processing'),
    ]


def test_a_new_chunk_kind_is_named_by_its_type():
    committed = _document(ChunkText=_chunk('text'))
    live = _document(ChunkText=_chunk('text'), ChunkPoll=_chunk('poll'))

    assert find_changes(committed, live) == [
        SchemaChange('new_chunk', 'ChunkPoll', 'poll')
    ]
