# page-debug 环境解耦设计

## 问题

调试工具通常与特定机器的环境强绑定：固定的 Python 路径、硬编码的端口号、依赖特定目录结构。page-debug 需要作为一个可发布的 Skill 在任何人的电脑上运行。

## 设计原则

1. **零配置启动** — 默认值覆盖常见场景，高级用户可通过 CLI 参数覆盖
2. **自动发现** — 自动检测运行环境中的 Python 解释器、框架、工作目录
3. **不动原始文件** — 所有临时产物在独立目录，原始项目零侵入
4. **跨平台兼容** — 不依赖 Windows/Linux/macOS 特定路径或命令

## 解耦清单

### Python 解释器

| 变量 | 解耦方式 |
|------|---------|
| Python 路径 | `sys.executable` — 自动获取当前运行中的 Python 解释器完整路径 |
| Python 版本 | 脚本用 Python 3.8+ 通用语法（f-string `f"...{var}..."` 而非 `format()`，`pathlib` 而非 `os.path`） |

```python
# 不硬编码 python/python3，使用当前解释器
cmd = [sys.executable, "-m", "pytest", modified_file, "-v"]
```

### 文件路径

| 变量 | 默认值 | 覆盖方式 |
|------|--------|---------|
| Skill 目录 | `{baseDir}` — Claude Code 自动解析为 SKILL.md 所在目录 | 无需覆盖 |
| 测试文件 | `--file` 必填参数 — 用户指定，支持相对/绝对路径 | — |
| 临时目录 | `os.getcwd() + "/temp"` — 项目根目录下的 temp/ | `--temp-dir` |
| conftest 位置 | 自动在 `temp_dir` 生成，合并原始 conftest 的 fixtures | — |

```bash
# {baseDir} 由 Claude Code 解析 = .claude/skills/page-debug
python {baseDir}/scripts/debug_breakpoint.py --file testcase/test_xxx.py --line 17

# 自定义临时目录
python {baseDir}/scripts/debug_breakpoint.py --file test.java --line 42 --temp-dir /tmp/debug
```

### 端口

| 变量 | 默认值 | 覆盖方式 |
|------|--------|---------|
| CDP 端口 | `9223` | `--cdp-port` |
| API 端口 | `9234` | `--api-port` |

两个端口仅绑定 `127.0.0.1`（本地回环），不暴露到外网。如果默认端口被占用（如其他 Chrome DevTools 实例），用户可通过参数指定备用端口。

### 外部命令

| 命令 | 解耦方式 |
|------|---------|
| `python` / `python3` | `sys.executable` — 自动使用当前 Python |
| `pytest` | 通过 `python -m pytest` 运行，不依赖 PATH 中的 pytest |
| `mvn` | 通过 `subprocess.Popen` 调用，依赖用户 PATH；Maven 是 Java 生态标配 |
| `curl` | Windows 10+ 内置 curl.exe，Unix 系统标配 |

### 浏览器

| 变量 | 解耦方式 |
|------|---------|
| Chrome 路径 | Playwright 管理浏览器安装 (`playwright install chromium`)，不依赖系统 Chrome |
| CDP WebSocket URL | 通过 `http://localhost:{port}/json/version` 动态获取，不硬编码 |
| 页面级 CDP URL | 通过 `http://127.0.0.1:{port}/json` 获取 target 列表，按 page.url 精确匹配 → 首个非空白页 → 浏览器级回退 |

### 测试框架

| 变量 | 解耦方式 |
|------|---------|
| 框架检测 | 自动按文件扩展名 + 源码特征正则匹配 |
| 手动指定 | `--framework` 参数覆盖自动检测 |
| 运行器命令 | `FRAMEWORK_BREAKPOINTS` 字典映射框架 → 运行器，可扩展 |

### 原始文件保护

断点注入过程中**不修改任何原始文件**：

```
原始项目                         temp/ (临时，调试结束自动清理)
├── testcase/                    ├── _debug_test_xxx.py   ← 注入断点的副本
│   ├── conftest.py (原始不动)    ├── conftest.py          ← 含 CDP 配置的副本
│   └── test_xxx.py  (原始不动)   └── __pycache__/
└── ...
```

## 环境依赖声明

用户需自行安装的依赖（一次性的环境准备）：

| 依赖 | 安装方式 | 用途 |
|------|---------|------|
| Python 3.8+ | 系统安装 | 运行断点注入器和桥接 |
| `playwright` | `pip install playwright` | CDP 连接 + 浏览器管理 |
| `websocket-client` | `pip install websocket-client` | CDP WebSocket 通信 |
| Chromium | `playwright install chromium` | 测试浏览器 |

依赖集中在 `requirements.txt`，用户一行命令完成安装。

## 跨平台兼容性

| 平台 | 注意事项 |
|------|---------|
| Windows | 路径使用 `os.path` / `pathlib` 处理反斜杠；curl 为 Windows 10+ 内置 |
| macOS | 与 Linux 路径兼容；curl 内置 |
| Linux | CI/CD 环境常见，headless 模式需额外配置（`--headed` 改为 `headless=True`） |

当前 `subprocess.Popen` 的 `cwd` 参数使用 `pathlib.Path` 对象，`sys.executable` 返回平台原生路径格式，无需特殊处理。

## 不依赖的环境变量

以下内容**不依赖**于运行环境：

- ❌ 不需要 `.env` 文件或环境变量配置
- ❌ 不需要 API Key 或 Token
- ❌ 不需要网络访问（CDP 和 API 均为 localhost）
- ❌ 不需要项目特定配置（自动检测框架）
- ❌ 不需要修改 `sys.path` 或 PYTHONPATH
