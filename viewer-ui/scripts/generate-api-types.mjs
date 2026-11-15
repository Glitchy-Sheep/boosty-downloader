import { execFileSync } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** @param {unknown} value */
function hasProperties(value) {
  return isObject(value) && Object.keys(value).length > 0
}

/** @param {unknown} value */
function normalizeClosedEmptyObjects(value) {
  if (Array.isArray(value)) {
    for (const child of value) normalizeClosedEmptyObjects(child)
    return
  }
  if (!isObject(value)) return
  for (const child of Object.values(value)) normalizeClosedEmptyObjects(child)
  if (
    value.type === 'object' &&
    value.additionalProperties === false &&
    !hasProperties(value.properties) &&
    !hasProperties(value.patternProperties)
  ) {
    value.tsType = 'Record<string, never>'
  }
}

const repository = fileURLToPath(new URL('../../', import.meta.url))
/** @type {unknown} */
const schema = JSON.parse(
  execFileSync('uv', ['run', 'python', 'scripts/viewer_schema.py'], {
    cwd: repository,
    encoding: 'utf8',
  }),
)
if (!isObject(schema) || schema.type !== 'object') {
  throw new TypeError('The viewer API schema must be an object schema')
}
normalizeClosedEmptyObjects(schema)
const declarations = await compile(schema, 'ViewerAPI', {
  bannerComment: '/* Generated from the viewer API models. Regenerate with: task ui:types */',
  style: { singleQuote: true, semi: false },
})

await writeFile(new URL('../src/lib/api.gen.ts', import.meta.url), declarations, 'utf8')
