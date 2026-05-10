# page-debug 鲁棒性设计

## 设计原则

page-debug 的核心任务是在用户机器上启动浏览器、注入断点、建立 CDP 桥接。这个过程涉及多进程协作（Python → pytest → Chrome），任何一个环节都可能因环境差异或残留状态而失败。

鲁棒性设计的核心约束：

1. **高内聚** — 所有容错逻辑在 page-debug 内部闭环，不修改系统配置
2. **不伤及无辜** — 清理残留进程时精准定位，绝不碰用户的其他 Chrome 窗口或无关进程
3. **自愈透明** — 连接失败时自动恢复，对 Agent 调用方无感
4. **可观测** — 关键阶段有显式输出，故障时有明确原因而非静默卡死

## 脆弱点与解决方案

### 1. CDP target ID 过期

**脆弱性**：Chrome 的 CDP 协议中，每个页面 target 有唯一 ID。页面导航后 target ID 可能变化，缓存的 WebSocket URL 指向已销毁的 target，导致 `No such target id` 错误。

**解决方案**：`PageOperator` 不永久缓存 target URL。

```
PageOperator._refresh_ws_url()
  ├── 第一轮: 按 self._page.url 精确匹配当前页面 target
  ├── 第二轮: 取首个非 about:blank 页面 target
  └── 回退: 浏览器级 URL (Runtime.evaluate 同样可用)
```

`_cdp()` 执行 CDP 命令时：
- 第一次尝试失败 → 自动调用 `_refresh_ws_url()` 刷新 target URL → 重试
- 两次都失败 → 返回明确错误信息

每次命令创建独立 WebSocket 连接（用完即关），避免长连接的断线重连复杂度。

### 2. connect_over_cdp 连接失败

**脆弱性**：Playwright 的 `connect_over_cdp` 可能因残留 Chrome 进程占用端口、CDP 尚未就绪等原因失败。单次尝试无重试，可靠性不足。

**解决方案**：最多 3 次重试，每次失败后执行恢复动作：

```
for retry in range(3):
    connect_over_cdp(ws_url)
    ↓ 失败
    _kill_process_on_port(cdp_port)  ← 精准清理
    sleep(2)
    重新从 /json/version 获取 ws_url  ← URL 可能已变
    ↓ 继续重试
```

关键：只杀占用 CDP 端口的那个进程，而非所有 Chrome。

### 3. 进程残留

**脆弱性**：page-debug 异常退出（Agent 中断、脚本崩溃）时，测试进程和 Chrome 可能残留，持续占用 CDP 端口。下次启动时端口冲突。

**解决方案**：双层清理机制。

**第一层 — atexit 预注册**（在 Phase 1 之前注册）：

```python
atexit.register(_emergency_cleanup)
```

清理动作：
1. 终止测试子进程（先 `terminate()`，5s 超时后 `kill()`）
2. 精准清理 CDP 端口上的 Chrome 进程
3. 删除临时文件

**第二层 — 正常退出 finally 块**：
- 关闭 API 服务
- 关闭 Playwright browser 和 playwright 实例
- 终止测试子进程
- 清理临时文件

两层互不冲突——重复 `terminate()` 和 `unlink()` 是安全的。

### 4. IPv4/IPv6 双栈解析不一致

**脆弱性**：Chrome 默认监听 `127.0.0.1`（IPv4），但 `localhost` 在某些 Windows 机器上被解析为 `::1`（IPv6）。Playwright 的 WebSocket 客户端用 IPv6 连接 → `ECONNREFUSED`。

**解决方案**：全链路统一强制 IPv4。

| 环节 | 变更 |
|------|------|
| Chrome 启动参数 | `--remote-debugging-address=127.0.0.1` |
| CDP 轮询 URL | `http://127.0.0.1:{port}/json/version` |
| PageOperator 内部 | `http://127.0.0.1:{port}/json` |
| Chrome 返回的 WS URL | `.replace("localhost", "127.0.0.1")` |

不修改 `hosts` 文件，不影响系统 DNS 解析行为。

### 5. 端口冲突

**脆弱性**：CDP 端口 (9223) 或 API 端口 (9234) 可能被其他程序占用。

**解决方案**：
- 端口号通过 `--cdp-port` / `--api-port` 参数可配置
- CDP 轮询有 60s 超时，超时后明确报错退出
- API 启动后有自检：内部调用 `/status`，10 次重试（每次 0.5s），失败时打印警告

### 6. 不同框架的断点注入

**脆弱性**：不同语言/框架的断点语法不同（Python `time.sleep`、Java `Thread.sleep`），硬编码只支持一种。

**解决方案**：框架检测 + 策略表（`FRAMEWORK_BREAKPOINTS`），按语言选择正确的断点语法和测试运行命令。未识别的框架回退到通用模式。

## 进程清理的安全性

这是鲁棒性设计中最关键的约束：page-debug 的清理逻辑绝不能影响用户正在运行的其它程序。

### 反模式（已弃用）

```
taskkill /F /IM chrome.exe
```

这会杀死用户所有的 Chrome 窗口——包括正在编辑的文档、正在参加的会议、正在填写的表单。

### 正确做法

```python
def _kill_process_on_port(port: int):
    """仅结束占用指定端口的进程。"""
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            pid = line.strip().split()[-1]
            subprocess.run(["taskkill", "/F", "/PID", pid], ...)
            return
```

1. 通过 `netstat -ano` 找到监听 CDP 端口的 PID
2. 仅 `taskkill` 该 PID
3. 不做模糊匹配、不做进程名匹配

这样即使端口被非 Chrome 进程占用，也只清理那个特定进程。

## 启动自检

API 桥接服务启动后，page-debug 在宣布"就绪"之前验证桥接可用：

```python
for _ in range(10):
    resp = urlopen(f"http://127.0.0.1:{api_port}/status")
    if resp.status == 200:
        api_ok = True
        break
    sleep(0.5)
```

不可用时打印警告而非静默失败，让 Agent 能感知到问题。

## 临时文件生命周期

- 所有临时文件统一放在项目 `./temp/` 目录（不污染系统临时目录）
- atexit 和 finally 块双重保障清理
- 用户可见临时文件内容，方便排查问题
