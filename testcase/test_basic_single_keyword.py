"""单关键词基本文本搜索 - Playwright Python 测试用例"""
import re
from time import sleep

from playwright.sync_api import Page, expect


class TestBasicSearch:

    def test_single_keyword_search(self, page: Page):
        keyword = "人工智能"

        # Step 1: 访问搜索结果页
        page.goto(f"https://www.baidu.com")
        sleep(1)

        page.locator("//*[@id='kw']").type(keyword)
        page.locator("//*[@id='su']").click()
        sleep(1)

        # Step 2: 验证搜索结果页标题包含搜索词
        expect(page).to_have_title(re.compile(re.escape(keyword)))
        sleep(1)

        # Step 3: 验证搜索框保留查询词
        search_input = page.locator("#kw")
        expect(search_input).to_have_value(keyword)
        sleep(1)

        page.locator("//*[@id='22kw']").type(keyword)
        page.locator("//*[@id='s222u']").click()
        sleep(1)

        # Step 4: 验证搜索结果列表
        result_headings = page.locator("h3")
        expect(result_headings.first).to_be_visible()

        result_count = result_headings.count()
        assert result_count >= 1, f"预期至少1条结果，实际 {result_count}"
        sleep(1)

        # 验证每个结果有可点击的链接
        result_links = page.locator("h3 a")
        link_count = result_links.count()
        assert link_count >= 1, f"预期至少1个结果链接，实际 {link_count}"

        for i in range(min(link_count, 5)):
            link = result_links.nth(i)
            expect(link).to_be_visible()
            href = link.get_attribute("href")
            assert href and len(href) > 0, f"链接 {i} 缺少 href"

        sleep(1)

        # 验证结果容器有描述/摘要文本
        containers = page.locator("#content_left .result-op.c-container")
        container_count = containers.count()
        assert container_count >= 1, f"预期至少1个结果容器，实际 {container_count}"
        for i in range(min(container_count, 5)):
            container = containers.nth(i)
            expect(container).to_be_visible()
            text = container.inner_text()
            assert len(text) > 0, f"结果 {i} 无文本内容"

        sleep(1)
