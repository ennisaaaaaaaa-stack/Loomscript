import { useEffect, useRef, useState } from 'react'
import { CoverCard } from '../components/CoverCard'
import { Timeline, type TimelineItem } from '../components/Timeline'
import { applyGen, GEN_STAGES, initialGen, type GenView } from '../contract/gen'
import { normalizeBundle } from '../contract/normalize'
import { startGen, type Stop } from '../data/gen'
import { useStore } from '../state/store'

const SEV_LABEL = { error: '错误', warning: '警告', info: '提示' } as const

export function GenPage() {
  const { handoff, load } = useStore()
  const [text, setText] = useState('')
  const [view, setView] = useState<GenView | null>(null)
  const stop = useRef<Stop | null>(null)
  useEffect(() => () => stop.current?.(), [])

  const running = !!view && !view.bundle && view.stages.done.status !== 'failed'
  const run = () => {
    stop.current?.()
    setView(initialGen())
    stop.current = startGen(text, (e) => setView((v) => applyGen(v ?? initialGen(), e, normalizeBundle)), handoff?.bundle)
  }

  const stageIds = view ? Object.keys(view.stages) : GEN_STAGES.map((s) => s.id as string)
  const items: TimelineItem[] = stageIds.map((id) => {
    const st = view?.stages[id]
    const label = GEN_STAGES.find((s) => s.id === id)?.label ?? id
    const status: TimelineItem['status'] = !st || st.status === 'pending' ? 'pending' : st.status === 'running' ? 'active' : st.status === 'failed' ? 'error' : 'done'
    return {
      id,
      status,
      title: <>{label}{st?.status === 'ok' && ' ✓'}{st?.status === 'skipped' && '（跳过）'}</>,
      sub: st && st.status !== 'pending' ? (
        <>
          {st.status === 'running' && <span className="bar"><i style={{ width: `${Math.round(st.progress * 100)}%` }} /></span>}
          {st.message}
          {st.issues.map((i, k) => (
            <span key={k} className={`issue issue--${i.severity}`}>
              {SEV_LABEL[i.severity] ?? i.severity}：{i.message}{i.auto_fixed && '（已自动处理）'}
            </span>
          ))}
        </>
      ) : undefined,
    }
  })

  return (
    <div className="gen">
      <section>
        <h2>导入文本 → 一键生成</h2>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="粘贴原著或剧本文本" rows={10} />
        <div className="row">
          <button className="primary" disabled={!text.trim() || running} onClick={run}>一键生成</button>
          <span className="muted">{text.length} 字{new URLSearchParams(location.search).get('gen') ? '' : ' · 本地模拟进度（加 ?gen=<SSE地址> 接后端）'}</span>
        </div>
      </section>
      <section>
        <h4>生成进度 {view?.jobId && <code>{view.jobId}</code>}</h4>
        <Timeline items={items} />
        {view?.bundle && (
          <div className="gen__preview">
            <h4>bundle 预览</h4>
            <CoverCard bundle={view.bundle} compact />
            <a className="primary" href="#/play" onClick={() => {
              // 新剧本还没有对局事件：只换 bundle，进开场前状态
              if (view.bundle!.id !== handoff?.bundle.id) load({ bundle: view.bundle, events: [], snapshot: null }, `生成：${view.bundle!.title}`)
            }}>一键游玩</a>
          </div>
        )}
      </section>
    </div>
  )
}
