# FFAN 玩家画像 — `data/profiles.json`

为大乱斗 (ARAM / KIWI 模式) 选人推荐设计的玩家画像文件。
**目的**: 把客观历史数据 (胜率/常用英雄/双排关系) 和主观人工标注 (性格/标签/拿手/自我评价) 合并到一个 JSON, 用于:

1. 选人界面实时显示队友标签 + 双排标识 + 自评 tooltip
2. 「本局核心」打分 (`carry_score` 公式见下)
3. 后期喂给 AI / 底座模型做训练或推理 (字段已扁平、命名稳定)

---

## 文件位置

```
data/profiles.json
```

字典顶层 key = LCU 暴露的 **puuid** (玩家唯一 ID), 加上一个保留键 `_meta`。

---

## Schema (v1.0)

```jsonc
{
  "_meta": {
    "format_version": "1.0",
    "generated_at": "2026-05-12T17:09:17",   // 最近一次 regen 时间
    "my_puuid": "78539098-...",              // 本机用户
    "min_games_with_me": 3,                  // regen 阈值
    "premade_threshold": 0.6,
    "count": 11
  },

  "<puuid>": {
    /* ───── manual (短结构化, UI 展示用; regen 保留, 永不覆盖) ───── */
    "nickname":      "朋友A",         // 显示名 (LCU 在线时被 LCU 名字覆盖)
    "self_role":     "jungle",          // 自评主玩位置: adc/ap/assassin/tank/support/jungle
    "self_desc":     "刺客 carry, 走脸专精",  // 短摘要 (20 字), tooltip 第一行
    "tags":          ["carry","上头"],  // 短标签数组, 第一个会展示在卡片角徽章
    "peer_review":   "顺风一打五, 逆风一秒钟",  // 短摘要 (40 字), tooltip 第二行
    "habits":        "找机会越塔, 大招换血",
    "skill":         "S",               // S/A/B/C/D 主观水平
    "carry_priority": 9,                // 0~10, 围绕他打的优先级 (打分加权)
    "favorite_champ_ids": [141, 7, 91, 245],  // 拿手英雄 cid 数组, 命中 +15 分
    "premade_with":  ["78539098-..."], // 默认双排/三排队友 puuid (auto + 可手填)

    /* ───── persona (自然语言, AI 训练语料用; manual 的扩展, regen 保留) ───── */
    "persona": {
      "self_voice": "我玩 Kayn 就要红色形态切人头啊, 蓝形态那种慢慢A的没意思. 看到能切的就切, 不上头不带打的. 团战找机会切后排, 顺风我可以一打五给你 carry 到飞起, 不过逆风心态偶尔会炸.",
      "peer_voices": [                  // 字符串数组, 多视角评价
        "这哥们儿玩刺客挺有数的, 双排首选",
        "顺风一打五的核武, 逆风心态炸的时候请躲远",
        "和他打 ARAM 基本不输, 团战切人有节奏"
      ],
      "updated_at": "2026-05-12T17:33:31"
    },

    /* ───── auto: 自动生成 (regen 时全量覆盖) ───── */
    "auto": {
      "name_from_history": "朋友A",
      "tag_from_history":  "33272",
      "games_total":       155,         // 该 puuid 在我历史里的全部局数
      "wins_total":        81,
      "wr_total":          0.523,       // 0~1
      "games_with_me":     155,         // 和我同队的局数 (子集 of games_total)
      "wins_with_me":      81,
      "wr_with_me":        0.523,
      "premade_score":     1.0,         // cooccurrence 里的 premade_score
      "top_champs": [                   // 该 puuid 全期常用前 5 英雄
        {"cid": 141, "name": "影流之镰", "games": 10, "wins": 6, "wr": 0.6},
        {"cid": 876, "name": "含羞蓓蕾", "games": 9,  "wins": 6, "wr": 0.667},
        ...
      ],
      "recent_focus": [                 // 最近 30 天 top 3 (当前在练什么)
        {"cid": 141, "name": "影流之镰", "games": 5, "wins": 3, "wr": 0.6}
      ],
      "recent_form": {                  // 最近 10 局连胜/连败趋势
        "last_n": 10, "wins": 7, "losses": 3, "wr": 0.7,
        "trend": "hot"                  // hot >=70%, cold <=30%, normal, unknown(<5局)
      },
      "generated_at": "2026-05-12T17:09:17"
    }
  }
}
```

