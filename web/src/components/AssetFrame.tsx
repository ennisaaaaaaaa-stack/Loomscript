import { useState } from 'react'
import { assetSrc, findAsset } from '../contract/lookup'
import type { Bundle } from '../contract/types'

/** 按 asset id 出图；没有 uri、还在 pending 或加载失败，就出占位框并标出 id，方便对清单。 */
export function AssetFrame({ bundle, assetId, label, ratio = '16 / 9', onClick }: {
  bundle: Bundle; assetId?: string; label?: string; ratio?: string; onClick?: () => void
}) {
  const asset = findAsset(bundle, assetId)
  const src = assetSrc(asset)
  const [failed, setFailed] = useState<string | null>(null)
  const show = src && failed !== src
  return (
    <div className={`asset ${show ? '' : 'asset--empty'}`} style={{ aspectRatio: ratio }} onClick={onClick}>
      {show ? <img src={src} alt={label ?? assetId} onError={() => setFailed(src)} /> : (
        <div className="asset__ph">
          <span>{label ?? '插图'}</span>
          <code>{assetId ?? '无 image_id'}{asset ? ` · ${asset.status === 'pending' ? '生成中' : '未出图'}` : ''}</code>
        </div>
      )}
    </div>
  )
}
