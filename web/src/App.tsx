import { useEffect, useState } from 'react'
import { BUILTIN_SOURCES, loadFromFile } from './data/sources'
import { GenPage } from './pages/GenPage'
import { LibraryPage } from './pages/LibraryPage'
import { PlayPage } from './pages/PlayPage'
import { ReviewPage } from './pages/ReviewPage'
import { useStore } from './state/store'

const ROUTES = [
  { path: '#/gen', label: '生成', el: <GenPage /> },
  { path: '#/library', label: '剧本库', el: <LibraryPage /> },
  { path: '#/play', label: '对局', el: <PlayPage /> },
  { path: '#/review', label: '复盘', el: <ReviewPage /> },
]

function useHash() {
  const [h, setH] = useState(location.hash || '#/library')
  useEffect(() => {
    const on = () => setH(location.hash || '#/library')
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return h
}

export function App() {
  const hash = useHash()
  const { sourceLabel, loadBuiltin, load, loadError } = useStore()
  const route = ROUTES.find((r) => hash.startsWith(r.path)) ?? ROUTES[1]

  return (
    <div className="app">
      <nav className="nav">
        <a className="brand" href="#/library">LoomScript</a>
        {ROUTES.map((r) => <a key={r.path} href={r.path} className={r === route ? 'on' : ''}>{r.label}</a>)}
        <span className="grow" />
        <label className="src">
          数据
          <select value={BUILTIN_SOURCES.find((s) => s.label === sourceLabel)?.id ?? ''} onChange={(e) => loadBuiltin(e.target.value)}>
            {!BUILTIN_SOURCES.some((s) => s.label === sourceLabel) && <option value="">{sourceLabel || '…'}</option>}
            {BUILTIN_SOURCES.map((s) => <option key={s.id} value={s.id} title={s.note}>{s.label}</option>)}
          </select>
        </label>
        <label className="ghost file" title="载入新版 frontend_handoff.json">
          载入 handoff…
          <input type="file" accept=".json,application/json" onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) loadFromFile(f).then((raw) => load(raw, f.name), (err) => alert(`解析失败：${err}`))
          }} />
        </label>
      </nav>
      {loadError && <div className="errbar">{loadError}</div>}
      <main>{route.el}</main>
    </div>
  )
}
