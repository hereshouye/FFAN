# 教练心理 AI — Schema 总览

> 本文档给**任何 AI 底座 (Claude / GPT / Qwen / 本地 LLM)** 看, 说明 FFAN 心理数据怎么组织、怎么读、怎么写、怎么演化。
> 所有数据都是 **纯 JSON / JSONL / Markdown**, 与具体 AI 底座解耦。

---

## 1. 三层数据结构

```
data/
├── profiles.json                          ← 玩家画像 (一个真相源, 三层字段)
├── players/<puuid>/
│   ├── psych_state.json                   ← 动态心理状态 (每次 regen 重算)
│   └── psych_timeline.jsonl               ← 状态变化追加 (持续监控)
└── coach/
    ├── persona.json                       ← 教练人设
    ├── history.jsonl                      ← 教练发言流水 (SFT 训练源)
    ├── feedback.jsonl                     ← 用户反馈 (DPO 偏好对源)
    └── kb/psychology/                     ← 心理学知识库
        ├── _index.json                    ← 目录 + 字段说明
        ├── profile_axes.json              ← 5 维 axes 词典
        ├── tilt_types.jsonl               ← 7 类 tilt
        ├── adolescent_traps.jsonl         ← 6 类青春期陷阱
        ├── cbt_techniques.jsonl
        ├── growth_mindset.jsonl
        ├── arousal_regulation.jsonl
        ├── stress_inoculation.jsonl
        ├── crisis_signals.md              ← 危机识别 (必读)
        ├── communication_protocols.md
        └── debrief_protocols.md
```

---

## 2. profiles.json — 玩家画像三层

每个 puuid 一条, 字段分 4 类:

```json
{
  "<puuid>": {
    /* 1. manual — 用户手填 (短结构化) */
    "nickname":           "朋友A",
    "self_role":          "jungle",
    "self_desc":          "刺客 carry, 走脸专精, 不顺也要硬秀",
    "tags":               ["carry", "上头"],
    "peer_review":        "顺风一打五, 逆风一秒钟",
    "habits":             "找机会越塔, 大招换血赌脸",
    "skill":              "S",
    "carry_priority":     9,
    "favorite_champ_ids": [141, 7, 91, 245],
    "premade_with":       ["<my_puuid>"],

    /* 2. persona — 自然语言长文本 (训练核心) */
    "persona": {
      "self_voice":  "我玩 Kayn 就要红色形态切人头啊...",     // 第一人称, 训练语气
      "peer_voices": ["顺风一打五的核武",                     // 他评, 多条
                      "和他打 ARAM 基本不输"],
      "updated_at":  "2026-05-12T17:33:31"
    },

    /* 3. psych — 5 维心理画像 (本次新增) */
    "psych": {
      "axes": {
        "competitive_style": "攻击型",    // 4 选 1, 见 kb/profile_axes.json
        "comm_style":        "独立型",
        "pressure_response": "高峰",
        "motivation_type":   "表现",
        "tilt_profile":      "易燃"
      },
      "adolescent_traps": ["T1", "T3"],   // T1~T6 多选, 见 adolescent_traps.jsonl
      "interventions_ok": ["数据展示", "重构 reframe", "短句鼓励"],
      "interventions_no": ["人身攻击", "讲大道理", "和高手比较"],
      "axes_source":      "auto_inferred", // manual / auto_inferred / mixed
      "axes_confidence":  0.7,             // 0-1
      "axes_updated_at":  "2026-05-13T..."
    },

    /* 4. auto — regen-profiles 自动算 (历史聚合) */
    "auto": {
      "games_total":   155,
      "wr_total":      0.523,
      "games_with_me": 155,
      "wr_with_me":    0.523,
      "premade_score": 1.0,
      "top_champs":    [{"cid": 141, "name": "影流之镰", "games": 10, "wr": 0.6}, ...],
      "recent_form":   {"last_n": 10, "wins": 8, "wr": 0.8, "trend": "hot"},
      "generated_at":  "2026-05-12T17:33:17"
    }
  }
}
```

### 字段保留规则 (重要)

| 字段类 | regen 时怎么处理 |
|---|---|
| manual + persona | **永不覆盖**, 手填永远是真相 |
| psych.axes | 保留旧值; `axes_source` 控制下次能否被 AI 重推 |
| auto | **整体重算**, 永远是最新 |

