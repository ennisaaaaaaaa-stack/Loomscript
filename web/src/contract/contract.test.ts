/**
 * 对拍仓库 contracts/：前端认的事件类型、资产 kind、降级档必须与 schema 一致。
 * schema 一改（加类型/加枚举），这里先红，提醒前端补渲染。
 */
import { describe, expect, it } from 'vitest'
import eventSchema from '../../../contracts/event.schema.json'
import bundleSchema from '../../../contracts/bundle.schema.json'
import snapshotSchema from '../../../contracts/snapshot.schema.json'
import genSchema from '../../../contracts/gen.schema.json'
import real from '../../../demos/frontend_handoff.json'
import mock from '../fixtures/handoff_v01_mock.json'
import { GEN_STAGES } from './gen'
import { KNOWN_TYPES, TIER_LABEL } from './normalize'

const eventTypes: string[] = eventSchema.properties.type.enum
const required = (s: { required: string[] }, o: Record<string, unknown>) => s.required.filter((k) => !(k in o))

describe('contracts/ 对拍', () => {
  it('前端认识 event.schema 里的全部事件类型，且不多认', () => {
    expect([...KNOWN_TYPES].sort()).toEqual([...eventTypes].sort())
  })
  it('降级档枚举全有文案', () => {
    for (const t of snapshotSchema.properties.degradation_tier.enum) expect(TIER_LABEL[t]).toBeTruthy()
  })
  it('生成阶段与 gen.schema 一致', () => {
    expect(GEN_STAGES.map((s) => s.id)).toEqual(genSchema.properties.stage.enum)
  })
  for (const [name, h] of [['真实录制', real], ['v0.1 预演', mock]] as const) {
    it(`${name}：事件必填字段齐、类型合法（预演里故意放的未知类型除外）`, () => {
      for (const e of h.events as Record<string, unknown>[]) {
        expect(required(eventSchema, e)).toEqual([])
        if (e.type !== 'future_event_x') expect(eventTypes).toContain(e.type)
      }
    })
    it(`${name}：bundle / snapshot 必填字段齐`, () => {
      expect(required(bundleSchema, h.bundle)).toEqual([])
      expect(required(snapshotSchema, h.snapshot)).toEqual([])
    })
  }
  it('预演资产符合 bundle.schema 的 assets 项', () => {
    const item = bundleSchema.properties.assets.items
    for (const a of mock.bundle.assets) {
      expect(required(item, a)).toEqual([])
      expect(item.properties.kind.enum).toContain(a.kind)
    }
  })
})
