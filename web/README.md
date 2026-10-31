# LoomScript Web（前端壳）

仓库前端。对着 `contracts/` 和 `demos/frontend_handoff.json`（b6f1965）搭的壳：**events → 时间线，snapshot → 当前帧，bundle → 剧本库**。字段即合同。

```bash
# 后端（仓库根目录）：pip install fastapi uvicorn jsonschema && python src/server.py   → :8740
npm install
npm run dev          # http://localhost:5173 ；后端不在默认地址就加 ?api=http://host:port
npm test             # 合同/回放单测
npm run build        # 正式构建 → dist/
npm run build:single # 单文件 HTML（fixtures 内联）→ dist-single/index.html，可直接发群里双击打开
```

## 页面（对应任务书 2.0）

| 路由 | 页面 | 状态 |
|---|---|---|
| `#play` | P0 对局页：事件时间线 / 场景舞台 / 主聊天流 / 当前帧 / 私聊窗 / 回放控制 | event.schema 15 种事件全接 |
| `#gen` | P0 生成页：粘贴文本 → 进度流 → bundle 预览 → 一键游玩 | 按 gen.schema 聚合；无后端时本地模拟 |
| `#library` | P1 剧本库：封面网格 + 详情 + 进本 | 列表接口未定，现在只有 handoff 里那一本 |
| `#review` | P1 复盘页：DM 复盘词 + 快照对照 + 自由交流 | 自由交流只在本地回显 |

复用组件：`ChatWindow`（主聊天/私聊/复盘/发现）、`CoverCard`、`Timeline`（事件流/生成进度）、`AssetFrame`（场景/CG/道具图，没图出占位框并标 asset id）。

## 数据源

- 顶栏「数据」切换内置两份：
  - `b6f1965 真实录制`：直接读仓库的 `demos/frontend_handoff.json`，handoff 升版前端自动跟上。
  - `v0.1 预演（mock）`：`src/fixtures/handoff_v01_mock.json`，在真实录制上按 `contracts/` 的 v0.1 字段手工插入 DM 发言、dm 私聊、choice 行动卡、clue_found、journal_push、error、reveal_texts、scene.image_id、bundle.assets，外加一个未知事件类型。**不是引擎产出**，只用来证明升版不用返工。
- 顶栏「载入 handoff…」：直接选新版 handoff JSON。
- `?src=<url>`：启动时从 URL 拉 handoff。
- 生成页 `?gen=<SSE 地址>`：每条 `message.data` 是一条 gen 进度事件；不带参数就本地按合同形状模拟。
- **直播**（`src/data/live.ts`）：剧本库从 `GET /bundles` 列剧本，选角色后 `POST /games` 开局，`GET /games/{id}/stream`（SSE）收事件，断线按 seq 续传；发言走 `/say`（私聊窗发 `channel: dm:<id>`），顶栏按钮走 `/scene`、`/dm`（推幕、发行动卡、复盘）。动作返回的事件与 SSE 推来的按 seq 去重合并。后端连不上时自动退回回放模式。

## 合同处理（`src/contract/`，对着仓库 `contracts/`）

- `types.ts`：bundle / event / snapshot 全字段，对象允许未知字段。
- `gen.ts`：gen.schema 的 8 个阶段、状态、progress、validation.issues 聚合，`done` 时取 bundle。
- `normalize.ts`：容错入口。
  - `channel` 缺省 `main`；`dm:<character_id>` 分流进私聊窗；其他前缀原样标注、落主频道。
  - 未知事件类型标 `__unknown`，时间线折叠显示，不改状态、不崩。
  - `error` 按 `error_code` 出文案（`dm_degraded` / `agent_unreachable`），事件带 `text` 就优先用。
  - `character_id: "dm"` 是主持人，不在 bundle 里，单独渲染，不计台词数（与 engine.py 一致）。
  - 资产图取 `uri`；`uri` 为空就出占位框并标 asset id。
- `state/frame.ts`：纯函数回放，`frameAt(events, seq)` 得到任意时刻的画面，推导快照与服务端 snapshot 同形；回放到末尾时直接用服务端 snapshot。
- `contract.test.ts`：直接读 `../contracts/*.json` 对拍。schema 加了事件类型、降级档、生成阶段，这里先红，提醒前端补渲染。

## 还没定的（后端定了改一处即可）

1. 生成任务的后端入口（server.py 还没有生成端点）→ `data/gen.ts` `startGen`
2. 资产图：bundle 里 `uri` 是相对路径、`status: pending`，图出来以后需要后端或静态目录提供 → `AssetFrame.tsx`
3. 复盘自由交流接口（现在只本地回显）→ `ReviewPage.tsx`
4. 合同里没有封面 kind：封面先取第一张出了图的 `scene_image` → `CoverCard.tsx`

## 信息隔离

按人物信息隔离 V3「普通前端只显示当前用户获准的文本与素材」：`GET /bundles/{id}?viewer=<角色>` 只下发该角色自己的 `secret_sheet`，演员包、DM 预生成台词、死亡定义、线索投放元数据都不出服务端；NPC 的已知信息只显示服务端 snapshot 给的，前端不自己推断；reveal 文字只用事件里下发的 `reveal_texts`。

### 带图的离线回放包

把一局直播录成 `web/src/fixtures/<名字>.recorded.json`（handoff 形状，图片可用 data URI 内嵌，角色可带 `portrait`），
数据源下拉里会自动出现在第一位；`npm run build:single` 打出的单文件可直接发给别人点开。
这类文件体积大，已在 `.gitignore` 里排除。路由用扁平 hash（`#play`），旧的 `#/play` 也认。
