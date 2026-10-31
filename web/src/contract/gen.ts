/** 生成进度合同：contracts/gen.schema.json。SSE 逐条推送，按 job_id 聚合。 */
import type { Bundle } from './types'

export const GEN_STAGES = [
  { id: 'ingest', label: '导入解析' },
  { id: 'act_structure', label: '幕结构' },
  { id: 'characters', label: '角色' },
  { id: 'scenes', label: '场景' },
  { id: 'props_assets', label: '道具与资产' },
  { id: 'cards', label: '卡牌' },
  { id: 'endgame', label: '结局' },
  { id: 'done', label: '完成' },
] as const

export type GenStage = (typeof GEN_STAGES)[number]['id']
export type GenStatus = 'running' | 'ok' | 'failed' | 'skipped'

export interface GenIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
  stage?: string
  auto_fixed?: boolean
}

export interface GenEvent {
  job_id: string
  stage: GenStage | string
  status: GenStatus | string
  ts: string
  progress?: number
  message?: string
  validation?: { issues?: GenIssue[] }
  bundle?: unknown
}

export interface StageState { status: GenStatus | 'pending'; progress: number; message?: string; issues: GenIssue[] }

export interface GenView {
  jobId: string | null
  stages: Record<string, StageState>
  bundle: Bundle | null
}

export function initialGen(): GenView {
  return { jobId: null, stages: Object.fromEntries(GEN_STAGES.map((s) => [s.id, { status: 'pending', progress: 0, issues: [] }])), bundle: null }
}

/** 纯函数：一条进度事件推进视图。未知 stage 也收（追加在后面显示）。 */
export function applyGen(v: GenView, e: GenEvent, toBundle: (raw: unknown) => Bundle): GenView {
  const prev = v.stages[e.stage] ?? { status: 'pending', progress: 0, issues: [] }
  const status = (e.status as GenStatus) ?? prev.status
  const issues = (e.validation?.issues ?? []).map((i) => ({ ...i, stage: i.stage ?? e.stage }))
  const next: StageState = {
    status,
    progress: typeof e.progress === 'number' ? e.progress : status === 'ok' || status === 'skipped' ? 1 : prev.progress,
    message: e.message ?? prev.message,
    issues: [...prev.issues, ...issues],
  }
  return {
    jobId: e.job_id ?? v.jobId,
    stages: { ...v.stages, [e.stage]: next },
    bundle: e.stage === 'done' && e.bundle ? toBundle(e.bundle) : v.bundle,
  }
}
