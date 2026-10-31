import { findAct, findCard, findChar, findChoice, findClue, findProp, findScene } from '../contract/lookup'
import { DM_ID, errorCopy, parseChannel, pickText, revealText } from '../contract/normalize'
import type { Bundle, GameEvent } from '../contract/types'
import { Avatar } from './Avatar'

/** 时间线上每个事件的一行摘要。新类型加一个 case 即可，未知类型走 default。 */
export function describe(e: GameEvent, b: Bundle): { icon: string; title: string; sub?: string; tag?: string } {
  const ch = parseChannel(e.channel)
  const tag = ch.kind === 'dm' ? `私聊·${findChar(b, ch.characterId)?.name ?? ch.characterId}` : ch.kind === 'other' ? ch.raw : undefined
  if ('__unknown' in e) return { icon: '·', title: `未识别事件 ${e.type}`, sub: '前端未适配，已跳过', tag }
  switch (e.type) {
    case 'game_start': return { icon: '◆', title: '开局', tag }
    case 'game_end': return { icon: '◆', title: e.ending_title ? `终局 · ${e.ending_title}` : '终局', sub: e.ending_text, tag }
    case 'act_begin': return { icon: '幕', title: `${e.act_id} · ${findAct(b, e.act_id)?.title ?? ''}`, tag }
    case 'act_end': return { icon: '幕', title: `${e.act_id} 落幕`, sub: e.interlude?.text, tag }
    case 'scene_begin': return { icon: '景', title: `场景 ${e.scene_id}`, sub: findScene(b, e.scene_id)?.text, tag }
    case 'player_line':
    case 'agent_line': return { icon: '言', title: findChar(b, e.character_id)?.name ?? e.character_id, sub: e.text, tag }
    case 'reveal': return { icon: '✦', title: '揭示', sub: e.reveal_keys.map((k) => revealText(e, k) ?? k).join(' / '), tag }
    case 'prop_gained': return { icon: '◇', title: `获得道具 · ${findProp(b, e.prop_id)?.name ?? e.prop_id}`, tag }
    case 'card_draw': return { icon: '☍', title: `抽卡 · ${findCard(b, e.card_id)?.name ?? e.card_id}`, tag }
    case 'review': return { icon: '✎', title: 'DM 复盘', sub: e.review_text ?? undefined, tag }
    case 'death': return { icon: '✝', title: `${findChar(b, e.character_id)?.name ?? e.character_id} 死亡`, sub: e.text, tag }
    case 'choice': return { icon: '▣', title: `行动卡 · ${e.text ?? findChoice(b, e.choice_id)?.label ?? e.choice_id}`, sub: e.character_id ? `发给 ${findChar(b, e.character_id)?.name ?? e.character_id}` : undefined, tag }
    case 'error': return { icon: '!', title: `降级 · ${e.error_code}`, sub: errorCopy(e.error_code, pickText(e, ['text', 'message'])), tag }
    case 'clue_found': return { icon: '⌕', title: `线索 · ${findClue(b, e.clue_id)?.title ?? e.clue_id}`, sub: pickText(e) ?? findClue(b, e.clue_id)?.text, tag }
    case 'journal_push': return { icon: '❏', title: 'DM 手账', sub: e.journal_text ?? pickText(e) ?? undefined, tag }
  }
}

/** 聊天流里的一条：台词是气泡，其他事件是居中的系统卡片。 */
export function ChatItem({ e, b }: { e: GameEvent; b: Bundle }) {
  if (!('__unknown' in e) && (e.type === 'player_line' || e.type === 'agent_line')) {
    const c = findChar(b, e.character_id)
    const mine = e.type === 'player_line'
    const dm = e.character_id === DM_ID
    return (
      <div className={`msg ${mine ? 'msg--mine' : ''} ${dm ? 'msg--dm' : ''}`}>
        <Avatar c={c} id={e.character_id} />
        <div className="msg__body">
          <div className="msg__name">{c?.name ?? e.character_id}{e.pose && <span className="msg__pose">（{e.pose}）</span>}</div>
          <div className="msg__text">{e.text}</div>
        </div>
      </div>
    )
  }
  const d = describe(e, b)
  const kind = '__unknown' in e ? 'unknown' : e.type
  // choice 在行动卡区翻牌，不进聊天流
  if (kind === 'unknown' || kind === 'game_start' || kind === 'choice') return null
  if (kind === 'act_end' && !d.sub) return null
  return (
    <div className={`sys sys--${kind}`}>
      <span className="sys__icon">{d.icon}</span>
      <div>
        <div className="sys__title">{d.title}</div>
        {d.sub && <div className="sys__sub">{d.sub}</div>}
      </div>
    </div>
  )
}
