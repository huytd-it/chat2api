import type { ManualRecipeSpec } from "./api";

export type DoneType = "stable_text" | "selector_appear" | "selector_disappear" | "copy_button";
export type InputMode = "fill" | "type";
export type SubmitMode = "enter" | "click";
export type NewChatMode = "none" | "selector" | "url";
export type CopyScope = "after" | "inside" | "page";
export type LoginStrategy = "round_robin" | "fill_first";

export const DONE_TYPE_LABEL: Record<DoneType, string> = {
  stable_text: "Text đứng yên",
  selector_appear: "Selector xuất hiện",
  selector_disappear: "Selector biến mất",
  copy_button: "Nút Copy hiện ra",
};

/** Giá trị của một ô <input type="number">. Svelte ép kiểu `bind:value` theo
 * type của thẻ input LÚC CHẠY, nên ô số trả về number, và ô trống trả về
 * `null` — không phải chuỗi rỗng như ô text. */
type NumField = string | number | null;

function str(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function dict(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Trạng thái của biểu mẫu recipe, dùng chung cho cả tạo mới lẫn sửa.
 *
 * Mọi ô số đi qua `toInt()` chứ không đọc thẳng: cùng một ô có thể giữ chuỗi
 * (vừa nạp từ recipe.yaml), số (người dùng vừa gõ) hay `null` (vừa xóa trắng)
 * — xem `NumField`.
 */
export class RecipeForm {
  url = $state("");
  inputSelector = $state("");
  inputMode = $state<InputMode>("fill");
  submitMode = $state<SubmitMode>("enter");
  submitSelector = $state("");
  lastMessageSelector = $state("");
  doneType = $state<DoneType>("copy_button");
  doneSelector = $state("");
  quietMs = $state<NumField>("");
  timeoutMs = $state<NumField>("");
  copyScope = $state<CopyScope>("after");
  copyFallbackMs = $state<NumField>("");
  copyExclude = $state("");
  useCopyResult = $state(true);
  markdownFormat = $state(false);
  captureHtml = $state(false);
  newChatMode = $state<NewChatMode>("none");
  newChatSelector = $state("");
  newChatUrl = $state("");
  keepContext = $state(true);
  anonTrialLimit = $state<NumField>("");
  loginStrategy = $state<LoginStrategy>("round_robin");
  loginQuota = $state<NumField>(50);
  legacyStorageState = $state("");
  accountNames = $state<string[]>([]);
  accountStorageStates = $state<string[]>([]);
  models = $state<string[]>([""]);
  modelActions = $state<string[]>([""]);
  modelValues = $state<string[]>([""]);
  readyDelayMs = $state<NumField>("");
  inputDelayMs = $state<NumField>("");
  readyTimeoutMs = $state<NumField>("");

  /** Lỗi của lần `validate()` gần nhất, rỗng khi biểu mẫu hợp lệ. */
  error = $state("");

  addModel() {
    this.models = [...this.models, ""];
    this.modelActions = [...this.modelActions, ""];
    this.modelValues = [...this.modelValues, ""];
  }

  removeModel(index: number) {
    this.models = this.models.filter((_, i) => i !== index);
    this.modelActions = this.modelActions.filter((_, i) => i !== index);
    this.modelValues = this.modelValues.filter((_, i) => i !== index);
  }

  setModels(items: { id: string; action?: string; value?: string }[]) {
    this.models = items.map((item) => item.id);
    this.modelActions = items.map((item) => item.action ?? "");
    this.modelValues = items.map((item) => item.value ?? "");
  }

  addAccount() {
    this.accountNames = [...this.accountNames, ""];
    this.accountStorageStates = [...this.accountStorageStates, ""];
  }

  removeAccount(index: number) {
    this.accountNames = this.accountNames.filter((_, i) => i !== index);
    this.accountStorageStates = this.accountStorageStates.filter((_, i) => i !== index);
  }

  reset() {
    this.url = "";
    this.inputSelector = "";
    this.inputMode = "fill";
    this.submitMode = "enter";
    this.submitSelector = "";
    this.lastMessageSelector = "";
    this.doneType = "copy_button";
    this.doneSelector = "";
    this.quietMs = "";
    this.timeoutMs = "";
    this.copyScope = "after";
    this.copyFallbackMs = "";
    this.copyExclude = "";
    this.useCopyResult = true;
    this.markdownFormat = false;
    this.captureHtml = false;
    this.newChatMode = "none";
    this.newChatSelector = "";
    this.newChatUrl = "";
    this.keepContext = true;
    this.anonTrialLimit = "";
    this.loginStrategy = "round_robin";
    this.loginQuota = 50;
    this.legacyStorageState = "";
    this.accountNames = [];
    this.accountStorageStates = [];
    this.models = [""];
    this.modelActions = [""];
    this.modelValues = [""];
    this.readyDelayMs = "";
    this.inputDelayMs = "";
    this.readyTimeoutMs = "";
    this.error = "";
  }

  /** Nạp biểu mẫu từ một recipe.yaml đã parse. */
  load(recipe: Record<string, unknown>) {
    this.reset();
    const prompt = dict(recipe.prompt);
    const response = dict(recipe.response);
    const done = dict(response.done_signal);
    const newChat = dict(recipe.new_chat);
    const timing = dict(recipe.timing);
    const login = dict(recipe.login);

    this.url = str(recipe.url);
    this.inputSelector = str(prompt.input_selector);
    this.inputMode = prompt.input_mode === "type" ? "type" : "fill";
    const submit = str(prompt.submit) || "Enter";
    if (submit.startsWith("click:")) {
      this.submitMode = "click";
      this.submitSelector = submit.slice("click:".length);
    }

    this.lastMessageSelector = str(response.last_message_selector);
    this.markdownFormat = response.format === "markdown";
    this.captureHtml = response.capture_html === true;
    const doneType = str(done.type) as DoneType;
    if (doneType in DONE_TYPE_LABEL) this.doneType = doneType;
    this.doneSelector = str(done.selector);
    this.quietMs = str(done.quiet_ms);
    this.timeoutMs = str(done.timeout_ms);
    if (done.scope === "inside" || done.scope === "page") this.copyScope = done.scope;
    this.copyFallbackMs = str(done.fallback_quiet_ms);
    this.copyExclude = str(done.exclude);
    this.useCopyResult = done.use_copy_result === true;

    if (newChat.selector) {
      this.newChatMode = "selector";
      this.newChatSelector = str(newChat.selector);
    } else if (newChat.url) {
      this.newChatMode = "url";
      this.newChatUrl = str(newChat.url);
    }

    this.readyDelayMs = str(timing.ready_delay_ms);
    this.inputDelayMs = str(timing.input_delay_ms);
    this.readyTimeoutMs = str(timing.ready_timeout_ms);
    this.anonTrialLimit = str(login.anon_trial_limit);
    this.loginStrategy = login.strategy === "fill_first" ? "fill_first" : "round_robin";
    this.loginQuota = str(login.quota || 50);
    this.legacyStorageState = str(login.storage_state);
    const accountItems = Array.isArray(login.accounts) ? login.accounts.map((item) => dict(item)) : [];
    this.accountNames = accountItems.map((item) => str(item.name));
    this.accountStorageStates = accountItems.map((item) => str(item.storage_state));
    this.keepContext = recipe.keep_context !== false;

    const models = Array.isArray(recipe.models) ? recipe.models : [];
    const items = models.map((m) => dict(m)).filter((m) => str(m.id));
    this.setModels(items.length
      ? items.map((m) => ({ id: str(m.id), action: str(m.action), value: str(m.value) }))
      : [{ id: "" }]);
  }

  /** Ô trống -> undefined; số hợp lệ -> number; chuỗi hỏng -> NaN (validate bắt lỗi). */
  private toInt(raw: NumField): number | undefined {
    if (raw === null || raw === undefined) return undefined;
    if (typeof raw === "number") return Number.isFinite(raw) ? Math.trunc(raw) : NaN;
    const s = raw.trim();
    if (!s) return undefined;
    const n = Number(s);
    return Number.isFinite(n) ? Math.trunc(n) : NaN;
  }

  private nums() {
    return {
      quiet_ms: this.toInt(this.quietMs),
      timeout_ms: this.toInt(this.timeoutMs),
      fallback_quiet_ms: this.toInt(this.copyFallbackMs),
      anon_trial_limit: this.toInt(this.anonTrialLimit),
      login_quota: this.toInt(this.loginQuota),
      ready_delay_ms: this.toInt(this.readyDelayMs),
      input_delay_ms: this.toInt(this.inputDelayMs),
      ready_timeout_ms: this.toInt(this.readyTimeoutMs),
    };
  }

  private modelSpecs(): { id: string; action?: string; value?: string }[] {
    return this.models.flatMap((raw, i) => {
      const id = raw.trim();
      if (!id) return [];
      const action = this.modelActions[i]?.trim();
      const value = this.modelValues[i]?.trim();
      return [{ id, ...(action ? { action } : {}), ...(value ? { value } : {}) }];
    });
  }

  private accountSpecs(): { name: string; storage_state: string }[] {
    return this.accountNames.flatMap((raw, i) => {
      const name = raw.trim();
      const storage_state = this.accountStorageStates[i]?.trim();
      return name || storage_state ? [{ name, storage_state }] : [];
    });
  }

  /** Đặt `error` và trả về false ở lỗi ĐẦU TIÊN gặp phải. */
  validate(): boolean {
    this.error = "";
    const fail = (message: string) => {
      this.error = message;
      return false;
    };
    const url = this.url.trim();
    if (!url) return fail("Nhập URL trang chat.");
    try {
      new URL(url);
    } catch {
      return fail("URL không hợp lệ.");
    }
    if (!this.inputSelector.trim()) return fail("Nhập CSS selector của ô nhập tin nhắn.");
    if (this.submitMode === "click" && !this.submitSelector.trim())
      return fail("Nhập CSS selector của nút gửi.");
    if (!this.lastMessageSelector.trim()) return fail("Nhập CSS selector của khối tin nhắn AI.");
    if ((this.doneType === "selector_appear" || this.doneType === "selector_disappear")
      && !this.doneSelector.trim())
      return fail("Nhập CSS selector cho tín hiệu hoàn tất.");
    if (!this.modelSpecs().length) return fail("Cần ít nhất một model id.");
    if (this.modelActions.some((action) => action.trim()
      && action.split(";").some((step) => !/^(click|select):.+/.test(step.trim()))))
      return fail('Action model phải có dạng "click:<selector>" hoặc "select:<selector>".');
    if (this.newChatMode === "selector" && !this.newChatSelector.trim())
      return fail("Nhập selector nút tạo chat mới.");
    if (this.newChatMode === "url" && !this.newChatUrl.trim()) return fail("Nhập URL mở chat mới.");
    const accounts = this.accountSpecs();
    if (accounts.some((account) => !account.name || !account.storage_state))
      return fail("Mỗi account cần đủ tên và đường dẫn storage state.");
    for (const [key, value] of Object.entries(this.nums())) {
      if (value !== undefined && Number.isNaN(value))
        return fail(`Trường "${key}" phải là số nguyên >= 0.`);
    }
    if ((this.nums().login_quota ?? 0) < 1) return fail("Quota account phải là số nguyên dương.");
    return true;
  }

  /** Recipe đầy đủ để TẠO MỚI — bỏ hẳn những khóa người dùng để trống. */
  toSpec(slug: string): ManualRecipeSpec {
    const n = this.nums();
    const spec: ManualRecipeSpec = {
      slug,
      url: this.url.trim(),
      prompt: {
        input_selector: this.inputSelector.trim(),
        input_mode: this.inputMode,
        submit: this.submitMode === "enter" ? "Enter" : `click:${this.submitSelector.trim()}`,
      },
      response: {
        last_message_selector: this.lastMessageSelector.trim(),
        done_signal: {
          type: this.doneType,
          ...(this.doneSelector.trim() ? { selector: this.doneSelector.trim() } : {}),
          ...(n.quiet_ms !== undefined ? { quiet_ms: n.quiet_ms } : {}),
          ...(n.timeout_ms !== undefined ? { timeout_ms: n.timeout_ms } : {}),
          ...(this.doneType === "copy_button" ? { scope: this.copyScope } : {}),
          ...(this.doneType === "copy_button" && this.useCopyResult
            ? { use_copy_result: true }
            : {}),
          ...(this.doneType === "copy_button" && this.copyExclude.trim()
            ? { exclude: this.copyExclude.trim() }
            : {}),
          ...(this.doneType === "copy_button" && n.fallback_quiet_ms !== undefined
            ? { fallback_quiet_ms: n.fallback_quiet_ms }
            : {}),
        },
        ...(this.markdownFormat ? { format: "markdown" } : {}),
        ...(this.captureHtml ? { capture_html: true } : {}),
      },
      models: this.modelSpecs(),
      keep_context: this.keepContext,
      ...(n.anon_trial_limit !== undefined ? { anon_trial_limit: n.anon_trial_limit } : {}),
      login: {
        strategy: this.loginStrategy,
        quota: n.login_quota ?? 50,
        ...(this.legacyStorageState.trim() ? { storage_state: this.legacyStorageState.trim() } : {}),
        ...(this.accountSpecs().length ? { accounts: this.accountSpecs() } : {}),
      },
    };
    if (this.newChatMode === "selector") spec.new_chat = { selector: this.newChatSelector.trim() };
    else if (this.newChatMode === "url") spec.new_chat = { url: this.newChatUrl.trim() };
    if (n.ready_delay_ms !== undefined || n.input_delay_ms !== undefined
      || n.ready_timeout_ms !== undefined) {
      spec.timing = {
        ...(n.ready_delay_ms !== undefined ? { ready_delay_ms: n.ready_delay_ms } : {}),
        ...(n.input_delay_ms !== undefined ? { input_delay_ms: n.input_delay_ms } : {}),
        ...(n.ready_timeout_ms !== undefined ? { ready_timeout_ms: n.ready_timeout_ms } : {}),
      };
    }
    return spec;
  }

  /** Mảnh recipe để SỬA một recipe đã có. Server deep-merge nên mọi ô người
   * dùng vừa xóa trắng phải nói rõ là `null` — nếu chỉ bỏ khóa, giá trị cũ
   * trong file sẽ sống sót và biểu mẫu nói dối về recipe đang chạy. */
  toPatch(): Record<string, unknown> {
    const n = this.nums();
    const orNull = (value: number | undefined) => (value === undefined ? null : value);
    const copy = this.doneType === "copy_button";
    return {
      url: this.url.trim(),
      prompt: {
        input_selector: this.inputSelector.trim(),
        input_mode: this.inputMode,
        submit: this.submitMode === "enter" ? "Enter" : `click:${this.submitSelector.trim()}`,
      },
      response: {
        last_message_selector: this.lastMessageSelector.trim(),
        done_signal: {
          type: this.doneType,
          selector: this.doneSelector.trim() || null,
          quiet_ms: orNull(n.quiet_ms),
          timeout_ms: orNull(n.timeout_ms),
          scope: copy ? this.copyScope : null,
          use_copy_result: copy ? this.useCopyResult : null,
          exclude: copy ? this.copyExclude.trim() || null : null,
          fallback_quiet_ms: copy ? orNull(n.fallback_quiet_ms) : null,
        },
        format: this.markdownFormat ? "markdown" : null,
        capture_html: this.captureHtml ? true : null,
      },
      models: this.modelSpecs(),
      keep_context: this.keepContext,
      new_chat:
        this.newChatMode === "selector"
          ? { selector: this.newChatSelector.trim(), url: null }
          : this.newChatMode === "url"
            ? { url: this.newChatUrl.trim(), selector: null }
            : null,
      timing: {
        ready_delay_ms: orNull(n.ready_delay_ms),
        input_delay_ms: orNull(n.input_delay_ms),
        ready_timeout_ms: orNull(n.ready_timeout_ms),
      },
      login: {
        anon_trial_limit: orNull(n.anon_trial_limit),
        strategy: this.loginStrategy,
        quota: n.login_quota ?? 50,
        storage_state: this.legacyStorageState.trim() || null,
        accounts: this.accountSpecs().length ? this.accountSpecs() : null,
      },
    };
  }
}
