"""page-debug 框架适配器

每个适配器实现 Phase 1 的全部逻辑：检测 → 断点注入 → CDP 配置 → 运行器命令。
Phase 2-3（CDP 连接 + API 桥接）由主引擎 debug_breakpoint.py 处理，与框架无关。
"""

from .base import BaseAdapter
from .playwright_pytest import PlaywrightPytestAdapter
from .playwright_java_junit import PlaywrightJavaJUnitAdapter

__all__ = ["BaseAdapter", "find_adapter",
           "PlaywrightPytestAdapter", "PlaywrightJavaJUnitAdapter"]


def find_adapter(filepath, line_num, cdp_port, temp_dir):
    """工厂方法：遍历注册的适配器，返回首个匹配的实例"""
    for cls in [PlaywrightJavaJUnitAdapter, PlaywrightPytestAdapter]:
        try:
            if cls.detect(filepath):
                return cls(filepath, line_num, cdp_port, temp_dir)
        except Exception:
            continue
    raise ValueError(f"不支持的文件类型或框架未检测到: {filepath}")
