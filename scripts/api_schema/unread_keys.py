"""
What the client's models read, so the schema can say what they ignore.

The keys come from the pydantic models themselves through their JSON schema,
so a new field in a DTO drops out of `x-unread-by-client` on the next run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, get_args

from api_schema.openapi_document import chunk_component_name
from boosty_downloader.infrastructure.boosty_api.models.blog import BlogInfoDTO
from boosty_downloader.infrastructure.boosty_api.models.post import post_data_types
from boosty_downloader.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

if TYPE_CHECKING:
    from pydantic import BaseModel

    from api_schema.observed_shapes import ObservedObject


def keys_unread_by_client(
    post: ObservedObject, page: ObservedObject, blog: ObservedObject
) -> dict[str, list[str]]:
    """Observed keys per component that no model field reads."""
    unread = {
        'Post': _unread(post, PostDTO),
        'BlogInfo': _unread(blog, BlogInfoDTO),
        'PageExtra': _unread(_nested(page, 'extra'), Extra),
    }
    unread.update(_unread_chunks(post, 'data'))
    unread.update(_unread_chunks(blog, 'description'))
    return {name: keys for name, keys in unread.items() if keys}


def _unread_chunks(shape: ObservedObject, path: str) -> dict[str, list[str]]:
    data = shape.keys.get(path)
    variants = data.variants if data is not None else None
    if not variants:
        return {}
    return {
        chunk_component_name(kind, path): _unread(variants[kind], model)
        for kind, model in _chunk_dto_by_type().items()
        if kind in variants
    }


def _unread(shape: ObservedObject | None, model: type[BaseModel]) -> list[str]:
    if shape is None:
        return []
    read = set(model.model_json_schema(by_alias=True)['properties'])
    return sorted(key for key in shape.keys if key not in read)


def _nested(shape: ObservedObject, key: str) -> ObservedObject | None:
    field = shape.keys.get(key)
    return field.nested if field is not None else None


def _chunk_dto_by_type() -> dict[str, type[BaseModel]]:
    """Chunk `type` value -> the DTO that parses it, from the Literal of each DTO."""
    models: dict[str, type[BaseModel]] = {}
    for name in post_data_types.__all__:
        model: type[BaseModel] = getattr(post_data_types, name)
        for kind in get_args(model.model_fields['type'].annotation):
            models[kind] = model
    return models
