# page-debug

Claude Code 的浏览器调试 Skill。UI 自动化测试失败时，在 Claude Code 内交互式定位根因并修复。

## 解决什么问题

UI 自动化测试失败后，传统的排查方式存在几个痛点：

- **复现成本高** — 需要手动重复登录、跳转、填表单等前置步骤，才能到达失败时的页面状态
- **上下文丢失** — 测试跑完浏览器就关了，看不到失败那一刻页面上到底有什么
- **排错效率低** — 靠看截图和日志猜原因，无法实时检查 DOM、执行 JS、查看网络请求
- **修复后无法即时验证** — 改了选择器后要重跑整个测试才能确认，迭代周期长

page-debug 通过在失败行前注入断点，让测试脚本自己跑完前置步骤，精准停在失败前一刻。然后通过 CDP 协议接管浏览器，让你在 Claude Code 中像 DevTools 一样实时检查页面状态、验证选择器、尝试操作，直到定位根因。

## 快速开始

### 环境要求

| 依赖 | 安装方式 |
|------|---------|
| Python 3.8+ | 系统安装 |
| `playwright` | `pip install playwright` |
| `websocket-client` | `pip install websocket-client` |
| Chromium | `playwright install chromium` |

```bash
pip install -r requirements.txt
playwright install chromium
```

### 安装 Skill

将 `page-debug` 目录复制到你的 Claude Code 项目的 `.claude/skills/` 下，然后在 `.claude/settings.json` 中注册：

```json
{
  "skills": {
    "page-debug": {
      "enabled": true,
      "path": ".claude/skills/page-debug/SKILL.md"
    }
  }
}
```

### 使用

测试失败后，在 Claude Code 中粘贴错误信息，或直接说"帮我调试这个测试"。Agent 会自动：

1. 读取失败的测试脚本，定位失败行
2. 注入断点，后台启动测试，停在失败前一刻
3. 接管浏览器，宣布进入交互调试模式

随后你可以在对话中要求 Agent 检查页面、执行 JS、验证选择器，直到找到根因。

## 调试中可以做什么

进入交互模式后，你可以让 Agent：

- 检查某个元素是否存在于 DOM 或可访问性树中
- 执行任意 JavaScript 查看元素属性、样式、位置
- 查看浏览器控制台的错误和警告
- 查看网络请求，排查 API 问题
- 手动操作页面（点击按钮、输入文本、导航到其他 URL）

每次操作后 Agent 会汇报结果，继续等你下一个指令。找到根因后，Agent 会修改测试脚本并帮你验证。

## 支持的框架

| 框架 | 状态 |
|------|------|
| Python / pytest + Playwright | 完整支持 |
| Java / JUnit + Maven + Playwright | 断点注入可用，CDP 配置需指定 browser launch 位置 |
| 其他 | 通用模式（按语言插入阻塞点），CDP 需手动配置 |

CDP 桥接层与测试语言无关——只要 Chrome 浏览器携带 `--remote-debugging-port` 参数启动，page-debug 就能接管。

## 项目结构

```
page-debug/
├── SKILL.md                       # Skill 定义（Agent 行为指令）
├── README.md                      # 本文档
├── requirements.txt               # Python 依赖
├── scripts/
│   └── debug_breakpoint.py        # 断点注入器 + CDP 桥接引擎
├── references/
│   ├── failure-taxonomy.md        # 测试失败分类与诊断策略
│   └── layered-debugging.md       # 分层架构项目的穿透追踪方法
├── scripts/
│   ├── debug_breakpoint.py        # 断点注入器 + CDP 桥接引擎
│   └── adapters/                  # 框架适配器
└── docs/
    ├── design.md                  # 架构设计与关键技术决策
    ├── environment-decoupling.md  # 环境解耦：如何做到跨机器可移植
    ├── multi-framework.md         # 多语言/多框架适配方案
    ├── robustness.md              # 鲁棒性设计：脆弱点与自愈机制
    └── usability-design.md        # 易用性设计：交互协议与信息架构
```

## License

MIT
