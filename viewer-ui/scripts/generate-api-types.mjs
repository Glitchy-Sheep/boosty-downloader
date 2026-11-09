import { execFileSync } from 'node:child_process'
import { writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

function normalizeClosedEmptyObjects(value) {
  if (value === null || typeof value !== 'object') return
  for (const child of Object.values(value)) normalizeClosedEmptyObjects(child)
  if (
    value.type === 'object' &&
    value.additionalProperties === false &&
    Object.keys(value.properties ?? {}).length === 0 &&
    Object.keys(value.patternProperties ?? {}).length === 0
  ) {
    value.tsType = 'Record<string, never>'
  }
}

const repository = fileURLToPath(new URL('../../', import.meta.url))
const schema = JSON.parse(execFileSync('uv', ['run', 'python', 'scripts/viewer_schema.py'], {
  cwd: repository,
  encoding: 'utf8',
}))
normalizeClosedEmptyObjects(schema)
const declarations = await compile(schema, 'ViewerAPI', {
  bannerComment: '/* Generated from the viewer API models. Regenerate with: task ui:types */',
  style: { singleQuote: true, semi: false },
})

await writeFile(new URL('../src/lib/api.gen.ts', import.meta.url), declarations, 'utf8')
