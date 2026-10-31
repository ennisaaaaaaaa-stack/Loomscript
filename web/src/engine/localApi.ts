/**
 * 本地后端：和 src/server.py 同一套接口（建局 / say / scene / dm / 事件流），
 * 只是跑在浏览器里。剧本来自仓库 bundles/*.json，以及 fixtures/*.bundle.json（带内嵌图片的打包版）。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { ActionResult, Backend, BundleSummary } from '../data/backend'
import { AiError, characterRespond, degradeCopy, dmRespond, getSample, reviewChat } from './ai'
import {
  advanceAct, Bundle, ContractError, DM_ID, dealCards, drawCard, note, opening, pg, proposeClue, proposePlay, publicBundle, review, Session, type Ev, type Raw,
} from './engine'

const repoBundles = import.meta.glob<Raw>('../../../bundles/*.json', { import: 'default' })
const packedBundles = import.meta.glob<Raw>('../fixtures/*.bundle.json', { import: 'default' })

const loaders = new Map<string, () => Promise<Raw>>()
for (const [p, l] of Object.entries(repoBundles)) loaders.set(p.split('/').pop()!.replace(/\.json$/, ''), l)
for (const [p, l] of Object.entries(packedBundles)) loaders.set(p.split('/').pop()!.replace(/\.bundle\.json$/, ''), l) // 打包版覆盖仓库版
const cache = new Map<string, Bundle>()

async function getBundle(id: string) {
  if (!cache.has(id)) {
    const l = loaders.get(id)
    if (!l) throw new Error(`404 bundle ${id} not found`)
    cache.set(id, new Bundle(await l()))
  }
  return cache.get(id)!
}

/** 生成页产出的新剧本挂进本地剧本库 */
export function registerBundle(data: Raw) {
  const b = new Bundle(data)
  cache.set(data.id, b)
  loaders.set(data.id, async () => data)
  return data.id as string
}

interface Room { s: Session; me?: string; subs: Set<(e: Ev) => void> }
const games = new Map<string, Room>()
const room = (sid: string) => {
  const r = games.get(sid)
  if (!r) throw new Error(`404 session ${sid} not found`)
  return r
}

/** 跑一段引擎操作，收集新事件并推给订阅者 */
async function run(r: Room, fn: () => void | Promise<void>): Promise<ActionResult> {
  const before = r.s.events.length
  try {
    await fn()
  } catch (e) {
    if (e instanceof ContractError) throw new Error(`400 ${e.message}`)
    throw e
  }
  const fresh = r.s.events.slice(before)
  for (const e of fresh) for (const f of r.subs) f(e)
  return { events: fresh, snapshot: r.s.snapshot() }
}

function degrade(r: Room, code: 'dm_degraded' | 'agent_unreachable', err: unknown) {
  if (err instanceof AiError && err.code === 'unavailable') r.s.s().degradation_tier = 'semi_manual'
  r.s.emit({ type: 'error', error_code: code, text: degradeCopy(err), ...r.s.stage() })
}

/** 主频道接话：DM 先说（可空），再按 DM 点名让一位 AI 角色接 */
async function mainTurn(r: Room, text: string) {
  const s = r.s
  const me = r.me!
  let turn
  try {
    turn = await dmRespond(s, me, text)
  } catch (e) {
    degrade(r, 'dm_degraded', e)
    s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text: pg(s.bundle, 'fallback') ?? '（主持人看着你，等你的下一句话。）', ...s.stage() })
    return
  }
  if (turn.dm_line) s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text: turn.dm_line, ...s.stage() })
  if (turn.next_speaker) {
    try {
      const l = await characterRespond(s, turn.next_speaker, me, 'main', text)
      s.line(turn.next_speaker, l.text, 'main', l.pose)
    } catch (e) {
      degrade(r, 'agent_unreachable', e)
    }
  }
  if (!turn.dm_line && !turn.next_speaker) s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text: pg(s.bundle, 'fallback') ?? '……', ...s.stage() })
}

