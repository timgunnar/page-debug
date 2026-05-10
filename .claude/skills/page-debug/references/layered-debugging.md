# 分层架构项目的调试

复杂项目（Java/Maven 等）测试代码采用多层封装，失败行号指向的可能不是原始选择器，而是封装方法调用。需**穿透封装层，追踪到真正的页面选择器**。

## 常见分层模式

```
测试用例层 → 调用业务层方法（如 searchPage.search(keyword)）
业务逻辑层 → 调用元素层方法（如 searchInput.type(keyword)）
元素封装层 → 定义真正的选择器（如 @FindBy(id="kw") 或 CSS/XPath）
测试数据层 → 独立于逻辑，提供参数化数据
设备继承层 → 不同设备类型共享基础页面，派生类覆写差异化选择器
```

## 穿透追踪流程

1. **定位失败调用链** — 从 traceback 找到测试用例中的失败行，识别方法名
2. **沿调用链查找** — Grep 搜索方法定义，逐层跟进：测试方法 → 业务层方法 → 元素层字段
3. **提取真实选择器** — 在元素封装层找到最终 locator（`@FindBy`、`page.locator()`、CSS/XPath 字符串）
4. **检查继承关系** — 选择器定义在父类中时，检查子类是否有覆写；不同设备类型可能使用不同选择器
5. **验证选择器** — 在桥接浏览器中通过 `POST /evaluate` 或 `POST /snapshot` 验证

## 示例

```
# traceback 指向: searchTest.java:45
searchPage.search("人工智能");  # 业务层

# Grep 找到业务层定义: SearchPage.java:30
public void search(String keyword) {
    searchInput.type(keyword);   # 元素层
    searchButton.click();
}

# Grep 找到元素层定义: SearchPage.java:12
@FindBy(id = "kw")
private WebElement searchInput;  # 真实选择器: #kw
```

## 继承的特殊处理

- 设备 A 和 B 共用 `BaseSearchPage`，但选择器不同 → 确认失败时用的是哪个子类的选择器
- 父类选择器被子类覆写 → Grep 检查子类中是否有同名字段或方法覆盖
- 选择器在运行时动态拼接 → `POST /evaluate` 验证拼接结果

## 主动验证模式

当用户指认某个业务文件要求检查其有效性时（如"xx文件中的选择器还有效吗"），按此流程：

1. 从用户指定的文件提取选择器 → 沿继承/封装链追踪到最终定义
2. 在桥接浏览器中批量验证 → 关联回业务方法名
3. 输出"方法 → 选择器 → 当前页面状态"的映射

详细步骤见 `references/failure-taxonomy.md`「验证业务文件的有效性」章节。
