import type { ReactNode } from 'react'

export interface TimelineItem {
  id: string | number
  status: 'done' | 'active' | 'pending' | 'error'
  title: ReactNode
  sub?: ReactNode
  tag?: string
}

/** 对局事件流 / 生成进度流共用：同一组件换数据源 */
export function Timeline({ items, onPick }: { items: TimelineItem[]; onPick?: (id: TimelineItem['id']) => void }) {
  return (
    <ol className="timeline">
      {items.map((it) => (
        <li key={it.id} className={`tl tl--${it.status}`} onClick={onPick ? () => onPick(it.id) : undefined}>
          <span className="tl__dot" />
          <div className="tl__body">
            <div className="tl__title">{it.title}{it.tag && <span className="tag">{it.tag}</span>}</div>
            {it.sub && <div className="tl__sub">{it.sub}</div>}
          </div>
        </li>
      ))}
    </ol>
  )
}
