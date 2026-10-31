import { useState } from 'react'
import { ChatWindow } from '../components/ChatWindow'
import { findCard, findProp } from '../contract/lookup'
import type { GameEvent } from '../contract/types'
import { useStore } from '../state/store'

export function ReviewPage() {
  const { handoff, frame, serverSnapshot, snapshotDiff, cursor, maxSeq } = useStore()
  const [talkTo, setTalkTo] = useState<string>('')
  const [local, setLocal] = useState<GameEvent[]>([])
  if (!handoff || !frame) return <div className="empty">加载中…</div>
  const b = handoff.bundle
  const s = serverSnapshot
  const npcs = b.characters.filter((c) => !c.is_player)
  const player = b.characters.find((c) => c.is_player)
  const target = talkTo || npcs[0]?.id

  return (
    <div className="review">
      <section className="review__dm">
        <h2>DM 复盘</h2>
        {frame.ending && (
          <div className="ending">
            <small>结局</small>
            <strong>{frame.ending.title ?? frame.ending.id}</strong>
            {frame.ending.text && <p>{frame.ending.text}</p>}
          </div>
        )}
        {frame.reviewText ? <blockquote>{frame.reviewText}</blockquote> : <p className="muted">还没有 review 事件{cursor < maxSeq ? '（回放未到终局）' : ''}。</p>}
        {b.endgame.review_prompt && <p className="muted">复盘引子：{b.endgame.review_prompt}</p>}
        <h4>结局集</h4>
        <ul className="ends">{b.endgame.conditions.map((c) => <li key={c.id}><code>{c.id}</code> {c.description}</li>)}</ul>
      </section>

      <section>
        <h4>快照对照（事件回放推导 vs 服务端 snapshot）</h4>
        {!s ? <p className="muted">handoff 里没有 snapshot</p> : (
          <>
            <p className={cursor < maxSeq ? 'muted' : snapshotDiff.length ? 'warn' : 'ok'}>
              {cursor < maxSeq ? '回放未到末尾，跳到末尾后对拍' : snapshotDiff.length ? `不一致：${snapshotDiff.join('、')}` : '✓ 逐字段一致'}
            </p>
            <table className="cmp">
              <thead><tr><th>角色</th><th>台词</th><th>已解锁</th></tr></thead>
              <tbody>
                {Object.entries(s.character_states).map(([id, cs]) => (
                  <tr key={id}>
                    <td>{b.characters.find((c) => c.id === id)?.name ?? id}</td>
                    <td>{cs.lines_spoken}</td>
                    <td>{cs.knowledge_unlocked.join('、') || '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>道具：{s.props_held.map((id) => findProp(b, id)?.name ?? id).join('、') || '–'}　卡：{s.cards_drawn.map((id) => findCard(b, id)?.name ?? id).join('、') || '–'}　降级档：<code>{s.degradation_tier || '–'}</code></p>
          </>
        )}
      </section>

      <section>
        <h4>和角色自由交流</h4>
        <div className="pills">
          {npcs.map((c) => <button key={c.id} className={c.id === target ? 'pill on' : 'pill'} onClick={() => { setTalkTo(c.id); setLocal([]) }}>{c.name}</button>)}
        </div>
        <ChatWindow
          title={`复盘 · ${b.characters.find((c) => c.id === target)?.name ?? ''}`}
          events={local}
          bundle={b}
          extra={<div className="sys"><div className="sys__sub">复盘对话接口未定，消息只在本地显示，不会发给后端。</div></div>}
          input={{
            placeholder: '问问 TA 当时在想什么',
            onSend: (text) => setLocal((l) => [...l, {
              type: 'player_line', character_id: player?.id ?? 'player', text,
              seq: 100000 + l.length, ts: new Date().toISOString(), session_id: 'local', channel: `dm:${target}`,
            }]),
          }}
        />
      </section>
    </div>
  )
}
