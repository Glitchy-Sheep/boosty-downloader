"""
Observed schema of the Boosty API: shapes of live answers turned into OpenAPI.

Dev tool, not part of the package. `live_api` reads the answers,
`observed_shapes` counts which keys and types came in them, `unread_keys`
lists what the client's models ignore, `openapi_document` renders it all as
OpenAPI 3.1. No value from an answer is kept, except short token-like
strings of vocabulary fields such as `type` or `uploadStatus`.
"""
