# 实时页面调试 Skill - 项目计划

## 概述
创建一个 Claude Code Skill，用户调用后即可通过自然语言与 Agent 对话，Agent 利用已有的 Playwright MCP 工具实时操控浏览器。无需额外平台或 MCP Server，纯 Skill 方案。

## 核心理念
- **一个 Skill** — 用户通过 `/实时页面调试` (或类似命令) 调用
- **对话驱动** — 用户用自然语言描述想做什么，Agent 理解并执行
- **实时可见** — 浏览器操作在用户屏幕上可见，Agent 截图反馈
- **零部署** — 利用已有的 Playwright MCP 工具，无需额外服务

## 工作流

```
用户: /实时页面调试
  ↓
Agent: "实时页面调试模式已启动。请告诉我你想做什么？"
  ↓
用户: "打开百度，搜索 Python 教程"
  ↓
Agent: 1) browser_navigate("https://www.baidu.com")
       2) browser_snapshot() 查看页面结构
       3) browser_type(搜索框, "Python 教程")
       4) browser_click(搜索按钮)
       5) browser_snapshot() + browser_take_screenshot() 展示结果
  ↓
Agent: "已完成。百度搜索 'Python 教程'，显示 N 条结果。需要点击某个结果吗？"
  ↓
用户: "打开第三个结果"
  ↓
Agent: browser_click(第三个链接) ...
```

## Skill 设计

### Skill 名称
`page-debug` / `实时页面调试`

### Skill 职责
将 Agent 转变为浏览器操控专家，专注于：
1. 理解用户的自然语言浏览器操作意图
2. 使用 Playwright MCP 工具执行操作
3. 每次操作后截图/快照确认结果
4. 保持对话流畅，主动提示下一步

### Skill 核心指令
- 使用 `mcp__playwright__browser_*` 系列工具
- 每次页面变化后，自动调用 `browser_snapshot` 确认状态
- 对关键操作结果调用 `browser_take_screenshot` 展示
- 用中文回复，简洁描述操作结果
- 遇到页面错误或意外状态时主动报告
- 保持浏览器窗口可见 (headless=false)

## 项目文件

```
实时页面调试/
├── .claude/
│   └── skills/
│       └── page-debug.md    # Skill 定义文件
├── PLAN.md                   # 本计划文档
└── README.md                 # 使用说明
```

## 实施步骤

### Step 1: 创建 Skill 文件
- 编写 `.claude/skills/page-debug.md`
- 包含 Skill 名称、描述、系统提示词
- 定义 Agent 行为和工具使用规范

### Step 2: Skill 内容核心
- **角色定义**: 你是浏览器操控专家
- **工具清单**: 列出所有可用的 Playwright MCP 工具
- **行为规范**: 操作后必须确认、错误要报告、中文回复
- **示例对话**: 展示典型交互模式

### Step 3: 测试验证
- 在 Claude Code 中调用 `/page-debug`
- 测试导航、点击、输入、截图等操作
- 验证自然语言理解准确性

## 验证方法
1. 在 Claude Code 中输入 `/page-debug` 调用 Skill
2. 输入 "打开 https://example.com 并截图"
3. 验证浏览器正确导航并返回截图
4. 测试复杂指令如 "在百度搜索框中输入 Claude Code 并点击搜索"
5. 确认每次操作后有状态反馈
