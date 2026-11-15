import { createHash } from 'node:crypto'
import { gunzipSync } from 'node:zlib'

const GZIP_OS_OFFSET = 9
const CANONICAL_OS_CODE = 255
const MINIMUM_GZIP_SIZE = 18

/** @param {Buffer} body */
function sha256(body) {
  return createHash('sha256').update(body).digest('hex')
}

/**
 * @typedef {Object} GzipProvenance
 * @property {number | null} osByte
 * @property {string} canonicalExpected
 * @property {string | null} canonicalActual
 * @property {string} payloadExpected
 * @property {string | null} payloadActual
 * @property {'missing' | 'invalid-header' | 'invalid-stream' | null} error
 * @property {boolean} matches
 */

/**
 * Compare the complete gzip stream with only its platform OS marker normalized.
 * The original buffer and served files remain unchanged.
 * @param {Buffer | null} body
 * @param {string} canonicalExpected
 * @param {string} payloadExpected
 * @returns {GzipProvenance}
 */
export function gzipProvenance(body, canonicalExpected, payloadExpected) {
  /** @type {GzipProvenance} */
  const result = {
    osByte: body?.[GZIP_OS_OFFSET] ?? null,
    canonicalExpected,
    canonicalActual: null,
    payloadExpected,
    payloadActual: null,
    error: null,
    matches: false,
  }
  if (!body) return { ...result, error: 'missing' }
  // The fixture compressor emits gzip without optional header fields.
  if (
    body.length < MINIMUM_GZIP_SIZE ||
    !body.subarray(0, 4).equals(Buffer.from([0x1f, 0x8b, 8, 0]))
  )
    return { ...result, error: 'invalid-header' }
  const canonical = Buffer.from(body)
  canonical[GZIP_OS_OFFSET] = CANONICAL_OS_CODE
  result.canonicalActual = sha256(canonical)
  try {
    result.payloadActual = sha256(gunzipSync(body))
  } catch {
    return { ...result, error: 'invalid-stream' }
  }
  result.matches =
    result.canonicalActual === canonicalExpected && result.payloadActual === payloadExpected
  return result
}
