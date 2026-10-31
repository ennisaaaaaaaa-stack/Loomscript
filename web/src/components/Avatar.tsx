import { useState } from 'react'
import { portraitSrc } from '../contract/lookup'
import type { Character } from '../contract/types'

// 立绘没到位（或加载失败）时用名字首字 + 稳定配色
const hue = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7)

export function Avatar({ c, id, size = 36 }: { c?: Character; id?: string; size?: number }) {
  const key = c?.id ?? id ?? '?'
  const label = (c?.name ?? id ?? '?').slice(0, 1)
  // bundle 里角色自带 portrait（内嵌/URL）优先，否则按 assets/portraits/<id>.png 约定
  const src = c?.portrait ?? portraitSrc(key)
  const [failed, setFailed] = useState<string | null>(null)
  return (
    <span
      className="avatar"
      title={c?.name ?? id}
      style={{ width: size, height: size, fontSize: size * 0.45, background: `hsl(${hue(key)} 35% 32%)` }}
    >
      {src && failed !== src ? <img src={src} alt="" onError={() => setFailed(src)} /> : label}
    </span>
  )
}
