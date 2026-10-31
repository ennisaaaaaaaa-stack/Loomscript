/**
 * 演出层：DM 与 AI 演员的台词。对应 dm.py 的装配器 + PianistPort。
 * 模型来源：claude.ai 链接页面的 sample 能力（window.claude.use('sample')）。
 * 拿不到（本地 dev、未授权、限流）就降级：DM 用 bundle.dm_lines.fallback，
 * 角色用占位串，并发 error 事件（error_code=dm_degraded / agent_unreachable），前端出提示。
 *
 * 隔离墙与 Python 版一致：角色材料只含到当前幕为止的世界、按幕切片的秘密、
 * 当前幕的演员包、自己私聊窗的历史、已揭示的知识；DM 是唯一全知点，私聊只拿摘要。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { specBrief, type GenSpec, type SpecPatch } from '../contract/genSpec'
import { DM_ID, type Bundle, type Ev, type Raw, type Session } from './engine'

type SampleFn = ((input: string | { role: 'user' | 'assistant'; content: string }[], opts?: Raw) => Promise<{ text: string }>) & {
  json?: (input: unknown, opts?: Raw) => Promise<unknown>
}

let samplePromise: Promise<SampleFn | null> | null = null
export function getSample(): Promise<SampleFn | null> {
  if (!samplePromise) {
    const c = (window as any).claude
    samplePromise = c?.use ? Promise.race([
      Promise.resolve(c.use('sample')).catch(() => null),
      new Promise<null>((r) => setTimeout(() => r(null), 12000)),
    ]) as Promise<SampleFn | null> : Promise.resolve(null)
  }
  return samplePromise
}

export class AiError extends Error {
  code: string
  constructor(code: string, message: string) { super(message); this.code = code }
}

async function ask(prompt: string, opts: Raw = {}): Promise<string> {
  const sample = await getSample()
  if (!sample) throw new AiError('unavailable', '这个页面拿不到模型（需要在 claude.ai 链接里打开并允许调用 Claude）')
  try {
    const r = await sample(prompt, { cache: false, ...opts })
    return (r?.text ?? '').trim()
  } catch (e: any) {
    throw new AiError(e?.code ?? 'error', e?.message ?? String(e))
  }
}

const clip = (s: unknown, n: number) => { const t = typeof s === 'string' ? s : JSON.stringify(s ?? ''); return t.length > n ? t.slice(0, n) + '…' : t }
const nameOf = (b: Bundle, id: string) => (id === DM_ID ? '主持人' : b.chars[id]?.name ?? id)
const secretOf = (c: Raw) => c.secret_sheet ?? c.secret ?? ''
const publicOf = (c: Raw) => c.public_sheet ?? c.public ?? ''
const voiceOf = (c: Raw) => c.voice ?? (Array.isArray(c.voice_fingerprint) ? c.voice_fingerprint.join(' / ') : '')

function transcript(b: Bundle, events: Ev[], channel: string, n: number) {
  return events
    .filter((e) => (e.type === 'player_line' || e.type === 'agent_line') && (e.channel ?? 'main') === channel)
    .slice(-n)
    .map((e) => `${nameOf(b, e.character_id)}：${e.text}`)
    .join('\n')
}

function storySoFar(b: Bundle, events: Ev[]) {
  const out: string[] = []
  for (const e of events) {
    if (e.type === 'act_begin') out.push(`【${b.act(e.act_id)?.title ?? e.act_id}】`)
    else if (e.type === 'scene_begin') out.push(`场景 ${e.scene_id}：${clip(b.scenes(e.act_id)[e.scene_id]?.text, 160)}`)
    else if (e.type === 'reveal') out.push(`揭示：${(e.reveal_keys ?? []).map((k: string) => b.data.clues?.find((c: Raw) => c.clue_id === k)?.title ?? k).join('；')}`)
    else if (e.type === 'death') out.push(`死亡：${e.text}`)
  }
  return out.slice(-30).join('\n')
}

/** dm.py assemble_character_prompt 的 TS 版 */
export function characterMaterial(s: Session, cid: string) {
  const b = s.bundle
  const acts = b.data.acts as Raw[]
  const i = Math.max(0, acts.findIndex((a) => a.act_id === s.s().act_id))
  const c = b.chars[cid]
  const known = s.events.filter((e) => e.type === 'reveal').flatMap((e) => e.reveal_keys ?? [])
  const dead = s.events.some((e) => e.type === 'death' && e.character_id === cid)
  const cues = (b.data.actor_turns?.[s.s().act_id]?.[cid] ?? []).map((q: Raw) => q.pack ?? q).slice(0, 3)
  const death = Object.values(b.deaths).find((d) => d.character_id === cid)
  return {
    you_are: { id: cid, name: c.name, public_sheet: publicOf(c), voice: voiceOf(c), drive: c.drive, bottom_line: c.bottom_line },
    secret_slice: secretOf(c).slice(0, 200 * (i + 1)),
    world_so_far: acts.slice(0, i + 1).map((a) => a.world_info).filter(Boolean),
    current_scene: s.s().scene_id ? b.scenes(s.s().act_id)[s.s().scene_id]?.text : null,
    knowledge_unlocked: known.map((k) => b.data.clues?.find((x: Raw) => x.clue_id === k)?.title ?? k),
    actor_pack: cues,
    observer: dead ? (death?.observer_brief ?? '肉身已谢幕，你的目光留在台上——只看，不再推进。') : undefined,
    law: dead ? '你已退场，转为观察者视角：不再以角色身份推进剧情；你仍不能知道还没演到的真相。' : '你不能知道还没演到的真相。材料里没有的就是你不知道的。',
  }
}

