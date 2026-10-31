import { findCard, findProp } from '../contract/lookup'
import { TIER_LABEL } from '../contract/normalize'
import type { Bundle, Snapshot } from '../contract/types'
import type { Frame } from '../state/frame'
import { Avatar } from './Avatar'


/** 当前帧：照 snapshot 摆。clue/journal 是 v0.1 事件派生的，snapshot 未来若加字段再切过去。 */
export function FramePanel({ bundle, snap, frame, unread, onOpenDm, fromServer }: {
  bundle: Bundle; snap: Snapshot; frame: Frame; unread: Record<string, number>
  onOpenDm: (id: string) => void; fromServer: boolean
}) {
  return (
    <aside className="frame">
      <div className="frame__src">{fromServer ? '服务端 snapshot' : '回放推导帧'} · seq {snap.seq}</div>

      <h4>角色</h4>
      <ul className="roster">
        {bundle.characters.map((c) => {
          const st = snap.character_states[c.id]
          const n = unread[c.id] ?? 0
          return (
            <li key={c.id} className={st?.on_stage === false || st?.alive === false ? 'off' : ''}>
              <button className="roster__btn" onClick={() => onOpenDm(c.id)} disabled={c.is_player} title={c.is_player ? '你' : `私聊 ${c.name}`}>
                <Avatar c={c} size={32} />
                {n > 0 && <span className="badge">{n}</span>}
              </button>
              <div>
                <div>{c.name}{c.is_player && <span className="tag">你</span>}{st?.alive === false && <span className="tag tag--dim">已死·观演</span>}</div>
                <small>台词 {st?.lines_spoken ?? 0} · 已知 {st?.knowledge_unlocked.length ?? 0}</small>
              </div>
            </li>
          )
        })}
      </ul>

      <h4>道具栏</h4>
      <div className="chips">
        {snap.props_held.length ? snap.props_held.map((id) => <span key={id} className="chip pop">{findProp(bundle, id)?.name ?? id}</span>) : <em>空</em>}
      </div>

      <h4>已抽卡</h4>
      <div className="chips">
        {snap.cards_drawn.length ? snap.cards_drawn.map((id) => {
          const c = findCard(bundle, id)
          return <span key={id} className="chip chip--card flip" title={c?.symbol}>{c?.name ?? id}</span>
        }) : <em>无</em>}
      </div>

      <h4>线索 <small>{frame.clues.length}</small></h4>
      {frame.clues.length ? frame.clues.map((c) => (
        <div key={c.id} className="note pop"><b>{c.title ?? c.id}</b>{c.text && <p>{c.text}</p>}</div>
      )) : <em>暂无</em>}

      <h4>DM 手账 <small>{frame.journal.length}</small></h4>
      {frame.journal.length ? frame.journal.map((j) => (
        <div key={j.id} className="note note--journal pop">{j.text}</div>
      )) : <em>暂无</em>}

      <h4>已解锁 CG</h4>
      <div className="chips">{snap.cg_unlocked.length ? snap.cg_unlocked.map((id) => <span key={id} className="chip">{id}</span>) : <em>无</em>}</div>

      <h4>运行状态</h4>
      <div className="kv"><span>降级档</span><code>{snap.degradation_tier ? TIER_LABEL[snap.degradation_tier] ?? snap.degradation_tier : '–'}</code></div>
      <div className="kv"><span>位置</span><code>{snap.act_id ?? '–'} / {snap.scene_id ?? '–'}</code></div>
    </aside>
  )
}
