import { useEffect, useMemo, useRef, useState } from 'react'
import { AssetFrame } from '../components/AssetFrame'
import { ChatWindow } from '../components/ChatWindow'
import { describe } from '../components/eventView'
import { FramePanel } from '../components/FramePanel'
import { ReplayBar } from '../components/ReplayBar'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { findAct, findChar, findScene } from '../contract/lookup'
import { useStore } from '../state/store'

export function PlayPage() {
  const { handoff, frame, cursor, setCursor, displaySnapshot, serverSnapshot, maxSeq } = useStore()
  const [openDms, setOpenDms] = useState<string[]>([])
  // 每个私聊窗已读到的 seq；窗开着就视为已读
  const [readSeq, setReadSeq] = useState<Record<string, number>>({})
  const tlRef = useRef<HTMLDivElement>(null)

  const threads = frame?.threads ?? {}
  useEffect(() => {
    setReadSeq((r) => {
      const n = { ...r }
      for (const id of openDms) n[id] = threads[id]?.at(-1)?.seq ?? -1
      return n
    })
  }, [openDms, cursor]) // eslint-disable-line react-hooks/exhaustive-deps

  const unread = useMemo(() => {
    const u: Record<string, number> = {}
    for (const [id, evs] of Object.entries(threads)) {
      if (id === 'main') continue
      u[id] = evs.filter((e) => e.seq > (readSeq[id] ?? -1)).length
    }
    return u
  }, [threads, readSeq])

  useEffect(() => {
    tlRef.current?.querySelector('.tl--active')?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  if (!handoff || !frame || !displaySnapshot) return <div className="empty">加载中…</div>
  const b = handoff.bundle
  const snap = displaySnapshot
  const act = findAct(b, snap.act_id)
  const scene = findScene(b, snap.scene_id)
  const player = b.characters.find((c) => c.is_player)
  const current = handoff.events.find((e) => e.seq === cursor)
  const lastError = frame.errors.at(-1)
  const showError = lastError && cursor - lastError.seq <= 3

  const items: TimelineItem[] = handoff.events.map((e) => {
    const d = describe(e, b)
    const bad = '__unknown' in e || e.type === 'error'
    const status: TimelineItem['status'] = e.seq > cursor ? 'pending' : e.seq === cursor ? 'active' : bad ? 'error' : 'done'
    return { id: e.seq, status, title: <><span className="tl__icon">{d.icon}</span>{d.title}</>, sub: d.sub, tag: d.tag }
  })

  return (
    <div className="play">
      <ReplayBar />
      <div className="play__grid">
        <div className="play__tl" ref={tlRef}>
          <h4>事件时间线 <small>{handoff.events.length}</small></h4>
          <Timeline items={items} onPick={(id) => setCursor(Number(id))} />
        </div>

        <div className="play__main">
          <div className="stage">
            <AssetFrame bundle={b} assetId={scene?.image_id} label={scene ? `场景 ${scene.scene_id}` : act ? act.title : '幕布'} ratio="21 / 9" />
            <div className="stage__cap">
              <div className="stage__act">{act ? `${act.act_id} · ${act.title}` : frame.phase === 'pregame' ? '开场前' : ''}</div>
              {scene ? <p>{scene.text}</p> : act && <p>{act.world_info}</p>}
            </div>
            {current && !('__unknown' in current) && current.type === 'act_begin' && (
              <div className="actcard" key={current.seq}>
                <small>{current.act_id}</small>
                <strong>{findAct(b, current.act_id)?.title}</strong>
                <p>{findAct(b, current.act_id)?.world_info}</p>
              </div>
            )}
            {frame.phase === 'ended' && cursor === maxSeq && (
              <a className="stage__end" href="#/review">终局 · 查看复盘 →</a>
            )}
          </div>
          {showError && (
            <div className="errbar" role="alert">
              <b>降级提示</b> {lastError.message} <code>{lastError.code}</code>
            </div>
          )}
          {frame.choices.length > 0 && (
            <div className="actions" aria-label="行动卡">
              {frame.choices.map((c) => (
                <button key={c.seq} className="actcard-btn flip" disabled title="回放模式下不可用">{c.label}</button>
              ))}
            </div>
          )}
          <ChatWindow
            className="chat--main"
            title={`主频道 · ${b.title}`}
            events={threads.main ?? []}
            bundle={b}
            input={{ placeholder: player ? `以「${player.name}」发言（回放模式下不可用）` : '发言', disabled: true, onSend: () => {} }}
          />
        </div>

        <FramePanel
          bundle={b}
          snap={snap}
          frame={frame}
          unread={unread}
          fromServer={snap === serverSnapshot}
          onOpenDm={(id) => setOpenDms((o) => (o.includes(id) ? o : [...o, id].slice(-3)))}
        />
      </div>

      <div className="dms">
        {openDms.map((id) => (
          <ChatWindow
            key={id}
            className="chat--dm"
            title={`私聊 · ${findChar(b, id)?.name ?? id}`}
            events={threads[id] ?? []}
            bundle={b}
            extra={!(threads[id]?.length) ? <div className="sys"><div className="sys__sub">还没有消息。角色主动找你时头像会亮。</div></div> : undefined}
            input={{ placeholder: '回放模式下不可用', disabled: true, onSend: () => {} }}
            onClose={() => setOpenDms((o) => o.filter((x) => x !== id))}
          />
        ))}
      </div>
    </div>
  )
}
