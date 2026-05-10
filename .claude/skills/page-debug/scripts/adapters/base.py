"""框架适配器基类"""

from pathlib import Path


class BaseAdapter:
    """框架适配器基类。子类需实现所有 Phase 1 方法。"""

    @staticmethod
    def detect(filepath: str) -> bool:
        """能否处理此文件"""
        raise NotImplementedError

    def __init__(self, filepath: str, line_num: int, cdp_port: int, temp_dir: str):
        self.filepath = filepath
        self.line_num = line_num
        self.cdp_port = cdp_port
        self.temp_dir = Path(temp_dir)

    # -- Phase 1a: 断点注入 --

    def inject_breakpoint(self) -> str:
        """在原文件副本的失败行前注入阻塞点，返回修改后的文件路径"""
        raise NotImplementedError

    # -- Phase 1b: CDP 配置 --

    def configure_cdp(self, test_dir: str) -> list:
        """配置 CDP 远程调试端口，返回新生成的临时文件路径列表"""
        raise NotImplementedError

    # -- Phase 1c: 测试运行器 --

    def get_runner(self, headed: bool = True) -> dict:
        """返回 {"cmd": [...], "cwd": "..."}"""
        raise NotImplementedError
