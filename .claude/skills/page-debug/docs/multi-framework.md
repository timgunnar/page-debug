# page-debug 多语言/多框架适配设计

## 现状分析

当前 `debug_breakpoint.py` 的 Phase 1（断点注入 + CDP 配置）有针对 Python/pytest 的硬编码逻辑，但 Phase 2-3（CDP 连接 + API 桥接）**100% 语言无关**——只要 Chrome 带 `--remote-debugging-port` 启动，同一套代码就能接管。

```
┌──────────────────────────────────────────────────────┐
│ Phase 1: 断点注入 + CDP 配置    ← 框架相关（需要适配）  │
├──────────────────────────────────────────────────────┤
│ Phase 2: CDP 连接 + 接管浏览器   ← 语言无关            │
│ Phase 3: HTTP API 桥接服务       ← 语言无关            │
│ Agent 交互式调试                 ← 语言无关            │
└──────────────────────────────────────────────────────┘
```

所以适配的关键**只在 Phase 1**：如何为不同框架插入断点，以及如何让测试启动的浏览器带上 CDP 端口。

## 框架适配矩阵

### A. 断点注入

| 语言/框架 | 检测方式 | 断点语法 | 注入难度 |
|-----------|---------|---------|---------|
| Python/pytest | `.py` + `import playwright` | `time.sleep(3600)` | 低 — 纯文本插入 |
| Python/unittest | `.py` + `from playwright` | `time.sleep(3600)` | 低 — 同上 |
| Java/JUnit+Maven | `.java` + `com.microsoft.playwright` | `Thread.sleep(3600000L);` | 中 — 需处理缩进、import |
| Java/TestNG+Gradle | `.java` + `com.microsoft.playwright` | `Thread.sleep(3600000L);` | 中 — 同上 |
| TypeScript/Jest | `.ts` + `import.*playwright` | `await new Promise(r => setTimeout(r, 3600000));` | 中 — 需处理 async 上下文 |
| JavaScript/Jest | `.js` + `require.*playwright` | 同上 | 中 — 同上 |
| C#/NUnit | `.cs` + `Microsoft.Playwright` | `Thread.Sleep(3600000);` | 中 — 需处理 using |

### B. CDP 配置（关键难点）

每种框架让浏览器暴露 CDP 端口的方式完全不同：

| 框架 | CDP 配置方式 | 实现思路 |
|------|-------------|---------|
| **Python/pytest** | `conftest.py` 的 `browser_type_launch_args` fixture | ✅ 已实现：生成临时 conftest |
| **Python/unittest** | 测试文件内的 `launch()` 调用 | 修改测试文件中的 `launch(args=[])` |
| **Java/JUnit** | `BrowserType.LaunchOptions.setArgs()` | 见下方 Java 专题 |
| **TypeScript/JavaScript** | `launch({ args: [] })` 或配置文件 | 修改 launch 调用或 playwright.config.ts |
| **C#/NUnit** | `BrowserTypeLaunchOptions.Args` | 修改 Playwright.Create 附近代码 |

### C. 测试运行器

| 框架 | 启动命令 | 当前状态 |
|------|---------|---------|
| pytest | `python -m pytest <file> -v --headed` | ✅ |
| Maven | `mvn test -Dtest=<Class>` | 骨架已有 |
| Gradle | `gradle test --tests <Class>` | 未实现 |
| Jest | `npx jest <file>` | 未实现 |
| dotnet | `dotnet test --filter <Name>` | 未实现 |

## 关键设计：CDP 配置的 3 种策略

### 策略 1：源码注入（当前 Python 方式）

直接在测试基础设施代码中注入 `--remote-debugging-port`。

**优点**：精确控制，与测试框架深度集成。
**缺点**：每种框架需要独立的注入逻辑；复杂分层项目需要穿透封装找到真正的 launch 调用点。

**适用**：Python/pytest（conftest fixture 模式，注入点明确）、简单项目。

### 策略 2：环境变量 / 系统属性注入

不修改源码，通过环境变量或 JVM 属性让 Playwright 启动时带 CDP 端口。

```bash
# Java Playwright 可能的系统属性方式
-Dplaywright.launch.args=--remote-debugging-port=9223

# 或通用方式
PLAYWRIGHT_BROWSER_ARGS="--remote-debugging-port=9223" pytest
```

