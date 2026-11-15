# Library benchmark

The benchmark exercises the production JSON codecs, index rebuild, change synchronization and SQL schema on deterministic synthetic data. It needs no credentials or network access. Run it on a local SSD with other tests and builds stopped:

```bash
task benchmark:library -- /tmp/boosty-library-benchmark --json /tmp/boosty-library-results.json
```

The default workload contains 20 authors with 1000 saved posts each and 100000 media entries. It mixes media states, retained removed pieces, viewing marks and access observations. Small cover files stand in for image payloads; recorded sizes represent the larger media. The report includes actual source sizes and runtime information.

Use a new directory. The script reuses only its own versioned fixture with matching settings and verified contents; it never adopts or overwrites an existing downloaded library. Keep JSON reports outside the fixture. `--generate-only` prepares or verifies data without running performance acceptance. Smaller `--authors` and `--posts-per-author` values are useful for smoke checks and are explicitly not the 20000-post acceptance workload.

## Budgets

| Operation | Budget |
| --- | --- |
| Each SQL query, including storage sums for all authors | Under 10 ms |
| Full production index rebuild | Under 10 s |
| Unchanged synchronization, including integrity checks | Under 1 s |

SQL measurements consume the complete selected result and use bound parameters. They cover the author post list, combined filters, month groups, author counts, full-text search and storage sums. Downloaded pieces removed by the author still count toward storage; other download states do not. The benchmark checks results against the synthetic fixture as well as measuring time.

The SQL budget excludes ORM and domain object construction. Full reader timing is reported separately, as is synchronization after changing one percent of records. The viewer has its own response-time acceptance tests. Rebuild and unchanged-open measurements include the complete production operations, not reduced benchmark substitutes.

Use `--samples` to choose query/open repetitions and `--rebuild-samples` for full rebuilds. Results show the first sample and warm median/range. A failed budget produces a nonzero exit status. Ordinary unit tests verify fixture safety and query correctness without hardware-dependent timing gates.

These are warm local-SSD measurements. Cold caches, network storage and other hardware can be slower; include the report and environment when comparing results. Performance changes must preserve source validation, transactional updates and canonical data.
