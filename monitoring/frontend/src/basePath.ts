export function normalizeBasePath(pathname: string): string {
  const normalized = `/${pathname}`.replace(/\/{2,}/g, '/').replace(/\/+$/, '')
  return normalized === '' || normalized === '/' ? '' : normalized
}

export function detectBasePath(): string {
  const base = document.querySelector('base')
  if (!base) return ''
  return normalizeBasePath(new URL(base.href, window.location.origin).pathname)
}

export const APP_BASE_PATH = detectBasePath()

export function toAppPath(publicPath: string, basePath = APP_BASE_PATH): string {
  if (!basePath) return publicPath || '/'
  if (publicPath === basePath || publicPath === `${basePath}/`) return '/'
  if (publicPath.startsWith(`${basePath}/`)) return publicPath.slice(basePath.length)
  return '/'
}

export function toPublicPath(appPath: string, basePath = APP_BASE_PATH): string {
  if (!appPath.startsWith('/')) throw new Error('application path must start with /')
  if (appPath === '/') return basePath ? `${basePath}/` : '/'
  return `${basePath}${appPath}`
}

export function apiBasePath(basePath = APP_BASE_PATH): string {
  return `${basePath}/api/v1`
}
