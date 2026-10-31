import { findAct } from '../contract/lookup'
import { api } from '../data/live'
import type { Frame } from '../state/frame'
import { useStore } from '../state/store'

/** 直播模式顶栏：连接状态 + DM 结构性推进（确定性动作，不走 LLM）。 */
export function LiveBar({ frame }: { frame: Frame }) {
  const { live, handoff, act, myRole, stopLive } = useStore()
  if (!live || !handoff) return null
  const b = handoff.bundle
  const actId = frame.snapshot.act_id
  const begun = new Set(handoff.events.flatMap((e) => (e.type === 'scene_begin' && 'scene_id' in e ? [String(e.scene_id)] : [])))
  const nextScene = findAct(b, actId)?.scenes.find((s) => !begun.has(s.scene_id))
  const ended = frame.phase === 'ended'
  const reviewed = frame.reviewText !== null
  const dis = live.busy || live.conn !== 'open'

  return (
    <div className="replay live">
      <span className={`dot dot--${live.conn}`} title={live.conn} />
      <span className="replay__seq">{live.conn === 'open' ? '直播中' : live.conn === 'connecting' ? '连接中' : '断线重连中'} · seq {frame.lastSeq}</span>
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
      {ended && !reviewed && <button className="primary" disabled={dis} onClick={() => act((sid) => api.dm(sid, 'review'))}>DM 复盘</button>}
      {ended && reviewed && <a className="primary" href="#/review">看复盘 →</a>}
      <span className="grow" />
      {live.error && <span className="warn small">{live.error}</span>}
      <code title={live.sid}>{live.sid.slice(0, 8)}</code>
      <button className="ghost" onClick={stopLive}>离开</button>
    </div>
  )
}
