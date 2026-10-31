/**
 * 直播：对接 src/server.py。地址取 ?api=<base>，缺省 http://127.0.0.1:8740。
 *   GET  /bundles               剧本列表
 *   GET  /bundles/{id}?viewer=  玩家视图 bundle
 *   POST /games                 建局
 *   GET  /games/{sid}/stream    SSE 事件流（after=seq 续传）
 *   POST /games/{sid}/say       发言
 *   POST /games/{sid}/scene     进场景（结算揭示/死亡）
 *   POST /games/{sid}/dm        DM 结构性动作
 */
export const API_BASE = new URLSearchParams(location.search).get('api') ?? 'http://127.0.0.1:8740'

export interface BundleSummary { bundle_id: string; id: string; title: string; version: string; characters: number; acts: number }
export interface ActionResult { events: unknown[]; snapshot: unknown }

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

export const api = {
  health: () => call<{ ok: boolean; bundles: string[] }>('/healthz'),
  bundles: () => call<BundleSummary[]>('/bundles'),
  bundle: (id: string, viewer?: string) => call<unknown>(`/bundles/${encodeURIComponent(id)}${viewer ? `?viewer=${encodeURIComponent(viewer)}` : ''}`),
  createGame: (bundle_id: string, opts: { tier?: string; port?: string } = {}) =>
    post<{ session_id: string; snapshot: unknown; last_seq: number }>('/games', { bundle_id, ...opts }),
  say: (sid: string, character_id: string, text: string, channel = 'main') =>
    post<ActionResult>(`/games/${sid}/say`, { character_id, text, channel }),
  scene: (sid: string, scene_id: string) => post<ActionResult>(`/games/${sid}/scene`, { scene_id }),
  dm: (sid: string, action: string, body: Record<string, unknown> = {}) => post<ActionResult>(`/games/${sid}/dm`, { action, ...body }),
}

/** SSE 订阅。浏览器自带断线重连；重连时从上次 seq 续传，store 侧按 seq 去重。 */
export function openStream(sid: string, after: () => number, onEvent: (e: unknown) => void, onState: (s: 'open' | 'error') => void) {
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
}
