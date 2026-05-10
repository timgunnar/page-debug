# page-debug Skill 设计与实现

## 概述

`page-debug` 是一个 Claude Code Skill，用于调试 UI 自动化测试失败。核心流程：在失败测试脚本中注入阻塞断点 → 通过 CDP 连接测试的浏览器 → 启动 HTTP API 桥接 → Agent 通过 curl 操控浏览器进行交互式排错。

## 当前架构

```
用户报告测试失败
       │
       ▼
┌─────────────────────────────────────────────────────┐
│  SKILL.md (Agent 行为定义)                           │
│  - 断点注入工作流                                     │
│  - 交互式调试协议                                     │
│  - 桥接 API 参考                                     │
│  - 诊断策略指引 → references/                         │
└─────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│  debug_breakpoint.py (核心引擎)                       │
│                                                      │
│  Phase 1: 断点注入                                    │
│    - 检测测试框架 (Playwright Python/Java)             │
│    - 在失败行前插入 time.sleep(3600)                   │
│    - 生成 CDP conftest 到 temp/ 目录                   │
│                                                      │
│  Phase 2: 启动 & 连接                                 │
│    - subprocess 后台运行 pytest                       │
│    - 轮询 localhost:9223/json/version 等待 CDP 就绪   │
│    - connect_over_cdp 接管浏览器                       │
│                                                      │
│  Phase 3: API 桥接服务                                │
│    - HTTPServer 监听 127.0.0.1:9234                  │
│    - 守护线程处理 HTTP 请求                            │
│    - PageOperator 通过 raw CDP WebSocket 执行命令      │
└─────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│  Agent 交互式调试 (curl ↔ API)                        │
│  GET  /status    → 页面 URL + 标题                    │
│  POST /snapshot  → CDP Accessibility.getFullAXTree    │
│  POST /click     → document.querySelector().click()   │
│  POST /type      → 模拟 input/change 事件              │
│  POST /evaluate  → CDP Runtime.evaluate               │
│  POST /navigate  → CDP Page.navigate                  │
│  POST /press_key → CDP Input.dispatchKeyEvent         │
│  POST /wait      → time.sleep 或轮询文本出现            │
│  POST /close     → 关闭服务和浏览器                     │
└─────────────────────────────────────────────────────┘
```

## 关键技术

### 1. 断点注入（源码级）

在原测试脚本副本中，失败行之前插入 `time.sleep(3600)`。这相当于在原脚本上打了一个断点——所有前置步骤（登录、跳转、表单填写）由脚本自己完成，停在失败前一刻。Agent 无需手动复现复杂的前置流程。

```python
# 注入前（testcase/test_xxx.py:17）
page.locator("#kw").type(keyword)

# 注入后（temp/_debug_test_xxx.py:17）
time.sleep(3600)  # [page-debug breakpoint]
page.locator("#kw").type(keyword)
```

### 2. CDP 远程调试

通过 `conftest.py` 的 `browser_type_launch_args` fixture 注入 `--remote-debugging-port=9223`，让 Playwright 启动的 Chrome 暴露 CDP 端口。脚本用 `chromium.connect_over_cdp(ws_url)` 接管浏览器。

### 3. Raw CDP WebSocket（绕过 Playwright greenlet 限制）

Playwright 的同步 API 依赖 greenlet，有严格的线程亲和性——只能在创建 page 对象的线程中调用。但 HTTP API 服务在守护线程中运行，直接调用 Playwright API 会报错。

**解决方案**：`PageOperator` 不通过 Playwright API 操作页面，而是创建独立的 CDP WebSocket 连接，直接发送 CDP 协议命令（`Runtime.evaluate`、`Input.dispatchKeyEvent`、`Page.navigate` 等）。每次命令建立新连接，执行完即关闭，避免线程问题。`page.url` 是 Playwright 缓存的只读属性，跨线程安全。

### 4. 临时文件隔离

所有临时文件统一放在项目 `./temp/` 目录：

