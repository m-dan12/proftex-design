import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = resolve(__dirname, '../..')

describe('src/api/types.ts', () => {
  it('совпадает с contracts/openapi.yaml (иначе выполните npm run gen:api)', () => {
    const out = join(mkdtempSync(join(tmpdir(), 'gen-api-')), 'types.ts')
    const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')) as { scripts: Record<string, string> }
    const args = pkg.scripts['gen:api']!.split(' ').slice(1).map((a) => (a === 'src/api/types.ts' ? out : a))
    execFileSync(join(root, 'node_modules/.bin/openapi-typescript'), args, { cwd: root, stdio: 'ignore' })
    expect(readFileSync(out, 'utf8')).toBe(readFileSync(join(root, 'src/api/types.ts'), 'utf8'))
  }, 20_000)
})
