"""Export the viewer wire models as one JSON Schema generation bundle."""

from __future__ import annotations

import json
import sys
from inspect import getmembers, isabstract, isclass

from pydantic import BaseModel
from pydantic.json_schema import (
    GenerateJsonSchema,
    JsonSchemaValue,
    models_json_schema,
)

from boosty_downloader.viewer import api_models


class _ViewerSchema(GenerateJsonSchema):
    def field_title_should_be_set(self, schema: object) -> bool:  # noqa: ARG002
        return False


def _get_models() -> list[type[BaseModel]]:
    return [
        model
        for name, model in getmembers(api_models, isclass)
        if not name.startswith('_')
        and issubclass(model, BaseModel)
        and model.__module__ == api_models.__name__
        and not isabstract(model)
    ]


def build_schema() -> JsonSchemaValue:
    """Include every concrete API model, including standalone request bodies."""
    models = _get_models()
    references, schema = models_json_schema(
        [(model, 'serialization') for model in models], schema_generator=_ViewerSchema
    )
    return {
        **schema,
        '$schema': GenerateJsonSchema.schema_dialect,
        'title': 'ViewerAPI',
        'description': 'A schema generation bundle, never an HTTP response envelope.',
        'type': 'object',
        'properties': {
            model.__name__: references[model, 'serialization'] for model in models
        },
        'required': [model.__name__ for model in models],
        'additionalProperties': False,
    }


def main() -> None:
    """Write deterministic UTF-8 JSON to stdout for the TypeScript generator."""
    document = json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.buffer.write((document + '\n').encode('utf-8'))


if __name__ == '__main__':
    main()