| 文件 | 用途 |
|------|------|
| `temp/_debug_<原名>.py` | 注入断点后的测试副本 |
| `temp/conftest.py` | 含 CDP 配置的 conftest（合并了原始 conftest 的 fixtures） |

原始文件不动，清理时直接删除 temp 目录内容即可。

### 5. 渐进式披露

Skill 按 Claude Code 规范分层：

```
.claude/skills/page-debug/
├── SKILL.md              ← 核心指令 (<200行)，工作流 + API 参考
├── scripts/
│   ├── debug_breakpoint.py  ← 核心引擎 (~650行)，Phase 2-3
│   └── adapters/            ← 框架适配器，Phase 1
│       ├── base.py          ← 适配器基类接口
│       ├── playwright_pytest.py     ← Python/pytest 适配器
│       └── playwright_java_junit.py ← Java/JUnit 适配器
└── references/
    ├── failure-taxonomy.md   ← 失败分类与诊断方法
    └── layered-debugging.md  ← 分层架构项目穿透追踪
```

SKILL.md 保持精简，详细参考按需查阅。框架适配通过插件化架构实现，新增框架只需添加适配器文件，主引擎无需修改。

## 备选方案及弃用原因

### 方案 A：MCP 浏览器作为调试器

通过 `mcp__playwright__browser_*` 工具手动操控独立浏览器，从零开始复现测试场景。

**缺陷**：Agent 需要手动重复测试脚本的所有前置步骤（导航、登录、表单填写）；无法精准停在失败前一刻，与测试实际运行环境有偏差；与断点调试的定位偏离，混入了通用浏览器操控。

**结论**：page-debug 聚焦断点注入 + 交互式调试，不包含通用浏览器操控。

### 方案 B：Playwright page.pause()

Playwright 内置的 `page.pause()` 可暂停脚本并启动 Playwright Inspector。

**缺陷**：Inspector 是交互式 GUI 工具，Agent 无法程序化操控；无 HTTP API，无法通过 curl 与浏览器交互；依赖 Playwright 专属协议，无法扩展到非 Playwright 测试。

**结论**：不适合 Agent 自动化调试场景。

### 方案 C：修改原始 conftest.py + 备份恢复

直接修改项目 `conftest.py` 注入 CDP 配置，备份原文件到 `temp/`，调试结束后恢复。

**缺陷**：调试副本在 `temp/` 下但 CDP conftest 在原目录下，pytest conftest 发现机制无法跨兄弟目录查找；修改原始文件存在异常退出未恢复的风险；需维护备份和恢复逻辑。

**结论**：在 `temp/` 生成 CDP conftest（合并原始 conftest 的所有 fixtures），原始文件零修改。

### 方案 D：Playwright API 直接操控

在 HTTP API 线程中直接调用 Playwright 的 `page.click()`、`page.type()` 等方法。

**缺陷**：Playwright 同步 API 基于 greenlet，有严格的线程亲和性；HTTP 服务在守护线程中运行，跨线程调用会抛出 `greenlet.error`。

**结论**：通过 raw CDP WebSocket 发送协议命令，每次建立独立连接，完全避开线程问题。

### 方案 E：WebSocket 长连接复用

PageOperator 维护一条长连接 CDP WebSocket，所有命令复用。

**缺陷**：CDP WebSocket 连接存在超时和断连风险，需重连逻辑；请求-响应匹配需维护递增 `msg_id`，增加状态管理复杂度；浏览器级 CDP URL 被 `connect_over_cdp` 占用后不能复用，需页面级 URL。

**结论**：每次命令新建连接，简单可靠。

## 关键设计决策

1. **断点位置**：注入在失败行**之前**而非之后——停在失败前一刻才能看到失败时的真实页面状态
2. **sleep(3600) 而非无限循环**：1 小时足够调试，避免忘记清理时永久占用资源
3. **temp/ 而非系统临时目录**：放在项目内方便排查问题，用户可见临时文件内容
4. **守护线程 HTTP 服务**：`daemon=True` 确保主进程退出时自动清理，不会残留端口占用
5. **每次独立 CDP 连接**：牺牲少量性能换取线程安全和无状态简单性
