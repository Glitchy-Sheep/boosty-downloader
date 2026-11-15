import { readdir, readFile, writeFile } from 'node:fs/promises'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brotliCompressSync, constants, gzipSync } from 'node:zlib'

const output = fileURLToPath(new URL('../../boosty_downloader/viewer/static/app/', import.meta.url))
const compressibleExtensions = new Set(['.js', '.css'])

async function compressDirectory(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      await compressDirectory(path)
    } else if (entry.isFile() && compressibleExtensions.has(extname(entry.name))) {
      const content = await readFile(path)
      await Promise.all([
        writeFile(`${path}.gz`, gzipSync(content, { level: 9 })),
        writeFile(`${path}.br`, brotliCompressSync(content, {
          params: {
            [constants.BROTLI_PARAM_MODE]: constants.BROTLI_MODE_TEXT,
            [constants.BROTLI_PARAM_QUALITY]: 11,
          },
        })),
      ])
    }
  }
}

await compressDirectory(output)
