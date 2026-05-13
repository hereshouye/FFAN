# 贡献指南 / Contributing to FFAN

> **提交任何贡献前, 请先完整阅读 [DISCLAIMER.md](DISCLAIMER.md) 与 [BOUNDARIES.md](BOUNDARIES.md).**
> 提交 PR / Issue / 训练数据 即视为已阅读并同意全部条款.

---

## 0. 范围声明 / Scope

**FFAN 接受的贡献类型**:
- 🐛 Bug 修复 (任何模块)
- ✨ ROADMAP 上已列出方向的新功能
- 📚 心理学 KB 条目 (需附 `evidence` 字段, 概念性引用, 不复制原文)
- 🎨 UI / 文档改进
- 🧪 训练数据 (走 [训练贡献 issue 模板](.github/ISSUE_TEMPLATE/contribution.md))

**FFAN 拒绝的贡献类型** (会被直接关闭):
- ❌ 任何自动化游戏操作 (dodge / ban / pick / 移动 / 战斗)
- ❌ 任何对 LCU 的写操作
- ❌ 任何绕过/对抗反作弊机制的代码
- ❌ 服务化 / 云同步 / 多用户后端
- ❌ 跨平台 UI 移植 (Mac/Linux/Web)
- ❌ 直接复制商业心理学/体育教材原文
- ❌ 含真实玩家 PUUID / 召唤师名 / 真人姓名 的测试数据或截图
- ❌ 修改 `DISCLAIMER.md` / `BOUNDARIES.md` 的核心条款 (除非真正发现错误)

---

## 1. 法律前提 / Legal Preconditions

### 1.1 许可
本项目采用 **MIT 协议** ([LICENSE](LICENSE)). 提交 PR 即视为你同意:
- 你贡献的代码在 MIT 协议下发布
- 你对自己贡献的代码享有版权或获得了原作者授权
- 你的贡献不侵犯任何第三方专利、版权、商标、商业机密

### 1.2 心理学 KB 条目
所有提交到 `bundle_defaults/coach/kb/psychology/*` 的内容必须:
- 是**概念性转述**, 不是原文复制 (避免侵犯出版商版权)
- 在 `evidence` 字段标注理论来源 (如 "Tendler 2011 framework, conceptual application")
- 应用于电竞场景, 而非作为临床心理治疗建议

### 1.3 训练数据贡献
通过 [训练贡献 issue](.github/ISSUE_TEMPLATE/contribution.md) 上传 JSON 即视为:
- 自愿贡献, 无对价
- 数据已脱敏 (puuid → sha256[:12], 无召唤师名/真名)
- 授予项目维护者永久、不可撤销、免版税的使用权 (仅限 LoL 教练 AI 训练/衍生发布/学术研究)
- 你保留对原始本地数据的所有权; 合入训练集后无法单条撤销

### 1.4 Riot ToS
FFAN 工作在 Riot ToS 灰区. 贡献者须确认:
- 你的代码不增加违反 ToS 的风险面 (不写操作, 不修改客户端, 不绕过反作弊)
- 你不会以 FFAN 名义对外宣称 Riot 授权/认可

---

## 2. 开发流程 / Development Flow

### 2.1 起步
```bash
git clone https://github.com/hereshouye/FFAN.git
cd FFAN
python rankprobe_lite.py --demo    # 用内置 demo 数据启动, 不需要 LoL 客户端
# 浏览器开 http://127.0.0.1:6280/
```

### 2.2 改代码前
- 先在 Issue 中讨论你的方案 (避免做无用功)
- 单 PR 单关注点, 不要在一个 PR 里塞多个无关改动

### 2.3 测试
- 跑 `python -c "import ast; ast.parse(open('rankprobe_lite.py', encoding='utf-8').read())"` 确保语法正确
- 跑 `python rankprobe_lite.py --demo` 确保启动不崩
- UI 改动: 至少在 demo 模式下手动验证浏览器渲染正常

### 2.4 提 PR
- 标题用 [中括号] 前缀分类: `[bug]` / `[feat]` / `[doc]` / `[kb]` / `[ui]`
- 描述里说明: 解决了什么问题 / 怎么改的 / 有没有破坏性变更
- PR 描述末尾确认: "我已阅读并同意 CONTRIBUTING.md 全部条款"

---

## 3. 行为准则 / Code of Conduct

- 友善、专业、就事论事
- 不接受人身攻击、歧视性语言、骚扰
- 不要在公开 issue 中讨论真人玩家 (姓名/账号)
- 不要诊断任何人的心理问题 — FFAN 不是医疗工具, 贡献者也不是医生
- 维护者保留关闭/删除任何违反上述准则内容的权利

---

## 4. 报告安全/隐私问题 / Reporting Security Issues

**不要**在公开 Issue 中报告以下类型的问题:
- API 密钥泄漏 / 凭据泄漏
- 用户数据可被远程读取的漏洞
- LCU token 处理缺陷
- 心理学 KB 中含未脱敏的真实临床案例

请使用 [GitHub Security Advisory](https://github.com/hereshouye/FFAN/security/advisories/new) 私下报告.

---

## 5. 联系方式

- 一般问题: [GitHub Issues](https://github.com/hereshouye/FFAN/issues) (走对应模板)
- 安全/隐私: [Security Advisory](https://github.com/hereshouye/FFAN/security/advisories/new)
- 严重心理危机: 不要等待软件回应, 请立即拨打专业热线 (见 [DISCLAIMER §3](DISCLAIMER.md))
