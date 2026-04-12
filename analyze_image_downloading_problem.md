# Analyze slow image downloading

Images reportedly take much longer to download than expected. Need to understand what happens during each download request.

## Current download flow

1. Boosty API returns complete image URLs in post data
2. `file_downloader.py` makes GET request via `RetryClient` (aiohttp)
3. Response is streamed in 512 KiB chunks, written to disk via `aiofiles`
4. Downloads are sequential - one file at a time, no parallelism
5. No timeout set (`total=None`)
6. Rate limiting only applies to API pagination, not file downloads

## Investigation plan

### Step 1: Add temporary logging to file_downloader.py

Instrument `download_file()` to log per-request timing:
- Time from request start to first byte (TTFB) - shows server/network latency
- Time from first byte to download complete - shows transfer speed
- Response status code and headers (Content-Length, Content-Type, redirects)
- Final file size vs Content-Length (detect incomplete downloads)

### Step 2: Run a test download and collect logs

Download a small set of posts and analyze the timing data:
- Are images slow because of high TTFB? (server-side issue, redirects, CDN)
- Are they slow because of low throughput? (bandwidth, chunking)
- Are there unexpected redirects adding latency?
- Are there 429 (rate limit) or 503 responses causing retries?

### Step 3: Identify the bottleneck

Based on logs, determine if the issue is:
- **Server-side**: high TTFB, slow CDN, redirects
- **Client-side**: sequential downloads, no connection reuse, DNS per request
- **Network**: low bandwidth, packet loss

### Step 4: Fix based on findings

Possible fixes depending on the root cause:
- **Parallel downloads** via `asyncio.gather()` or `TaskGroup` with concurrency limit
- **Connection pooling tuning** if connections aren't being reused
- **DNS caching** if DNS resolution adds latency per request
- **Redirect following optimization** if Boosty CDN adds redirect hops
