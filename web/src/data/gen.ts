/**
 * 生成进度数据源。
 *  - 真实：?gen=<SSE 地址>，每条 message.data 是一条 GenEvent（gen.schema.json）。
 *    怎么把文本交给后端（POST 还是 query）后端还没定，定了在 startGen 里补。
 *  - 模拟：按合同形状本地吐事件，done 时附上内置麦克白 bundle。
 */
import type { GenEvent } from '../contract/gen'
import { GEN_STAGES } from '../contract/gen'

export type Stop = () => void

export function startGen(text: string, onEvent: (e: GenEvent) => void, mockBundle: unknown): Stop {
  const url = new URLSearchParams(location.search).get('gen')
  if (url) {
    const es = new EventSource(`${url}${url.includes('?') ? '&' : '?'}text=${encodeURIComponent(text.slice(0, 2000))}`)
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as GenEvent
        onEvent(e)
        if (e.stage === 'done') es.close()
      } catch { /* 坏行跳过 */ }
    }
    return () => es.close()
  }
  return mockGen(onEvent, mockBundle)
}

function mockGen(onEvent: (e: GenEvent) => void, bundle: unknown): Stop {
  const job_id = `mock-${Date.now()}`
  const ev = (p: Omit<GenEvent, 'job_id' | 'ts'>): GenEvent => ({ job_id, ts: new Date().toISOString(), ...p })
  const script: GenEvent[] = []
  for (const s of GEN_STAGES.filter((s) => s.id !== 'done')) {
    script.push(ev({ stage: s.id, status: 'running', progress: 0, message: `正在处理：${s.label}` }))
    script.push(ev({ stage: s.id, status: 'running', progress: 0.5, message: `${s.label}（1/2）` }))
    const end = ev({ stage: s.id, status: 'ok', progress: 1, message: `${s.label}完成` })
    if (s.id === 'act_structure') end.validation = { issues: [{ severity: 'warning', code: 'act_gap', message: '第二幕与第三幕之间缺过渡场景，已补一场', auto_fixed: true }] }
    if (s.id === 'props_assets') end.validation = { issues: [{ severity: 'info', code: 'image_placeholder', message: '图像 key 不可用，CG 先用占位图' }] }
    script.push(end)
  }
  script.push(ev({ stage: 'done', status: 'ok', progress: 1, message: '生成完成', bundle }))
  let i = 0
  const t = setInterval(() => {
    onEvent(script[i++])
    if (i >= script.length) clearInterval(t)
  }, 250)
  return () => clearInterval(t)
}
