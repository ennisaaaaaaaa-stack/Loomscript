import { useEffect, useState } from 'react'
import { Avatar } from '../components/Avatar'
import { CoverCard } from '../components/CoverCard'
import { normalizeBundle } from '../contract/normalize'
import type { Bundle } from '../contract/types'
import { API_BASE, api } from '../data/live'
import { useStore } from '../state/store'

interface Entry { key: string; bundle: Bundle; backendId?: string }

/**
 * 剧本库：封面网格 + 详情 + 进本。
 * 后端在线时列 server 的 /bundles（玩家视图，NPC 私密本已剥离），可选角色开直播局；
 * 后端不在时只有当前 handoff 里那本，进本=回放。
 */
export function LibraryPage() {
  const { handoff, startLive } = useStore()
  const [remote, setRemote] = useState<Entry[] | null>(null)
  const [offline, setOffline] = useState<string | null>(null)
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [role, setRole] = useState<string>('')
  const [starting, setStarting] = useState(false)
  const [startErr, setStartErr] = useState<string | null>(null)

  useEffect(() => {
    api.bundles()
      .then((list) => Promise.all(list.map(async (s) => ({ key: `api:${s.bundle_id}`, backendId: s.bundle_id, bundle: normalizeBundle(await api.bundle(s.bundle_id)) }))))
      .then(setRemote, (e) => setOffline(String(e)))
  }, [])

  if (!handoff) return <div className="empty">加载中…</div>
  const entries: Entry[] = remote ?? [{ key: 'local', bundle: handoff.bundle }]
  const open = entries.find((e) => e.key === openKey)
  const playable = open?.bundle.characters.filter((c) => c.is_player) ?? []
  const chosen = role && playable.some((c) => c.id === role) ? role : playable[0]?.id

  return (
    <div className="lib">
      <h2>剧本库</h2>
      {offline && <p className="muted small">后端 {API_BASE} 没连上，只显示本地 handoff 里的剧本。开直播局先跑 <code>python src/server.py</code>。</p>}
      <div className="lib__grid">
        {entries.map((x) => <CoverCard key={x.key} bundle={x.bundle} onClick={() => { setOpenKey(x.key); setRole(''); setStartErr(null) }} />)}
        <a className="cover cover--new" href="#/gen"><span>＋</span><div className="cover__meta"><strong>导入文本生成新剧本</strong></div></a>
      </div>

      {open && (
        <div className="detail">
          <header>
            <CoverCard bundle={open.bundle} compact />
            <div>
              <h3>{open.bundle.title}</h3>
              <p className="muted">{open.bundle.id} · v{open.bundle.version} · {open.bundle.language}</p>
              <p>{open.bundle.acts[0]?.world_info}</p>
              {open.backendId ? (
                <>
                  <div className="muted small">选你的角色</div>
                  <div className="picker">
                    {playable.map((c) => (
                      <button key={c.id} className={c.id === chosen ? 'pill on' : 'pill'} onClick={() => setRole(c.id)}>{c.name}</button>
                    ))}
                  </div>
                  <button
                    className="primary"
                    disabled={!chosen || starting}
                    onClick={() => {
                      setStarting(true)
                      startLive(open.backendId!, chosen!)
                        .then(() => { location.hash = '#/play' }, (e) => setStartErr(String(e)))
                        .finally(() => setStarting(false))
                    }}
                  >{starting ? '开局中…' : '进本（开新局）'}</button>
                  {startErr && <p className="warn small">{startErr}</p>}
                </>
              ) : <a className="primary" href="#/play">进本（回放录制）</a>}
            </div>
            <button className="ghost" onClick={() => setOpenKey(null)}>×</button>
          </header>
          <h4>角色</h4>
          <ul className="cast">
            {open.bundle.characters.map((c) => (
              <li key={c.id}>
                <Avatar c={c} size={44} />
                <div>
                  <b>{c.name}</b>{c.is_player ? <span className="tag">可扮演</span> : <span className="tag tag--dim">AI 补位</span>}
                  <p>{c.public_sheet}</p>
                </div>
              </li>
            ))}
          </ul>
          <h4>结构</h4>
          <p className="muted">{open.bundle.acts.length} 幕 · {open.bundle.acts.reduce((n, a) => n + a.scenes.length, 0)} 场 · {open.bundle.props.length} 道具 · {open.bundle.cards.length} 张卡 · {open.bundle.endgame.conditions.length} 种结局{open.bundle.assets ? ` · ${open.bundle.assets.length} 项资产` : ''}</p>
        </div>
      )}
    </div>
  )
}
