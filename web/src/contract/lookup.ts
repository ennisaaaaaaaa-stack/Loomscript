import { DM_ID } from './normalize'
import type { Bundle, Character } from './types'

// 查不到时返回 undefined，UI 统一用 id 兜底显示
const DM_CHAR: Character = { id: DM_ID, name: '主持人', is_player: false, public_sheet: '' }
/** 'dm' 不在 bundle.characters 里，单独兜一个主持人 */
export const findChar = (b: Bundle, id?: string) => b.characters.find((c) => c.id === id) ?? (id === DM_ID ? DM_CHAR : undefined)
export const findAct = (b: Bundle, id?: string | null) => b.acts.find((a) => a.act_id === id)
export const findScene = (b: Bundle, id?: string | null) => b.acts.flatMap((a) => a.scenes).find((s) => s.scene_id === id)
export const findProp = (b: Bundle, id?: string) => b.props.find((p) => p.id === id)
export const findCard = (b: Bundle, id?: string) => b.cards.find((c) => c.id === id)
export const findAsset = (b: Bundle, id?: string) => (id ? b.assets?.find((a) => a.id === id) : undefined)
/** 合同字段是 uri；url 兜底 */
export const assetSrc = (a?: { uri?: unknown; url?: unknown }) =>
  typeof a?.uri === 'string' && a.uri ? a.uri : typeof a?.url === 'string' && a.url ? a.url : undefined
export const findChoice = (b: Bundle, id?: string) => b.acts.flatMap((a) => a.scenes).flatMap((s) => s.choices ?? []).find((c) => c.id === id)
export const playerOf = (b: Bundle) => b.characters.find((c) => c.is_player)
