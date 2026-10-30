import { useState } from 'react'
import { Avatar } from '../components/Avatar'
import { CoverCard } from '../components/CoverCard'
import { useStore } from '../state/store'

/** 剧本库最小版：封面网格 + 详情 + 进本。详情只放玩家可见信息（NPC secret_sheet 不进前端界面）。 */
export function LibraryPage() {
  const { handoff } = useStore()
  const [open, setOpen] = useState(false)
  if (!handoff) return <div className="empty">加载中…</div>
  const b = handoff.bundle
  const library = [b] // 后端给出剧本列表接口后换成列表

  return (
    <div className="lib">
      <h2>剧本库</h2>
      <div className="lib__grid">
        {library.map((x) => <CoverCard key={x.id} bundle={x} onClick={() => setOpen(true)} />)}
        <a className="cover cover--new" href="#/gen"><span>＋</span><div className="cover__meta"><strong>导入文本生成新剧本</strong></div></a>
      </div>

      {open && (
        <div className="detail">
          <header>
            <CoverCard bundle={b} compact />
            <div>
              <h3>{b.title}</h3>
              <p className="muted">{b.id} · v{b.version} · {b.language}</p>
              <p>{b.acts[0]?.world_info}</p>
              <a className="primary" href="#/play">进本</a>
            </div>
            <button className="ghost" onClick={() => setOpen(false)}>×</button>
          </header>
          <h4>角色</h4>
          <ul className="cast">
            {b.characters.map((c) => (
              <li key={c.id}>
                <Avatar c={c} size={44} />
                <div>
                  <b>{c.name}</b>{c.is_player ? <span className="tag">玩家</span> : <span className="tag tag--dim">AI 补位</span>}
                  <p>{c.public_sheet}</p>
                </div>
              </li>
            ))}
          </ul>
          <h4>结构</h4>
          <p className="muted">{b.acts.length} 幕 · {b.acts.reduce((n, a) => n + a.scenes.length, 0)} 场 · {b.props.length} 道具 · {b.cards.length} 张卡 · {b.endgame.conditions.length} 种结局{b.assets ? ` · ${b.assets.length} 项资产` : ''}</p>
        </div>
      )}
    </div>
  )
}
