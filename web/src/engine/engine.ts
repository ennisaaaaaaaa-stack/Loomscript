/**
 * 浏览器内本地引擎：src/engine.py + src/dm.py（结构性动作）+ src/play_blocks.py 的 TS 移植。
 * 口径与 Python 版逐条对齐：事件溯源、死亡结算、揭示、推幕、结局判定、线索/抽卡校验。
 * 用途：没有后端（比如 claude.ai 链接里）时也能完整开局。演出层台词见 ./ai.ts。
 * 没做 JSON Schema 校验（Python 版每次 emit 都校验）；合同对拍由 contract.test.ts 兜。
 */
/* eslint-disable @typescript-eslint/no-explicit-any */

export class ContractError extends Error {}

export type Raw = Record<string, any>
export type Ev = Raw & { session_id: string; seq: number; ts: string; type: string }

export const DM_ID = 'dm'

export class Bundle {
  data: Raw
  acts: Record<string, Raw>
  chars: Record<string, Raw>
  deaths: Record<string, Raw>
  constructor(data: Raw) {
    this.data = data
    this.acts = Object.fromEntries((data.acts ?? []).map((a: Raw) => [a.act_id, a]))
    this.chars = Object.fromEntries((data.characters ?? []).map((c: Raw) => [c.id, c]))
    this.deaths = Object.fromEntries((data.deaths ?? []).map((d: Raw) => [d.id, d]))
  }
  act(id: string) { return this.acts[id] }
  scenes(actId: string): Record<string, Raw> {
    return Object.fromEntries((this.act(actId)?.scenes ?? []).map((s: Raw) => [s.scene_id, s]))
  }
}