**优点**：零源码侵入，框架无关。
**缺点**：Playwright 官方未提供统一的环境变量来控制 browser args（Python/Java 都没有）。需要框架自身支持或自行实现拦截。

**适用**：如果 Playwright 后续版本支持此类环境变量，将成为最优雅的方案。当前不可行。

### 策略 3：CDP Wrapper 脚本

创建一个包装脚本，启动一个 "空" Playwright 浏览器带 CDP 端口，然后修改测试让复用这个浏览器。

```python
# wrapper 启动共享浏览器
browser = playwright.chromium.connect_over_cdp("http://localhost:9223")
```

**优点**：完全不改测试代码。
**缺点**：需要测试脚本改用 `connect_over_cdp` 而非 `launch()`；破坏了测试的浏览器生命周期管理；并行测试冲突。

**适用**：无法修改源码的场景。不推荐作为通用方案。

### 当前选择：策略 1（源码注入），按框架实现独立插件

## Java/Maven 适配方案

### 断点注入

```java
// 原始测试
@Test
public void testSearch() {
    page.locator("#kw").type("人工智能");
    page.locator("#su").click();
}

// 注入后
@Test
public void testSearch() {
    Thread.sleep(3600000L);  // [page-debug breakpoint]
    page.locator("#kw").type("人工智能");
    page.locator("#su").click();
}
```

需额外处理：如果方法有 `throws` 声明，确保 `InterruptedException` 在 throws 列表中或注入 try-catch。

### CDP 配置（Java 核心难点）

Java Playwright 的 browser launch 通常出现在以下位置之一：

```java
// 模式 1: @BeforeAll 中直接 launch
@BeforeAll
static void setup() {
    browser = playwright.chromium().launch(
        new BrowserType.LaunchOptions().setHeadless(false));
}

// 模式 2: 自定义 BrowserFactory
Browser browser = BrowserFactory.create();

// 模式 3: Spring Bean
@Bean
public Browser browser() { ... }

// 模式 4: 基类继承
class BaseTest {
    protected Browser createBrowser() { ... }
}
```

**注入策略**：按优先级尝试：

1. **Grep 定位 launch 调用** → 修改 `setArgs()` 添加 `"--remote-debugging-port=9223"`
2. **找不到显式 launch** → 检查是否有自定义 BrowserFactory，追踪到最终 launch 点
3. **Spring/DI 项目** → 检查 `@Configuration` 类中的 Browser Bean
4. **兜底** → 提示用户手动配置，提供清晰的错误信息

```java
// 修改前
browser = playwright.chromium().launch(
    new BrowserType.LaunchOptions().setHeadless(false));

// 修改后
browser = playwright.chromium().launch(
    new BrowserType.LaunchOptions()
        .setHeadless(false)
        .setArgs(Arrays.asList("--remote-debugging-port=9223")));
```

### 分层架构项目的额外处理

复杂企业项目（Java/Maven 常见）测试代码分多层：

```
测试用例层 TestSearch.java
    ↓ 调用
业务层 SearchPage.java
    ↓ 调用
元素层 BaseSearchPage.java (定义选择器)
    ↓ 使用
浏览器工厂 BrowserFactory.java (启动浏览器)
```

**穿透追踪**：

1. 失败行号指向 `TestSearch.java` 中的 `searchPage.search("xxx")`
2. Grep 找到 `SearchPage.java` 中的 `search()` 方法 → 调用了 `searchInput.type()` + `searchButton.click()`
3. Grep 找到 `BaseSearchPage.java` 中的选择器 `@FindBy(id="kw")`
4. **关键**：CDP 配置不一定在测试用例层，需要追踪到 `BrowserFactory.java` 找到真正的 `launch()` 调用

`references/layered-debugging.md` 已记录此追踪方法。可考虑增强 debug_breakpoint.py 实现自动化追踪——从测试文件出发，沿 import/继承链自动定位 browser launch 点。

## 建议的插件化架构

将 Phase 1 拆为独立的"框架适配器"，每个适配器实现统一接口：

```
scripts/
├── debug_breakpoint.py          # 主引擎（框架无关）
├── adapters/
│   ├── __init__.py
│   ├── base.py                  # 适配器接口定义
│   ├── playwright_pytest.py     # Python/pytest（当前实现）
│   ├── playwright_java_junit.py # Java/JUnit + Maven
│   ├── playwright_java_testng.py# Java/TestNG + Gradle
│   └── playwright_ts_jest.py    # TypeScript/Jest
```

