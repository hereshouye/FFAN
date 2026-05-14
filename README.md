# FFAN

**大乱斗本地选人助手 + 鹤哥 AI 教练** · 单文件 · 仅 Windows · 客户端只读 · 数据全本地

> ⚠️ 非 Riot 官方产品 · 可能违反 Riot 服务条款, 风险自担. 详见 [DISCLAIMER.md](DISCLAIMER.md).

---

## 下载

👉 **[FFAN.exe (最新版)](https://github.com/hereshouye/FFAN/releases/latest)** · ~8.5 MB · 双击即用

所有历史版本: [Releases](https://github.com/hereshouye/FFAN/releases)

---

## 怎么用

1. 双击 `FFAN.exe` (同目录会自动建 `data/`)
2. 启动后浏览器自动开 http://127.0.0.1:6280/
3. 打开英雄联盟客户端 → 进选人 → 自动弹出教练点评 / 队友画像 / 海克斯推荐
4. 首次使用先点顶栏「**更新数据**」(下字典, ~5 分钟, 仅第一次)

游戏开始后, 底部抽屉持续显示对局历史, 可补写每局复盘 / 编辑队友画像。

源码运行:
```
python rankprobe_lite.py
```

---

## 怎么贡献数据 (帮鹤哥变聪明)

完全 **opt-in**, 不勾就不传:

1. 教练发言下面有 👍 / 👎 / ✏️ 改写 按钮 — 旁边勾选「**贡献到训练集**」
2. 累积的脱敏样本存在本地 `data/contributed/`
3. 在 💝 贡献面板点「**导出 JSON**」
4. 把那个 JSON 通过 [GitHub Issue (训练贡献模板)](https://github.com/hereshouye/FFAN/issues/new?template=contribution.yml) 发给我

样本里已经做了 PII 脱敏 (puuid → sha256, 无玩家名). 你随时可在面板点「撤回同意」/「清空」。

也可以**导出问卷给朋友答** (Modal → 🧪 快测人格 → 📤 导出问卷), 朋友本地用浏览器答完, 把 JSON 回传你导入即可。

完整规则: [CONTRIBUTING.md](CONTRIBUTING.md)

---

## 文档跳转

| 想看什么 | 去哪 |
|---|---|
| 完整免责 / 隐私 / Riot 法律 | [DISCLAIMER.md](DISCLAIMER.md) |
| AI 能做和不能做 | [BOUNDARIES.md](BOUNDARIES.md) |
| 未来规划 / 训练数据闭环 | [ROADMAP.md](ROADMAP.md) |
| 玩家画像 schema | [PROFILES.md](PROFILES.md) |
| 教练 schema | [COACH.md](COACH.md) |
| 5 轴心理画像 schema | [PSYCH_SCHEMA.md](PSYCH_SCHEMA.md) |
| 贡献 / 反馈 / 报 bug | [CONTRIBUTING.md](CONTRIBUTING.md) · [Issues](https://github.com/hereshouye/FFAN/issues) |
| 许可证 | [MIT](LICENSE) |

---

## 危机时刻

软件不能替代专业帮助。如果你正在经历严重情绪危机:

- 北京心理危机研究与干预中心 **010-82951332** (24h)
- 希望 24 热线 **400-161-9995** (24h)
- 国际: <https://www.iasp.info/resources/Crisis_Centres/>

---

*FFAN isn't endorsed by Riot Games. League of Legends © Riot Games, Inc.*
