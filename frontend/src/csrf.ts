/** The sign-in cookie that the page may read and echo back as a header, so other websites cannot make changes. */
export const CSRF_COOKIE = 'pathippu_csrf'
export const CSRF_HEADER = 'X-CSRF-Token'

/** The value of a cookie from a cookie string (defaults to this page's cookies), or an empty string. */
export function readCookie(name: string, source: string = typeof document === 'undefined' ? '' : document.cookie): string {
  for (const part of source.split(';')) {
    const [key, ...rest] = part.trim().split('=')
    if (key === name) return decodeURIComponent(rest.join('='))
  }
  return ''
}
