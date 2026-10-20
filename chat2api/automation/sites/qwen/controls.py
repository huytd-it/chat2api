"""Qwen project and Thinking controls, migrated from the shared adapter file."""
import re

from ....errors import OpenAIError
from ..base import SiteAdapter


class QwenAdapter(SiteAdapter):
    async def list_projects(self, page):
        await page.goto(self.origin, wait_until="domcontentloaded")
        await page.locator(".project-list").wait_for()
        names = None
        for _ in range(12):
            await page.wait_for_timeout(500)
            current = await page.locator(".project-item-text").all_text_contents()
            if current and current == names:
                break
            names = current
        names = [n for n in (names or []) if n != "New Project"]
        out = []
        for name in names:
            item = page.locator(".project-item-text").filter(has_text=re.compile("^" + re.escape(name) + "$"))
            if await item.count() != 1:
                raise OpenAIError(409, "project_ambiguous", "Có project trùng tên; cần chọn trực tiếp trên website")
            await item.click()
            await page.wait_for_url(re.compile(r"/p/[^/?]+$"), timeout=30000)
            out.append({"title": name, "remote_url": page.url})
        return out

    async def create_project(self, page, title, instructions, files):
        await page.goto(self.origin, wait_until="domcontentloaded")
        await page.locator(".project-item-text").filter(has_text=re.compile("^New Project$")).click()
        dialog = page.get_by_role("dialog", name="New Project", exact=True)
        await dialog.get_by_role("textbox", name="Project Name", exact=True).fill(title)
        if instructions or files:
            await dialog.get_by_text("Advanced Settings", exact=True).click()
        if instructions:
            await dialog.locator("textarea").fill(instructions)
        for file in files:
            async with page.expect_file_chooser() as pending:
                await dialog.get_by_role("button", name="Add Files", exact=True).click()
            await (await pending.value).set_files(file)
            await dialog.get_by_text(file["name"], exact=True).wait_for()
        await dialog.get_by_role("button", name="Create project", exact=True).click()
        await page.wait_for_url(re.compile(r"/p/[^/?]+$"))
        await page.locator(".pcht__name").filter(has_text=title).wait_for()
        return page.url

    async def delete_project(self, page, url):
        self.validate_conversation(url)
        await page.goto(url, wait_until="domcontentloaded")
        await page.locator(".herder-project-edit-btn").click()
        await page.get_by_role("menuitem", name="Delete Project", exact=True).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_role("button", name=re.compile(r"^Delete", re.I)).click()
        await page.wait_for_url(lambda actual: "/p/" not in str(actual))

    async def thinking(self, page, enabled: bool):
        control = page.locator(".qwen-thinking-selector")
        if await control.count() != 1 or not await control.is_visible():
            raise OpenAIError(422, "thinking_unavailable", "Account/model hiện tại không có điều khiển Thinking")
        desired = "Thinking" if enabled else "Fast"
        label = control.locator(".qwen-chat-v2-dropdown-menu-select-label")
        if (await label.inner_text()).strip() != desired:
            await control.click()
            option = page.get_by_role("menuitem", name=desired, exact=True)
            if await option.count() != 1:
                raise OpenAIError(422, "thinking_unknown", "Không xác định được lựa chọn Thinking; cần kiểm chứng DOM")
            await option.click()
        if (await label.inner_text()).strip() != desired:
            raise OpenAIError(422, "thinking_not_applied", "Website không xác nhận trạng thái Thinking")
