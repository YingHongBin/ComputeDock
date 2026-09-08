import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { expirationState } from './ResourceDetailPage'

describe('expirationState', () => {
  const now = dayjs('2026-09-08T00:00:00Z')

  it('marks upcoming and elapsed expiration times', () => {
    expect(expirationState('2026-09-08T12:00:00Z', now)).toBe('expiring')
    expect(expirationState('2026-09-08T00:00:00Z', now)).toBe('expired')
    expect(expirationState('2026-09-07T23:59:59Z', now)).toBe('expired')
  })

  it('leaves later and missing expiration times unmarked', () => {
    expect(expirationState('2026-09-09T00:00:01Z', now)).toBe('active')
    expect(expirationState(null, now)).toBeNull()
  })
})
