import { describe, expect, it } from 'vitest'
import { readCookie } from './csrf'

describe('readCookie', () => {
  it('finds a cookie among several', () => {
    const cookies = 'theme=dark; pathippu_csrf=abc123_-XYZ; other=1'
    expect(readCookie('pathippu_csrf', cookies)).toBe('abc123_-XYZ')
    expect(readCookie('theme', cookies)).toBe('dark')
  })

  it('keeps equals signs and decodes the value', () => {
    expect(readCookie('token', 'token=a%20b=c')).toBe('a b=c')
  })

  it('returns an empty string when the cookie is missing', () => {
    expect(readCookie('pathippu_csrf', 'a=1; b=2')).toBe('')
    expect(readCookie('pathippu_csrf', '')).toBe('')
  })

  it('does not match a cookie whose name only ends the same way', () => {
    expect(readCookie('csrf', 'pathippu_csrf=secret')).toBe('')
  })
})
