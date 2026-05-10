"""page-debug 断点注入器 + CDP 浏览器桥接 (v5)

三阶段工作流:

Phase 1 — 断点注入 + CDP 配置（由框架适配器处理）
    遍历 adapters/ 找到匹配的适配器 → 注入断点 → 配置 CDP 端口。

Phase 2 — 启动 & 连接
    后台运行测试脚本 → 等待 Chrome CDP 就绪 → WebSocket 连接 CDP。

Phase 3 — API 桥接服务
    启动本地 HTTP 服务，Agent 通过 curl 调用，通过 CDP 协议操控测试脚本的浏览器。

用法:
    python {baseDir}/scripts/debug_breakpoint.py --file <test_file> --line <N>

API 端点:
    GET  /status        → {"url": "...", "title": "..."}
    POST /snapshot      → {"snapshot": {...}}
    POST /click         ← {"selector": "#kw"}
    POST /type          ← {"selector": "#kw", "text": "hello"}
    POST /evaluate      ← {"code": "document.title"} → {"result": ...}
    POST /navigate      ← {"url": "https://..."}
    POST /reload        → 恢复到断点 URL
    POST /restart       → 重跑脚本回到断点
    POST /press_key     ← {"key": "Enter"}
    POST /wait          ← {"time": 1} 或 {"text": "搜索"}
    POST /close         → 关闭浏览器和 API 服务
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Windows 控制台 UTF-8 编码（避免中文输出乱码）
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

CDP_PORT = 9223
API_PORT = 9234

# ---------------------------------------------------------------------------
# 适配器加载
# ---------------------------------------------------------------------------

_adapters_dir = Path(__file__).resolve().parent / "adapters"
if str(_adapters_dir.parent) not in sys.path:
    sys.path.insert(0, str(_adapters_dir.parent))

from adapters import find_adapter


# ---------------------------------------------------------------------------
# HTTP API 桥接服务
#
# HTTPServer 在守护线程运行。PageOperator 通过 raw CDP WebSocket
# 直接与 Chrome 通信，完全绕过 Playwright，避免 greenlet 线程亲和性问题。
# ---------------------------------------------------------------------------

class BridgeHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    operator = None   # PageOperator
    running = True
    # 重启上下文（由 main() 设置，PageOperator._op_restart 使用）
    _state = None     # {"test_proc": ..., "restarting": bool}
    _cmd = None       # 测试启动命令
    _cwd = None       # 工作目录
    _cdp_port = None
    _pw = None        # sync_playwright 实例
    _browser = None   # 浏览器实例

    def log_message(self, format, *args):
        print(f"[api] {args[0]}", file=sys.stderr)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path == "/status":
            try:
                result = BridgeHandler.operator.execute("status", {})
                self._send_json(result)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._read_body()
            op = self.path.lstrip("/")
            result = BridgeHandler.operator.execute(op, body)
            self._send_json(result)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


# ---- 浏览器操作执行器 (raw CDP WebSocket, 线程安全) ----

class PageOperator:
    """通过 raw CDP WebSocket 操控 Chrome，避开 Playwright greenlet 限制。

    CDP target URL 不永久缓存——每次 CDP 命令失败时自动从 /json 刷新
    页面级 target URL 并重试一次，消除 target ID 过期导致的 404。
    """

    def __init__(self, page, cdp_port):
        self._page = page
        self._cdp_port = cdp_port
        self._ws_url = None
        self._initial_url = page.url  # 断点时的页面 URL，/reload 恢复到此处
        self._refresh_ws_url()

    def _refresh_ws_url(self):
        """从 CDP /json 端点获取当前页面 target 的 WebSocket URL。"""
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{self._cdp_port}/json", timeout=5)
            targets = json.loads(resp.read().decode())
            page_url = self._page.url
            for t in targets:
                if t.get("type") == "page" and t.get("url") == page_url:
                    raw = t.get("webSocketDebuggerUrl") or ""
                    self._ws_url = raw.replace("localhost", "127.0.0.1")
                    return
            for t in targets:
                if t.get("type") == "page" and t.get("url") != "about:blank":
                    raw = t.get("webSocketDebuggerUrl") or ""
                    self._ws_url = raw.replace("localhost", "127.0.0.1")
                    return
        except Exception:
            pass
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{self._cdp_port}/json/version", timeout=5)
            data = json.loads(resp.read().decode())
            raw = data.get("webSocketDebuggerUrl", "")
            self._ws_url = raw.replace("localhost", "127.0.0.1") if raw else self._ws_url
        except Exception:
            pass

    def _cdp(self, method, params=None):
        """每次调用创建新的 CDP WebSocket 连接。target URL 过期时自动刷新并重试。"""
        import websocket

        for attempt in range(2):
            try:
                ws = websocket.create_connection(self._ws_url, timeout=10)
                try:
                    msg_id = 1
                    msg = json.dumps({"id": msg_id, "method": method,
                                      "params": params or {}})
                    ws.send(msg)
                    while True:
                        resp = json.loads(ws.recv())
                        if resp.get("id") == msg_id:
                            if "error" in resp:
                                return {"error": resp["error"].get("message",
                                        str(resp["error"]))}
                            return resp.get("result", {})
                finally:
                    ws.close()
            except Exception as e:
                if attempt == 0:
                    self._refresh_ws_url()
                else:
                    return {"error": f"CDP 命令失败 (已重试): {e}"}

        return {"error": "CDP 命令失败: 重试已用尽"}

    def execute(self, op: str, kwargs: dict) -> dict:
        method = getattr(self, f"_op_{op}", None)
        if method is None:
            return {"error": f"unknown operation: {op}"}
        try:
            return method(kwargs)
        except Exception as e:
            return {"error": str(e)}

    def _op_status(self, _):
        result = self._cdp("Runtime.evaluate", {
            "expression": "document.title", "returnByValue": True})
        title = result.get("result", {}).get("value", "")
        return {"url": self._page.url, "title": title}

    def _op_snapshot(self, _):
        result = self._cdp("Accessibility.getFullAXTree", {})
        return {"snapshot": result.get("nodes", [])}

    def _op_click(self, body):
        selector = json.dumps(body.get("selector", ""))
        self._cdp("Runtime.evaluate", {
            "expression": f"document.querySelector({selector}).click()"})
        return {"ok": True}

    def _op_type(self, body):
        selector = json.dumps(body.get("selector", ""))
        text = json.dumps(body.get("text", ""))
        self._cdp("Runtime.evaluate", {
            "expression": (
                f"(function(){{var e=document.querySelector({selector});"
                f"e.focus();e.value={text};"
                f"e.dispatchEvent(new Event('input',{{bubbles:true}}));"
                f"e.dispatchEvent(new Event('change',{{bubbles:true}}));}})()"
            )})
        return {"ok": True}

    def _op_evaluate(self, body):
        code = body.get("code", "")
        if not code:
            return {"error": "需要 code"}
        result = self._cdp("Runtime.evaluate", {
            "expression": code, "returnByValue": True})
        return {"result": result.get("result", {}).get("value")}

    def _op_navigate(self, body):
        url = body.get("url", "")
        if not url:
            return {"error": "需要 url"}
        result = self._cdp("Page.navigate", {"url": url})
        new_url = self._page.url
        if result.get("result", {}).get("frameId"):
            new_url = url
        return {"url": new_url}

    def _op_reload(self, _):
        self._cdp("Page.navigate", {"url": self._initial_url})
        time.sleep(1)
        result = self._cdp("Runtime.evaluate", {
            "expression": "document.title", "returnByValue": True})
        title = result.get("result", {}).get("value", "")
        return {"url": self._initial_url, "title": title}

    def _op_restart(self, _):
        """一键恢复断点：重跑整个测试脚本，回到断点位置。"""
        state = BridgeHandler._state
        if not state:
            return {"error": "重启上下文不可用"}
        state["restarting"] = True

        try:
            old_proc = state["test_proc"]
            if old_proc and old_proc.poll() is None:
                old_proc.terminate()
                try:
                    old_proc.wait(timeout=10)
                except Exception:
                    old_proc.kill()

            try:
                BridgeHandler._browser.close()
            except Exception:
                pass
            try:
                BridgeHandler._pw.stop()
            except Exception:
                pass
            BridgeHandler._pw = None
            BridgeHandler._browser = None
            time.sleep(1)

            _kill_process_on_port(BridgeHandler._cdp_port)
            time.sleep(1)

            new_proc = subprocess.Popen(
                BridgeHandler._cmd,
                cwd=BridgeHandler._cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            state["test_proc"] = new_proc
            print(f"[page-debug] 重启测试进程 PID: {new_proc.pid}", file=sys.stderr)

            cdp_port = BridgeHandler._cdp_port
            ws_url = None
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    resp = urllib.request.urlopen(
                        f"http://127.0.0.1:{cdp_port}/json/version", timeout=2)
                    data = json.loads(resp.read().decode())
                    ws_url = data.get("webSocketDebuggerUrl", "")
                    if ws_url:
                        ws_url = ws_url.replace("localhost", "127.0.0.1")
                        break
                except Exception:
                    pass
                time.sleep(1)

            if not ws_url:
                return {"error": f"CDP 端口 {cdp_port} 在 60s 内未就绪"}

            from playwright.sync_api import sync_playwright
            new_pw = sync_playwright().start()
            browser = new_pw.chromium.connect_over_cdp(ws_url)
            BridgeHandler._pw = new_pw
            BridgeHandler._browser = browser
            page = browser.contexts[0].pages[0]
            time.sleep(2)

            self._page = page
            self._initial_url = page.url
            self._refresh_ws_url()

            print(f"[page-debug] 已恢复断点: {page.url}", file=sys.stderr)
            return self._op_status({})

        except Exception as e:
            return {"error": f"重启失败: {e}"}
        finally:
            state["restarting"] = False

    def _op_press_key(self, body):
        key = body.get("key", "")
        if not key:
            return {"error": "需要 key"}
        self._cdp("Input.dispatchKeyEvent", {"type": "keyDown", "key": key})
        self._cdp("Input.dispatchKeyEvent", {"type": "keyUp", "key": key})
        return {"ok": True}

    def _op_wait(self, body):
        secs = body.get("time", 0)
        text = body.get("text", "")
        if secs:
            time.sleep(secs)
        elif text:
            text_js = json.dumps(text)
            deadline = time.time() + 30
            while time.time() < deadline:
                result = self._cdp("Runtime.evaluate", {
                    "expression": f"document.body.innerText.includes({text_js})",
                    "returnByValue": True})
                if result.get("result", {}).get("value"):
                    break
                time.sleep(0.5)
        return {"ok": True}

    def _op_close(self, _):
        BridgeHandler.running = False
        return {"ok": True, "message": "浏览器即将关闭，API 服务停止"}

    def close(self):
        pass


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _kill_process_on_port(port: int):
    """结束占用指定端口的进程，不影响其它 Chrome 窗口。"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="page-debug 断点注入器 + 浏览器桥接")
    parser.add_argument("--file", required=True, help="测试脚本文件路径")
    parser.add_argument("--line", type=int, required=True, help="失败行号")
    parser.add_argument("--headed", action="store_true", default=True)
    parser.add_argument("--framework", default=None)
    parser.add_argument("--dry-run", action="store_true", help="仅生成断点脚本，不运行")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT)
    parser.add_argument("--api-port", type=int, default=API_PORT)
    parser.add_argument("--temp-dir", default=None,
                        help="临时文件目录，默认 ./temp")
    args = parser.parse_args()

    filepath = os.path.abspath(args.file)
    if not os.path.isfile(filepath):
        print(f"[ERROR] 文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)

    test_dir = os.path.dirname(filepath) or "."
    cdp_port = args.cdp_port
    api_port = args.api_port

    temp_dir = Path(args.temp_dir or os.path.join(os.getcwd(), "temp"))
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 预注册清理回调
    _cleanup_registry = {"test_proc": None, "temp_files": []}

    def _emergency_cleanup():
        tp = _cleanup_registry.get("test_proc")
        if tp and tp.poll() is None:
            tp.terminate()
            try:
                tp.wait(timeout=5)
            except Exception:
                tp.kill()
        _kill_process_on_port(cdp_port)
        for f in _cleanup_registry.get("temp_files", []):
            try:
                if Path(f).exists():
                    Path(f).unlink()
            except Exception:
                pass

    import atexit
    atexit.register(_emergency_cleanup)

    _kill_process_on_port(cdp_port)
    _kill_process_on_port(api_port)

    # ---- Phase 1: 断点注入 + CDP 配置（框架适配器） ----
    adapter = find_adapter(filepath, args.line, cdp_port, str(temp_dir))
    print(f"[page-debug] 检测框架: {type(adapter).__name__}")

    print(f"[page-debug] 在行 {args.line} 前注入断点...")
    try:
        modified_file = adapter.inject_breakpoint()
        _cleanup_registry["temp_files"].append(modified_file)
        print(f"[page-debug] 断点已注入 → {modified_file}")
    except Exception as e:
        print(f"[ERROR] 断点注入失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        cft_files = adapter.configure_cdp(test_dir)
        for f in cft_files:
            _cleanup_registry["temp_files"].append(f)
    except Exception as e:
        print(f"[ERROR] CDP 配置失败: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print("[page-debug] dry-run 模式，不运行测试")
        sys.exit(0)

    runner = adapter.get_runner(headed=args.headed)
    cmd = runner["cmd"]
    cwd = runner["cwd"]

    # ---- Phase 2: 启动测试 + CDP 连接 ----
    print(f"[page-debug] 启动测试: {' '.join(cmd)}")
    test_proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"[page-debug] 测试进程 PID: {test_proc.pid}")
    _cleanup_registry["test_proc"] = test_proc

    deadline = time.time() + 60
    ws_url = None
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{cdp_port}/json/version", timeout=2)
            data = json.loads(resp.read().decode())
            ws_url = data.get("webSocketDebuggerUrl", "")
            if ws_url:
                ws_url = ws_url.replace("localhost", "127.0.0.1")
                break
        except Exception:
            pass
        time.sleep(1)

    if not ws_url:
        print(f"[ERROR] CDP 端口 {cdp_port} 在 60s 内未就绪", file=sys.stderr)
        test_proc.terminate()
        sys.exit(1)

    print(f"[page-debug] CDP 就绪: {ws_url}")

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = None
    for cdp_retry in range(3):
        try:
            browser = pw.chromium.connect_over_cdp(ws_url)
            break
        except Exception as e:
            if cdp_retry < 2:
                print(f"[page-debug] CDP 连接失败 ({e})，清理残留进程后重试...")
                _kill_process_on_port(cdp_port)
                time.sleep(2)
                try:
                    resp = urllib.request.urlopen(
                        f"http://127.0.0.1:{cdp_port}/json/version", timeout=5)
                    data = json.loads(resp.read().decode())
                    ws_url = (data.get("webSocketDebuggerUrl") or "").replace(
                        "localhost", "127.0.0.1")
                except Exception:
                    pass
            else:
                raise Exception(f"CDP 连接失败（已重试 3 次）: {e}") from e

    page = None
    for ctx in browser.contexts:
        for p in ctx.pages:
            if p.url != "about:blank":
                page = p
                break
    if not page:
        page = browser.contexts[0].pages[0]

    print(f"[page-debug] 已接管页面: {page.url}")

    page_cdp_url = None
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{cdp_port}/json", timeout=5)
        targets = json.loads(resp.read().decode())
        for t in targets:
            if t.get("type") == "page" and t.get("url") == page.url:
                raw = t.get("webSocketDebuggerUrl") or ""
                page_cdp_url = raw.replace("localhost", "127.0.0.1")
                break
        if not page_cdp_url:
            for t in targets:
                if t.get("type") == "page" and t.get("url") != "about:blank":
                    raw = t.get("webSocketDebuggerUrl") or ""
                    page_cdp_url = raw.replace("localhost", "127.0.0.1")
                    break
    except Exception as e:
        print(f"[page-debug] 获取页面 CDP URL 失败: {e}", file=sys.stderr)

    if not page_cdp_url:
        print("[page-debug] 未找到页面级 CDP 端点，使用浏览器级 URL")
        page_cdp_url = ws_url
    else:
        print(f"[page-debug] 页面 CDP: {page_cdp_url}")

    # ---- Phase 3: 启动 API 桥接 ----
    BridgeHandler.operator = PageOperator(page, cdp_port)
    BridgeHandler._state = {"test_proc": test_proc, "restarting": False}
    BridgeHandler._cmd = cmd
    BridgeHandler._cwd = cwd
    BridgeHandler._cdp_port = cdp_port
    BridgeHandler._pw = pw
    BridgeHandler._browser = browser

    server = HTTPServer(("127.0.0.1", api_port), BridgeHandler)
    server_thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="api-server")
    server_thread.start()

    api_ok = False
    for _ in range(10):
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{api_port}/status", timeout=3)
            if resp.status == 200:
                api_ok = True
                break
        except Exception:
            time.sleep(0.5)
    if not api_ok:
        print("[page-debug] WARNING: API 自检未通过，桥接可能不可用", file=sys.stderr)

    print()
    print("=" * 56)
    print("  page-debug 浏览器桥接已就绪")
    print(f"  API: http://127.0.0.1:{api_port}")
    if not api_ok:
        print("  ** 自检未通过，请检查端口占用或浏览器状态 **")
    print()
    print("  Agent 可通过 curl 操控测试脚本的浏览器:")
    print(f"    curl -s http://127.0.0.1:{api_port}/status")
    print(f"    curl -s -X POST http://127.0.0.1:{api_port}/snapshot")
    print(f"    curl -s -X POST http://127.0.0.1:{api_port}/evaluate \\")
    print(f"         -d '{{\"code\": \"document.title\"}}'")
    print(f"    curl -s -X POST http://127.0.0.1:{api_port}/close")
    print("=" * 56)
    sys.stdout.flush()

    try:
        while BridgeHandler.running and (
            BridgeHandler._state["test_proc"].poll() is None
            or BridgeHandler._state["restarting"]
        ):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[page-debug] 关闭 API 服务...")
        BridgeHandler.running = False
        server.shutdown()
        BridgeHandler.operator.close()
        try:
            BridgeHandler._browser.close()
        except Exception:
            pass
        try:
            BridgeHandler._pw.stop()
        except Exception:
            pass
        tp = BridgeHandler._state["test_proc"]
        if tp and tp.poll() is None:
            tp.terminate()
        for f in [Path(modified_file), temp_dir / "conftest.py"]:
            try:
                if f.exists():
                    f.unlink()
                    print(f"[page-debug] 已清理: {f}")
            except Exception:
                pass
        try:
            remaining = list(temp_dir.iterdir())
            if not remaining:
                temp_dir.rmdir()
                print(f"[page-debug] 已清理: {temp_dir}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