---

## 3. psych_state.json — 动态心理状态

文件: `data/players/<puuid>/psych_state.json`. 每次 `regen-profiles` 覆盖写入。

```json
{
  "_v": 1,
  "puuid": "<puuid>",
  "updated_at": "2026-05-13T11:08:44",
  "_patch": "14.22",

  "form": {
    "l10":         ["W","L","W","W","L","L","L","W","L","W"],
    "wr_l10":      0.5,
    "wr_l30d":     0.48,
    "decay_score": 0.42         // exp(-i/3) 加权胜率, 越近的局权重越高
  },

  "streak": {
    "now":               -2,    // 负=连负, 正=连胜
    "longest_loss_l30d": -5,
    "longest_win_l30d":  4
  },

  "tilt": {
    "score": 0.51,              // 0-1, 综合
    "level": "moderate",        // calm | mild | moderate | severe
    "components": {
      "streak_factor": 0.4,     // streak 贡献
      "form_factor":   0.5,     // 近 10 局胜率贡献
      "decay_factor":  0.2      // 加权胜率衰减贡献
    }
  },

  "mood_inference":    "上头中, 倾向冲动决策",   // 规则版生成的 mood 标签
  "signals":           ["近 3 局连败", "加权胜率持续下滑"],
  "self_efficacy_hint": "low",   // high | mid | low
  "social_risk":        "watch"  // none | watch | alert
}
```

### tilt_score 公式

```
streak_factor = min(1.0, max(0, -streak_now) / 5.0)
form_factor   = 0   if wr_l10 >= 0.7
                1   if wr_l10 <= 0.3
                (0.7 - wr_l10) / 0.4   线性插值
decay_factor  = 1 - decay_score   if decay_score < 0.5  else 0

tilt_score = 0.5 * streak_factor + 0.3 * form_factor + 0.2 * decay_factor
```

### tilt level 阈值 (按 tilt_profile 校准)

| tilt_profile | mild | moderate | severe |
|---|---|---|---|
| 易燃 | 0.25 | 0.45 | 0.65 |
| 慢热 | 0.35 | 0.55 | 0.75 |
| 钝感 | 0.45 | 0.65 | 0.85 |
| 自调节 | 0.35 | 0.55 | 0.75 |
| (未定) | 0.3 | 0.5 | 0.75 |

---

## 4. psych_timeline.jsonl — 成长曲线监控

文件: `data/players/<puuid>/psych_timeline.jsonl`. 状态变化才追加, 不变不写。

```jsonl
{"_v":1, "_ts":"...", "_patch":"14.22", "kind":"first_seen", "level":"calm", "wr_l10":0.5}
{"_v":1, "_ts":"...", "_patch":"14.22", "kind":"tilt_level", "from":"calm", "to":"mild", "context":{...}}
{"_v":1, "_ts":"...", "_patch":"14.22", "kind":"self_efficacy", "from":"high", "to":"low", "context":{...}}
{"_v":1, "_ts":"...", "_patch":"14.22", "kind":"streak_flip", "from":3, "to":-2, "context":{...}}
```

### 监控的变化 kind

| kind | 触发 |
|---|---|
| `first_seen` | 第一次有 psych_state |
| `tilt_level` | tilt level 跨档 (calm↔mild↔moderate↔severe) |
| `self_efficacy` | self_efficacy_hint 变化 |
| `streak_flip` | streak 跨越 0 且变化 ≥ 2 局 |

未来可扩展:
- `axes_change` — manual 修改 axes
- `top_champ_shift` — 主玩英雄发生变化
- `comm_style_drift` — 沟通模式演变

### 用途

- **可视化成长曲线** (前端图表, 规划中)
- **训练数据筛选** — "玩家 X 上升期" vs "下降期" 用不同样本
- **回顾性教练发言** — "你 30 天前是 severe tilt, 现在 mild, 这是真进步"

---

## 5. coach/history.jsonl — 教练发言流水 (SFT 训练源)

每次 `coach_build()` 调用都追加一行。包含完整 context, 离线训练时不用反查别处。

