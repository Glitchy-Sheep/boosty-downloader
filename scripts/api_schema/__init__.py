"""
Observed schema of the Boosty API: shapes of live answers turned into OpenAPI.

Dev tool, not part of the package. `shapes` counts what keys and types came
in the answers, `openapi` renders the counts as an OpenAPI 3.1 document.
No value from an answer is kept, except short token-like strings of
vocabulary fields such as `type` or `uploadStatus`.
"""
