import { assetSrc, findAsset } from '../contract/lookup'
import type { Bundle } from '../contract/types'

/** 按 asset id 出图；没有 url（未生成/未下发）就出占位框，标出 id 方便对清单。 */
export function AssetFrame({ bundle, assetId, label, ratio = '16 / 9', onClick }: {
  bundle: Bundle; assetId?: string; label?: string; ratio?: string; onClick?: () => void
}) {
  const asset = findAsset(bundle, assetId)
  const url = assetSrc(asset)
  return (
    <div className={`asset ${url ? '' : 'asset--empty'}`} style={{ aspectRatio: ratio }} onClick={onClick}>
      {url ? <img src={url} alt={label ?? assetId} onError={(e) => { e.currentTarget.style.display = "none" }} /> : (
        <div className="asset__ph">
          <span>{label ?? '插图'}</span>
          <code>{assetId ?? '无 image_id'}{asset && !url ? ' · 未出图' : ''}</code>
        </div>
      )}
    </div>
  )
}