### 适配器接口

```python
class FrameworkAdapter:
    """每个框架实现的统一接口"""

    # ---- 断点注入 ----
    def detect(self, filepath: str) -> bool:
        """是否能处理此文件"""

    def breakpoint_syntax(self, indent: str) -> str:
        """生成断点语句"""

    def inject_breakpoint(self, filepath: str, line: int, temp_dir: Path) -> str:
        """注入断点，返回修改后的文件路径"""

    # ---- CDP 配置 ----
    def configure_cdp(self, test_dir: str, cdp_port: int, temp_dir: Path) -> None:
        """配置 CDP 远程调试端口"""

    # ---- 运行器 ----
    def get_runner_command(self, modified_file: str) -> list[str]:
        """构建测试运行命令"""

    def get_cwd(self, original_file: str) -> str:
        """返回运行测试的工作目录"""
```

### 主引擎

```python
def main():
    adapter = detect_adapter(filepath)  # 工厂方法，遍历所有适配器
    modified = adapter.inject_breakpoint(...)
    adapter.configure_cdp(...)
    cmd = adapter.get_runner_command(modified)
    cwd = adapter.get_cwd(filepath)
    test_proc = subprocess.Popen(cmd, cwd=cwd, ...)
    # Phase 2-3 完全不变
    ...
```

## 各框架适配器实现要点

### playwright_pytest.py（当前已有，需抽离）

将现有 `detect_framework`、`inject_breakpoint`、`setup_cdp` 中的 pytest 逻辑抽离为适配器，主引擎不再包含框架判断。

### playwright_java_junit.py（需新建）

- **检测**：`.java` + `com.microsoft.playwright` + `@Test` (JUnit 注解)
- **断点**：`Thread.sleep(3600000L);`，处理缩进和 `throws` 声明
- **CDP**：Grep 定位 `chromium().launch(` 或 `launch(` → 注入 `setArgs()` 
- **运行**：`mvn test -Dtest=<ClassName> -pl <module>`
- **分层追踪**：从测试类出发，沿 import/extends 自动定位 browser launch 点（见分层专题）

### playwright_ts_jest.py（需新建）

- **检测**：`.test.ts` / `.spec.ts` + `import.*@playwright/test`
- **断点**：`await new Promise(r => setTimeout(r, 3600000));`
- **CDP**：修改 `playwright.config.ts` 的 `use.launchOptions.args`，或修改测试文件中的 `launch()`
- **运行**：`npx playwright test <file> --headed`

## 分层架构框架的 CDP 注入专题

对于 Playwright 自封装框架（企业自建测试平台），browser launch 被封装在深层工具类中，从测试文件到 browser 可能跨越 3-5 层调用。

**自动追踪算法**：

```
输入: 测试文件路径
输出: Browser launch 点所在文件 + 行号

1. 解析测试文件的 import/package 语句，构建依赖图
2. 从测试类出发，沿 extends 链找到基类
3. 在基类中搜索 @BeforeAll/@BeforeEach/@BeforeMethod 方法
4. 如果方法中直接调用 launch() → 找到目标
5. 如果调用了工厂方法 → 追踪工厂类 → 递归步骤 4
6. 如果通过 DI (Spring @Autowired) → 追踪 @Configuration/@Bean → 递归步骤 4
7. 超时或循环 → 失败，提示用户手动配置
```

**实现考虑**：
- Java 类名到文件路径的映射（package → 目录结构）
- 处理 Maven/Gradle 多模块项目（需扫描依赖模块的源码）
- DI 追踪的复杂度最高，初版可跳过，提示用户手动指定

## 优先级建议

| 优先级 | 框架 | 理由 |
|--------|------|------|
| P0 | Python/pytest | 已实现，当前主力 |
| P1 | Java/JUnit + Maven | 需求明确，骨架已有 |
| P2 | TypeScript/Jest | Playwright 生态最大用户群 |
| P3 | Java/TestNG + Gradle | 与 P1 类似，增量适配 |
| P4 | C#/NUnit | 企业市场存在需求 |

适配的核心工作量在 CDP 配置阶段，每个框架需要理解其 browser launch 机制。断点注入和运行器相对简单，可按模板快速扩展。
