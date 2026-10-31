/**
 * 生成进度数据源。
 *  - 真实：?gen=<SSE 地址>，每条 message.data 是一条 GenEvent（gen.schema.json）。
 *    怎么把文本交给后端（POST 还是 query）后端还没定，定了在 startGen 里补。
 *  - 浏览器内：本地引擎模式下用 Claude（sample 能力）真生成一本，挂进本地剧本库，可直接开局。
 *  - 模拟：拿不到模型时按合同形状本地吐事件，done 时附上当前 bundle。
 */
import { getBackend } from './backend'
import type { GenSpec } from '../contract/genSpec'
import type { GenEvent } from '../contract/gen'
import { GEN_STAGES } from '../contract/gen'

export type Stop = () => void

export function startGen(text: string, onEvent: (e: GenEvent) => void, mockBundle: unknown, spec?: GenSpec): Stop {
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
  let stopped = false
  let stopMock: Stop | null = null
  void getBackend().then(async (be) => {
    if (stopped) return
    if (be.kind !== 'local') { stopMock = mockGen(onEvent, mockBundle); return }
    const [{ generateBundle, AiError }, { registerBundle }] = await Promise.all([import('../engine/ai'), import('../engine/localApi')])
    const job_id = `gen-${Date.now()}`
    const ev = (p: Omit<GenEvent, 'job_id' | 'ts'>) => { if (!stopped) onEvent({ job_id, ts: new Date().toISOString(), ...p }) }
    let cur: string | null = null
    const tick = setInterval(() => cur && ev({ stage: cur, status: 'running', message: undefined }), 4000)
    try {
      const { bundle, issues } = await generateBundle(text, (stage, message) => {
        if (cur) ev({ stage: cur, status: 'ok', progress: 1 })
        cur = stage
        ev({ stage, status: 'running', progress: 0.3, message })
      }, spec)
      if (cur) ev({ stage: cur, status: 'ok', progress: 1, message: `${bundle.characters.length} 个角色` })
      const scenes = bundle.acts.reduce((n: number, a: { scenes: unknown[] }) => n + a.scenes.length, 0)
      ev({ stage: 'scenes', status: 'ok', progress: 1, message: `${bundle.acts.length} 幕 ${scenes} 场` })
      ev({ stage: 'props_assets', status: 'ok', progress: 1, message: `${(bundle.clues ?? []).length} 条线索 · ${bundle.props.length} 件道具`, validation: { issues: [{ severity: 'info', code: 'image_placeholder', message: '没有生图，场景先用占位' }] } })
      ev({ stage: 'cards', status: 'ok', progress: 1, message: `${bundle.cards.length} 张象征卡` })
      ev({ stage: 'endgame', status: 'ok', progress: 1, message: `${(bundle.endgame.endings ?? []).length} 个结局`, validation: { issues: issues.map((m: string) => ({ severity: 'warning' as const, code: 'auto_fix', message: m, auto_fixed: true })) } })
      registerBundle(bundle)
      ev({ stage: 'done', status: 'ok', progress: 1, message: '生成完成，已放进剧本库', bundle })
    } catch (e) {
      if (e instanceof AiError && e.code === 'unavailable') {
        ev({ stage: cur ?? 'ingest', status: 'failed', message: `${e.message}，改用模拟进度` })
        stopMock = mockGen(onEvent, mockBundle)
      } else {
        ev({ stage: cur ?? 'ingest', status: 'failed', message: e instanceof Error ? e.message : String(e) })
        ev({ stage: 'done', status: 'failed', message: '生成失败，可以再试一次' })
      }
    } finally {
      clearInterval(tick)
    }
  })
  return () => { stopped = true; stopMock?.() }
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