const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`)

export class Session {
  bundle: Bundle
  session_id = uuid()
  tier: string
  events: Ev[] = []
  state: Raw | null = null
  constructor(bundle: Bundle, tier = 'tangwu') {
    this.bundle = bundle
    this.tier = tier
  }

  s(): Raw {
    if (!this.state) throw new ContractError('game not started')
    return this.state
  }

  emit(fields: Raw): Ev {
    const ev = { session_id: this.session_id, seq: this.events.length, ts: new Date().toISOString(), ...fields } as Ev
    this.events.push(ev)
    this.apply(ev)
    return ev
  }

  apply(ev: Ev) {
    if (!this.state) {
      if (ev.type !== 'game_start') throw new ContractError('first event must be game_start')
      this.initState()
      return
    }
    const st = this.state
    switch (ev.type) {
      case 'act_begin': st.act_id = ev.act_id; st.scene_id = null; break
      case 'scene_begin': st.scene_id = ev.scene_id; break
      case 'player_line':
      case 'agent_line':
        if (st.character_states[ev.character_id]) st.character_states[ev.character_id].lines_spoken += 1
        break
      case 'reveal':
        for (const k of ev.reveal_keys ?? [])
          for (const [cid, cs] of Object.entries<Raw>(st.character_states))
            if (this.bundle.chars[cid]?.is_player) cs.knowledge_unlocked.push(k)
        break
      case 'death': {
        const cs = st.character_states[ev.character_id]
        cs.alive = false
        cs.on_stage = false
        break
      }
      case 'prop_gained': st.props_held.push(ev.prop_id); break
      case 'card_draw': st.cards_drawn.push(ev.card_id); break
    }
  }

  private initState() {
    this.state = {
      bundle_id: this.bundle.data.id,
      act_id: null, scene_id: null, seq: -1,
      character_states: Object.fromEntries((this.bundle.data.characters ?? []).map((c: Raw) => [c.id, { on_stage: true, alive: true, lines_spoken: 0, knowledge_unlocked: [] }])),
      props_held: [], cards_drawn: [], cg_unlocked: [],
      degradation_tier: this.tier,
    }
  }

  start() {
    this.emit({ type: 'game_start' })
    this.emit({ type: 'act_begin', act_id: this.bundle.data.acts[0].act_id })
    return this
  }

  enterScene(sceneId: string) {
    if (!this.bundle.scenes(this.s().act_id)[sceneId]) throw new ContractError(`unknown scene ${sceneId} in act ${this.s().act_id}`)
    this.emit({ type: 'scene_begin', act_id: this.s().act_id, scene_id: sceneId })
    this.settleDeaths(sceneId)
  }

  private settleDeaths(sceneId: string) {
    const scene = this.bundle.scenes(this.s().act_id)[sceneId]
    for (const did of scene.deaths ?? []) {
      if (this.events.some((e) => e.type === 'death' && e.death_id === did)) continue
      const d = this.bundle.deaths[did]
      if (!d) continue
      this.emit({ type: 'death', death_id: did, character_id: d.character_id, act_id: d.act_id, scene_id: d.scene_id, channel: 'main', text: d.description })
    }
  }

  line(cid: string, text: string, channel = 'main', pose?: string) {
    const cs = this.s().character_states[cid]
    if (cs && !cs.alive && channel === 'main') throw new ContractError(`character ${cid} is dead (observer); cannot speak in main`)
    if (!this.bundle.chars[cid]) throw new ContractError(`unknown character ${cid}`)
    const kw: Raw = { type: this.bundle.chars[cid].is_player ? 'player_line' : 'agent_line', character_id: cid, act_id: this.s().act_id, text, channel }
    if (pose) kw.pose = pose
    if (this.s().scene_id != null) kw.scene_id = this.s().scene_id
    return this.emit(kw)
  }

  fireReveals(sceneId: string) {
    const keys = this.bundle.scenes(this.s().act_id)[sceneId]?.reveals ?? []
    if (keys.length) this.emit({ type: 'reveal', act_id: this.s().act_id, scene_id: sceneId, reveal_keys: keys })
  }

  /** 当前位置字段；scene 未进入时省略（合同不收 null） */
  stage(): Raw {
    const kw: Raw = { act_id: this.s().act_id }
    if (this.s().scene_id != null) kw.scene_id = this.s().scene_id
    return kw
  }

  snapshot() {
    const st = this.s()
    return {
      session_id: this.session_id, bundle_id: st.bundle_id, act_id: st.act_id, scene_id: st.scene_id,
      seq: this.events.length - 1, character_states: st.character_states,
      props_held: st.props_held, cards_drawn: st.cards_drawn, cg_unlocked: st.cg_unlocked,
      degradation_tier: st.degradation_tier,
    }
  }
}

// ---------------------------------------------------------------- DM 结构性动作（dm.py）

export function pg(b: Bundle, key: string, actId?: string): string | undefined {
  const lines = b.data.dm_lines ?? {}
  if (actId) return lines.act_report?.[actId]
  return lines[key]
}

export function opening(s: Session) {
  const b = s.bundle
  const text = pg(b, 'opening') ?? (
    `欢迎来到《${b.data.title}》。我是主持人，全程陪着你。今晚与你同台的演员：${(b.data.characters as Raw[]).filter((c) => !c.is_player).map((c) => c.name).join('、')}。` +
    '你可以自由发言推进剧情，可以打开私聊窗找某位角色密谈，也可以随时和我聊。想先听我提议一种玩法吗？')
  return s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text, ...s.stage() })
}

export function proposePlay(s: Session) {
  const text = pg(s.bundle, 'propose_play') ?? '提议玩法：跟着台词的节奏走，该说话时说话；每个场景结束我会推幕并结算揭示。随时可以密谈——有些话只有私聊里说得出口。'
  return s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text, ...s.stage() })
}

export function actionCards(b: Bundle, actId: string, cid: string) {
  const cards: Raw[] = []
  for (const sc of b.act(actId).scenes) for (const ch of sc.choices ?? []) cards.push({ id: ch.id, label: ch.label, leads_to: ch.leads_to })
  cards.push({ id: 'free_talk', label: '自由发言（不限选项）' }, { id: 'ask_dm', label: '和 DM 交谈（主框）' }, { id: 'private', label: '私聊某位角色', target_channel: `dm:${cid}` })
  return cards
}

export function dealCards(s: Session, cid: string) {
  for (const c of actionCards(s.bundle, s.s().act_id, cid)) s.emit({ type: 'choice', character_id: cid, choice_id: c.id, text: c.label, ...s.stage() })
}

export function advanceAct(s: Session) {
  const b = s.bundle
  const acts = (b.data.acts as Raw[]).map((a) => a.act_id as string)
  const i = acts.indexOf(s.s().act_id)
  const nxt = acts[i + 1]
  const inter = b.act(acts[i])?.interlude
  s.emit({ type: 'act_end', act_id: acts[i], ...(inter ? { interlude: inter } : {}) })
  if (nxt) {
    s.emit({ type: 'act_begin', act_id: nxt })
    const report = pg(b, 'act_report', nxt) ?? `—— 第${i + 2}幕 · ${b.act(nxt).title} ——`
    s.emit({ type: 'agent_line', character_id: DM_ID, channel: 'main', text: report, act_id: nxt })
  } else {
    const ending = judgeEnding(s)
    const kw: Raw = { type: 'game_end', review_text: null }
    if (ending) {
      Object.assign(kw, { ending_id: ending.id, ending_title: ending.title ?? '', ending_text: ending.text ?? '' })
      if (ending.cg_id) s.s().cg_unlocked.push(ending.cg_id)
    }
    s.emit(kw)
  }
  sweepDeadline(s)
}

export function note(s: Session, journal_text: string) {
  return s.emit({ type: 'journal_push', journal_text, act_id: s.s().act_id })
}

export function review(s: Session, review_text?: string) {
  return s.emit({ type: 'review', review_text: review_text || pg(s.bundle, 'review') || '', act_id: s.state ? s.s().act_id : null })
}

// ---------------------------------------------------------------- play_blocks.py

const FINAL = 'final'
function actIndex(b: Bundle, actId: string) {
  const ids = (b.data.acts as Raw[]).map((a) => a.act_id)
  if (actId === FINAL) return ids.length - 1
  const i = ids.indexOf(actId)
  if (i < 0) throw new ContractError(`unknown act id in constraint: ${actId}`)
  return i
}

const firedClues = (s: Session) => new Set(s.events.filter((e) => e.type === 'clue_found').map((e) => e.clue_id))

export function proposeClue(s: Session, clueId: string, jitter_text?: string) {
  const clue = (s.bundle.data.clues ?? []).find((c: Raw) => c.clue_id === clueId)
  if (!clue) throw new ContractError(`unknown clue: ${clueId}`)
  if (actIndex(s.bundle, s.s().act_id) < actIndex(s.bundle, clue.visible_at)) throw new ContractError(`clue ${clueId} not yet visible (visible_at=${clue.visible_at}, current=${s.s().act_id})`)
  if (firedClues(s).has(clueId)) return null
  const payload: Raw = { ...(clue.payload ?? {}) }
  for (const k of ['type', 'act_id', 'session_id', 'seq', 'ts', 'clue_id']) delete payload[k]
  if (jitter_text != null) payload.jitter_text = jitter_text
  return s.emit({ type: 'clue_found', clue_id: clueId, act_id: s.s().act_id, ...payload })
}

export function sweepDeadline(s: Session) {
  if (!s.state) return
  const fired = firedClues(s)
  const archived = new Set(s.events.filter((e) => e.type === 'journal_push' && e.clue_id).map((e) => e.clue_id))
  const cur = actIndex(s.bundle, s.s().act_id)
  for (const clue of s.bundle.data.clues ?? []) {
    const cid = clue.clue_id
    if (fired.has(cid) || archived.has(cid)) continue
    if (actIndex(s.bundle, clue.must_ready_by ?? FINAL) < cur)
      s.emit({ type: 'journal_push', journal_text: `线索${cid}逾期未发（死线${clue.must_ready_by ?? FINAL}已过），已归档`, clue_id: cid, act_id: s.s().act_id })
  }
}

export function drawCard(s: Session, cardId: string, character_id?: string, jitter_text?: string) {
  if (!(s.bundle.data.cards ?? []).some((c: Raw) => c.id === cardId)) throw new ContractError(`unknown card: ${cardId}`)
  if (s.events.some((e) => e.type === 'card_draw' && e.card_id === cardId)) return null
  const kw: Raw = { type: 'card_draw', card_id: cardId, act_id: s.s().act_id }
  if (character_id) kw.character_id = character_id
  if (jitter_text != null) kw.text = jitter_text
  return s.emit(kw)
}

export function publicTestimonyCount(s: Session) {
  return new Set(s.events.filter((e) => e.type === 'player_line' && (e.channel ?? 'main') === 'main').map((e) => e.character_id)).size
}

export function judgeEnding(s: Session): Raw | null {
  const eg = s.bundle.data.endgame ?? {}
  const endings: Raw[] | undefined = eg.endings
  if (!endings?.length) return null
  const priority: string[] = eg.priority ?? endings.map((e) => e.id)
  const testimony = publicTestimonyCount(s)
  const preserved = s.events.some((e) => e.type === 'reveal' && (e.reveal_keys ?? []).includes('archive_preserved'))
  for (const id of priority) {
    const e = endings.find((x) => x.id === id)
    if (!e) continue
    const c = e.condition ?? {}
    let ok = true
    if ('public_testimony_count_min' in c) ok &&= testimony >= c.public_testimony_count_min
    if ('archive_preserved' in c) ok &&= c.archive_preserved === preserved
    if ('fallback_when_END01_false' in c) ok &&= c.fallback_when_END01_false === true
    if (ok) return { id: e.id, title: e.title ?? '', text: e.text ?? '', cg_id: e.cg_id }
  }
  return null
}

// ---------------------------------------------------------------- 玩家视图（server.public_bundle）

export function publicBundle(data: Raw, viewer?: string): Raw {
  const hidden = new Set(['actor_turns', 'dm_lines', 'deaths', 'source_pack'])
  const out: Raw = Object.fromEntries(Object.entries(data).filter(([k]) => !hidden.has(k)))
  out.characters = (data.characters ?? []).map((c: Raw) => {
    if (c.id === viewer) return c
    const { secret_sheet: _s, ...rest } = c
    return rest
  })
  out.props = (data.props ?? []).map((p: Raw) => {
    const { redline: _r, visibility: _v, release_event: _e, ...rest } = p
    return rest
  })
  if (data.clues) out.clues = data.clues.map((c: Raw) => Object.fromEntries(['clue_id', 'title', 'text', 'visible_at'].filter((k) => k in c).map((k) => [k, c[k]])))
  return out
}
