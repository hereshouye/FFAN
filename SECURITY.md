# 安全策略 / Security Policy

## 支持版本 / Supported Versions

只对 [最新 Release](https://github.com/hereshouye/FFAN/releases/latest) 提供安全修复. 老版本不再回溯.

## 报告漏洞 / Reporting a Vulnerability

**请勿在公开 Issue 中披露安全漏洞**. 公开披露可能导致用户在补丁发布前被攻击.

请通过 [GitHub Security Advisory](https://github.com/hereshouye/FFAN/security/advisories/new) 私下报告. 这个渠道:

- 仓库维护者会收到通知
- 你和维护者可以在私有空间讨论细节
- 修复后可一键发布 CVE + 致谢

### 报告时请尽量包含

- 受影响版本 / 平台
- 复现步骤 (最小复现脚本最佳)
- 实际影响 (数据泄漏 / 远程代码执行 / 拒绝服务 / ...)
- 你建议的修复方向 (可选)

### 响应承诺 (best-effort, 非合同义务)

| 严重程度 | 首次回应 | 计划修复 |
|---|---|---|
| 严重 (远程读用户数据 / API key 泄漏 / LCU token 利用) | 7 天内 | 14 天内出 patch release |
| 中 (本地权限提升 / DoS) | 14 天内 | 下一个 minor release |
| 低 (信息泄漏 / 日志噪音) | 30 天内 | 看情况合入 |

本项目是单人业余维护, 上面是"努力目标"不是 SLA. 严重问题作者不在线时可能延迟.

## 范围 / Scope

### 在范围内 / In scope

- `rankprobe_lite.py` 主程序及 `tools/` 下脚本
- `web/` 前端 (XSS / CSRF / 注入)
- `bundle_defaults/` 静态资源 (含未脱敏临床案例 = 安全问题)
- PyInstaller 打包脚本 (`build.spec`) 中的 hiddenimports / datas
- 训练贡献流程的 PII 处理

### 不在范围内 / Out of scope

- Riot Games 反作弊 / 客户端漏洞 (找 Riot 报)
- 你本机其他软件被攻击 — FFAN 仅本地监听 6280 端口
- 社会工程 / 仿冒 FFAN 的钓鱼站 (找 GitHub Abuse Team)
- 第三方依赖 (CommunityDragon, apexlol) — 找对应上游

## 数据 / Data

FFAN 不会上传你的任何数据到任何远端服务. 如果你发现 FFAN 主动外联到本文档未明列的域名, 视为**严重安全问题**, 请立即按上述渠道私下报告.

明列允许的外联 (均由用户主动触发):
- `raw.communitydragon.org` — 字典刷新 ("更新数据"按钮)
- `apexlol.info` — 海克斯推荐刷新 ("更新数据"按钮)
- 用户自配的 LLM API endpoint (`data/llm_config.json`) — AI 战报模式

## 致谢 / Credit

合规披露的安全研究者可在 release notes 中获得致谢 (除非你要求匿名).
