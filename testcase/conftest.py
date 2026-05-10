"""项目级 conftest - 配置 Playwright 浏览器参数"""
import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args():
    """配置浏览器启动参数，避免被检测为自动化工具"""
    return {
        "headless": False,
        "args": [
                "--remote-debugging-port=9223",
                "--remote-allow-origins=*",
            "--disable-blink-features=AutomationControlled",
        ],
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """配置浏览器上下文参数"""
    return {
        **browser_context_args,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


@pytest.fixture(autouse=True)
def baidu_anti_detect(context):
    """注入反检测脚本，覆盖 webdriver 属性"""
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)
    yield
