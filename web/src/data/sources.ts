/**
 * 数据源层。UI 只认 normalizeHandoff 之后的形状，换数据源不动组件。
 *  - 内置 fixtures：b6f1965 真实录制 / v0.1 预演 mock
 *  - ?src=<url>：拉一份 handoff JSON（handoff 升版后直接指过去）
 *  - 拖入/选择本地 handoff JSON
 *  - TODO(后端合同落地后)：直播流。onEvents 收增量事件，store 里用 mergeEvents 合并即可。
 */
// 真实录制直接读仓库里的 demos/frontend_handoff.json，handoff 升版前端自动跟上
import real from '../../../demos/frontend_handoff.json'
import mock from '../fixtures/handoff_v01_mock.json'

export interface SourceDef { id: string; label: string; note: string; load: () => Promise<unknown> }

export const BUILTIN_SOURCES: SourceDef[] = [
  { id: 'b6f1965', label: 'b6f1965 真实录制', note: '麦克白真实对局，冻结版', load: async () => real },
  { id: 'v01-mock', label: 'v0.1 预演（mock）', note: '真实录制 + 手工插入 channel/error/clue/journal/reveal_texts/assets，验证壳不返工', load: async () => mock },
]

export async function loadFromUrl(url: string): Promise<unknown> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export async function loadFromFile(file: File): Promise<unknown> {
  return JSON.parse(await file.text())
}

/** 直播接口占位：后端给出 SSE/WS 地址和消息格式后在这里实现。 */
export interface LiveConnection { close(): void; sendPlayerLine(text: string, channel: string): Promise<void> }
