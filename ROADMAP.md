# FFAN 未来规划 (ROADMAP)

> 目标: 把 FFAN 从一个**选人助手**演化成一个**AI 教练训练底座**, 具备四项能力:
> 1. 心理专家 (画像 + 安抚 + diss + 专项训练指导)
> 2. 数据复盘 (准确、专业的报告)
> 3. 自然语言人设 + 真人评价
> 4. LoL 专业知识 (装备/符文/连招/版本)

---

## 当前进度 (Sprint 1, 2026-05 已完成)

| 项目 | 状态 |
|---|---|
| v2 数据布局 (coach/me/games/players) | ✅ 代码已写, 新数据按 v2 落盘 |
| `_write_jsonl_v2()` 自动加 `_v/_ts/_patch` tag | ✅ |
| `coach/history.jsonl` 自动记录每次发言 | ✅ |
| `coach/feedback.jsonl` 用户反馈端点 + UI | ✅ 👍/👎/✏️ |
| `me/ranked_timeline.jsonl` 段位时间序列 | ✅ |
| `me/friends.json` 社交图谱采集 | ✅ |
| `games/<gid>/timeline.json.gz` raw timeline | ✅ |
| README 反映 v2 架构 | ✅ |
| **训练贡献 (opt-in)**: `data/contributed/` + 4 个端点 + 浮动面板 | ✅ v2 payload 带 context (画像/局势/人设) |

**Sprint 1 的核心成果**: 教练每次发言都进 history, 用户每次按按钮都进 feedback. **从今天起, 每一局都在为训练攒数据**.

