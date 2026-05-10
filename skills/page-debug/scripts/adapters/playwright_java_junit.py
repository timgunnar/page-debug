"""Java/JUnit + Maven 适配器

检测: .java + com.microsoft.playwright
断点: Thread.sleep(3600000L)
CDP:  ⚠ 骨架 — launch() 追踪 + setArgs() 注入待实现（见 multi-framework.md § Java/Maven）
运行: mvn test -Dtest=<ClassName>

当前限制:
- CDP 配置为骨架：不会自动在 Java 源码中注入 --remote-debugging-port。
  使用者需确保被测项目的 browser launch 已带 CDP 端口。
- Maven 命令为基线：多模块项目需通过 --mvn-opts 补充 -pl/-P 等参数。
"""

import re
from pathlib import Path

from .base import BaseAdapter


class PlaywrightJavaJUnitAdapter(BaseAdapter):
    """Java/JUnit + Maven + Playwright（骨架）"""

    @staticmethod
    def detect(filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() != ".java":
            return False

        # 1) 当前文件直接 import Playwright
        content = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"com\.microsoft\.playwright", content):
            return True

        # 2) 复杂分层项目：测试文件可能通过继承间接使用 Playwright。
        #    搜索项目源码目录中是否有其他文件 import 了 Playwright。
        project_root = PlaywrightJavaJUnitAdapter._find_project_root(path)
        if project_root:
            for src_dir_name in ("src",):
                src_dir = project_root / src_dir_name
                if src_dir.is_dir():
                    for java_file in src_dir.rglob("*.java"):
                        try:
                            fc = java_file.read_text(encoding="utf-8", errors="ignore")
                            if "com.microsoft.playwright" in fc:
                                return True
                        except Exception:
                            continue
        return False

    @staticmethod
    def _find_project_root(filepath: Path) -> Path:
        """从文件所在目录向上搜索 pom.xml，找到 Maven 项目根目录"""
        current = filepath.resolve().parent
        for _ in range(10):
            if (current / "pom.xml").is_file():
                return current
            if current.parent == current:
                break
            current = current.parent
        return None

    def inject_breakpoint(self) -> str:
        filepath = self.filepath
        line_num = self.line_num
        temp_dir = self.temp_dir

        lines = Path(filepath).read_text(encoding="utf-8", errors="ignore").splitlines(True)
        if line_num < 1 or line_num > len(lines):
            raise ValueError(f"行号 {line_num} 超出文件范围 (1-{len(lines)})")

        # 获取缩进
        target_line = lines[line_num - 1]
        stripped = target_line.lstrip()
        indent = target_line[: len(target_line) - len(stripped)]
        if not indent and line_num > 1:
            for prev in reversed(range(line_num - 1)):
                prev_indent = lines[prev][: len(lines[prev]) - len(lines[prev].lstrip())]
                if prev_indent:
                    indent = prev_indent
                    break
            else:
                indent = "    "

        bp = indent + "Thread.sleep(3600000L);  // [page-debug breakpoint]\n"

        # 处理方法签名可能带 throws
        if "throws" in stripped and "InterruptedException" not in stripped:
            lines[line_num - 1] = target_line.replace(
                "throws ", "throws InterruptedException, ")

        lines.insert(line_num - 1, "\n" + bp + "\n")
        modified = temp_dir / f"_debug_{Path(filepath).name}"
        modified.write_text("".join(lines), encoding="utf-8")
        return str(modified)

    def configure_cdp(self, test_dir: str) -> list:
        """
        ⚠ 骨架实现 — 不修改 Java 源码。

        完整实现的步骤（参见 docs/multi-family.md § Java/Maven 适配方案）:
        1. 从测试文件出发，沿 extends/import 链定位 @BeforeAll/@BeforeEach
        2. 追踪到 chromium().launch() 或 BrowserType.launch() 调用
        3. 注入 .setArgs(Arrays.asList("--remote-debugging-port=9223", ...))

        在实现之前，需确保被测项目的 conftest 等价物（BaseTest / BrowserFactory）
        已手动配置 --remote-debugging-port={cdp_port}。
        """
        print(f"[page-debug] Java 项目 CDP 配置为骨架，跳过源码注入")
        print(f"[page-debug] 确保 browser launch 已带 --remote-debugging-port={self.cdp_port}")
        return []

    def get_runner(self, headed: bool = True) -> dict:
        root = self._find_project_root(Path(self.filepath))
        cwd = str(root) if root else str(Path(self.filepath).parent)
        stem = Path(self.filepath).stem
        mvn = self._find_mvn()
        cmd = [mvn, "test", f"-Dtest={stem}"]
        return {"cmd": cmd, "cwd": cwd}

    @staticmethod
    def _find_mvn() -> str:
        """查找 mvn 可执行文件"""
        import shutil
        # 先尝试直接找
        for name in ("mvn", "mvn.cmd", "mvn.bat"):
            found = shutil.which(name)
            if found:
                return found
        # 回退：常见安装路径
        import os
        for home in os.environ.get("MAVEN_HOME", ""), \
                   os.environ.get("M2_HOME", ""):
            if home:
                candidate = Path(home) / "bin" / "mvn.cmd"
                if candidate.is_file():
                    return str(candidate)
        return "mvn"  # 最后尝试
