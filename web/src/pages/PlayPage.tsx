import { useEffect, useMemo, useRef, useState } from 'react'
import { AssetFrame } from '../components/AssetFrame'
import { ChatWindow } from '../components/ChatWindow'
import { describe } from '../components/eventView'
import { FramePanel } from '../components/FramePanel'
import { LiveBar } from '../components/LiveBar'
import { ReplayBar } from '../components/ReplayBar'
import { Theater } from '../components/Theater'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { findAct, findChar, findChoice, findScene } from '../contract/lookup'
import { api } from '../data/live'
import { useStore } from '../state/store'

export function PlayPage() {
  const { handoff, frame, cursor, setCursor, displaySnapshot, serverSnapshot, maxSeq, myRole, live, act: runAction } = useStore()
  const [openDms, setOpenDms] = useState<string[]>([])
  // 每个私聊窗已读到的 seq；窗开着就视为已读
  const [readSeq, setReadSeq] = useState<Record<string, number>>({})
  const tlRef = useRef<HTMLDivElement>(null)
  // 已发出、后端还没回的一句：先显示出来，并挂一个「正在想」
  const [pending, setPending] = useState<{ text: string; channel: string } | null>(null)

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
  const player = findChar(b, myRole)
  const meAlive = displaySnapshot.character_states[myRole ?? '']?.alive !== false
  const canTalk = !!live && !!myRole && live.conn === 'open' && !live.busy
  const say = async (text: string, channel: string) => {
    setPending({ text, channel })
    try { await runAction((sid) => api.say(sid, myRole!, text, channel)) } finally { setPending(null) }
  }
  const pendingIn = (ch: string) => pending && pending.channel === ch ? (
    <>
      <div className="msg msg--mine msg--pending"><div className="msg__body"><div className="msg__text">{pending.text}</div></div></div>
      {ch === 'main' && <div className="typing"><span>主持人正在想</span><i /><i /><i /></div>}
    </>
  ) : null
  const openDm = (id: string) => setOpenDms((o) => (o.includes(id) ? o : [...o, id].slice(-3)))
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
      {live ? <LiveBar frame={frame} /> : <ReplayBar />}
      <div className="play__grid">
        <div className="play__tl" ref={tlRef}>
          <h4>事件时间线 <small>{handoff.events.length}</small></h4>
          <Timeline items={items} onPick={(id) => setCursor(Number(id))} />
        </div>

        <div className="play__main">
          <div className="stage">
            <AssetFrame bundle={b} assetId={scene?.image_id ?? act?.scenes[0]?.image_id /* 进场景前先用本幕首场的图 */} label={scene ? `场景 ${scene.scene_id}` : act ? act.title : '幕布'} ratio="21 / 9" />
            <div className="stage__cap">
              <div className="stage__act">{act ? `${act.act_id} · ${act.title}` : frame.phase === 'pregame' ? '开场前' : ''}</div>
              {scene ? <p>{scene.text}</p> : act && <p>{act.world_info}</p>}
            </div>
            {frame.phase === 'ended' && cursor === maxSeq && !frame.ending && (
              <a className="stage__end" href="#/review">终局 · 查看复盘 →</a>
            )}
          </div>
          <Theater events={handoff.events} cursor={cursor} bundle={b} onReview={() => {
            if (live && frame.reviewText === null) void runAction((sid) => api.dm(sid, 'review'))
            location.hash = '#/review'
          }} />
          {showError && (
            <div className="errbar" role="alert">
              <b>降级提示</b> {lastError.message} <code>{lastError.code}</code>
            </div>
          )}
          {frame.choices.length > 0 && (
            <div className="actions" aria-label="行动卡">
              {frame.choices.map((c) => (
                <button
                  key={c.seq}
                  className="actcard-btn flip"
                  disabled={!canTalk}
                  title={live ? undefined : '回放模式下不可用'}
                  onClick={() => {
                    // 引擎的通用三件：free_talk / ask_dm 只是提示，private 打开私聊；剧本 choice 有去向就进场景，否则当台词说出
                    if (c.id === 'free_talk' || c.id === 'ask_dm') return document.querySelector<HTMLInputElement>('.chat--main input')?.focus()
                    if (c.id === 'private') return openDm(b.characters.find((x) => x.id !== myRole)?.id ?? '')
                    const to = findChoice(b, c.id)?.leads_to
                    void (to ? runAction((sid) => api.scene(sid, to)) : say(c.label, 'main'))
                  }}
                >{c.label}</button>
              ))}
            </div>
          )}
          <ChatWindow
            className="chat--main"
            title={`主频道 · ${b.title}`}
            events={threads.main ?? []}
            bundle={b}
            me={myRole}
            extra={pendingIn('main')}
            input={{
              placeholder: !live ? `以「${player?.name ?? '玩家'}」发言（回放模式下不可用）` : !meAlive ? '你已死亡，转为观演，只能私聊' : `以「${player?.name ?? myRole}」发言`,
              disabled: !canTalk || !meAlive,
              onSend: (t) => void say(t, 'main'),
            }}
          />
        </div>

        <FramePanel
          bundle={b}
          snap={snap}
          frame={frame}
          unread={unread}
          fromServer={snap === serverSnapshot}
          me={myRole}
          onOpenDm={openDm}
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
            me={myRole}
            extra={pendingIn(`dm:${id}`) ?? (!(threads[id]?.length) ? <div className="sys"><div className="sys__sub">还没有消息。角色主动找你时头像会亮。</div></div> : undefined)}
            input={{ placeholder: live ? '私聊' : '回放模式下不可用', disabled: !canTalk, onSend: (t) => void say(t, `dm:${id}`) }}
            onClose={() => setOpenDms((o) => o.filter((x) => x !== id))}
          />
        ))}
      </div>
    </div>
  )
}
