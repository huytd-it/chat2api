"""Site-specific controls. Missing/ambiguous controls are errors, never success."""
from urllib.parse import urlsplit
import re

from ..errors import OpenAIError


class SiteAdapter:
    def __init__(self, origin: str):
        self.origin = origin

    def validate_conversation(self, url: str):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != urlsplit(self.origin).netloc:
            raise OpenAIError(409, "conversation_invalid", "URL hội thoại không thuộc website/account đã chọn")

    async def thinking(self, page, enabled: bool):
        raise OpenAIError(422, "thinking_unknown", "Chưa kiểm chứng điều khiển Thinking cho account/model này")

    async def list_projects(self, page):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")

    async def create_project(self, page, title, instructions, files):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")

    async def delete_project(self, page, url):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")


class QwenAdapter(SiteAdapter):
    async def list_projects(self, page):
        await page.goto(self.origin, wait_until="domcontentloaded")
        await page.locator(".project-list").wait_for()
        # Items are rendered after the empty container mounts.
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


class ChatGPTAdapter(SiteAdapter):
    """Selectors verified on chatgpt.com Free accounts (Oct 2026).

    Project pages live at ``/g/g-p-<id>/project``; a chat started there becomes
    ``/g/g-p-<id>/c/<chat>``. Sidebar overlays swallow real mouse clicks in a
    persistent profile, so project controls are activated with ``force`` —
    Playwright still dispatches the same click event to the target element.
    """

    PROJECT_URL = re.compile(r"/g/g-p-[^/]+(?:/project|/c/[^/?]+)/?(?:[?#].*)?$")

    def validate_conversation(self, url: str):
        super().validate_conversation(url)
        parsed = urlsplit(url)
        if parsed.path in ("", "/") or not (
                re.search(r"/c/[^/]+/?$", parsed.path) or self.PROJECT_URL.search(parsed.path)):
            raise OpenAIError(409, "conversation_invalid", "URL không phải project/hội thoại ChatGPT")

    async def _project_rows(self, page):
        """Read project rows from their data attributes.

        ChatGPT only paints the disclosure / actions buttons on hover, but each
        project row permanently carries its id and label, so listing must not
        depend on hover-only controls.
        """
        await page.goto(self.origin, wait_until="domcontentloaded")
        nav = page.locator('nav[aria-label="Chat history"]')
        await nav.wait_for(state="visible")
        rows = nav.locator("[data-app-action-sidebar-project-id]")
        try:
            await rows.first.wait_for(state="attached", timeout=20000)
        except Exception:
            pass
        raw = await rows.evaluate_all(
            "els => els.map(e => ({id: e.getAttribute('data-app-action-sidebar-project-id'),"
            " title: e.getAttribute('data-app-action-sidebar-project-label')}))")
        out = []
        seen = set()
        for row in raw:
            ident = (row.get("id") or "").strip()
            title = (row.get("title") or "").strip()
            if not ident or not title or ident in seen:
                continue
            seen.add(ident)
            out.append({"id": ident, "title": title})
        return out

    async def list_projects(self, page):
        return [{"title": row["title"],
                 "remote_url": f"https://chatgpt.com/g/{row['id']}/project"}
                for row in await self._project_rows(page)]

    async def _open_settings(self, page):
        actions = page.get_by_role("button", name="Project actions", exact=True)
        try:
            await actions.first.wait_for(state="visible", timeout=30000)
        except Exception:
            raise OpenAIError(422, "project_controls_unknown", "Không xác định được menu Project actions")
        if await actions.count() != 1:
            raise OpenAIError(422, "project_controls_unknown", "Không xác định được menu Project actions")
        await actions.first.click(force=True)
        await page.get_by_role("menuitem", name="Project settings", exact=True).click()
        dialog = page.get_by_role("dialog", name="Project settings", exact=True)
        await dialog.wait_for(state="visible")
        return dialog

    async def create_project(self, page, title, instructions, files):
        await page.goto(self.origin, wait_until="domcontentloaded")
        add = page.locator('button[aria-label="Add new project"]')
        await add.wait_for(state="visible")
        await add.press("Enter")
        dialog = page.get_by_role("dialog", name="Create project", exact=True)
        await dialog.wait_for(state="visible")
        await dialog.locator("input[name=project-name]").fill(title)
        create = dialog.get_by_role("button", name="Create project", exact=True)
        await create.click()
        await page.wait_for_url(self.PROJECT_URL, timeout=30000)
        url = page.url

        if instructions:
            settings = await self._open_settings(page)
            await settings.locator("textarea[name=project-instructions]").fill(instructions)
            save = settings.get_by_role("button", name="Save", exact=True)
            if await save.count() != 1:
                await settings.get_by_role("button", name="Close dialog").click()
                raise OpenAIError(422, "project_instructions_not_saved",
                                  "Website không hiện nút Save cho Instructions")
            await save.click()
            await settings.wait_for(state="hidden", timeout=20000)
            # Re-open and verify, so a silent UI reset cannot pass as success.
            verify = await self._open_settings(page)
            saved = await verify.locator("textarea[name=project-instructions]").input_value()
            await verify.get_by_role("button", name="Close dialog").click()
            await verify.wait_for(state="hidden", timeout=20000)
            if saved != instructions:
                raise OpenAIError(422, "project_instructions_not_saved",
                                  "Instructions không được website lưu đúng")

        if files:
            await page.get_by_role("tab", name="Sources", exact=True).click()
            await page.get_by_role("button", name="Add sources", exact=True).click()
            for file in files:
                payload = {"name": file["name"], "mimeType": file["mimeType"], "buffer": file["buffer"]}
                try:
                    async with page.expect_file_chooser(timeout=8000) as pending:
                        await page.get_by_role("button", name="Upload", exact=True).click()
                    await (await pending.value).set_files(payload)
                except Exception:
                    hidden = page.locator('input[type="file"]')
                    if await hidden.count() != 1:
                        raise OpenAIError(422, "project_files_unknown",
                                          "Không mở được hộp chọn file của project")
                    await hidden.set_input_files(payload)
                panel = page.get_by_role("tabpanel", name="Sources", exact=True)
                await panel.get_by_text(file["name"], exact=True).wait_for(timeout=120000)
                close = page.get_by_role("button", name="Close dialog", exact=True)
                if await close.count() and await close.first.is_visible():
                    await close.first.click()
        # The create flow may still be mid-navigation; the caller stores this
        # URL as the canonical project, so wait for it to settle.
        await page.wait_for_timeout(800)
        return url

    async def delete_project(self, page, url):
        self.validate_conversation(url)
        if not self.PROJECT_URL.search(urlsplit(url).path):
            raise OpenAIError(409, "conversation_invalid", "URL không phải project ChatGPT")
        await page.goto(url, wait_until="domcontentloaded")
        settings = await self._open_settings(page)
        await settings.get_by_role("button", name="Delete project", exact=True).click()
        confirm = page.get_by_role("dialog", name=re.compile("^Delete this project", re.I))
        await confirm.wait_for(state="visible")
        await confirm.get_by_role("button", name="Delete from Chat and Work", exact=True).click()
        await page.wait_for_url(lambda actual: "/g/g-p-" not in str(actual), timeout=30000)

    async def thinking(self, page, enabled: bool):
        control = page.get_by_role("button", name="Think", exact=True)
        if await control.count() != 1:
            raise OpenAIError(422, "thinking_unknown", "Không xác định được nút Think")
        button = control.first
        if not await button.is_visible() or await button.is_disabled():
            raise OpenAIError(422, "thinking_unavailable",
                              "Account/model/ngữ cảnh hiện tại không bật được Thinking")
        current = (await button.get_attribute("aria-pressed")) == "true"
        if current != enabled:
            await button.click()
        deadline = 0
        while True:
            pressed = (await button.get_attribute("aria-pressed")) == "true"
            if pressed == enabled:
                return
            if deadline >= 20:
                raise OpenAIError(422, "thinking_not_applied", "Website không xác nhận trạng thái Think")
            await page.wait_for_timeout(100)
            deadline += 1


def adapter_for(url: str) -> SiteAdapter:
    host = urlsplit(url).hostname
    if host == "chat.qwen.ai":
        return QwenAdapter("https://chat.qwen.ai")
    if host == "chatgpt.com":
        return ChatGPTAdapter("https://chatgpt.com")
    return SiteAdapter(url)
