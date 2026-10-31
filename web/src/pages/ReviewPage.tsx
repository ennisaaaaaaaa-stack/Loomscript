import { useState } from 'react'
import { ChatWindow } from '../components/ChatWindow'
import { findCard, findChar, findProp } from '../contract/lookup'
import { DM_ID } from '../contract/normalize'
import type { GameEvent } from '../contract/types'
import { useStore } from '../state/store'

export function ReviewPage() {
  const { handoff, frame, serverSnapshot, snapshotDiff, cursor, maxSeq, myRole, live } = useStore()
  const [talkTo, setTalkTo] = useState<string>('')
  const [local, setLocal] = useState<GameEvent[]>([])
  const [thinking, setThinking] = useState(false)
  if (!handoff || !frame) return <div className="empty">加载中…</div>
  const b = handoff.bundle
  const s = serverSnapshot
  const npcs = b.characters.filter((c) => c.id !== myRole)
  const player = b.characters.find((c) => c.id === myRole)
  const target = talkTo || DM_ID
  const chatApi = live?.backend.reviewChat
  const line = (type: 'player_line' | 'agent_line', character_id: string, text: string, n: number): GameEvent => ({
    type, character_id, text, seq: 100000 + n, ts: new Date().toISOString(), session_id: 'local', channel: `dm:${target}`,
  })
  const send = async (text: string) => {
    const mine = line('player_line', player?.id ?? 'player', text, local.length)
    const history = local.map((e) => ({ from: e.type === 'player_line' ? (player?.name ?? '玩家') : (findChar(b, (e as { character_id: string }).character_id)?.name ?? ''), text: String((e as { text?: string }).text ?? '') }))
    setLocal((l) => [...l, mine])
    if (!chatApi || !live) return
    setThinking(true)
    try {
      const reply = await chatApi(live.sid, target, history, text)
      setLocal((l) => [...l, line('agent_line', target, reply, l.length)])
    } catch (e) {
      setLocal((l) => [...l, { type: 'error', error_code: 'agent_unreachable', text: String(e instanceof Error ? e.message : e), seq: 100000 + l.length, ts: new Date().toISOString(), session_id: 'local', channel: `dm:${target}` } as GameEvent])
    } finally { setThinking(false) }
  }

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
                    <td>{[...new Set(cs.knowledge_unlocked)].join('、') || '–'}</td>
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
          <button className={target === DM_ID ? 'pill on' : 'pill'} onClick={() => { setTalkTo(DM_ID); setLocal([]) }}>主持人</button>
          {npcs.map((c) => <button key={c.id} className={c.id === target ? 'pill on' : 'pill'} onClick={() => { setTalkTo(c.id); setLocal([]) }}>{c.name}</button>)}
        </div>
        <ChatWindow
          title={`复盘 · ${findChar(b, target)?.name ?? ''}`}
          events={local}
          bundle={b}
          me={myRole}
          extra={thinking ? <div className="typing"><span>{findChar(b, target)?.name}正在想</span><i /><i /><i /></div>
            : !local.length ? <div className="sys"><div className="sys__sub">{chatApi ? '对局已经结束，秘密可以摊开说了。问问 TA 当时在想什么。' : '这个后端还没有复盘对话接口：消息只在本地显示。开一局浏览器引擎的对局，复盘时就能和角色聊。'}</div></div> : undefined}
          input={{ placeholder: '问问 TA 当时在想什么', disabled: thinking, onSend: (text) => void send(text) }}
        />
      </section>
    </div>
  )
}
