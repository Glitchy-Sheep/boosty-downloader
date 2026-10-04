"""Blog metadata tolerates broken optional fields without inventing values."""

import pytest
from pydantic import ValidationError
from support.synthetic_blog import BLOG_TITLE, OWNER_NAME, POST_COUNT, synthetic_blog
from support.synthetic_post import unknown_chunk

from boosty_downloader.infrastructure.boosty_api.models.blog import BlogInfoDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataUnknownDTO,
)


def test_blog_keeps_metadata_and_structured_description() -> None:
    raw = synthetic_blog()
    raw['futureField'] = {'unexpected': True}
    blog = BlogInfoDTO.model_validate(raw)

    assert blog.title == BLOG_TITLE
    assert blog.cover_url == raw['coverUrl']
    assert blog.owner is not None
    assert blog.owner.name == OWNER_NAME
    assert blog.owner.avatar_url == raw['owner']['avatarUrl']
    assert blog.count is not None
    assert blog.count.posts == POST_COUNT
    assert blog.description is not None
    assert [block.type for block in blog.description] == [
        'text',
        'text',
        'image',
        'audio_file',
        'ok_video',
    ]


@pytest.mark.parametrize(
    'raw', [{}, dict.fromkeys(('title', 'description', 'coverUrl', 'owner', 'count'))]
)
def test_absent_and_null_metadata_are_unknown(raw: dict[str, object]) -> None:
    blog = BlogInfoDTO.model_validate(raw)

    assert all(value is None for value in blog.model_dump().values())


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('title', []),
        ('coverUrl', 1),
        ('description', 'plain text'),
        ('description', [None]),
        ('description', [{'type': 'image'}]),
        ('owner', []),
        ('owner', 'name'),
        ('count', []),
        ('count', 7),
    ],
)
def test_broken_field_keeps_valid_siblings(field: str, value: object) -> None:
    raw = synthetic_blog()
    raw[field] = value
    blog = BlogInfoDTO.model_validate(raw)

    assert blog.model_dump(by_alias=True)[field] is None
    if field != 'title':
        assert blog.title == BLOG_TITLE
    if field != 'owner':
        assert blog.owner is not None
        assert blog.owner.name == OWNER_NAME


@pytest.mark.parametrize(
    ('broken', 'valid'), [('avatarUrl', 'name'), ('name', 'avatarUrl')]
)
def test_broken_owner_field_keeps_the_other(broken: str, valid: str) -> None:
    raw = synthetic_blog()
    raw['owner'][broken] = []
    blog = BlogInfoDTO.model_validate(raw)

    assert blog.owner is not None
    fields = blog.owner.model_dump(by_alias=True)
    assert fields[broken] is None
    assert fields[valid] == raw['owner'][valid]


@pytest.mark.parametrize('value', [None, -1, True, False, 1.5, 1.0, '12', [], {}])
def test_bad_post_count_stays_unknown(value: object) -> None:
    blog = BlogInfoDTO.model_validate({'count': {'posts': value}})

    assert blog.count is not None
    assert blog.count.posts is None


def test_empty_values_and_zero_are_preserved() -> None:
    blog = BlogInfoDTO.model_validate(
        {
            'title': '',
            'description': [],
            'coverUrl': '',
            'owner': {'avatarUrl': '', 'name': ''},
            'count': {'posts': 0},
        }
    )

    assert blog.title == blog.cover_url == ''
    assert blog.description == []
    assert blog.owner is not None
    assert blog.owner.name == blog.owner.avatar_url == ''
    assert blog.count is not None
    assert blog.count.posts == 0


def test_empty_nested_objects_have_unknown_fields() -> None:
    blog = BlogInfoDTO.model_validate({'owner': {}, 'count': {}})

    assert blog.owner is not None
    assert blog.owner.name is None
    assert blog.owner.avatar_url is None
    assert blog.count is not None
    assert blog.count.posts is None


def test_unknown_description_kind_uses_the_existing_fallback() -> None:
    blog = BlogInfoDTO.model_validate({'description': [unknown_chunk()]})

    assert blog.description is not None
    assert len(blog.description) == 1
    assert isinstance(blog.description[0], BoostyPostDataUnknownDTO)


@pytest.mark.parametrize('raw', [None, [], 'blog', 42])
def test_non_object_root_is_invalid(raw: object) -> None:
    with pytest.raises(ValidationError):
        BlogInfoDTO.model_validate(raw)
