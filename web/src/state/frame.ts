import { findClue, findEnding } from '../contract/lookup'
import { emptySnapshot, errorCopy, parseChannel, pickText, revealText } from '../contract/normalize'
import type { Bundle, GameEvent, Snapshot } from '../contract/types'

export interface RevealItem { key: string; text: string | null; seq: number; sceneId?: string }
export interface PushItem { id: string; title: string | null; text: string | null; seq: number }
export interface ErrorItem { code: string; message: string; seq: number }
export interface EndingItem { id: string; title: string | null; text: string | null }
export interface ChoiceItem { id: string; label: string; characterId?: string; seq: number }

/** 回放到某一 seq 时的完整画面。snapshot 部分与服务端 snapshot 同形，终局时可直接对拍。 */
export interface Frame {
  snapshot: Snapshot
  phase: 'pregame' | 'playing' | 'ended'
  reveals: RevealItem[]
  clues: PushItem[]
  journal: PushItem[]
  errors: ErrorItem[]
  /** 本幕 DM 发出的行动卡（落幕清空） */
  choices: ChoiceItem[]
  reviewText: string | null
  ending: EndingItem | null
  /** key = 'main' 或 dm 角色 id */
  threads: Record<string, GameEvent[]>
  lastSeq: number
}

export function initialFrame(bundle: Bundle): Frame {
  const snapshot = emptySnapshot()
  snapshot.bundle_id = bundle.id
  snapshot.degradation_tier = 'tangwu' // 合同默认档
  for (const c of bundle.characters) {
    snapshot.character_states[c.id] = { on_stage: true, alive: true, lines_spoken: 0, knowledge_unlocked: [] }
  }
  return { snapshot, phase: 'pregame', reveals: [], clues: [], journal: [], errors: [], choices: [], reviewText: null, ending: null, threads: { main: [] }, lastSeq: -1 }
}

const threadKey = (e: GameEvent) => {
  const ch = parseChannel(e.channel)
  return ch.kind === 'dm' ? ch.characterId : 'main'
}

const uniq = (xs: string[], x: string) => (xs.includes(x) ? xs : [...xs, x])

/** 纯函数：一个事件推进一帧。认不出的事件只进时间线，不改状态。 */
export function applyEvent(f: Frame, e: GameEvent, bundle: Bundle): Frame {
  const s: Snapshot = { ...f.snapshot, seq: e.seq, session_id: e.session_id || f.snapshot.session_id }
  const next: Frame = { ...f, snapshot: s, lastSeq: e.seq }

  // 所有事件按 channel 进对应消息流（chat 只渲染需要的类型）
  const k = threadKey(e)
  next.threads = { ...f.threads, [k]: [...(f.threads[k] ?? []), e] }

  if ('__unknown' in e) return next

  switch (e.type) {
    case 'game_start':
      next.phase = 'playing'
      break
    case 'act_end':
      next.choices = []
      break
    case 'game_end':
      next.phase = 'ended'
      if (e.review_text) next.reviewText = e.review_text
      if (e.ending_id) {
        next.ending = { id: e.ending_id, title: e.ending_title || null, text: e.ending_text || null }
        // 引擎在 game_end 时把结局 CG 记进快照；回放时按结局表推回来
        const cg = findEnding(bundle, e.ending_id)?.cg_id
        if (cg) s.cg_unlocked = uniq(s.cg_unlocked, cg)
      }
      break
    case 'death': {
      const cs = s.character_states[e.character_id]
      if (cs) s.character_states = { ...s.character_states, [e.character_id]: { ...cs, alive: false } }
      break
    }
    case 'act_begin':
      s.act_id = e.act_id
      s.scene_id = null
      next.choices = []
      break
    case 'scene_begin':
      s.act_id = e.act_id
      s.scene_id = e.scene_id
      break
    case 'player_line':
    case 'agent_line': {
      // 与引擎一致：DM 等不在 bundle 里的说话人不计数
      const cs = s.character_states[e.character_id]
      if (cs) s.character_states = { ...s.character_states, [e.character_id]: { ...cs, lines_spoken: cs.lines_spoken + 1 } }
      break
    }
    case 'choice':
      next.choices = [...f.choices, { id: e.choice_id, label: e.text ?? e.choice_id, characterId: e.character_id, seq: e.seq }]
      break
    case 'reveal': {
      next.reveals = [...f.reveals, ...e.reveal_keys.map((key) => ({ key, text: revealText(e, key), seq: e.seq, sceneId: e.scene_id }))]
      // 录制里 reveal 只解锁给玩家角色（NPC 知识走服务端送达回执，前端不推断）
      const states = { ...s.character_states }
      for (const c of bundle.characters.filter((c) => c.is_player)) {
        const cs = states[c.id] ?? { on_stage: true, lines_spoken: 0, knowledge_unlocked: [] }
        states[c.id] = { ...cs, knowledge_unlocked: e.reveal_keys.reduce(uniq, cs.knowledge_unlocked) }
      }
      s.character_states = states
      break
    }
    case 'prop_gained':
      s.props_held = uniq(s.props_held, e.prop_id)
      break
    case 'card_draw':
      s.cards_drawn = uniq(s.cards_drawn, e.card_id)
      break
    case 'review':
      next.reviewText = e.review_text ?? next.reviewText
      break
    case 'error':
      next.errors = [...f.errors, { code: e.error_code, message: errorCopy(e.error_code, pickText(e, ['text', 'message'])), seq: e.seq }]
      if (typeof e.degradation_tier === 'string') s.degradation_tier = e.degradation_tier
      break
    case 'clue_found': {
        const def = findClue(bundle, e.clue_id)
        next.clues = [...f.clues, { id: e.clue_id ?? String(e.seq), title: def?.title ?? null, text: pickText(e) ?? def?.text ?? null, seq: e.seq }]
      break
    }
    case 'journal_push':
      next.journal = [...f.journal, { id: String(e.seq), title: null, text: e.journal_text ?? pickText(e), seq: e.seq }]
      break
  }
  return next
}

export function frameAt(events: GameEvent[], cursor: number, bundle: Bundle): Frame {
  let f = initialFrame(bundle)
  for (const e of events) {
    if (e.seq > cursor) break
    f = applyEvent(f, e, bundle)
  }
  return f
}

/** 推导快照与服务端快照逐字段对拍，返回不一致的字段路径（只比合同字段）。 */
export function diffSnapshot(derived: Snapshot, server: Snapshot): string[] {
  const out: string[] = []
  const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
  for (const k of ['act_id', 'scene_id', 'seq', 'props_held', 'cards_drawn'] as const) {
    if (!eq(derived[k], server[k])) out.push(k)
  }
  for (const [id, cs] of Object.entries(server.character_states)) {
    const d = derived.character_states[id]
    if (!d) { out.push(`character_states.${id}`); continue }
    if (d.lines_spoken !== cs.lines_spoken) out.push(`character_states.${id}.lines_spoken`)
    if (!eq([...d.knowledge_unlocked].sort(), [...cs.knowledge_unlocked].sort())) out.push(`character_states.${id}.knowledge_unlocked`)
  }
  return out
}
