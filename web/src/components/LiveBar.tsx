import { findAct } from '../contract/lookup'
import { TIER_LABEL } from '../contract/normalize'
import { api } from '../data/backend'
import type { Frame } from '../state/frame'
import { useStore } from '../state/store'

/** 直播模式顶栏：连接状态 + DM 结构性推进（确定性动作，不走 LLM）。 */
export function LiveBar({ frame }: { frame: Frame }) {
  const { live, handoff, act, myRole, stopLive, serverSnapshot } = useStore()
  if (!live || !handoff) return null
  const b = handoff.bundle
  const actId = frame.snapshot.act_id
  const begun = new Set(handoff.events.flatMap((e) => (e.type === 'scene_begin' && 'scene_id' in e ? [String(e.scene_id)] : [])))
  const nextScene = findAct(b, actId)?.scenes.find((s) => !begun.has(s.scene_id))
  const ended = frame.phase === 'ended'
  const reviewed = frame.reviewText !== null
  const dis = live.busy || live.conn !== 'open'
  const acts = b.acts.map((a) => a.act_id)
  const curIdx = acts.indexOf(actId ?? '')
  const firedClues = new Set(handoff.events.flatMap((e) => (e.type === 'clue_found' ? [String(e.clue_id)] : [])))
  const nextClue = (b.clues ?? []).find((c) => !firedClues.has(c.clue_id) && (c.visible_at === 'final' ? curIdx === acts.length - 1 : acts.indexOf(c.visible_at ?? '') <= curIdx))
  const drawn = new Set(frame.snapshot.cards_drawn)
  const undrawn = b.cards.filter((c) => !drawn.has(c.id))
  const tier = serverSnapshot?.degradation_tier ?? frame.snapshot.degradation_tier

  return (
    <div className="replay live">
      <span className={`dot dot--${live.conn}`} title={live.conn} />
      <span className="replay__seq">{live.conn === 'open' ? (live.backend.kind === 'local' ? '对局中' : '直播中') : live.conn === 'connecting' ? '连接中' : '断线重连中'} · seq {frame.lastSeq}</span>
      {!ended && nextScene && (
        <button className="primary" disabled={dis} onClick={() => act((sid) => api.scene(sid, nextScene.scene_id))}>进入场景 {nextScene.scene_id}</button>
      )}
      {!ended && (
        <button className={nextScene ? 'ghost' : 'primary'} disabled={dis} onClick={() => act((sid) => api.dm(sid, 'advance_act'))}>
          {b.acts.at(-1)?.act_id === actId ? '终局' : '推幕'}
        </button>
      )}
      {!ended && myRole && (
        <button className="ghost" disabled={dis} onClick={() => act((sid) => api.dm(sid, 'deal_cards', { character_id: myRole }))}>发行动卡</button>
      )}
      {!ended && nextClue && (
        <button className="ghost" disabled={dis} title={`DM 提议线索 ${nextClue.clue_id}，引擎校验可见幕后放行`} onClick={() => act((sid) => api.dm(sid, 'propose_clue', { clue_id: nextClue.clue_id }))}>给线索</button>
      )}
      {!ended && undrawn.length > 0 && (
        <button className="ghost" disabled={dis} onClick={() => act((sid) => api.dm(sid, 'draw_card', { card_id: undrawn[Math.floor(Math.random() * undrawn.length)].id, character_id: myRole }))}>抽象征卡</button>
      )}
      {ended && !reviewed && <button className="primary" disabled={dis} onClick={() => act((sid) => api.dm(sid, 'review'))}>DM 复盘</button>}
      {ended && reviewed && <a className="primary" href="#review">看复盘 →</a>}
      <span className="grow" />
      {live.error && <span className="warn small">{live.error}</span>}
      <span className="tag" title={live.backend.label}>{live.backend.kind === 'local' ? '浏览器引擎' : '后端'} · {live.backend.kind === 'local' && tier === 'pianist' ? 'Claude 实时演出' : TIER_LABEL[tier] ?? tier}</span>
      <code title={live.sid}>{live.sid.slice(0, 8)}</code>
      <button className="ghost" onClick={stopLive}>离开</button>
    </div>
  )
}
