# FFAN

**大乱斗 (ARAM / KIWI)** 本地选人助手 + 鹤哥 AI 教练 — 单文件 / 零依赖 / 仅 Windows / 客户端只读。

---

> ## ⚠️ 法律与合规声明 / Legal & Compliance Notice
>
> **请在使用前完整阅读 [DISCLAIMER.md](DISCLAIMER.md) 与 [BOUNDARIES.md](BOUNDARIES.md). 下载/使用即视为已知悉并同意全部条款.**
>
> - 🚫 **非 Riot Games 官方产品**. 本项目与 Riot Games 无任何隶属、赞助、认可关系. "League of Legends" / "英雄联盟" / "ARAM" 等商标归 Riot Games, Inc. 所有.
> - 🛡️ **仅通过 LCU 只读访问**. 不发任何写操作 / 不修改客户端 / 不绕过反作弊 / 不替玩家执行任何游戏内操作.
> - ⚖️ **使用本工具可能违反 Riot 服务条款**. 风险由使用者自担, 作者不承担因封号/限号等导致的任何损失. 如果你的账号特别重要请不要使用.
> - 🧠 **AI 教练仅提供运动心理学层面的参考建议**. 不是临床心理治疗工具, 不是医疗设备, 不能替代心理咨询师或精神科医生. 出现严重情绪问题请立即拨打专业危机热线 (见 DISCLAIMER §3).
> - 🔒 **数据完全本地**. `data/` 目录不出本机. 任何对外通信均为可选、用户主动触发, 且已在文档中明列.
> - 📜 **MIT 协议** ([LICENSE](LICENSE)). 软件按"AS IS"提供, 不附带任何明示或暗示的保证.
>
> *English version of all notices is included in [DISCLAIMER.md](DISCLAIMER.md). Both languages are provided; English controls for legal interpretation.*

---

```
python rankprobe_lite.py
# 浏览器打开 http://127.0.0.1:6280/
```

启动后:
- 检测到客户端 → 顶栏绿点, 进入选人阶段后自动展开
- 检测不到 → 灰点, 底部搜索框照常可用 (查英雄海克斯推荐 / 海克斯说明)

> 这个项目同时是一个**面向 AI 教练训练**的数据底座。看 [ROADMAP.md](ROADMAP.md) 了解未来规划。

---

## 项目结构

```
rankprobe_lite.py          ← 主程序 (服务 + 服务 + 工具一体)
ROADMAP.md                 ← 未来规划 (AI 教练能力路线图)
PROFILES.md                ← 玩家画像 schema 文档
COACH.md                   ← AI 教练 schema 文档
web/                       ← 前端 (SSE 实时推送)
  index.html
  styles.css
  app.js
tools/
  cache_official_augments.py     ← 下载 KIWI augment 字典 (CommunityDragon)
  cache_hex_recommendations.py   ← 爬 apexlol.info 海克斯推荐
data/                      ← 用户数据 (v2 布局, 见下)
```

---

## 数据架构 (v2 · 2026-05)

按事务分目录, 不按时间。每类数据有清晰的归宿:

```
data/
├── _VERSION                ← 布局版本号 (=2)
├── profiles.json           ← 玩家画像 (manual + persona + auto), 单一真相源
│
├── coach/                  ← AI 教练命脉 (训练数据闭环核心)
│   ├── persona.json        ← 教练人设 + 模板 (取代老 data/coach.json)
│   ├── history.jsonl       ← 每次发言流水 (SFT 训练源)
│   ├── feedback.jsonl      ← 用户 👍/👎/改写 (DPO 偏好对源)
│   ├── kb/                 ← 知识库 (RAG)
│   │   ├── psychology.md   ← 心理学原则手册 [规划中]
│   │   ├── champions_meta.jsonl  [规划中]
│   │   ├── items.jsonl     [规划中]
│   │   └── runes.jsonl     [规划中]
│   └── training_seeds/     ← 老报告作为冷启动种子 [规划中]
│
├── me/                     ← 我自己长期状态 (最新即真相)
│   ├── summoner.json
│   ├── ranked_stats.json
│   ├── ranked_timeline.jsonl  ← 每日段位序列 (情绪曲线根)
│   ├── champion_mastery.json
│   ├── friends.json        ← 社交图谱 (区分好友 vs 路人)
│   ├── honor_profile.json
│   └── last_champ_select.json ← 选人快照 (没 gid 时暂存)
│
├── games/                  ← 每局一文件夹, 训练抽样天然
│   ├── _index.jsonl        ← 每局 1 行, 全局索引
│   └── <gid>/
│       ├── detail.json         ← raw LCU match detail
│       ├── timeline.json.gz    ← raw timeline (gzip ~10x)
│       ├── normalized.json     ← 单局聚合 {game, participants}
│       ├── champ_select.json   ← 选人快照 (局后归位)
│       └── eog.json            ← 局后结算块 (LCU 实时页)
│
├── players/                ← 玩家长期状态 (puuid 直接顶级)
│   └── <puuid>/
│       ├── summoner.json
│       ├── ranked.json
│       └── psych_state.json    [规划中: 滚动 tilt/streak/form]
│
├── assets/                 ← 静态字典 [规划中: 提升到顶级]
│
└── _cache/                 ← 老 v1 兼容目录 (assets/hex 还活着, normalized 仅 regen 读)
    ├── assets/                 ← 英雄字典 / KIWI augment 字典 (lite 读这里)
    ├── hex_recommendations/    ← apexlol 推荐 (lite 读这里)
    ├── normalized/             ← 老聚合 jsonl (regen-profiles 还在写&读)
    └── players/                ← 老 player cache (新数据写 data/players/)
```

