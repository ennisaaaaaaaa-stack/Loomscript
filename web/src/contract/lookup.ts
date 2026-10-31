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
/** 相对 uri（assets/bg/BG01.png）挂在哪个地址下；直播时由 store 设成后端地址 */
let assetBase = ''
export const setAssetBase = (base: string) => { assetBase = base.replace(/\/$/, '') }

/** 合同字段是 uri；url 兜底。相对路径按 assetBase 解析 */
export const assetSrc = (a?: { uri?: unknown; url?: unknown; status?: unknown }) => {
  if (!a || a.status === 'pending') return undefined
  const u = typeof a.uri === 'string' && a.uri ? a.uri : typeof a.url === 'string' && a.url ? a.url : undefined
  if (!u || /^(https?:|data:|blob:|\/)/.test(u) || !assetBase) return u
  return `${assetBase}/${u}`
}
/** 道具图标按 ICON_<prop_id> 约定，卡面 asset id 即卡 id */
export const propIcon = (b: Bundle, id: string) => assetSrc(findAsset(b, `ICON_${id}`) ?? findAsset(b, b.props.find((p) => p.id === id)?.cg_id))
export const cardArt = (b: Bundle, id: string) => assetSrc(b.assets?.find((a) => a.id === id && a.kind === 'card_art'))
export const findClue = (b: Bundle, id?: string) => b.clues?.find((c) => c.clue_id === id)
export const findEnding = (b: Bundle, id?: string) => b.endgame.conditions.find((c) => c.id === id)
export const findChoice = (b: Bundle, id?: string) => b.acts.flatMap((a) => a.scenes).flatMap((s) => s.choices ?? []).find((c) => c.id === id)
export const playerOf = (b: Bundle) => b.characters.find((c) => c.is_player)
