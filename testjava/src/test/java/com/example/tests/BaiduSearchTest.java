package com.example.tests;

import com.example.base.BaseTest;
import com.example.pages.BaiduSearchPage;
import org.testng.annotations.Test;

import static org.testng.Assert.*;

/**
 * 百度搜索测试 — TestNG + Page Object 模式。
 *
 * testSearchBasic:      正常流程（应通过）
 * testSearchWithBroken: 使用错误选择器（应失败，供 page-debug 调试用）
 */
public class BaiduSearchTest extends BaseTest {

    private static final String KEYWORD = "人工智能";

    @Test(description = "基本搜索流程 — 正确的选择器")
    public void testSearchBasic() throws InterruptedException {
        BaiduSearchPage searchPage = new BaiduSearchPage(page);
        searchPage.open();
        Thread.sleep(1000);

        // Step 1: 执行搜索
        searchPage.search(KEYWORD);
        Thread.sleep(1000);

        // Step 2: 验证标题包含搜索词
        assertTrue(searchPage.getTitle().contains(KEYWORD),
            "标题应包含搜索词，实际: " + searchPage.getTitle());

        // Step 3: 验证搜索框保留查询词
        assertEquals(searchPage.getInputValue(), KEYWORD,
            "搜索框应保留查询词");
    }

    @Test(description = "使用错误选择器搜索 — 预期失败")
    public void testSearchWithBroken() throws InterruptedException {
        BaiduSearchPage searchPage = new BaiduSearchPage(page);
        searchPage.open();
        Thread.sleep(1000);

        // 先正常搜索以到达结果页
        searchPage.search(KEYWORD);
        Thread.sleep(1000);

        // 验证搜索成功
        assertTrue(searchPage.getTitle().contains(KEYWORD));

        // ★ 第 46 行附近 — 使用错误选择器点击（page-debug 断点目标）
        searchPage.clickSearchBroken();  // #s222u 不存在，此处超时
    }
}
