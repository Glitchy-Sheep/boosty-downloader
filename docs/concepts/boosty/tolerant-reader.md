# Tolerant Reader: surviving Boosty API changes

Boosty changes its API without notice: new content types, new fields and new enum values appear over time - most recently the `ondemand_*` video url types (Aug 2026). One new word from the server used to kill the whole download.

This client follows the [Tolerant Reader](https://martinfowler.com/bliki/TolerantReader.html) pattern with the [RFC 9413](https://www.rfc-editor.org/rfc/rfc9413.html) amendment: **accept the unknown, lose nothing, and always tell the user**.

## The invariant: unknown is a type

Unknown data exists in the codebase only as two wrapper types:

| Wrapper | Covers | Example |
|---|---|---|
| `BoostyUnknownValue(raw=...)` | a value outside a known enum | new video url type `'ondemand_dash'` |
| `BoostyPostDataUnknownDTO` | a whole chunk of an unknown type | a new Boosty content block |

Every field with a fixed set of values follows one pattern - enum plus catch-all:

```python
TolerantOkVideoType = Annotated[
    BoostyOkVideoType | UnknownValue,
    Field(union_mode='left_to_right'),
]
```

- The enum is the point of truth for the known set.
- Anything else parses into `BoostyUnknownValue`, keeping the raw word.
- `union_mode='left_to_right'` is required: pydantic's default smart mode lets the catch-all swallow known values too. Pinned by `test_known_url_type_still_parses_exactly`.

Unknown chunk types fall back the same way: the discriminated union of known chunks gets `BoostyPostDataUnknownDTO` as the last resort. Only tag errors trigger the fallback. A known chunk with a broken body still fails validation, so a real breakage never hides behind "unknown".

## Observability: the generic walk

`collect_unknown_content(post)` walks a parsed post and returns every wrapper it finds, with its API path:

```
data[8].playerUrls[2].type = 'ondemand_hls'
```

There is no registry of tolerant fields to keep in sync. Adding a new tolerant field takes zero extra steps:

- without the wrapper an unknown value fails loudly (ValidationError) - you cannot become tolerant silently;
- with the wrapper the walk finds it automatically.

The run summary (being built now) will list the findings and ask to report them - new Boosty content becomes a GitHub issue instead of a silent loss.

## Where the code lives

- `infrastructure/boosty_api/models/unknown_value.py` - the value wrapper
- `infrastructure/boosty_api/models/post/post_data_types/post_data_unknown.py` - the chunk fallback
- `infrastructure/boosty_api/models/post/base_post_data.py` - the union with tag-only fallback
- `infrastructure/boosty_api/models/unknown_content.py` - the generic walk
- Tests: `test/unit/boosty_api/`, `test/unit/mappers/post_mapper_test.py`
