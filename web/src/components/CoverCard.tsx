import { assetSrc } from '../contract/lookup'
import type { Bundle } from '../contract/types'

export function CoverCard({ bundle, onClick, compact }: { bundle: Bundle; onClick?: () => void; compact?: boolean }) {
  // 合同里没有封面 kind：有 cover 用 cover，否则用第一张出了图的场景图
  const pick = (k: string) => bundle.assets?.find((a) => a.kind === k && assetSrc(a))
  const src = assetSrc(pick('cover') ?? pick('scene_image'))
  return (
    <button className={`cover ${compact ? 'cover--compact' : ''}`} onClick={onClick}>
      <div className="cover__art" style={src ? { backgroundImage: `url(${src})` } : undefined}>
        {!src && <span className="cover__glyph">{bundle.title.slice(0, 1)}</span>}
      </div>
      <div className="cover__meta">
        <strong>{bundle.title}</strong>
        <span>{bundle.characters.length} 角色 · {bundle.acts.length} 幕 · v{bundle.version}</span>
      </div>
    </button>
  )
}
