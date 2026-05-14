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
通过 [训练贡献 issue](.github/ISSUE_TEMPLATE/contribution.yml) 上传 JSON 即视为:
- 自愿贡献, 无对价
- 你**对该数据享有合法权利**, 不含未授权第三方信息 (朋友真名 / 召唤师名 / 他人评价 / 他人 PUUID 等)
- 数据已脱敏 (puuid → sha256[:12], 无召唤师名/真名)
- 授予项目维护者**永久、不可撤销、免版税、非独占**的使用权 (仅限 LoL 教练 AI 训练 / 衍生模型发布 / 学术研究)
- 你保留对原始**本地**数据的所有权; 合入训练集后无法单条撤销

**关于 GDPR / PIPL 删除请求** (重要 — 技术限制声明):
- 你可随时要求维护者删除你贡献的**原始 JSON 样本**, 维护者承诺收到请求后 30 日内从所有存档中删除
- 但**已基于该样本训练完成的模型权重**, 由于神经网络的不可逆训练过程, **无法回滚或定向擦除**
- 这一限制是当前 AI 训练技术的客观属性, 非维护者拒绝履约
- 提交贡献即视为知悉并接受此限制. 如不接受, **请不要提交**

### 1.4 Riot ToS
FFAN 工作在 Riot ToS 灰区. 贡献者须确认:
- 你的代码不增加违反 ToS 的风险面 (不写操作, 不修改客户端, 不绕过反作弊)
- 你不会以 FFAN 名义对外宣称 Riot 授权/认可

### 1.5 二次开发 / 分发 / 商业化 (Fork & Redistribute)

MIT 协议允许你 fork / 修改 / 重新分发 / 商业使用 FFAN. 但**为避免责任混淆**, 二次开发者必须遵守:

**强制要求 (违反者请勿使用本项目代码)**:
- ✅ **必须改名**. 衍生作品不得继续叫 "FFAN" / "鹤哥" / "FFAN AI Coach" 或任何足以引起混淆的名称
- ✅ **必须在显著位置 (README 顶部 / 关于页) 注明**: "基于 FFAN 开发, 原项目: https://github.com/hereshouye/FFAN (MIT)"
- ✅ **必须移除或替换**原项目的联系方式 (Issue 链接 / Security Advisory 链接 / 危机热线引导联系信息) — 用你自己的或删除
- ✅ **必须移除或重写** `DISCLAIMER.md` / `BOUNDARIES.md` / `SECURITY.md` 中提及"原作者"的部分 — 你是新的作者, 你自己负责
- ✅ **必须保留** `LICENSE` 文件 + 原版权声明 (MIT 标准要求)

**责任划分**:
- 🛡️ 衍生作品造成的任何问题 (封号 / 心理伤害 / 数据泄漏 / 第三方诉讼) **完全由衍生作品的维护者承担**, 与原 FFAN 作者无关
- 🛡️ 衍生作品的用户**不得**通过原 FFAN 的 Issue / Security Advisory / 联系渠道寻求支持. 原作者保留直接关闭此类 Issue 的权利, 不予回应
- 🛡️ 若衍生作品被发现违反上述强制要求 (尤其是"必须改名"), 原作者可发函要求修正; 拒不修正者, 原作者可公开声明该衍生作品**未经认可**并保留进一步法律权利

**不希望但允许的行为**:
- ⚠️ 商业化售卖衍生作品 — MIT 允许, 但请确保你的用户清楚知道这不是原 FFAN
- ⚠️ 闭源衍生 — MIT 允许, 但请注意你仍需要在分发物里包含原 MIT LICENSE 文件
- ⚠️ 训练你自己的模型 — 可以, 但若你使用了原 FFAN 训练贡献者的数据, 你必须独立向那些贡献者获得授权 (原项目获得的授权不能转授)

**明确禁止**:
- ❌ 冒用 FFAN 名义在外宣传 / 拉投资 / 拉用户
- ❌ 把衍生作品的崩溃 / 封号 / 退款问题反向引导到原 FFAN 仓库
- ❌ 在衍生作品中保留原作者的真实身份信息后, 让用户误以为原作者背书该衍生作品

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