### 资源、画像、事实、产出 — 四类分离

| 类别 | 位置 | 是否增长 | 什么时候被改 |
|---|---|---|---|
| **资源** (字典/知识库) | `_cache/assets/`, `_cache/hex_*/`, `coach/kb/` | 静态 (refresh 覆盖) | 「更新数据」按钮 / patch 变化 |
| **画像** (谁是谁) | `profiles.json`, `players/<puuid>/`, `me/` | 慢 (按人) | 选人/局后采集, 手动 persona 编辑 |
| **事实** (对局原始) | `games/<gid>/` | 线性 (按对局) | 每场局后 collect_match_history |
| **产出** (教练发言/反馈) | `coach/history.jsonl`, `coach/feedback.jsonl` | 按使用 | 每次选人 / 用户按按钮 |

### 数据带 patch tag

所有 jsonl 行通过 `_write_jsonl_v2()` 写入, 自动加上 `_v` (schema 版本) / `_ts` (写入时间) / `_patch` (当时游戏版本) 三个 tag。训练时按 patch 切片可避免老 balance 改动污染新版本推荐。

---

## 启动模式

| 命令 | 行为 |
|---|---|
| `python rankprobe_lite.py` | 正常模式: 启服务线程 + HTTP 服务, 等 LCU 上线 |
| `python rankprobe_lite.py --demo` | 演示模式: 不连 LCU, 从 `data/` 最新快照构造 STATE |
| `python rankprobe_lite.py regen-profiles` | 重算 `data/profiles.json` (保留手填字段) |
| `python rankprobe_lite.py ai-prompt <puuid> [--persona]` | 输出给外部 AI 的 prompt 模板 |
| `python rankprobe_lite.py merge-profile <puuid> <ai_response.json>` | 把 AI 返回合并到 profile |
| `python rankprobe_lite.py set-self <puuid>` | stdin 写 persona.self_voice |
| `python rankprobe_lite.py add-peer <puuid> "<text>"` | 追加一条 persona.peer_voices |
| `python rankprobe_lite.py clear-peers <puuid>` | 清空 peer_voices |

---

## 界面元素

**顶栏**: 状态点 (绿/灰) + phase + 「更新数据」云朵按钮 + 「调试 ▲」抽屉。

**选人时**显示 5 张卡:
1. 我 (头像 / 段位 / 选定英雄 / 本英雄近期胜率)
2. **AI 教练点评** — 一句话本局指挥棒 + 心态提醒 + **👍 / 👎 / ✏️ 改写** 反馈按钮
3. 队友 (英雄头像 + 名字 + tag徽章 + 该英雄历史胜率, 点击编辑画像)
4. AI 阵容架构 (AD/AP/坦/辅 分布 + 一句话评语 + **本局核心** + 风险点)
5. 海克斯推荐 (apex 的 SS/A 级搭配)

**选人结束**: 卡片转为"上一局"复盘模式, 等待下一次选人 (不会瞬间清空)。

**底部**: 搜索框, 输入英雄名/英文 alias/海克斯名实时查。

---

## AI 教练训练数据闭环

这是 v2 架构的核心新增能力 —