async function privateTurn(r: Room, target: string, text: string) {
  const s = r.s
  const ch = `dm:${target}`
  if (target === DM_ID) {
    try {
      const t = await dmRespond(s, r.me!, `（私下对主持人说）${text}`)
      s.emit({ type: 'agent_line', character_id: DM_ID, channel: ch, text: t.dm_line ?? '我听着。', ...s.stage() })
    } catch (e) {
      degrade(r, 'dm_degraded', e)
    }
    return
  }
  if (!s.bundle.chars[target]) return
  try {
    const l = await characterRespond(s, target, r.me!, ch, text)
    s.line(target, l.text, ch, l.pose)
  } catch (e) {
    degrade(r, 'agent_unreachable', e)
  }
}

export const localBackend: Backend = {
  kind: 'local',
  assetBase: '',
  label: '浏览器内引擎',
  health: async () => ({ ok: true, bundles: [...loaders.keys()] }),
  bundles: async () => {
    const out: BundleSummary[] = []
    for (const id of [...loaders.keys()].sort()) {
      const b = (await getBundle(id)).data
      out.push({ bundle_id: id, id: b.id, title: b.title, version: b.version, characters: b.characters?.length ?? 0, acts: b.acts?.length ?? 0 })
    }
    // 带图的打包版排前面
    return out.sort((a, b) => Number(packedHas(b.bundle_id)) - Number(packedHas(a.bundle_id)))
  },
  bundle: async (id, viewer) => publicBundle((await getBundle(id)).data, viewer),
  createGame: async (bundle_id, opts = {}) => {
    const b = await getBundle(bundle_id)
    const tier = opts.tier ?? ((await getSample()) ? 'pianist' : 'semi_manual')
    const s = new Session(b, tier)
    s.start()
    opening(s)
    games.set(s.session_id, { s, me: opts.me, subs: new Set() })
    return { session_id: s.session_id, snapshot: s.snapshot(), last_seq: s.events.length - 1 }
  },
  say: async (sid, cid, text, channel = 'main') => {
    const r = room(sid)
    r.me ??= cid
    return run(r, async () => {
      r.s.line(cid, text, channel)
      if (channel === 'main') await mainTurn(r, text)
      else if (channel.startsWith('dm:')) await privateTurn(r, channel.slice(3), text)
    })
  },
  scene: async (sid, scene_id) => {
    const r = room(sid)
    return run(r, () => { r.s.enterScene(scene_id); r.s.fireReveals(scene_id) })
  },
  dm: async (sid, action, body = {}) => {
    const r = room(sid)
    const s = r.s
    return run(r, async () => {
      switch (action) {
        case 'opening': opening(s); break
        case 'propose_play': proposePlay(s); break
        case 'deal_cards': dealCards(s, String(body.character_id ?? r.me)); break
        case 'advance_act': advanceAct(s); break
        case 'review': review(s, body.review_text as string | undefined); break
        case 'note': note(s, String(body.journal_text ?? '')); break
        case 'draw_card': drawCard(s, String(body.card_id), body.character_id as string | undefined, body.jitter_text as string | undefined); break
        case 'propose_clue': proposeClue(s, String(body.clue_id), body.jitter_text as string | undefined); break
        default: throw new Error(`400 unknown dm action: ${action}`)
      }
    })
  },
  openStream: (sid, after, onEvent, onState) => {
    const r = games.get(sid)
    if (!r) { onState('error'); return () => {} }
    const f = (e: Ev) => onEvent(e)
    r.subs.add(f)
    queueMicrotask(() => {
      onState('open')
      for (const e of r.s.events) if (e.seq > after()) onEvent(e)
    })
    return () => { r.subs.delete(f) }
  },
  reviewChat: async (sid, cid, history, message) => {
    const r = room(sid)
    return reviewChat(r.s.bundle, r.s.events, cid, r.me, history, message)
  },
}

function packedHas(id: string) {
  return Object.keys(packedBundles).some((p) => p.endsWith(`/${id}.bundle.json`))
}

