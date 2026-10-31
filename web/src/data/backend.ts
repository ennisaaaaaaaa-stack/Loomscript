/**
 * 后端选择：同一套接口，两种实现。
 *  - remote：src/server.py（HTTP + SSE），地址 ?api=<base>，缺省 http://127.0.0.1:8740
 *  - local：浏览器内引擎（src/engine/），台词走 claude.ai 页面的 sample 能力
 * 规则：带 ?api= 强制 remote；带 ?local 强制 local；否则先探 remote /healthz，连不上就用 local。
 * claude.ai 链接里的页面连不了外部服务器，所以那里总是 local。
 */
export interface BundleSummary { bundle_id: string; id: string; title: string; version: string; characters: number; acts: number }
export interface ActionResult { events: unknown[]; snapshot: unknown }

export interface Backend {
  kind: 'remote' | 'local'
  label: string
  /** 资产相对路径的前缀；local 用内嵌图片，为空 */
  assetBase: string
  health: () => Promise<{ ok: boolean; bundles: string[] }>
  bundles: () => Promise<BundleSummary[]>
  bundle: (id: string, viewer?: string) => Promise<unknown>
  createGame: (bundle_id: string, opts?: { tier?: string; port?: string; me?: string }) => Promise<{ session_id: string; snapshot: unknown; last_seq: number }>
  say: (sid: string, character_id: string, text: string, channel?: string) => Promise<ActionResult>
  scene: (sid: string, scene_id: string) => Promise<ActionResult>
  dm: (sid: string, action: string, body?: Record<string, unknown>) => Promise<ActionResult>
  openStream: (sid: string, after: () => number, onEvent: (e: unknown) => void, onState: (s: 'open' | 'error') => void) => () => void
  /** 复盘自由交流；remote 还没有这个接口 */
  reviewChat?: (sid: string, character_id: string, history: { from: string; text: string }[], message: string) => Promise<string>
}

const params = new URLSearchParams(location.search)
export const API_BASE = params.get('api') ?? 'http://127.0.0.1:8740'

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: init?.body ? { 'content-type': 'application/json' } : undefined,
  })
  if (!r.ok) {
    const detail = await r.json().then((j) => j.detail, () => r.statusText)
    throw new Error(`${r.status} ${detail}`)
  }
  return r.json()
}
const post = <T>(path: string, body: unknown) => call<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const remoteBackend: Backend = {
  kind: 'remote',
  label: `后端 ${API_BASE}`,
  assetBase: API_BASE,
  health: () => call('/healthz'),
  bundles: () => call('/bundles'),
  bundle: (id, viewer) => call(`/bundles/${encodeURIComponent(id)}${viewer ? `?viewer=${encodeURIComponent(viewer)}` : ''}`),
  createGame: (bundle_id, opts = {}) => post('/games', { bundle_id, tier: opts.tier, port: opts.port }),
  say: (sid, character_id, text, channel = 'main') => post(`/games/${sid}/say`, { character_id, text, channel }),
  scene: (sid, scene_id) => post(`/games/${sid}/scene`, { scene_id }),
  dm: (sid, action, body = {}) => post(`/games/${sid}/dm`, { action, ...body }),
  /** SSE：断线 2s 重连，从上次 seq 续传，store 侧按 seq 去重 */
  openStream: (sid, after, onEvent, onState) => {
    let es: EventSource | null = null
    let closed = false
    const connect = () => {
      es = new EventSource(`${API_BASE}/games/${sid}/stream?after=${after()}`)
      es.onopen = () => onState('open')
      es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)) } catch { /* 坏行跳过 */ } }
      es.onerror = () => {
        onState('error')
        es?.close()
        if (!closed) setTimeout(connect, 2000)
      }
    }
    connect()
    return () => { closed = true; es?.close() }
  },
}

let chosen: Promise<Backend> | null = null
let current: Backend | null = null

export function getBackend(): Promise<Backend> {
  if (!chosen) {
    chosen = (async () => {
      if (params.has('api')) return remoteBackend
      const { localBackend } = await import('../engine/localApi')
      if (params.has('local')) return localBackend
      try {
        const ctl = new AbortController()
        const t = setTimeout(() => ctl.abort(), 1500)
        const r = await fetch(`${API_BASE}/healthz`, { signal: ctl.signal })
        clearTimeout(t)
        if (r.ok) return remoteBackend
      } catch { /* 连不上：本地引擎 */ }
      return localBackend
    })().then((b) => (current = b))
  }
  return chosen
}

const need = () => {
  if (!current) throw new Error('后端还没选好')
  return current
}

/** 组件里直接用的门面：转发到当前后端 */
export const api = {
  say: (...a: Parameters<Backend['say']>) => need().say(...a),
  scene: (...a: Parameters<Backend['scene']>) => need().scene(...a),
  dm: (...a: Parameters<Backend['dm']>) => need().dm(...a),
}