### 字段分组规则

| 类型 | 关键词 | 长度 / 形式 | regen 行为 |
|---|---|---|---|
| **manual** (短摘要) | self_desc / peer_review / tags / habits / skill / carry_priority / favorite_champ_ids | 短结构化 | 保留, 不动 |
| **manual** (布线) | premade_with | puuid 数组 | 合并: 自动加 + 手填都保留 |
| **persona** (自然语言) | self_voice / peer_voices | **长文 / 数组**, 第一人称 + 第三人称 | 保留, 不动 |
| **auto** (客观) | auto.* | 数字 / 数组, 机器算 | 全量覆盖 |

### manual 与 persona 的关系

- **manual** 字段: 短归短, 但 UI **第一眼就能看到** (卡片徽章 + tooltip 第一行)
- **persona** 字段: 长归长, 用来**记录真人的说话语气和人设**, 留给后期 AI 训练用
- 两者**并存**, 不互斥. manual 是 persona 的浓缩版, persona 是 manual 的展开版.

---

## 维护工作流

三种场景, 按需选用:

### A. 日常: 客观数据自动刷新

打完几局, 想更新胜率/常用英雄/最近状态:

```bash
python rankprobe_lite.py regen-profiles
```

只读 `data/_cache/normalized/`, 不上网, 不动手填字段。
更新 `auto.*` (含 `recent_focus` 和 `recent_form`)。

> ℹ️ 注意: 现版本的 `rankprobe_lite.py` 不会自动写 normalized 数据。
> 已有的 `data/_cache/normalized/*.jsonl` 是旧探针留下的 (~310 局), regen 会读这部分。
> 想拿到最新对局, 暂时只能等老版本探针补回, 或后期为 lite 加一个 normalize 子命令。

### B. 手工调优: 主观字段编辑

直接编辑 `data/profiles.json`, 修改任意 **manual** 字段:

```jsonc
"e3df201e-...": {
  "tags": ["carry", "上头", "脾气大"],
  "carry_priority": 8,
  "favorite_champ_ids": [141, 7, 91],
  ...
}
```

保存即生效, **不用重启**, 浏览器刷新即看到。

### C. 人设语料 (persona) 维护

**为什么需要:** manual 的 self_desc/peer_review 只是 20-40 字摘要, 给 UI 用够了, 但**不够 AI 训练**。
persona 是放真人原话和自然语气的语料库, 后期可以拿来 fine-tune 一个能"说像他"的模型。

#### 方式 1: 浏览器里点击队友卡片 (最快)

选人时 (或 demo 模式), **点击任意队友卡片**会弹出编辑框:
- 「他人评价 (追加)」: 写一段自然语言, 保存追加到 `persona.peer_voices`
- 「第一人称自评 (覆盖)」: 写一段, 保存覆盖 `persona.self_voice`
- 当前已有的 persona 在弹窗顶部展示
- `Cmd/Ctrl+Enter` 快捷保存, `Esc` 关闭

写完保存 → 立即写入 `data/profiles.json` → SSE 推送 → 鼠标移开重悬停立刻看到新内容。

#### 方式 2: 命令行 (批量 / 脚本化)