```jsonl
{
  "_v": 1,
  "_ts": "2026-05-13T...",
  "_patch": "14.22",
  "context": {
    "stage":     "champ_select",
    "my_puuid":  "...",
    "game_id":   123456789,
    "core_name": "朋友A",
    "core_champ": "影流之镰",
    "core_score": 87.5,
    "verdict":   "AD 过载 · 无前排坦克",
    "advice":    "刺客切后 + 拉扯节奏 · 需硬控接应 + 视野压制",
    "warnings":  ["⚠ 全员无前排"],
    "mates_brief": [{"name":"...", "champ":"...", "is_me":false}, ...]
  },
  "mates_psych": [        // 关键: 每个 mate 的心理快照, LLM 训练时直接当 ctx
    {
      "name": "朋友A",
      "axes": {"competitive_style":"攻击型", ...},
      "tilt_score": 0.42,
      "tilt_level": "mild",
      "mood": "略上头, 留意",
      "signals": ["近 3 局连败"],
      "interventions_ok": [...],
      "interventions_no": [...],
      "self_voice_excerpt": "我玩 Kayn 就要红色形态切人头啊...",
      "peer_voices_excerpts": ["顺风一打五的核武"]
    }, ...
  ],
  "voice_pre":  "本局指挥棒交给 朋友A (影流之镰, 87 分). 刺客切后 + 拉扯节奏 ...",
  "voice_psych": ["无前排阵容, 不要硬冲..."],
  "coach_name": "鹤哥",
  "coach_voice": "幽默但毒舌, 偶尔骂醒, 关键时刻温柔"
}
```

### 如何转 SFT 训练样本 (chat format)

```python
# 给任意底座 (Claude/GPT/Qwen) 通用
for row in read_jsonl("coach/history.jsonl"):
    sft_sample = {
        "messages": [
            {"role": "system",   "content": COACH_SYSTEM_PROMPT(row["coach_name"], row["coach_voice"])},
            {"role": "user",     "content": json.dumps({
                "context":     row["context"],
                "mates_psych": row["mates_psych"],
            }, ensure_ascii=False)},
            {"role": "assistant", "content": row["voice_pre"] + "\n" + "\n".join(row["voice_psych"])}
        ]
    }
```

---

## 6. coach/feedback.jsonl — DPO 偏好对源

用户点 👍/👎/✏️ 改写后追加。

```jsonl
{
  "_v": 1,
  "_ts": "...",
  "_patch": "14.22",
  "ref":     "123456789|champ_select",   // 对应 history 里的 ref
  "rating":  "edit",                      // good | bad | edit
  "rewrite": "兄弟连负 3 把别上了, 喝口水", // rating=edit 时填
  "comment": "",
  "snapshot": {                            // 被评价的发言原文
    "pre_game": "...",
    "psych":    [...]
  },
  "my_puuid": "..."
}
```

### 转 DPO 训练样本

```python
for row in read_jsonl("coach/feedback.jsonl"):
    if row["rating"] == "edit":
        dpo_sample = {
            "context":  row["snapshot"],
            "chosen":   row["rewrite"],          // 用户改写 = 更好
            "rejected": row["snapshot"]["pre_game"]  // AI 原版 = 较差
        }
```

---

## 7. KB 条目 schema (用于 RAG / 训练 KB-aware)

见 `data/coach/kb/psychology/_index.json` 的 `schema_field_map`. 通用结构:

```json
{
  "_v":      1,
  "id":      "tilt.running_bad.01",
  "category": "tilt_types",
  "subtype":  "running_bad",
  "title":    "运势 tilt — 连续黑车",
  "summary":  "...",
  "trigger": {
    "psych_state":   {"streak_now": {"max": -3}, "form": {"wr_l10": {"max": 0.35}}},
    "axes_match":    {"tilt_profile": ["易燃", "慢热"]},
    "signals_any":   ["连败", "黑车"],
    "context_hint":  "champ_select | in_game | 局后"
  },
  "intervention": {
    "tone":              "温柔",
    "primary_voice":     "{name} 连负 {streak_abs} 局了, ...",
    "alt_voice_aggressive": "...",
    "behavior_suggestion": "强制 5 分钟离屏",
    "follow_up_check":   "10 分钟后再问情绪自评"
  },
  "do":   ["承认运气不好", "客观数据展示"],
  "dont": ["归罪玩家", "讲大道理"],
  "evidence": [{"source": "Tendler 2011", "ref": "..."}],
  "tags": ["tilt", "streak", "early_intervention"]
}
```

