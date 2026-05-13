# FFAN AI 教练 — `data/coach.json`

把死板的 ARCH_ADVICE 查表换成**有人设、有语气**的输出层。
教练是输出方，玩家 (`profiles.json`) 是被分析对象，**两者分离**。

---

## 文件位置

```
data/coach.json
```

启动时 `load_coach()` 把它读进内存的 `COACH` dict。选人时**热重载**（改完保存即生效）。

---

## Schema

```jsonc
{
  // 教练身份
  "name":  "鹤哥",
  "voice": "幽默但毒舌, 偶尔骂醒, 关键时刻温柔",

  // 给后期 LLM 当 few-shot 示范
  "style_examples": [
    "兄弟这英雄稳了, 你别上头",
    "心态炸了? 喝口水, 这局我帮你过",
    "你 Kayn 4-0 别浪, 等队友再开团"
  ],
  "do":   ["指出客观问题", "鼓励但不浮夸", "适度调侃", "用真人语气"],
  "dont": ["人身攻击", "无意义吹捧", "讲废话", "重复模板"],

  // 规则版输出 (无 LLM, 当前实现)
  "templates": {
    "pre_game_with_core":
      "本局指挥棒交给 {core_name} ({core_champ}, {core_score:.0f}分). {advice}",
    "pre_game_no_core":
      "5 个英雄看着都不太硬核, 各打各的吧, 别上头梭哈.",
    "pre_game_me_core":
      "兄弟你是本局 carry, {core_champ} {core_score:.0f}分, {advice} 队友配合你打.",
    "psych_cold":
      "{name} 最近手有点冷 ({recent_wr:.0f}% last10), 让他先 farm 点好处.",
    "psych_no_frontline":
      "无前排阵容, 不要硬冲. 先让 ADC/AP 站后排消耗, 看到敌方先手再反打.",
    "psych_assassin_pile":
      "刺客一堆? 这种阵容拖后期容易散, 速战速决, 见人就秒."
  }
}
```

---

## 模板占位符 (`{var}`)

| 变量 | 含义 |
|---|---|
| `{core_name}` | 本局核心玩家昵称 (carry_score 最高那位) |
| `{core_champ}` | 本局核心的英雄中文名 |
| `{core_score}` | 本局核心的 carry_score |
| `{core_role_zh}` | 中文定位 (射手/法师/坦克...) |
| `{advice}` | `ARCH_ADVICE` 表给出的 1 句建议 |
| `{verdict}` | 阵容评语 (`AD/AP 均衡` 等) |
| `{warning_count}` | 阵容警告条数 |
| `{name}` (psych 模板) | 队友昵称 |
| `{recent_wr}` (psych_cold) | 最近 10 局胜率 % |

格式串支持 `:.0f` 等 Python format 语法。**缺 key 不抛**，模板 fallback 为原文。

---

## 模板选择逻辑

```
pre_game:
  if 没有 core:               → pre_game_no_core
  elif core 是我:              → pre_game_me_core (if 定义)
  else:                       → pre_game_with_core

psych (返回 0-3 条):
  · 每个 trend=cold 的队友:    → psych_cold
  · 阵容有 "无前排" 警告:        → psych_no_frontline
  · 阵容有 "刺客过多" 警告:      → psych_assassin_pile
```

---

## 教练的 4 个维度

| 维度 | 当前 (阶段 1) | 阶段 2 (TODO) |
|---|---|---|
| **赛前指导** | ✅ pre_game 模板, 显示在 UI「AI 教练点评」卡 | LLM 接入版本 |
| **队友心理辅导** | ✅ psych 数组, 显示在 UI「心态提醒」 | 监控对局中的 KDA 跌幅触发 |
| **赛后复盘** | ⚠ TODO (需要 EOG 探针接回) | post_win / post_loss 模板 + sessions/ |
| **总结数据** | ⚠ TODO (需要 timeline.jsonl) | weekly_summary 模板 |

---

## 维护方式

### A. 修改人设 (最常见)

直接编辑 `data/coach.json` 的 `name` / `voice` / `style_examples` / `do` / `dont`。
保存即生效 (选人时热重载)。

### B. 改/加模板

```jsonc
"templates": {
  "pre_game_with_core": "你的新模板...{core_name}...",
  "your_new_template":  "..."   // 自由添加, 在 Python 端用 _fmt 触发
}
```

### C. 想接 LLM (阶段 2/3)

当前规则版的 `coach_say_pre_game()` 是入口。要换成 LLM:

```python
def coach_say_pre_game(arch, my_puuid=""):
    # 1. 构造 system prompt: 从 COACH['voice'] + style_examples + do/dont 生成
    # 2. 构造 user prompt: arch 序列化 (核心/警告/阵容分布) + profiles 摘要
    # 3. 调 LLM (Anthropic/OpenAI/本地 Ollama)
    # 4. 返回 LLM 输出
    return llm_chat(system, user)
```

输入输出格式不变, UI 端无需改动。

---

## 训练数据导出 (远期)

`coach.json` 本身就是 LLM 训练数据的一部分:

- `voice` + `style_examples` → SFT 的 system prompt / few-shot
- `templates` 每条 → (context, expected_output) 对，可生成训练样本
- 后期 `timeline.jsonl` 里的 (context, coach_output, user_feedback) 可训练 DPO

设计上,**任何 LLM 底座** (Claude/GPT/Qwen/Llama) 都可消化 coach.json - 字段全是 JSON 基础类型, 无私有结构。

---

## FAQ

**Q: 改 coach.json 需要重启吗?**
A: 不需要。选人时热重载 (每次进 ChampSelect)，浏览器刷新就看到新台词。

**Q: 教练显示在哪?**
A: 选人界面顶部 (我自己卡片下面) 的「🎙️ AI 教练点评」卡。心态/警告显示在橙色区块。

**Q: 不要心理辅导栏怎么办?**
A: 删 coach.json 里所有 `psych_*` 模板，或编辑 UI 隐藏 `.coach-psych`。

**Q: 多个教练人设可以切换吗?**
A: 当前只读一个 `coach.json`。你可以备份成 `coach_friendly.json` / `coach_savage.json`, 用 shell 切换:
```bash
cp data/coach_savage.json data/coach.json
# 浏览器刷新即变身
```

**Q: pre_game 输出永远是一行?**
A: 模板可以包含 `\n`, JSON 里写 `"...\n..."` 即可换行。前端 `<div class="coach-voice">` 有 `white-space:pre-wrap`。
