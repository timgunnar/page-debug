package com.example.pages;

import com.microsoft.playwright.Page;

/**
 * 百度搜索页面 — 封装搜索相关的选择器和业务方法。
 *
 * 选择器定义在元素层，业务方法在业务层。
 * 选择器变更时只需改本类，不影响测试用例。
 */
public class BaiduSearchPage extends BasePage {

    // ---- 元素层：选择器定义 ----

    private static final String SEARCH_INPUT = "#kw";
    private static final String SEARCH_BUTTON = "#su";
    // 故意拼错的选择器，用于验证 page-debug 的调试能力
    private static final String SEARCH_BUTTON_BROKEN = "#s222u";

    public BaiduSearchPage(Page page) {
        super(page);
    }

    // ---- 业务层：组合元素操作 ----

    /** 打开百度首页 */
    public void open() {
        page.navigate("https://www.baidu.com");
        waitForLoad();
    }

    /** 在搜索框输入关键词 */
    public void typeKeyword(String keyword) {
        page.locator(SEARCH_INPUT).type(keyword);
    }

    /** 点击搜索按钮 */
    public void clickSearch() {
        page.locator(SEARCH_INPUT).press("Enter");
    }

    /**
     * 执行搜索 — 组合输入 + 点击。
     * 测试用例直接调用此方法即可。
     */
    public void search(String keyword) {
        typeKeyword(keyword);
        clickSearch();
    }

    /** 获取搜索框当前值 */
    public String getInputValue() {
        return page.locator(SEARCH_INPUT).inputValue();
    }

    /** 使用错误选择器点击搜索（故意拼错，用于测试 page-debug） */
    public void clickSearchBroken() {
        page.locator(SEARCH_BUTTON_BROKEN).click();
    }
}