```bash
PUUID=<这里填你想编辑的队友 puuid (从 data/profiles.json 查)>

# 1. 写第一人称自评 (多行 stdin, Ctrl+Z 结束 / Unix Ctrl+D)
python rankprobe_lite.py set-self $PUUID
> 我玩 Kayn 就要红色形态切人头啊...
> ^Z

# 或者一行 echo 管道直入
echo "我玩 Kayn 就要红色形态切人头啊..." | python rankprobe_lite.py set-self $PUUID

# 2. 追加一条 peer voice (自然语气)
python rankprobe_lite.py add-peer $PUUID "这哥们儿玩刺客挺有数的, 双排首选"
python rankprobe_lite.py add-peer $PUUID "顺风一打五的核武"

# 3. 清空 peer_voices (重来)
python rankprobe_lite.py clear-peers $PUUID
```

### D. AI 辅助批量生成

**两种 prompt 模式:**

```bash
# 模式 1: 生成 manual 短结构化字段
python rankprobe_lite.py ai-prompt $PUUID > prompt.md

# 模式 2: 生成 persona 自然语言语料
python rankprobe_lite.py ai-prompt $PUUID --persona > prompt.md
```

**完整步骤 (4 个命令):**

```bash
# 1. 选一个 puuid (用 regen-profiles 后, profile.json 里可以查)
PUUID=<这里填你想编辑的队友 puuid (从 data/profiles.json 查)>

# 2. 导出提示词 + 这个玩家的数据 (--persona 生成自然语言版)
python rankprobe_lite.py ai-prompt $PUUID --persona > prompt.md

# 3. 把 prompt.md 整段贴到 Claude / GPT / DeepSeek / 任意 LLM
#    LLM 输出一段 JSON, 你存成 ai_response.json (只保留 JSON 不要前后文)

# 4. 合并回 profiles.json (persona 在白名单内, 会被接受)
python rankprobe_lite.py merge-profile $PUUID ai_response.json
```

**merge-profile 的安全保证:**
- 只接受 `PROFILE_MANUAL_KEYS` 里的字段 (nickname / self_role / self_desc / tags /
  peer_review / habits / skill / carry_priority / favorite_champ_ids / premade_with)
- 其它字段 (auto, _meta, 未知字段) 会被忽略并提示
- 已有的 auto 字段保留不动

**批量处理:**
```bash
# bash 脚本: 对前 10 个 puuid 都生成
for puuid in $(python -X utf8 -c "import json; d=json.load(open('data/profiles.json',encoding='utf-8')); print('\n'.join(k for k in list(d)[:10] if not k.startswith('_')))"); do
    python rankprobe_lite.py ai-prompt $puuid > prompts/$puuid.md
done
```