### RAG 检索流程

```python
def find_kb_entries(psych_state, axes, voice_text=""):
    matches = []
    for entry in iter_all_kb():
        if _trigger_matches(entry["trigger"], psych_state, axes, voice_text):
            matches.append(entry)
    return sorted(matches, key=lambda e: _priority(e))[:3]   # top 3
```

---

## 8. 整体 prompt 组装 (给 LLM 底座)

LLM 替换模板版教练时, 完整 prompt:

```
[SYSTEM]
你是 LoL ARAM 教练 AI, 人设: {persona.name} - {persona.voice}.

你的风格示例: {persona.style_examples}.
你要做的: {persona.do}
你不要做的: {persona.dont}

⚠️ 在生成任何回复前, 先扫描用户消息和最近发言, 如果触发以下任何关键词:
    {crisis_signals.md L3 关键词}
立即切到危机模式, 推送热线, 不再生成游戏建议.

[USER]
当前选人情境:
  我方阵容: {mates_brief}
  AI 阵容评估: {arch}

每个队友的心理画像 (axes + state + persona):
{mates_psych}

可参考的 KB 条目 (按相关性 top 3):
{kb_matches.top3}

请用 {persona.voice} 的语气给一句话本局指挥 (pre_game) + 0-3 句心态提醒 (psych).
遵循每个 mate 的 interventions_ok/no.

[ASSISTANT]
...
```

---

## 9. 演化策略 (给开发者 / 其他 AI 底座维护者)

### 加新 KB 条目
1. 选 `kb/psychology/<category>.jsonl` (或新建 file)
2. 用上述 schema 写新行
3. `evidence` 字段写出处 (学术/书籍/职业战队实践), **不能是 AI 编的**
4. 测试 trigger 字段在哪些 psych_state 会被命中
5. 不必加版本号, 加条目就行

### 修 schema
1. 改 `_v` 递增
2. 在 `_index.json/schema_field_map` 说明字段
3. 老 v=1 数据通过 parser 路由继续读

### 切换 AI 底座
- **Claude / GPT (API)**: 直接把 `_index.json` + 当下 trigger 命中的 KB 条目当 system prompt
- **本地 LLM (Qwen / Llama via vllm)**: 用 RAG 向量化每条 KB entry, 推理时检索 top-3
- **微调小模型**: 用 `coach/history.jsonl` + `feedback.jsonl` → SFT + DPO (见上面转换代码)

### 加新心理学维度
1. 在 `profile_axes.json/axes` 加新轴 (或在 adolescent_traps 加新 trap)
2. 在 `_index.json` 同步说明
3. 现有 axes_source = "auto_inferred" 的 profile, 跑一次 `infer-psych-axes` 重推

### 多语言
- 现有 voice_templates 是中文
- 加 `voice_templates_en` 字段做英文版
- KB schema 不变

---

## 10. CLI 工具汇总 (与本 schema 相关)

```bash
# 重算 auto + psych_state
python rankprobe_lite.py regen-profiles

# 推断 psych axes (生成 AI prompt)
python rankprobe_lite.py infer-psych <puuid> > prompt.md
# 把 prompt.md 喂给 Claude/GPT → 拿到 response.json
python rankprobe_lite.py merge-psych <puuid> response.json

# 写 persona (自然语言)
python rankprobe_lite.py set-self <puuid>            # stdin
python rankprobe_lite.py add-peer <puuid> "..."

# 通用 AI prompt (用于历史画像 / 长文档生成)
python rankprobe_lite.py ai-prompt <puuid> [--persona] > prompt.md
python rankprobe_lite.py merge-profile <puuid> response.json
```

---

## 11. 边界 (Hard Constraints)

- ❌ 不做临床心理治疗 — 触发 crisis_signals L3 必须推热线
- ❌ 不存 crisis 触发的发言到 SFT 训练集
- ❌ 不让 AI 给医学建议
- ✅ 持续审计 — 定期人审 coach/history 和 feedback, 改进 KB
- ✅ 多 AI 底座可移植 — schema 通用, 不绑定 vendor