```
1. 选人 happens
   ↓
2. Coach.coach_build() 生成发言
   ↓
3. 自动 append → data/coach/history.jsonl  [SFT 训练源]
   ↓
4. 用户点 👍/👎/✏️ 改写
   ↓
5. POST /api/coach/feedback → data/coach/feedback.jsonl  [DPO 偏好对]
   ↓
6. 离线 build_training_set.py 组装 → sft.jsonl / dpo.jsonl  [规划中]
   ↓
7. 微调 Qwen/Llama → 新模型部署回 runtime  [规划中]
```

教练每次发言的 context 也存在 history.jsonl 里 (本局核心、阵容架构、警告、队友状态), 离线训练时不用反查别处。

详见 [ROADMAP.md](ROADMAP.md)。

---

## 更新缓存

点击顶栏「更新数据」云朵, 后台:
1. 跑 `tools/cache_official_augments.py refresh` (下载 KIWI augment 字典, ~200 条)
2. 跑 `tools/cache_hex_recommendations.py refresh` (爬 apexlol.info, 5+ 分钟, 200+ 英雄)
3. 重读两个 JSON + `data/profiles.json` + `coach/persona.json`, 覆盖式更新内存字典 (不删除字典本体)

进度在调试抽屉里实时打印。

---

## 玩家画像

见 [PROFILES.md](PROFILES.md). 简版要点:
- `data/profiles.json` 是单一真相源
- 一个 puuid 一条, **manual** (手填) + **persona** (自然语言长文本, 训练用) + **auto** (自动算) 三组字段
- `python rankprobe_lite.py regen-profiles` 重算 auto 字段, 永不覆盖 manual / persona
- 选人时**热重载**, 改完保存即生效
- 「本局核心」按 `carry_score` 排序得出, 公式见 PROFILES.md

### 写 persona (3 种方式)

1. **浏览器**: 点队友卡片 → 弹出 modal → 写 self/peer → 保存
2. **CLI**: `python rankprobe_lite.py set-self <puuid>` 然后 stdin 输入
3. **直接编辑**: 改 `data/profiles.json` 里的 `persona.self_voice` / `persona.peer_voices`

---

## 数据沿用 (老 data/ 兼容)

老 v1 数据**不强制迁移**, 直接当参考存在:
- `data/_cache/assets/` (英雄字典等) — 主程序仍读这里
- `data/_cache/hex_recommendations/` — 仍读这里
- `data/_cache/normalized/*.jsonl` — `regen-profiles` 仍读, 但**新对局已写入 `data/games/<gid>/`** + 维护 normalized jsonl 兼容
- `data/YYYY-MM-DD/` 日快照 — 冻结当参考, 新服务不再写
- `data/coach.json` (老) — `load_coach()` 优先读 `coach/persona.json`, 没有就回退到老路径

---