然后把每个 prompts/*.md 喂给 LLM, 得到 ai_responses/*.json, 再批量 merge。

---

## 字段速查 / 怎么影响 carry_score

| 字段 | 类型 | 影响 |
|---|---|---|
| **manual** `tags` | [str] | 仅展示用 (卡片第一个 tag 显示为徽章) |
| **manual** `self_desc` | str | 鼠标悬停 tooltip 显示 |
| **manual** `peer_review` | str | 鼠标悬停 tooltip 显示 |
| **manual** `habits` | str | tooltip 显示 |
| **manual** `skill` | "S~D" | tooltip 显示, 不参与打分 |
| **manual** `carry_priority` | 0-10 | **直接加分** (整 0~10 都进 carry_score) |
| **manual** `favorite_champ_ids` | [int] | **+15 分** 如果他选了里面的英雄 |
| **manual** `premade_with` | [puuid] | 卡片 ★ premade 徽章 |
| **auto** `top_champs[].wr` | 0-1 | **客观胜率主分项** ±50, 当他选到这个 cid 时生效 |
| **auto** `wr_total` | 0-1 | 整体微调 ±10 |
| **auto** `recent_form.trend` | hot/cold | 热手 +8 / 手冷 -8 |
| **auto** `recent_focus` | [obj] | 不打分, 只展示在 tooltip 里给 AI 看 |

**调优经验:**
- 希望某玩家永远是核心 → `carry_priority: 9` + 拿手英雄全加 `favorite_champ_ids` (一拿就是核心)
- 不希望某玩家做核心 → `carry_priority: 0`
- 客观打分够准的话, 不填 manual 也能跑 (新队友默认 0 优先级)

---

## carry_score 计算公式

```
score = obj_wr  + obj_total + obj_mastery + obj_recent + sub_fav + sub_pri

obj_wr      = (该 puuid 在该英雄的历史 wr - 0.5) × 100      # 范围 ±50, 起算 3 局
obj_total   = (该 puuid 整体大乱斗 wr - 0.5) × 20           # 范围 ±10, 起算 30 局
obj_mastery = min(熟练度 / 100k × 25, 30)                  # 范围 0~30, 仅自己 (LCU 暴露)
obj_recent  = +8 if recent_form.trend=="hot"               # 最近 10 局热手加分
              -8 if recent_form.trend=="cold"              # 最近 10 局手冷减分
              0  otherwise
sub_fav     = 15 if cid ∈ favorite_champ_ids else 0
sub_pri     = carry_priority                                # 范围 0~10
```

**分数范围**: 约 -60 ~ +118。
排序后最高分 (> 5) 视为「本局核心」, 用其英雄的 primary role 查 `ARCH_ADVICE` 表生成阵容建议。

### 调优经验

- 想让某玩家在某英雄上一定当核心 → 把 cid 加进 `favorite_champ_ids` + `carry_priority` 设 9
- 想让某玩家永远不被选作核心 → `carry_priority` 设 0
- 客观数据不足 (新队友, 没历史) → 主观字段成为主要分数源

---

## AI / 模型训练接入

这个文件**设计上就准备好喂给 LLM 或训练任务**:
1. **格式扁平**: 顶层 puuid → manual + auto 两组字段, 没有深层嵌套
2. **命名稳定**: 字段名不会变, 版本变化只加字段不改名
3. **数据完整**: 一个 puuid 一条记录, 自包含, 不依赖外部 join

### 喂 LLM 时建议的 prompt 结构

```
你是大乱斗选人助手。基于以下 5 个队友画像, 输出 50 字以内的本局策略:

{ "team": [ <profile JSON 数组, 删掉 _meta>, ... ] }

要求:
1. 指出本局核心 (carry_priority + 该英雄历史 wr 加权)
2. 评估阵容架构 (AD/AP/坦/辅 分布)
3. 给一条可执行的开局建议
```

### 训练数据导出

将历史对局 + profile 标注合并:

```bash
# (TODO) 后续可加: python rankprobe_lite.py export-training-set --out training.jsonl
# 每行 = {profile_state, lineup, eog_result, ...}
```

---

## 与原项目的差异

- **原 `probe/advisor_personal.py`** 是 Python 字典 (硬编码), 改字段要改代码。
- **原 `data/notes.json`** 是浏览器内编辑的覆盖层, 字段不固定。
- **本 `data/profiles.json`** 是单一真相源, 自动 + 手工合一, 字段固定可机器读。

---

## FAQ

**Q: regen 会不会冲掉我精心写的 self_desc?**
A: 不会。manual 字段永远保留, 哪怕你删掉了 `auto` 整个字段, regen 也只重建 `auto`。

**Q: profiles.json 多大?**
A: 11 条画像约 8KB, 200 条画像约 100KB。不必担心体积。

**Q: 选人时每次都读 JSON 不慢吗?**
A: I/O 加 JSON 解析 < 1ms, 选人间隔是 3 秒级, 完全可以。

**Q: 我能不能给所有陌生人 (单排碰到的) 也存 profile?**
A: 可以, 但 regen 只收录和你同队过 ≥3 局的 puuid (减小文件)。你想全收就改 `min_games_with_me=1`。

**Q: 删掉一个 profile 后又遇到同一个人会怎样?**
A: 下次 regen 会重新加 auto 字段, 但 manual 字段是空的 (因为你手动删过)。

**Q: cooccurrence.jsonl 怎么来的?**
A: 原项目 `probe/normalize.py` 的产物。如果你之后只用 `rankprobe_lite.py` 跑探针, 不会自动更新这个文件 — 但已有的数据继续可用。后期可加一个 normalize 子命令补回。
