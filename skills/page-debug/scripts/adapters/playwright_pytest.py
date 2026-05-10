"""Python/pytest 适配器

检测: .py + import playwright
断点: time.sleep(3600)
CDP:  生成临时 conftest.py（browser_type_launch_args fixture）
运行: python -m pytest <modified_file> -v --headed
"""

import re
from pathlib import Path

from .base import BaseAdapter

# ---- conftest 模板 ----

CONFTEST_CDP_TEMPLATE = '''"""page-debug 自动生成的 conftest — CDP 端口 {cdp_port}"""
import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {{
        "headless": False,
        "args": [
            "--remote-debugging-port={cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            "--disable-blink-features=AutomationControlled",
            "--remote-allow-origins=*",
        ],
    }}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {{
        **browser_context_args,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }}


@pytest.fixture(autouse=True)
def page_debug_anti_detect(context):
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
    """)
    yield
'''


# ---- 工具 ----

def _get_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _inject_cdp_into_args(content: str, cdp_port: int) -> str:
    cdp_arg = f'"--remote-debugging-port={cdp_port}"'
    addr_arg = '"--remote-debugging-address=127.0.0.1"'
    origins_arg = '"--remote-allow-origins=*"'

    if "browser_type_launch_args" not in content:
        new_fixture = (
            "\n\n@pytest.fixture(scope=\"session\")\n"
            "def browser_type_launch_args():\n"
            "    return {\n"
            '        "headless": False,\n'
            '        "args": [\n'
            f"            {cdp_arg},\n"
            f"            {addr_arg},\n"
            f"            {origins_arg},\n"
            "        ],\n"
            "    }\n"
        )
        return content.rstrip("\n") + new_fixture

    if f"--remote-debugging-port={cdp_port}" in content and \
       "--remote-debugging-address=127.0.0.1" in content:
        return content

    if '"args"' in content or "'args'" in content:
        inject_args = f"\\1\n                {cdp_arg},\n                {addr_arg},\n                {origins_arg},"
        new_content = re.sub(
            r'(return\s*\{[^}]*"args"\s*:\s*\[)',
            inject_args,
            content,
            count=1,
        )
        if new_content != content:
            return new_content
        new_content = re.sub(
            r'("args"\s*:\s*\[)',
            inject_args,
            content,
            count=1,
        )
        return new_content
    else:
        existing_args = re.findall(r'"--[^"]+"', content)
        existing_args = [a for a in existing_args if "remote-debugging-port" not in a
                         and "remote-allow-origins" not in a]
        all_args = [cdp_arg, addr_arg, origins_arg] + existing_args
        args_block = ",\n                ".join(all_args)
        new_fixture = (
            "@pytest.fixture(scope=\"session\")\n"
            "def browser_type_launch_args():\n"
            "    return {\n"
            '        "headless": False,\n'
            '        "args": [\n'
            f"                {args_block},\n"
            "        ],\n"
            "    }\n"
        )
        return re.sub(
            r'@pytest\.fixture[^\n]*\ndef browser_type_launch_args[^\n]*\n(?:    .*\n)*',
            new_fixture,
            content,
            count=1,
        )


# ---- 适配器 ----

class PlaywrightPytestAdapter(BaseAdapter):
    """Python/pytest + Playwright"""

    @staticmethod
    def detect(filepath: str) -> bool:
        path = Path(filepath)
        if path.suffix.lower() != ".py":
            return False
        content = path.read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(r"from playwright|import playwright", content))

    def inject_breakpoint(self) -> str:
        filepath = self.filepath
        line_num = self.line_num
        temp_dir = self.temp_dir

        lines = Path(filepath).read_text(encoding="utf-8", errors="ignore").splitlines(True)
        if line_num < 1 or line_num > len(lines):
            raise ValueError(f"行号 {line_num} 超出文件范围 (1-{len(lines)})")

        target_line = lines[line_num - 1]
        indent = _get_indent(target_line)
        bp = '__import__("time").sleep(3600)  # [page-debug breakpoint]'
        bp_line = indent + bp + "\n"

        if not indent and line_num > 1:
            for prev in reversed(range(line_num - 1)):
                prev_indent = _get_indent(lines[prev])
                if prev_indent:
                    indent = prev_indent
                    bp_line = indent + bp + "\n"
                    break
            else:
                indent = "    "
                bp_line = indent + bp + "\n"

        lines.insert(line_num - 1, "\n" + bp_line + "\n")
        modified = temp_dir / f"_debug_{Path(filepath).name}"
        modified.write_text("".join(lines), encoding="utf-8")
        return str(modified)

    def configure_cdp(self, test_dir: str) -> list:
        original_conftest = Path(test_dir) / "conftest.py"
        temp_conftest = self.temp_dir / "conftest.py"

        if original_conftest.exists():
            original = original_conftest.read_text(encoding="utf-8")
            if f"--remote-debugging-port={self.cdp_port}" in original:
                new_content = original
            else:
                new_content = _inject_cdp_into_args(original, self.cdp_port)
        else:
            new_content = CONFTEST_CDP_TEMPLATE.format(cdp_port=self.cdp_port)

        temp_conftest.write_text(new_content, encoding="utf-8")
        print(f"[page-debug] 已生成 CDP conftest → {temp_conftest}")
        return [str(temp_conftest)]

    def get_runner(self, headed: bool = True) -> dict:
        modified_file = str(self.temp_dir / f"_debug_{Path(self.filepath).name}")
        test_dir = str(Path(self.filepath).parent)
        cmd = [self._python(), "-m", "pytest", modified_file, "-v"]
        if headed:
            cmd.append("--headed")
        return {"cmd": cmd, "cwd": test_dir}

    @staticmethod
    def _python() -> str:
        import sys
        return sys.executable