**Sprint 1 增量 (2026-05-13)**: 加上"训练贡献"机制 — 单台电脑数据要半年才够训练, 走 opt-in 通道汇集后能跨越冷启动. 详见 [intro.html#contribute](intro.html) "为什么千人千面是优势" 一节.

---

## Sprint 2: 知识库 + 心理学先验 (1~2 周)

目标: 让教练**有知识可调用**。

### 任务

| 编号 | 任务 | 输出 | 估时 |
|---|---|---|---|
| S2.1 | `tools/cache_lol_kb.py` 爬 CommunityDragon | `coach/kb/champions_meta.jsonl`, `items.jsonl`, `runes.jsonl` | 4 h |
| S2.2 | 手写心理学原则手册 (借助 Claude/GPT 起草, 人审) | `coach/kb/psychology.md` (~50 条) | 2 h |
| S2.3 | 老 11 篇 daily report.md + `report_human_analysis.md` 入 `coach/training_seeds/` (复制, 不动原文件) | seed 样本 12+ | 30 min |
| S2.4 | 把 KB 内容暴露给 `/api/kb/search?q=...` (RAG 用) | HTTP 端点 | 1 h |
| S2.5 | Coach 模板支持 `{kb:champion(7)}` / `{kb:item(3084)}` 占位符, 渲染时查 KB | Coach class | 2 h |

### 验收

- `coach/kb/` 至少有: 168 英雄 meta, 250+ 装备, 70+ 符文
- 心理学手册 50 条原则覆盖: 连败干预、上头识别、安抚话术、carry 局调度
- 教练发言能引用 KB 内容 (例: "Kayn 的强势期在 11~16 分钟" 来自 champions_meta)

---

## Sprint 3: 心理状态滚动 + 抗风险机制 (1 周)

目标: 让画像**会随时间变化**, 让系统**抗版本/抗异常**。

### 任务

| 编号 | 任务 | 输出 |
|---|---|---|
| S3.1 | `players/<puuid>/psych_state.json` 计算 (regen-profiles 顺手算) | `{form_l10, tilt_score, streak_now, mood_inference}` |
| S3.2 | 多窗口画像: `top_champs_30d` vs `top_champs_alltime` | profiles.json auto 字段 |
| S3.3 | `coach/persona_history/<puuid>.jsonl` (persona 改动追加, 不丢老版本) | 写入逻辑 |
| S3.4 | `players/<puuid>/events.jsonl` 段位升降标记 | append on detect |
| S3.5 | `Circuit` 熔断类 + 包装所有 collector + 爬虫 fallback 链 | rankprobe_lite.py |
| S3.6 | Patch detector + `/api/health` 端点 + 调试抽屉状态条 | runtime + UI |

### 抗风险设计原则 (新代码必须遵守)

1. **Append-only > overwrite** — 老版本永远可回滚 (persona / KB / model output)
2. **Tag everything** — 时间 + patch + schema 版本, 没标的数据未来用不了
3. **Manual > auto, auto recomputable** — 手填永远不被自动覆盖
4. **Fail soft, log loud** — 一个 collector 挂不影响别的; **每次失败必须在调试抽屉可见**
5. **Schema is data** — 老 schema 数据通过 parser 路由, 不强制迁移
6. **Reversible migrations** — 任何 migration 留 `data/legacy/` 备份

### 验收

- 连败 3+ 局自动触发 `mood_inference: "上头中, 建议降火"`
- patch 升级 → `/api/health` 标红 KB 落后版本
- apexlol 关站时教练仍能讲话, 只是没了海克斯推荐文本

---

## Sprint 4: 训练管线 (2 周)

目标: 把攒到的数据**真的能训出模型**。

### 任务

| 编号 | 任务 | 输出 |
|---|---|---|
| S4.1 | `tools/build_training_set.py` 组装 chat 格式 | `train/sft.jsonl` |
| S4.2 | 从 `feedback.jsonl` 抽取 (good vs bad) 对 | `train/dpo.jsonl` |
| S4.3 | 冷启动: 用 Claude/GPT few-shot 当老师, 生成 1000 条历史复盘 | `train/cold_start_sft.jsonl` |
| S4.4 | LoRA 微调脚本 (Qwen2.5-7B / Llama-3-8B) | `tools/finetune.py` |
| S4.5 | 离线评估集 + 评估脚本 | `tools/eval_coach.py` |

### 数据流闭环

```
[runtime]
  champ_select → coach.speak() → log to coach/history.jsonl
  user 点 👍/👎/✏️ → coach/feedback.jsonl

[offline 周期性 (每周一次)]
  build_training_set.py 读:
    coach/history.jsonl + coach/feedback.jsonl
    + profiles.json + players/<puuid>/psych_state.json
    + coach/kb/*
  → 组装:
       system: coach/persona.json 人设 + KB 摘要
       user:   情境快照 (画像 + 阵容 + 心理状态)
       assistant: voice (good 样本)
  → train/sft.jsonl, train/dpo.jsonl

[训练]
  - 攒到 1000+ history + 100+ feedback: LoRA 微调 Qwen2.5-7B
  - 攒到 5000+: 上 DPO
  - 部署回 runtime, 替换 Coach._fmt() 的模板调用
```

### 验收

- `tools/build_training_set.py` 跑出 ≥ 1000 条 SFT 样本 (含冷启动)
- DPO 对至少 100 对
- 微调后的小模型在离线评估集上比模板版准确率 +15%

---

## Sprint 5: 后期能力 (3+ 周, 探索性)

### 5.1 实时复盘 (post-game review)

- 局后从 `games/<gid>/timeline.json.gz` 解析关键事件
- 教练讲 "你在 12:34 死亡 + 失了大龙, 应该 X" 这类话
- UI 加局后复盘卡 (替代选人卡显示)

### 5.2 多模型底座支持

- 抽象 `CoachBackend` 接口: `TemplateBackend` (现在的) / `ClaudeBackend` / `LocalLLMBackend`
- `data/coach/backend.json` 配置选哪个
- LocalLLMBackend 走 llama.cpp / vllm

### 5.3 训练数据导出 / 联邦学习 (Sprint 1 已起步)

**已完成 (2026-05-13)**:
- `/api/contribute/*` 4 个端点 + 浮动 💝 贡献面板
- 单条反馈勾选即写 `data/contributed/feedback_<ts>.json` (v2 schema 含 context)
- PIPL 合规四件套: 显式同意 / 可撤回 / 可导出 / 可删除
- PII 脱敏: puuid → sha256[:12], 不收召唤师名/真名

**后续**:
- `tools/import_contributions.py` 合并多个用户上传的 bundle → 统一训练池
- 按 `_patch` 字段切片, 避免跨版本污染
- 按 anon_id 计算每个贡献者的覆盖度, 避免少数人主导风格
- 个人模型 = 通用模型 + 个人 LoRA (个人那条线路由 self_voice + 自己的 feedback 微调)

### 5.3.1 蒸馏路线 (按样本量)

| 样本量 | 训练方法 | 期望效果 |
|---|---|---|
| < 500 | 仅用于验证 schema | 不蒸馏 |
| 500-2K | SFT on Qwen2.5-7B / Llama-3-8B (LoRA) | 风格 ≈ 鹤哥, 泛化弱 |
| 2K-5K | + DPO (good vs bad 偏好对) | ≈ Claude 在 LoL 垂域水平 |
| 5K-10K | + 用户原型聚类 LoRA | 真千人千面本地模型 |
| > 10K | 发 Hugging Face | LoL 教练 baseline 提供者 |

参照: LIMA 用 1K 高质量样本达到 GPT-3.5 水平. 我们领域更窄, 数据需求上限更低.

### 5.3.2 为什么"千人千面"是优势

模型学的是 **f(玩家画像, 局势, 人设) → 回复** 的条件函数, 不是单一映射. 1000 个不同条件下的好回复, 教会模型**在条件 C 下风格应为 R** 的泛化能力. 这就是 ChatGPT 同一模型既能辅导小学生也能聊拓扑的原理. 详见 intro.html #contribute 一节.

### 5.4 高级心理学能力

- 团队心态分析 (5 人情绪交叉项)
- 对手画像 (从历史 details 里挖)
- 比赛日 vs 平日的状态差异检测

---

## 长期愿景 (6+ 月)

```
FFAN 不只是"选人助手", 而是:

  [LCU 探针 + 数据底座]
       ↓
  [训练管线: 个人化教练模型]
       ↓
  [运行时: 真人语气的 AI 教练]
       ↓
  [闭环: 用户反馈不断改进模型]
```

最终交付:
- 一个**懂你的**教练 (画像 + 历史 + 风格)
- 一个**有专业知识**的教练 (LoL KB + 心理学先验)
- 一个**会成长**的教练 (反馈闭环 + 持续微调)
- 一个**抗变化**的教练 (patch / 玩家漂移 / 接口变更 都不崩)

---

## 优先级哲学

每个 Sprint 的取舍标准:

1. **数据闭环 > 单点能力** — 没数据再厉害的模型也喂不动 (这就是为什么 Sprint 1 优先做)
2. **可演化 > 一次到位** — 接口 / schema / persona 都允许版本化, 老数据永远能用
3. **真人能审 > 全自动** — manual / persona / feedback 都让用户能干预
4. **冷启动可用 > 最优** — 没微调好之前, 模板 + RAG 也能讲出有用的话

---

## 不会做的事 (反向清单)

避免 scope creep:

- ❌ **写功能模式分析** — 这个 LCU 不会给, 也不是教练重点
- ❌ **作弊功能** (强制 dodge / 自动 ban 等) — 仅只读, 永远不发写操作
- ❌ **服务化 / 多用户后端** — 单机本地, 隐私优先 (训练贡献是用户手动上传, 不是自动云同步)
- ❌ **跨平台 UI** — Windows 限定, 不投入 Mac/Linux UI
- ❌ **大乱斗以外模式深度优化** — 单双排可读可显示, 但教练 / 阵容分析仅大乱斗调优
- ❌ **手写 LoL 数据爬虫维护** — 用 CommunityDragon 官方导出, 不爬 op.gg / u.gg

---

## 当前可立刻贡献的事

如果你 (或我) 现在有 30 分钟空, 可以挑一个开搞:

| 任务 | 估时 | 收益 |
|---|---|---|
| 写 50 条心理学原则 (Claude 起草 + 人审) → `coach/kb/psychology.md` | 30 min | 教练立刻有专业语料 |
| `tools/cache_lol_kb.py` 爬 CommunityDragon items.json | 45 min | 装备 KB 立刻可查 |
| `players/<puuid>/psych_state.json` 计算 (单纯加在 regen-profiles 里) | 60 min | 教练能讲"队友手冷"的依据 |
| `tools/build_training_set.py` MVP (只读 history.jsonl, 输出 sft.jsonl) | 90 min | 至少能看到训练数据长啥样 |

每攒到一个 milestone 就 commit 一次, 不要憋大改动。