/** DM 拿私聊摘要不拿原文（dm.py digest_private_channels） */
function privateDigest(events: Ev[]) {
  const per: Record<string, { messages: number; recent: string[] }> = {}
  for (const e of events) {
    const ch = e.channel ?? ''
    if ((e.type !== 'agent_line' && e.type !== 'player_line') || !ch.startsWith('dm:')) continue
    const d = (per[ch.slice(3)] ??= { messages: 0, recent: [] })
    d.messages += 1
    d.recent.push(clip(e.text, 50))
  }
  for (const d of Object.values(per)) d.recent = d.recent.slice(-2)
  return per
}

function dmBrief(s: Session) {
  const b = s.bundle
  return {
    title: b.data.title,
    adaptation_note: clip(b.data.adaptation_note, 400),
    characters: (b.data.characters as Raw[]).map((c) => ({ id: c.id, name: c.name, is_player: !!c.is_player, alive: s.s().character_states[c.id]?.alive, public: clip(publicOf(c), 120), secret: clip(secretOf(c), 200), voice: clip(voiceOf(c), 80) })),
    acts: (b.data.acts as Raw[]).map((a) => ({ act_id: a.act_id, title: a.title, world_info: clip(a.world_info, 200), scenes: (a.scenes ?? []).map((x: Raw) => ({ id: x.scene_id, text: clip(x.text, 120) })) })),
    endgame: { rules: clip(b.data.endgame?.rules, 300), endings: (b.data.endgame?.endings ?? []).map((e: Raw) => ({ id: e.id, title: e.title })) },
    now: { act: s.s().act_id, scene: s.s().scene_id },
  }
}

export interface DmTurn { dm_line?: string; next_speaker?: string }

