package com.example.pages;

import com.microsoft.playwright.Page;

/**
 * 页面组件基类 — 提供公共元素操作。
 * 业务页面继承此类，定义各自的选择器和方法。
 */
public class BasePage {

    protected final Page page;

    public BasePage(Page page) {
        this.page = page;
    }

    /** 等待页面加载完成 */
    public void waitForLoad() {
        page.waitForLoadState();
    }

    /** 获取页面标题 */
    public String getTitle() {
        return page.title();
    }
}
