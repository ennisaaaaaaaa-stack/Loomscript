import { describe, expect, it } from 'vitest'
import raw from '../../../demos/frontend_handoff.json'
import mock from '../fixtures/handoff_v01_mock.json'
import { applyGen, initialGen } from '../contract/gen'
import { normalizeBundle, normalizeHandoff, parseChannel, revealText } from '../contract/normalize'
import { diffSnapshot, frameAt } from './frame'

describe('b6f1965 真实录制', () => {
  const { handoff, snapshot } = normalizeHandoff(raw)

  it('回放到最后一帧，推导快照与服务端 snapshot 对拍一致', () => {
    const f = frameAt(handoff.events, Infinity, handoff.bundle)
    expect(snapshot).not.toBeNull()
    expect(diffSnapshot(f.snapshot, snapshot!)).toEqual([])
    expect(f.phase).toBe('ended')
    expect(f.reviewText).toContain('DM复盘')
  })

  it('旧数据没有 channel，全部落 main', () => {
    const f = frameAt(handoff.events, Infinity, handoff.bundle)
    expect(Object.keys(f.threads)).toEqual(['main'])
    expect(f.threads.main).toHaveLength(handoff.events.length)
  })

  it('回放到中途：A2S1 拿到匕首前后', () => {
    expect(frameAt(handoff.events, 11, handoff.bundle).snapshot.props_held).toEqual([])
    expect(frameAt(handoff.events, 12, handoff.bundle).snapshot.props_held).toEqual(['p_dagger'])
  })
})

describe('v0.1 预演数据（mock）', () => {
  const { handoff } = normalizeHandoff(mock)
  const f = frameAt(handoff.events, Infinity, handoff.bundle)

  it('dm 频道分流', () => {
    expect(f.threads.banquo?.length).toBeGreaterThan(0)
    expect(f.threads.lady_m?.length).toBeGreaterThan(0)
  })
  it('DM 发言不计入角色台词数，推导快照仍与预演 snapshot 一致', () => {
    const { snapshot } = normalizeHandoff(mock)
    expect(diffSnapshot(f.snapshot, snapshot!)).toEqual([])
  })
  it('choice 行动卡按幕收集，error 按码出文案', () => {
    expect(f.choices).toEqual([])  // 落幕清空
    const mid = frameAt(handoff.events, 14, handoff.bundle)
    expect(mid.choices.map((c) => c.id)).toEqual(['c_grab', 'private'])
    expect(f.errors[0]).toMatchObject({ code: 'dm_degraded', message: 'DM嗓子哑了，剧本自己往下走' })
    expect(f.journal[0].text).toBe('DM手账：预言已种下，等它发芽。')
  })
  it('error / clue_found / journal_push 入帧', () => {
    expect(f.errors).toHaveLength(1)
    expect(f.clues.length).toBeGreaterThan(0)
    expect(f.journal.length).toBeGreaterThan(0)
  })
  it('未知事件类型不崩，只进时间线', () => {
    expect(handoff.events.some((e) => '__unknown' in e)).toBe(true)
  })
})

describe('v0.2 合同：death / ending / clues 表', () => {
  const { handoff } = normalizeHandoff(raw)
  const b = { ...handoff.bundle, clues: [{ clue_id: 'c1', title: '刀柄', text: '纹章不对', visible_at: 'A1' }] }
  const base = { session_id: 's', ts: '' }
  const evs = [
    { ...base, seq: 0, type: 'game_start' },
    { ...base, seq: 1, type: 'clue_found', clue_id: 'c1' },
    { ...base, seq: 2, type: 'death', death_id: 'd1', character_id: 'banquo', text: '班柯倒在路上' },
    { ...base, seq: 3, type: 'game_end', ending_id: 'end_fall', ending_title: '森林移动', ending_text: '……' },
  ] as never
  const f = frameAt(evs, Infinity, b)
  it('clue_found 只带 id 时从 bundle.clues 查标题正文', () => {
    expect(f.clues[0]).toMatchObject({ title: '刀柄', text: '纹章不对' })
  })
  it('death 翻 alive=false', () => {
    expect(f.snapshot.character_states.banquo.alive).toBe(false)
  })
  it('game_end 带结局，并按结局表解锁 CG', () => {
    expect(f.ending).toMatchObject({ id: 'end_fall', title: '森林移动' })
    expect(f.snapshot.cg_unlocked).toEqual(['cg_birnam'])
  })
})

describe('工具函数', () => {
  it('parseChannel', () => {
    expect(parseChannel(undefined)).toEqual({ kind: 'main' })
    expect(parseChannel('dm:banquo')).toEqual({ kind: 'dm', characterId: 'banquo' })
    expect(parseChannel('group:x')).toEqual({ kind: 'other', raw: 'group:x' })
  })
  it('revealText 兼容数组与对象', () => {
    expect(revealText({ reveal_keys: ['a', 'b'], reveal_texts: ['A', 'B'] }, 'b')).toBe('B')
    expect(revealText({ reveal_keys: ['a'], reveal_texts: { a: 'A' } }, 'a')).toBe('A')
    expect(revealText({ reveal_keys: ['a'] }, 'a')).toBeNull()
  })
  it('gen 进度聚合', () => {
    let v = initialGen()
    v = applyGen(v, { job_id: 'j', stage: 'characters', status: 'running', progress: 0.5, ts: '' }, normalizeBundle)
    v = applyGen(v, { job_id: 'j', stage: 'characters', status: 'ok', ts: '', validation: { issues: [{ severity: 'warning', code: 'x', message: 'm' }] } }, normalizeBundle)
    expect(v.stages.characters).toMatchObject({ status: 'ok', progress: 1, issues: [{ code: 'x', stage: 'characters' }] })
    v = applyGen(v, { job_id: 'j', stage: 'done', status: 'ok', ts: '', bundle: raw.bundle }, normalizeBundle)
    expect(v.bundle?.id).toBe('macbeth-mini')
  })
})