/** 主频道：玩家说完一句，DM 接话，并可点一位在场 AI 角色接着说（角色台词另由角色材料生成，DM 不代笔）。 */
export async function dmRespond(s: Session, me: string, message: string): Promise<DmTurn> {
  const b = s.bundle
  const aiCast = (b.data.characters as Raw[]).filter((c) => c.id !== me && s.s().character_states[c.id]?.alive).map((c) => `${c.id}（${c.name}）`)
  const prompt = [
    '你是一场中文 AI 剧本杀的主持人（DM），全知，但只以主持人身份吞吐信息：不剧透未演到的真相，不替玩家做决定。',
    `真人玩家扮演「${nameOf(b, me)}」（id=${me}）。其他角色都由 AI 演员扮演。`,
    '剧本全貌（只给你看）：', JSON.stringify(dmBrief(s)),
    '已发生：', storySoFar(b, s.events),
    '私聊摘要：', JSON.stringify(privateDigest(s.events)),
    '主频道最近对话：', transcript(b, s.events, 'main', 16),
    `玩家刚说：「${message}」`,
    `现在决定接话方式：要么你作为主持人接一句（引导、追问、描述场面，≤80字）；要么点一位最该回应的 AI 角色来说（从这些里选：${aiCast.join('、')}），两者也可以都有（你先说一句，再让角色接）。`,
    '只输出 JSON，不要别的：{"dm_line": "主持人的话，可为空字符串", "next_speaker": "角色 id，或空字符串"}',
  ].join('\n')
  const raw = await ask(prompt)
  const m = raw.match(/\{[\s\S]*\}/)
  try {
    const j = JSON.parse(m ? m[0] : raw)
    const sp = typeof j.next_speaker === 'string' && b.chars[j.next_speaker] && j.next_speaker !== me && s.s().character_states[j.next_speaker]?.alive ? j.next_speaker : undefined
    return { dm_line: typeof j.dm_line === 'string' && j.dm_line.trim() ? j.dm_line.trim() : undefined, next_speaker: sp }
  } catch {
    return { dm_line: raw.replace(/^["'「]|["'」]$/g, '') }
  }
}

/** 角色开口：主频道接话，或私聊窗回话。材料走隔离墙。 */
export async function characterRespond(s: Session, cid: string, me: string, channel: string, message?: string): Promise<{ text: string; pose?: string }> {
  const b = s.bundle
  const mat = characterMaterial(s, cid)
  const where = channel === 'main' ? '主频道（所有人都听得见）' : `和「${nameOf(b, me)}」的私聊（只有你们俩）`
  const prompt = [
    `你是 AI 演员，正在一场中文剧本杀里扮演「${b.chars[cid].name}」。下面是你的全部材料，材料里没有的就是你不知道的。`,
    JSON.stringify(mat),
    `场合：${where}。`,
    '最近对话：', transcript(b, s.events, channel, 14) || '（还没人说话）',
    message ? `「${nameOf(b, me)}」刚对你说：「${message}」` : '',
    mat.observer ? '你已是观演者：只说看见了什么、心里怎么想，不推进剧情。' : '',
    '用这个角色的口吻回一句，口语、具体、有立场，≤70字。可以试探、隐瞒、反问，但不要承认材料里没有的事。',
    '只输出 JSON：{"text": "台词", "pose": "可选的动作，≤8字，没有就空字符串"}',
  ].filter(Boolean).join('\n')
  const raw = await ask(prompt)
  const m = raw.match(/\{[\s\S]*\}/)
  try {
    const j = JSON.parse(m ? m[0] : raw)
    return { text: String(j.text ?? '').trim() || '……', pose: j.pose ? String(j.pose).slice(0, 12) : undefined }
  } catch {
    return { text: raw }
  }
}

/** 复盘自由交流：终局后谜底可以摊开，角色/主持人带着全部秘密回答。 */
export async function reviewChat(b: Bundle, events: Ev[], cid: string, me: string | undefined, history: { from: string; text: string }[], message: string) {
  const c = cid === DM_ID ? null : b.chars[cid]
  const ending = [...events].reverse().find((e) => e.type === 'game_end')
  const prompt = [
    c ? `你是剧本杀《${b.data.title}》里的「${c.name}」，对局已经结束，现在是复盘时间，可以说出你的全部秘密和真实动机。` : `你是剧本杀《${b.data.title}》的主持人，对局已结束，现在陪玩家复盘，可以讲出全部真相。`,
    c ? `你的公开身份：${publicOf(c)}\n你的秘密：${secretOf(c)}\n口吻：${voiceOf(c)}` : `剧本全貌：${JSON.stringify({ characters: (b.data.characters as Raw[]).map((x) => ({ name: x.name, secret: clip(secretOf(x), 160) })), endgame: b.data.endgame?.rules })}`,
    '这局发生了：', storySoFar(b, events),
    ending ? `结局：${ending.ending_title ?? ''} ${ending.ending_text ?? ''}` : '',
    '主频道对话（节选）：', transcript(b, events, 'main', 20),
    '复盘对话：', history.slice(-8).map((h) => `${h.from}：${h.text}`).join('\n'),
    `玩家（${me ? nameOf(b, me) : '玩家'}）问：「${message}」`,
    '直接回答，≤120字，坦诚、具体，可以评价玩家这局的选择。只输出回答本身。',
  ].filter(Boolean).join('\n')
  return ask(prompt)
}

/** 生成：粘贴文本 → 一份可玩的 bundle（按 contracts/bundle.schema.json 的必填字段）。 */
export async function generateBundle(text: string, onStage: (stage: string, msg: string) => void, spec?: GenSpec): Promise<Raw> {
  onStage('ingest', spec ? '读原文与创作结构' : '读原文')
  const src = text.slice(0, 12000)
  const acts = spec?.acts ?? 3
  onStage('act_structure', '拆幕、定人物、写场景（模型生成中，约半分钟）')
  const prompt = [
    '把下面的原文改编成一个可以在线游玩的中文剧本杀剧本包，严格输出一个 JSON 对象，不要任何解释或代码块标记。',
    '结构：',
    `{"id":"英文小写下划线","title":"标题","version":"0.1.0","language":"zh","adaptation_note":"改编说明，一两句",
"characters":[{"id":"英文id","name":"中文名","is_player":true或false,"public_sheet":"公开身份，一句","secret_sheet":"秘密，两三句，只有本人知道","voice":"三句口头禅，用 / 分隔"}],
"acts":[{"act_id":"A1","title":"幕名","world_info":"本幕世界信息，两句","scenes":[{"scene_id":"A1S1","text":"场景描述，给玩家看，两三句","reveals":["CL01"]}]}],
"clues":[{"clue_id":"CL01","title":"线索名","text":"线索内容一句","visible_at":"A1","must_ready_by":"final"}],
"props":[{"id":"CL01","name":"同线索名","description":"同线索内容"}],
"cards":[{"id":"CARD01","name":"象征卡名","symbol":"象征含义"}],
"endgame":{"conditions":[{"id":"END01","description":"条件说明"}],"review_prompt":"复盘引子一句","endings":[{"id":"END01","title":"结局名","text":"结局文字两句","condition":{}}]},
"dm_lines":{"opening":"主持人开场白","propose_play":"玩法提议","review":"复盘词","fallback":"主持人兜底台词","act_report":{"A1":"—— 第一幕 · 幕名 ——"}}}`,
    `要求：${acts} 幕，每幕 2 个场景；4 到 6 个角色，其中 3 到 4 个 is_player=true；${acts * 2} 到 ${acts * 2 + 2} 条线索，每条线索恰好被一个场景 reveals 一次；2 到 3 个结局；3 张象征卡。文字有悬念，不要在第一幕就揭开真相。`,
    spec ? `创作结构（硬约束，优先于上面的数量要求；与原文冲突时以这里为准）：\n${specBrief(spec)}` : '',
    src ? `原文：\n${src}` : '没有原文：按创作结构原创一个完整故事。',
  ].join('\n')
  const raw = await ask(prompt, { modelTier: 'default' })
  onStage('characters', '解析与校验')
  const m = raw.match(/\{[\s\S]*\}/)
  if (!m) throw new AiError('bad_output', '模型没有返回 JSON')
  const b = JSON.parse(m[0]) as Raw
  const issues: string[] = []
  b.id = String(b.id || `gen_${Date.now()}`).replace(/[^a-z0-9_]/gi, '_').toLowerCase()
  b.version ??= '0.1.0'
  b.language ??= 'zh'
  b.characters = (b.characters ?? []).filter((c: Raw) => c?.id && c?.name)
  for (const want of spec?.characters.filter((c) => c.name.trim()) ?? []) {
    const got = b.characters.find((c: Raw) => c.name === want.name)
    if (!got) {
      b.characters.push({ id: `c_${b.characters.length + 1}`, name: want.name, is_player: want.is_player, public_sheet: want.identity || '身份未明', secret_sheet: [want.secret, want.goal && `你的目标：${want.goal}`].filter(Boolean).join(' '), voice: '' })
      issues.push(`模型漏了指定角色「${want.name}」，已按你填的设定补上`)
    } else if (got.is_player !== want.is_player) {
      got.is_player = want.is_player
      issues.push(`「${want.name}」的可扮演设置按你填的改回来了`)
    }
  }
  if (spec?.title.trim()) b.title = spec.title.trim()
  if (!b.characters.some((c: Raw) => c.is_player)) { if (b.characters[0]) b.characters[0].is_player = true; issues.push('没有可扮演角色，已把第一个角色设为可扮演') }
  b.acts = (b.acts ?? []).filter((a: Raw) => a?.act_id && a?.scenes?.length)
  if (!b.acts.length) throw new AiError('bad_output', '生成结果里没有幕')
  b.props ??= []
  b.cards ??= []
  b.endgame ??= { conditions: [], endings: [] }
  b.endgame.conditions ??= (b.endgame.endings ?? []).map((e: Raw) => ({ id: e.id, description: e.title }))
  return { bundle: b, issues }
}

/** 创作助手：和用户聊设定，回一句话 + 对创作结构的增量修改 */
export async function assistGen(spec: GenSpec, text: string, history: { role: 'user' | 'assistant'; text: string }[], message: string): Promise<{ reply: string; patch: SpecPatch }> {
  const prompt = [
    '你是 LoomScript 的剧本杀创作助手，帮用户把一个剧本的「创作结构」聊清楚：背景（标题、类型、时代/地点、基调、世界观）、幕数（2-5）、角色卡（名字、身份、秘密、目标、是否玩家可扮演）、其他要求。',
    '风格：像一个懂行的编剧搭档，中文，直接，给具体建议；一次只追问一两个关键点；用户让你「帮我想」时就大胆替他填。',
    '当前创作结构：', JSON.stringify({ ...spec, characters: spec.characters.map(({ key: _k, ...c }) => c) }),
    text.trim() ? `用户贴了原文（节选）：${clip(text, 1500)}` : '用户没有贴原文。',
    '对话：', history.slice(-10).map((h) => `${h.role === 'user' ? '用户' : '助手'}：${h.text}`).join('\n'),
    `用户：${message}`,
    '只输出 JSON：{"reply":"给用户的回复，≤120字","patch":{"set":{"title":"","genre":"","era":"","world":"","tone":"","acts":3,"notes":""},"add_characters":[{"name":"","identity":"","secret":"","goal":"","is_player":true}],"update_characters":[{"name":"已有角色名","secret":"新秘密"}],"remove_characters":["角色名"]}}',
    'patch 里只放这次要改的字段，没改的省略；不改就给空对象 {}。不要改动用户没提到的已有内容。',
  ].join('\n')
  const raw = await ask(prompt)
  const m = raw.match(/\{[\s\S]*\}/)
  try {
    const j = JSON.parse(m ? m[0] : raw)
    return { reply: String(j.reply ?? '').trim() || '好。', patch: (j.patch && typeof j.patch === 'object' ? j.patch : {}) as SpecPatch }
  } catch {
    return { reply: raw, patch: {} }
  }
}

export const degradeCopy = (e: unknown) => (e instanceof AiError && e.code === 'unavailable' ? e.message : `模型调用失败：${e instanceof Error ? e.message : String(e)}`)
export const isRateLimited = (e: unknown) => e instanceof AiError && e.code === 'rate_limited'
export type { Raw }
