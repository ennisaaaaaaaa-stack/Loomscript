import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { normalizeHandoff } from '../contract/normalize'
import type { Handoff, Snapshot } from '../contract/types'
import { BUILTIN_SOURCES, loadFromUrl } from '../data/sources'
import { diffSnapshot, frameAt, type Frame } from './frame'

interface Store {
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

  const load = useCallback((raw: unknown, label: string) => {
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

  const value: Store = {
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
