import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { mergeEvents, normalizeBundle, normalizeEvent, normalizeHandoff, normalizeSnapshot } from '../contract/normalize'
import type { Handoff, Snapshot } from '../contract/types'
import { api, openStream, type ActionResult } from '../data/live'
import { BUILTIN_SOURCES, loadFromUrl } from '../data/sources'
import { diffSnapshot, frameAt, type Frame } from './frame'

export interface LiveState {
  sid: string
  bundleId: string
  conn: 'connecting' | 'open' | 'error'
  busy: boolean
  error: string | null
}

interface Store {
  /** 玩家扮演的角色：直播=开局时选的；回放=第一个 is_player */
  myRole: string | undefined
  live: LiveState | null
  startLive: (bundleId: string, role: string) => Promise<void>
  stopLive: () => void
  /** 调后端动作，结果里的事件与快照并入当前局 */
  act: (fn: (sid: string) => Promise<ActionResult>) => Promise<void>
  sourceLabel: string
  handoff: Handoff | null
  serverSnapshot: Snapshot | null
  loadError: string | null
  load: (raw: unknown, label: string) => void
  loadBuiltin: (id: string) => void
  cursor: number
  setCursor: (seq: number) => void
  maxSeq: number
  frame: Frame | null
  /** 回放到末尾且服务端快照 seq 对得上时，当前帧以服务端 snapshot 为准 */
  displaySnapshot: Snapshot | null
  snapshotDiff: string[]
}

const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [handoff, setHandoff] = useState<Handoff | null>(null)
  const [serverSnapshot, setServerSnapshot] = useState<Snapshot | null>(null)
  const [sourceLabel, setSourceLabel] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [cursor, setCursor] = useState(-1)
  const [live, setLive] = useState<LiveState | null>(null)
  const [liveRole, setLiveRole] = useState<string>()
  const stopStream = useRef<(() => void) | null>(null)
  const lastSeq = useRef(-1)

  const ingest = useCallback((raw: unknown[], snap?: unknown) => {
    const evs = raw.map((r, i) => normalizeEvent(r, i)).filter((e) => e !== null)
    if (evs.length) {
      setHandoff((h) => {
        if (!h) return h
        const events = mergeEvents(h.events, evs)
        lastSeq.current = events.at(-1)?.seq ?? -1
        return { ...h, events }
      })
      setCursor(Math.max(...evs.map((e) => e.seq), lastSeq.current)) // 直播永远跟到最新
    }
    const s = snap ? normalizeSnapshot(snap) : null
    if (s) setServerSnapshot((cur) => (!cur || s.seq >= cur.seq ? s : cur))
  }, [])

  const stopLive = useCallback(() => {
    stopStream.current?.()
    stopStream.current = null
    setLive(null)
  }, [])

  const startLive = useCallback(async (bundleId: string, role: string) => {
    stopLive()
    const bundle = normalizeBundle(await api.bundle(bundleId, role))
    const g = await api.createGame(bundleId)
    lastSeq.current = -1
    setHandoff({ bundle, events: [], snapshot: normalizeSnapshot(g.snapshot)! })
    setServerSnapshot(normalizeSnapshot(g.snapshot))
    setSourceLabel(`直播 · ${bundle.title}`)
    setLoadError(null)
    setCursor(-1)
    setLiveRole(role)
    setLive({ sid: g.session_id, bundleId, conn: 'connecting', busy: false, error: null })
    stopStream.current = openStream(
      g.session_id,
      () => lastSeq.current,
      (e) => ingest([e]),
      (st) => setLive((l) => (l ? { ...l, conn: st } : l)),
    )
  }, [ingest, stopLive])

  const act = useCallback(async (fn: (sid: string) => Promise<ActionResult>) => {
    if (!live) return
    setLive((l) => (l ? { ...l, busy: true, error: null } : l))
    try {
      const r = await fn(live.sid)
      ingest(r.events ?? [], r.snapshot)
      setLive((l) => (l ? { ...l, busy: false } : l))
    } catch (err) {
      setLive((l) => (l ? { ...l, busy: false, error: String(err instanceof Error ? err.message : err) } : l))
    }
  }, [live, ingest])

  useEffect(() => () => stopStream.current?.(), [])

  const load = useCallback((raw: unknown, label: string) => {
    stopStream.current?.()
    stopStream.current = null
    setLive(null)
    setLiveRole(undefined)
    try {
      const { handoff, snapshot } = normalizeHandoff(raw)
      setHandoff(handoff)
      setServerSnapshot(snapshot)
      setSourceLabel(label)
      setLoadError(null)
      setCursor(handoff.events.at(-1)?.seq ?? -1)
    } catch (err) {
      setLoadError(String(err))
    }
  }, [])

  const loadBuiltin = useCallback((id: string) => {
    const s = BUILTIN_SOURCES.find((s) => s.id === id) ?? BUILTIN_SOURCES[0]
    s.load().then((raw) => load(raw, s.label))
  }, [load])

  useEffect(() => {
    const src = new URLSearchParams(location.search).get('src')
    if (src) loadFromUrl(src).then((raw) => load(raw, src), (e) => setLoadError(`加载 ${src} 失败：${e}`))
    else loadBuiltin(BUILTIN_SOURCES[0].id)
  }, [load, loadBuiltin])

  const maxSeq = handoff?.events.at(-1)?.seq ?? -1
  const frame = useMemo(() => (handoff ? frameAt(handoff.events, cursor, handoff.bundle) : null), [handoff, cursor])
  const atEnd = cursor >= maxSeq
  const useServer = !!serverSnapshot && atEnd && serverSnapshot.seq === maxSeq
  const displaySnapshot = useServer ? serverSnapshot : frame?.snapshot ?? null
  const snapshotDiff = useMemo(
    () => (frame && serverSnapshot && atEnd ? diffSnapshot(frame.snapshot, serverSnapshot) : []),
    [frame, serverSnapshot, atEnd],
  )

  const myRole = liveRole ?? handoff?.bundle.characters.find((c) => c.is_player)?.id

  const value: Store = {
    myRole, live, startLive, stopLive, act,
    sourceLabel, handoff, serverSnapshot, loadError, load, loadBuiltin,
    cursor, setCursor, maxSeq, frame, displaySnapshot, snapshotDiff,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useStore(): Store {
  const s = useContext(Ctx)
  if (!s) throw new Error('useStore outside StoreProvider')
  return s
}
