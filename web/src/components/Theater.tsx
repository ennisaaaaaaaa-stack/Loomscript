import { useEffect, useRef, useState } from 'react'
import { assetSrc, findAct, findChar, findEnding } from '../contract/lookup'
import type { Bundle, GameEvent } from '../contract/types'

type Show =
  | { kind: 'act'; key: number; actId: string }
  | { kind: 'death'; key: number; characterId: string; text?: string }
  | { kind: 'ending'; key: number; id?: string; title?: string; text?: string }

/**
 * 舞台演出层：游标向前推进时，挑这一段新事件里最重要的一个做全屏演出。
 * 优先级 结局 > 死亡 > 换幕。往回拖进度条不触发，直播一次来一批也不会漏掉。
 */
export function Theater({ events, cursor, bundle, onReview }: {
  events: GameEvent[]; cursor: number; bundle: Bundle; onReview?: () => void
}) {
  const prev = useRef(cursor)
  const [show, setShow] = useState<Show | null>(null)

  useEffect(() => {
    const from = prev.current
    prev.current = cursor
    if (cursor <= from) return
    const fresh = events.filter((e) => e.seq > from && e.seq <= cursor && !('__unknown' in e))
    const last = <T extends GameEvent['type']>(t: T) => [...fresh].reverse().find((e) => e.type === t) as Extract<GameEvent, { type: T }> | undefined
    const end = last('game_end')
    const death = last('death')
    const actBegin = last('act_begin')
    if (end?.ending_id) setShow({ kind: 'ending', key: end.seq, id: end.ending_id, title: end.ending_title, text: end.ending_text })
    else if (death) setShow({ kind: 'death', key: death.seq, characterId: death.character_id, text: death.text })
    else if (actBegin) setShow({ kind: 'act', key: actBegin.seq, actId: actBegin.act_id })
  }, [cursor, events])

  // 换幕、死亡自动收；结局留着等人点
  useEffect(() => {
    if (!show || show.kind === 'ending') return
    const t = setTimeout(() => setShow(null), show.kind === 'death' ? 4200 : 2600)
    return () => clearTimeout(t)
  }, [show])

  if (!show) return null
  if (show.kind === 'act') {
    const a = findAct(bundle, show.actId)
    return (
      <div className="theater theater--act" key={show.key} onClick={() => setShow(null)}>
        <small>{show.actId}</small>
        <strong>{a?.title}</strong>
        <p>{a?.world_info}</p>
      </div>
    )
  }
  if (show.kind === 'death') {
    const c = findChar(bundle, show.characterId)
    return (
      <div className="theater theater--death" key={show.key} onClick={() => setShow(null)}>
        <small>死亡</small>
        <strong>{c?.name ?? show.characterId}</strong>
        {show.text && <p>{show.text}</p>}
      </div>
    )
  }
  const cg = assetSrc(bundle.assets?.find((a) => a.id === findEnding(bundle, show.id)?.cg_id))
  return (
    <div className="theater theater--ending" key={show.key} style={cg ? { backgroundImage: `linear-gradient(rgba(10,8,12,.55), rgba(10,8,12,.92)), url(${cg})` } : undefined}>
      <small>结局</small>
      <strong>{show.title || show.id}</strong>
      {show.text && <p>{show.text}</p>}
      <div className="theater__actions">
        {onReview && <button className="primary" onClick={() => { setShow(null); onReview() }}>进入复盘</button>}
        <button className="ghost" onClick={() => setShow(null)}>留在对局</button>
      </div>
    </div>
  )
}
