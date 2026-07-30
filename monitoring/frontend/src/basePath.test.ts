import { describe, expect, it } from 'vitest'
import { apiBasePath, normalizeBasePath, toAppPath, toPublicPath } from './basePath'

describe('application base path', () => {
  it('supports root and nested proxy prefixes', () => {
    expect(normalizeBasePath('/')).toBe('')
    expect(normalizeBasePath('/platform/tools/console/')).toBe('/platform/tools/console')
    expect(apiBasePath('/platform/tools/console')).toBe('/platform/tools/console/api/v1')
  })

  it('maps browser paths to internal routes and back', () => {
    const base = '/platform/tools/console'
    expect(toAppPath(`${base}/resources/123`, base)).toBe('/resources/123')
    expect(toAppPath(`${base}/`, base)).toBe('/')
    expect(toPublicPath('/resources/123', base)).toBe(`${base}/resources/123`)
    expect(toPublicPath('/', base)).toBe(`${base}/`)
  })
})
