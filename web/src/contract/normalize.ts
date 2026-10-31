import type { Bundle, GameEvent, Handoff, KnownType, Snapshot } from './types'

export const KNOWN_TYPES: ReadonlySet<string> = new Set<KnownType>([
  'game_start', 'game_end', 'act_begin', 'act_end', 'scene_begin',
  'player_line', 'agent_line', 'reveal', 'prop_gained', 'card_draw', 'review',
  'choice', 'death', 'error', 'clue_found', 'journal_push',
])

type Raw = Record<string, unknown>
const isObj = (v: unknown): v is Raw => typeof v === 'object' && v !== null && !Array.isArray(v)
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])

export function normalizeEvent(raw: unknown, fallbackSeq: number): GameEvent | null {
  if (!isObj(raw) || typeof raw.type !== 'string') return null
  const e = {
    ...raw,
    seq: typeof raw.seq === 'number' ? raw.seq : fallbackSeq,
    ts: typeof raw.ts === 'string' ? raw.ts : '',
    session_id: typeof raw.session_id === 'string' ? raw.session_id : '',
    channel: typeof raw.channel === 'string' && raw.channel ? raw.channel : 'main',
  }
  if (!KNOWN_TYPES.has(raw.type)) return { ...e, type: raw.type, __unknown: true } as GameEvent
  return e as unknown as GameEvent
}

/** 按 seq 排序并去重（直播流可能重发），后到的覆盖先到的。 */
export function mergeEvents(existing: GameEvent[], incoming: GameEvent[]): GameEvent[] {
  const bySeq = new Map<number, GameEvent>()
  for (const e of existing) bySeq.set(e.seq, e)
  for (const e of incoming) bySeq.set(e.seq, e)
  return [...bySeq.values()].sort((a, b) => a.seq - b.seq)
}

export function normalizeBundle(raw: unknown): Bundle {
  const b = isObj(raw) ? raw : {}
  const endgame = isObj(b.endgame) ? b.endgame : {}
  return {
    ...b,
    id: String(b.id ?? 'unknown'),
    title: String(b.title ?? '未命名剧本'),
    version: String(b.version ?? ''),
    language: String(b.language ?? 'zh'),
    characters: arr(b.characters),
    acts: arr<Raw>(b.acts).map((a) => ({ ...a, scenes: arr(a.scenes) })) as Bundle['acts'],
    props: arr(b.props),
    cards: arr(b.cards),
    endgame: { ...endgame, conditions: arr(endgame.conditions) },
    assets: Array.isArray(b.assets) ? b.assets : undefined,
  }
}

export function normalizeSnapshot(raw: unknown): Snapshot | null {
  if (!isObj(raw)) return null
  return {
    ...raw,
    session_id: String(raw.session_id ?? ''),
    bundle_id: String(raw.bundle_id ?? ''),
    act_id: (raw.act_id as string) ?? null,
    scene_id: (raw.scene_id as string) ?? null,
    seq: typeof raw.seq === 'number' ? raw.seq : -1,
    character_states: isObj(raw.character_states) ? (raw.character_states as Snapshot['character_states']) : {},
    props_held: arr(raw.props_held),
    cards_drawn: arr(raw.cards_drawn),
    cg_unlocked: arr(raw.cg_unlocked),
    degradation_tier: String(raw.degradation_tier ?? ''),
  }
}

export function normalizeHandoff(raw: unknown): { handoff: Handoff; snapshot: Snapshot | null } {
  const h = isObj(raw) ? raw : {}
  const events = mergeEvents([], arr(h.events).map(normalizeEvent).filter((e): e is GameEvent => e !== null))
  const snapshot = normalizeSnapshot(h.snapshot)
  return {
    handoff: { ...h, bundle: normalizeBundle(h.bundle), events, snapshot: snapshot ?? emptySnapshot() },
    snapshot,
  }
}

export function emptySnapshot(): Snapshot {
  return {
    session_id: '', bundle_id: '', act_id: null, scene_id: null, seq: -1,
    character_states: {}, props_held: [], cards_drawn: [], cg_unlocked: [], degradation_tier: '',
  }
}

// ---------- channel ----------

export type ChannelInfo = { kind: 'main' } | { kind: 'dm'; characterId: string } | { kind: 'other'; raw: string }

export function parseChannel(ch: string | undefined): ChannelInfo {
  if (!ch || ch === 'main') return { kind: 'main' }
  if (ch.startsWith('dm:') && ch.length > 3) return { kind: 'dm', characterId: ch.slice(3) }
  return { kind: 'other', raw: ch }
}

// ---------- reveal_texts ----------

/** reveal_texts 合同是数组（与 reveal_keys 对齐）；对象形状也兜着。没有就返回 null，UI 显示 key。 */
export function revealText(e: { reveal_keys: string[]; reveal_texts?: unknown }, key: string): string | null {
  const t = e.reveal_texts
  if (Array.isArray(t)) {
    const i = e.reveal_keys.indexOf(key)
    return typeof t[i] === 'string' ? t[i] : null
  }
  if (isObj(t) && typeof t[key] === 'string') return t[key] as string
  return null
}

/** 取事件正文：合同字段在前，其余兜底。 */
export function pickText(e: Raw, keys = ['text', 'journal_text', 'content', 'message']): string | null {
  for (const k of keys) if (typeof e[k] === 'string' && e[k]) return e[k] as string
  return null
}

// ---------- error / 降级档 文案 ----------

const ERROR_COPY: Record<string, string> = {
  dm_degraded: 'DM 嗓子哑了，剧本自己往下走',
  agent_unreachable: '有位演员暂时联系不上，由预设台词顶上',
}
export const errorCopy = (code: string, text?: string | null) => text || ERROR_COPY[code] || '出了点状况，剧本按预设继续推进'

export const TIER_LABEL: Record<string, string> = { pianist: '全量（pianist）', tangwu: '堂屋（tangwu）', semi_manual: '半人工（semi_manual）' }

export const DM_ID = 'dm'
