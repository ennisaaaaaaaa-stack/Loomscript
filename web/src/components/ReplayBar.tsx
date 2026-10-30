import { useEffect, useState } from 'react'
import { useStore } from '../state/store'

const SPEEDS = [0.5, 1, 2, 4]

export function ReplayBar() {
  const { handoff, cursor, setCursor, maxSeq } = useStore()
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const seqs = handoff?.events.map((e) => e.seq) ?? []
  const idx = seqs.findIndex((s) => s >= cursor)
  const step = (d: number) => {
    const i = Math.min(seqs.length - 1, Math.max(-1, (idx === -1 ? seqs.length - 1 : idx) + d))
    setCursor(i < 0 ? -1 : seqs[i])
  }

  useEffect(() => {
    if (!playing) return
    if (cursor >= maxSeq) { setPlaying(false); return }
    const t = setTimeout(() => step(1), 900 / speed)
    return () => clearTimeout(t)
  })

  return (
    <div className="replay">
      <button className="ghost" title="回到开头" onClick={() => { setPlaying(false); setCursor(-1) }}>⏮</button>
      <button className="ghost" title="上一个事件" onClick={() => step(-1)}>◀</button>
      <button
        className="primary"
        onClick={() => { if (cursor >= maxSeq) setCursor(-1); setPlaying(!playing) }}
      >{playing ? '暂停' : cursor >= maxSeq ? '重播' : '播放'}</button>
      <button className="ghost" title="下一个事件" onClick={() => step(1)}>▶</button>
      <button className="ghost" title="跳到末尾" onClick={() => { setPlaying(false); setCursor(maxSeq) }}>⏭</button>
      <input type="range" min={-1} max={maxSeq} value={cursor} onChange={(e) => { setPlaying(false); setCursor(+e.target.value) }} />
      <span className="replay__seq">seq {cursor < 0 ? '–' : cursor}/{maxSeq}</span>
      <select value={speed} onChange={(e) => setSpeed(+e.target.value)}>
        {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
    </div>
  )
}
