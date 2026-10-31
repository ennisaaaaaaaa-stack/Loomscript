/**
 * 前端合同类型。来源：frontend_handoff.json @ b6f1965（字段即合同）。
 * v0.1 新增字段全部标为可选，旧数据缺省即可用；升版只加不改。
 * 所有对象都允许未知字段（Extra），前端不因多出字段报错。
 */

type Extra = { [k: string]: unknown }

// ---------- bundle（剧本库） ----------

export interface Character extends Extra {
  id: string
  name: string
  is_player: boolean
  public_sheet: string
  /** 只给本人看。NPC 的 secret_sheet 不进玩家界面（见人物信息隔离 V3）。 */
  secret_sheet?: string
  voice?: string
}

export interface Choice extends Extra {
  id: string
  label: string
  leads_to?: string
}

export interface Scene extends Extra {
  scene_id: string
  text: string
  reveals: string[]
  /** v0.1：场景插图，指向 bundle.assets 里的 id */
  image_id?: string
  choices?: Choice[]
}

export interface Interlude extends Extra { text?: string; image_id?: string }

export interface Act extends Extra {
  act_id: string
  title: string
  world_info: string
  scenes: Scene[]
  /** 本幕收尾过场；act_end 事件会回显同样的内容 */
  interlude?: Interlude
}

export interface Prop extends Extra {
  id: string
  name: string
  act_introduced: string
  cg_id?: string
}

export interface Card extends Extra {
  id: string
  name: string
  symbol: string
}

export interface EndCondition extends Extra {
  id: string
  description: string
  cg_id?: string
}

/** 线索总表。clue_found 事件只带 clue_id，标题和正文从这里查 */
export interface ClueDef extends Extra {
  clue_id: string
  title: string
  text: string
  visible_at: string
}

export interface DeathDef extends Extra {
  id: string
  character_id: string
  act_id: string
  scene_id: string
  description: string
}

/** v0.1：资产清单。scene.image_id / props.cg_id / 卡面都指向这里 */
export type AssetKind = 'scene_image' | 'cg' | 'card_art' | 'prop_icon'
export interface Asset extends Extra {
  id: string
  kind: AssetKind | string
  uri: string
  prompt?: string
}

export interface Bundle extends Extra {
  id: string
  title: string
  version: string
  language: string
  characters: Character[]
  acts: Act[]
  props: Prop[]
  cards: Card[]
  endgame: { conditions: EndCondition[]; review_prompt?: string } & Extra
  /** v0.1 */
  assets?: Asset[]
  clues?: ClueDef[]
  deaths?: DeathDef[]
}

// ---------- events（时间线） ----------

/** main 或 dm:<character_id>。缺省视为 main。 */
export type Channel = string

interface EventBase extends Extra {
  session_id: string
  seq: number
  ts: string
  /** v0.1，缺省 main */
  channel?: Channel
}

export type KnownEvent =
  | (EventBase & { type: 'game_start' })
  /** 结局随事件下发（ending_*），不预发货 */
  | (EventBase & { type: 'game_end'; review_text?: string | null; ending_id?: string; ending_title?: string; ending_text?: string })
  | (EventBase & { type: 'act_begin'; act_id: string })
  | (EventBase & { type: 'act_end'; act_id: string; interlude?: Interlude })
  | (EventBase & { type: 'scene_begin'; act_id: string; scene_id: string })
  /** character_id 可能是 'dm'（主持人，不在 bundle.characters 里） */
  | (EventBase & { type: 'player_line' | 'agent_line'; character_id: string; act_id?: string; scene_id?: string; text: string; pose?: string })
  /** DM 发的行动卡，前端翻牌；text = 卡面文字 */
  | (EventBase & { type: 'choice'; character_id?: string; choice_id: string; text?: string; act_id?: string; scene_id?: string })
  | (EventBase & {
      type: 'reveal'
      act_id?: string
      scene_id?: string
      reveal_keys: string[]
      /** v0.1：与 reveal_keys 一一对应的展示文字，揭示瞬间随事件下发 */
      reveal_texts?: string[]
    })
  /** 引擎进入死亡场景时确定性触发；text = 死亡叙述 */
  | (EventBase & { type: 'death'; death_id: string; character_id: string; text?: string; act_id?: string; scene_id?: string })
  | (EventBase & { type: 'prop_gained'; act_id?: string; prop_id: string })
  | (EventBase & { type: 'card_draw'; act_id?: string; card_id: string })
  | (EventBase & { type: 'review'; review_text: string | null })
  // ---- v0.1 新增 ----
  /** error_code 如 dm_degraded / agent_unreachable，前端按码出提示；text 有就优先显示 */
  | (EventBase & { type: 'error'; error_code: string; text?: string })
  | (EventBase & { type: 'clue_found'; clue_id: string; text?: string })
  | (EventBase & { type: 'journal_push'; journal_text: string })

export type KnownType = KnownEvent['type']

/** 认不出的事件类型：保留原样，时间线里折叠显示，不崩。 */
export type UnknownEvent = EventBase & { type: string; __unknown: true }

export type GameEvent = KnownEvent | UnknownEvent

// ---------- snapshot（当前帧） ----------

export interface CharacterState extends Extra {
  on_stage: boolean
  /** 缺省视为活着；死后转观演 */
  alive?: boolean
  lines_spoken: number
  knowledge_unlocked: string[]
}

export interface Snapshot extends Extra {
  session_id: string
  bundle_id: string
  act_id: string | null
  scene_id: string | null
  seq: number
  character_states: Record<string, CharacterState>
  props_held: string[]
  cards_drawn: string[]
  cg_unlocked: string[]
  /** pianist → tangwu（堂屋）→ semi_manual（半人工）；未知值原样显示 */
  degradation_tier: 'pianist' | 'tangwu' | 'semi_manual' | string
}

export interface Handoff extends Extra {
  bundle: Bundle
  events: GameEvent[]
  snapshot: Snapshot
}