## 配置 (环境变量)

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROBE_PORT` | 6280 | HTTP 监听端口 |
| `PROBE_PHASE_POLL` | 5 | 闲时 phase 轮询秒数 |
| `PROBE_CS_POLL` | 3 | 选人阶段轮询秒数 |
| `PROBE_WAIT_CLIENT` | 8 | 客户端未启动时的等待秒数 |
| `RANKPROBE_DATA_DIR` | (自动) | tools/cache_*.py 找 data 目录的环境变量, exe 模式必需 |

---

## 依赖

- Python 3.8+
- Windows (LCU 进程发现用 Win32 ctypes; 非 Windows 上脚本能跑但服务永远等不到客户端)
- **没有 pip 包依赖**

---

## 限制

- 仅 LCU 只读, 不发任何写操作给客户端
- 仅大乱斗模式调优 (经典 5v5 / 极地大乱斗的 lane 概念已移除)
- 海克斯/装备图标暂未本地化 (英雄头像走 CommunityDragon CDN)

---

## 打包成 exe (PyInstaller)

### 快速打包

```
build.bat
```

或手动:
```
pip install pyinstaller
pyinstaller build.spec --clean --noconfirm
```

### 输出结构

```
dist/FFAN/
├── FFAN.exe
├── _internal/                  ← Python 运行时 + web/ + tools/
└── (data/ 由首次启动时自动创建 v2 骨架)
```

### 分发方式

整个 `dist/FFAN/` 目录复制给用户。用户双击 `FFAN.exe` 启动。

**首次启动时:**
- 自动创建 `data/` 顶级骨架 (coach/, me/, games/, players/, assets/)
- 写默认 `data/profiles.json` (空) 和 `data/coach/persona.json` (内置默认人设)
- 写 `data/_VERSION = 2`
- 浏览器打开 http://127.0.0.1:6280/ 引导用户点「更新数据」下载字典 (5+ 分钟)

### 兼容老 data 架构

老用户拿到新 exe, 老的 `data/` 目录里:
- `_cache/assets/`, `_cache/hex_recommendations/` → 主程序仍读, 不需要重下
- `_cache/normalized/*.jsonl` → `regen-profiles` 仍读, 让 11+ 条画像不丢
- `coach.json` (顶级) → 自动被新 `coach/persona.json` 接管 (优先后者)
- `YYYY-MM-DD/` → 冻结当参考, 新数据写 `games/<gid>/`

第一次启动后, 命令行跑一次:

```
FFAN.exe regen-profiles
```

### 路径感知

代码用 `getattr(sys, "frozen", False)` 检测 PyInstaller 环境:

| 模式 | ROOT | DATA_DIR | WEB_DIR / TOOLS_DIR |
|---|---|---|---|
| 开发 (python rankprobe_lite.py) | 脚本目录 | ROOT/data | ROOT/web, ROOT/tools |
| 冻结 exe | exe 同级目录 | exe/data | bundle/web, bundle/tools |

`tools/cache_*.py` 通过 `RANKPROBE_DATA_DIR` 环境变量拿到正确的 data 路径。

---

## 抗风险设计

| 风险 | 抵抗机制 |
|---|---|
| 新英雄/装备没字典 | 显示 raw ID + patch detector 自动触发 KB refresh [规划中] |
| LoL balance 改动 | 数据带 patch tag, 训练按 patch 切片 |
| 玩家段位/风格漂移 | 多窗口 (recent_form / alltime) + persona_history [规划中] |
| LCU 字段重命名 | schema_version 路由 (老行用老 parser) |
| 网络/CommunityDragon 失败 | Fallback 链: 本地缓存 → 内嵌 → online → 显示 raw [规划中] |
| 突发崩溃 | atomic write (tmp.replace) + append-only jsonl |
| 老 data/ 不兼容 | v1 路径仍读, 新数据走 v2, 不强制迁移 |

更多细节见 [ROADMAP.md](ROADMAP.md) "抗风险" 章节。

---

## 第三方资源与归属 / Third-Party Resources & Attribution

| 资源 | 来源 | 用途 | 许可 |
|---|---|---|---|
| 英雄字典 (`champion-summary.json`) | [CommunityDragon](https://www.communitydragon.org/) | 英雄名称/角色映射 | Riot 官方静态资源镜像, 公开 |
| KIWI augment 字典 | [CommunityDragon](https://www.communitydragon.org/) | 海克斯英文/中文翻译 | 同上 |
| 海克斯推荐快照 (`apexlol_data.json`) | [apexlol.info](https://apexlol.info) | 海克斯组合社区数据 | 第三方公开页面解析快照, 仅本地离线参考 |

**心理学知识库引用** (见 `bundle_defaults/coach/kb/psychology/*` 各条 `evidence` 字段):
Tendler · Dweck · Beck · Burns · Ericsson · Csikszentmihalyi · Steinberg 等公开学术作品的**概念性转述与电竞场景应用**, 不复制原文. 完整清单见 [DISCLAIMER.md §6](DISCLAIMER.md).

---

## Riot Games 法律声明 / Riot Legal Jibber Jabber

**中文**:
FFAN 不是 Riot Games 官方产品, 也未获得 Riot Games 认可. Riot Games, 以及所有相关属性, 均为 Riot Games, Inc. 的商标或注册商标. 英雄联盟 © Riot Games, Inc.

**English**:
FFAN isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties, are trademarks or registered trademarks of Riot Games, Inc.

---

## 报告问题 / Reporting Issues

- 一般 bug / 功能反馈: [GitHub Issues](https://github.com/hereshouye/FFAN/issues) (请使用对应模板)
- 安全漏洞 / 隐私问题 / 心理学 KB 错误: 请使用 **GitHub Security Advisory** 私下报告, 不要直接发 Issue
- 严重危机 (自伤念头、严重抑郁): 请**立即**拨打专业热线, 不要等待软件回应
  - 北京心理危机研究与干预中心: **010-82951332** / 800-810-1117 (24h)
  - 希望 24 热线: **400-161-9995** (24h)
  - 国际: https://www.iasp.info/resources/Crisis_Centres/

---

## 许可 / License

[MIT](LICENSE). Copyright (c) 2026 FFAN contributors. Software provided AS IS, without warranty of any kind.
