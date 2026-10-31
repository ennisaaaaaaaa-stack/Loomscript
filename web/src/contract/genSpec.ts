/**
 * 生成页的「创作结构」：背景设定 + 角色卡 + 原文。生成时作为硬约束交给模型。
 * 创作助手（聊天框）回的是对这份结构的增量 patch，前端按 applyPatch 合并，用户随时可手改。
 */

export interface CharSpec {
  key: string
  name: string
  identity: string
  secret: string
  goal: string
  is_player: boolean
}

export interface GenSpec {
  title: string
  genre: string
  era: string
  world: string
  tone: string
  acts: number
  notes: string
  characters: CharSpec[]
}

export interface SpecPatch {
  set?: Partial<Omit<GenSpec, 'characters'>>
  add_characters?: Partial<CharSpec>[]
  update_characters?: (Partial<CharSpec> & { name: string })[]
  remove_characters?: string[]
}

let n = 0
export const newKey = () => `c${Date.now().toString(36)}${n++}`

export const blankChar = (p: Partial<CharSpec> = {}): CharSpec => ({ key: newKey(), name: '', identity: '', secret: '', goal: '', is_player: true, ...p })

export const emptySpec = (): GenSpec => ({ title: '', genre: '', era: '', world: '', tone: '', acts: 3, notes: '', characters: [] })

/** 背景预设：点一下填好类型/时代/基调，世界观留给用户或助手写 */
export const PRESETS: { label: string; set: Partial<GenSpec> }[] = [
  { label: '古风宫廷', set: { genre: '宫廷权谋', era: '架空古代王朝', tone: '压抑、步步惊心' } },
  { label: '民国谍战', set: { genre: '谍战悬疑', era: '1930 年代上海', tone: '紧张、人人有两张脸' } },
  { label: '现代校园', set: { genre: '校园推理', era: '当代高中', tone: '青春、表面平静暗流涌动' } },
  { label: '暴风雪山庄', set: { genre: '本格推理', era: '当代', tone: '封闭、互相猜疑' } },
  { label: '克苏鲁', set: { genre: '恐怖调查', era: '1920 年代新英格兰', tone: '诡异、理智逐渐崩塌' } },
  { label: '赛博朋克', set: { genre: '科幻黑色', era: '2077 年巨型都市', tone: '冷硬、霓虹下的背叛' } },
]

export function applyPatch(spec: GenSpec, p: SpecPatch): GenSpec {
  const next: GenSpec = { ...spec, characters: [...spec.characters] }
  if (p.set) {
    for (const [k, v] of Object.entries(p.set)) {
      if (v === undefined || v === null || k === 'characters') continue
      if (k === 'acts') next.acts = Math.min(5, Math.max(2, Number(v) || spec.acts))
      else (next as unknown as Record<string, unknown>)[k] = String(v)
    }
  }
  const byName = (name: string) => next.characters.findIndex((c) => c.name === name)
  for (const name of p.remove_characters ?? []) {
    const i = byName(name)
    if (i >= 0) next.characters.splice(i, 1)
  }
  for (const u of p.update_characters ?? []) {
    const i = byName(u.name)
    if (i >= 0) next.characters[i] = { ...next.characters[i], ...clean(u), key: next.characters[i].key }
    else next.characters.push(blankChar(clean(u)))
  }
  for (const a of p.add_characters ?? []) {
    if (!a?.name) continue
    const i = byName(a.name)
    if (i >= 0) next.characters[i] = { ...next.characters[i], ...clean(a), key: next.characters[i].key }
    else next.characters.push(blankChar(clean(a)))
  }
  return next
}

function clean(c: Partial<CharSpec>): Partial<CharSpec> {
  const o: Partial<CharSpec> = {}
  for (const k of ['name', 'identity', 'secret', 'goal'] as const) if (typeof c[k] === 'string') o[k] = c[k]
  if (typeof c.is_player === 'boolean') o.is_player = c.is_player
  return o
}

/** 结构里填了多少：给「一键生成」按钮和提示用 */
export function specReady(spec: GenSpec, text: string) {
  const named = spec.characters.filter((c) => c.name.trim())
  return {
    hasAnything: !!(text.trim() || spec.world.trim() || spec.title.trim() || spec.genre.trim() || named.length),
    players: named.filter((c) => c.is_player).length,
    chars: named.length,
  }
}

/** 给模型看的约束文本（只放用户填了的） */
export function specBrief(spec: GenSpec) {
  const lines: string[] = []
  if (spec.title) lines.push(`标题：${spec.title}`)
  if (spec.genre) lines.push(`类型：${spec.genre}`)
  if (spec.era) lines.push(`时代/地点：${spec.era}`)
  if (spec.tone) lines.push(`基调：${spec.tone}`)
  if (spec.world) lines.push(`世界观与背景：${spec.world}`)
  lines.push(`幕数：${spec.acts}`)
  const cs = spec.characters.filter((c) => c.name.trim())
  if (cs.length) {
    lines.push('指定角色（必须全部出现，名字不改，设定照用，空着的由你补全）：')
    for (const c of cs) lines.push(`- ${c.name}｜${c.is_player ? '玩家可扮演' : 'AI 角色'}｜身份：${c.identity || '待补'}｜秘密：${c.secret || '待补'}｜目标：${c.goal || '待补'}`)
  }
  if (spec.notes) lines.push(`其他要求：${spec.notes}`)
  return lines.join('\n')
}
