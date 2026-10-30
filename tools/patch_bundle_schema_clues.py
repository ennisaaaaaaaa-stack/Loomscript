#!/usr/bin/env python3
"""7.4 合同层钉子：clues 总表进 bundle 合同（visible_at / must_ready_by）。

主 session 亲自动的合同层，两个分身照此实现，防止 schema 漂移。
幂等：重复跑无副作用（先检查是否已加过）。
"""
import json
import glob
import sys

P = 'contracts/bundle.schema.json'

raw = open(P).read()
if '"clues": {' in raw:
    print('already patched, skip')
    sys.exit(0)

# 在顶层 properties 里、endgame 块之前插入 clues 总表
anchor = '\"endgame\": {'
i = raw.find(anchor)
assert i > 0, 'endgame block anchor not found'

clues_block = '''  "clues": {
   "type": "array",
   "description": "Loomscript clue master table (7.4). visible_at = earliest act where the clue may fire; must_ready_by = deadline (act id or final); past the deadline the engine degrades or drops. These two fields are what the engine checks before releasing a DM proposal.",
   "items": {
    "type": "object",
    "required": ["clue_id", "title", "text", "visible_at"],
    "properties": {
     "clue_id": {"type": "string"},
     "title": {"type": "string"},
     "text": {"type": "string"},
     "visible_at": {"type": "string"},
     "must_ready_by": {"type": "string"},
     "act_scoped": {"type": "boolean"},
     "payload": {
      "type": "object",
      "description": "default clue_found event payload used when the engine releases the proposal"
     }
    }
   }
  },
'''
raw = raw[:i] + clues_block + '  ' + raw[i:]
open(P, 'w').write(raw)
print('schema patched')

# 1) schema 自身仍是合法 JSON 且是合法 schema
schema = json.load(open(P))
assert isinstance(schema, dict) and 'properties' in schema

import jsonschema
jsonschema.Draft202012Validator.check_schema(schema)
print('schema self-check OK')

# 2) 现有 bundle 全部通过（新字段可选，旧 bundle 必须不受影响）
for b in sorted(glob.glob('bundles/*.json')):
    try:
        jsonschema.Draft202012Validator(schema).validate(json.load(open(b)))
        print('PASS', b)
    except jsonschema.ValidationError as e:
        print('FAIL', b, str(e.message)[:120])
        sys.exit(1)
print('all bundles pass')
