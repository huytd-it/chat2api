<script lang="ts">
  import { flowNodeLabel, type FlowNode } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import { Trash } from "phosphor-svelte";

  interface Props {
    node: FlowNode;
    onChange: (node: FlowNode) => void;
    onDelete: (id: string) => void;
  }
  let { node, onChange, onDelete }: Props = $props();

  function params(): Record<string, unknown> {
    return { ...(node.params ?? {}) };
  }

  function set(key: string, value: unknown) {
    const next = params();
    if (value === "" || value === null || value === undefined) delete next[key];
    else next[key] = value;
    onChange({ ...node, params: next });
  }

  function get(key: string, fallback: string = ""): string {
    const v = params()[key];
    return v === null || v === undefined ? fallback : String(v);
  }

  function getBool(key: string, fallback = false): boolean {
    const v = params()[key];
    return typeof v === "boolean" ? v : fallback;
  }

  function getInt(key: string): string {
    const v = params()[key];
    return typeof v === "number" ? String(v) : "";
  }

  function setInt(key: string, raw: string) {
    const s = raw.trim();
    if (!s) set(key, undefined);
    else {
      const n = Number(s);
      if (Number.isFinite(n)) set(key, Math.trunc(n));
    }
  }

  const doneTypes = ["stable_text", "copy_button", "selector_appear", "selector_disappear"];
  const scopes = ["after", "inside", "page"];
</script>

<div class="grid gap-3">
  <div class="flex items-center gap-2">
    <div class="min-w-0 flex-1">
      <div class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {flowNodeLabel(node.type)}
      </div>
      <div class="truncate font-data text-xs text-muted-foreground">{node.id}</div>
    </div>
    {#if node.type !== "start" && node.type !== "output"}
      <Button variant="ghost" size="sm" title="Xóa node" onclick={() => onDelete(node.id)}>
        <Trash size={15} />
      </Button>
    {/if}
  </div>

  {#if node.type === "goto-url"}
    <div class="grid gap-1.5">
      <Label>URL</Label>
      <Input value={get("url")} oninput={(e) => set("url", e.currentTarget.value)} placeholder="https://…" />
    </div>
  {:else if node.type === "wait-ready"}
    <div class="grid grid-cols-2 gap-2">
      <div class="grid gap-1.5">
        <Label>Chờ sau hiện (ms)</Label>
        <Input value={getInt("delay_ms")} oninput={(e) => setInt("delay_ms", e.currentTarget.value)} placeholder="1200" />
      </div>
      <div class="grid gap-1.5">
        <Label>Timeout (ms)</Label>
        <Input value={getInt("timeout_ms")} oninput={(e) => setInt("timeout_ms", e.currentTarget.value)} placeholder="20000" />
      </div>
    </div>
  {:else if node.type === "new-chat"}
    <div class="grid gap-1.5">
      <Label>URL chat mới (tùy chọn)</Label>
      <Input value={get("url")} oninput={(e) => set("url", e.currentTarget.value)} placeholder="https://…" />
    </div>
    <div class="grid gap-1.5">
      <Label>Selector nút New chat (tùy chọn)</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} placeholder="a.new-chat" />
    </div>
  {:else if node.type === "assign-account"}
    <div class="grid grid-cols-2 gap-2">
      <div class="grid gap-1.5">
        <Label>Chiến lược</Label>
        <Input value={get("strategy", "round_robin")} oninput={(e) => set("strategy", e.currentTarget.value)} />
      </div>
      <div class="grid gap-1.5">
        <Label>Quota</Label>
        <Input value={getInt("quota") || "50"} oninput={(e) => setInt("quota", e.currentTarget.value)} />
      </div>
    </div>
  {:else if node.type === "check-trial-limit"}
    <div class="grid gap-1.5">
      <Label>Giới hạn dùng thử</Label>
      <Input value={getInt("limit")} oninput={(e) => setInt("limit", e.currentTarget.value)} placeholder="20" />
    </div>
  {:else if node.type === "action-sequence"}
    <div class="grid gap-1.5">
      <Label>Chuỗi thao tác</Label>
      <Textarea value={get("action")} oninput={(e) => set("action", e.currentTarget.value)} placeholder="click:.tab;click:[data-v=image]" rows={3} />
      <p class="text-[11px] text-muted-foreground">Nhiều bước ngăn bằng “;”: click:&lt;selector&gt; | select:&lt;selector&gt;</p>
    </div>
  {:else if node.type === "select-model"}
    <div class="grid gap-1.5">
      <Label>Selector dropdown (tùy chọn)</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} placeholder=".model-btn" />
    </div>
    <div class="grid gap-1.5">
      <Label>Thao tác mở dropdown (tùy chọn)</Label>
      <Input value={get("prelude_action")} oninput={(e) => set("prelude_action", e.currentTarget.value)} placeholder="click:.model-btn" />
    </div>
    <div class="grid gap-1.5">
      <Label>Đường bấm tới model</Label>
      <Input value={get("model_action") || get("action")} oninput={(e) => set("model_action", e.currentTarget.value)} placeholder="click:[data-model=x]" />
    </div>
    <div class="grid gap-1.5">
      <Label>Value / model</Label>
      <Input value={get("value") || get("model")} oninput={(e) => set("value", e.currentTarget.value)} />
    </div>
  {:else if node.type === "fill-input"}
    <div class="grid gap-1.5">
      <Label>Selector ô nhập</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} placeholder="textarea" />
    </div>
    <div class="grid gap-1.5">
      <Label>Chế độ nhập</Label>
      <Select.Root type="single" value={get("mode", "fill")} onValueChange={(v) => v && set("mode", String(v))}>
        <Select.Trigger>{get("mode", "fill")}</Select.Trigger>
        <Select.Content>
          <Select.Item value="fill">fill</Select.Item>
          <Select.Item value="type">type</Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
  {:else if node.type === "submit-click"}
    <div class="grid gap-1.5">
      <Label>Selector nút gửi</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} placeholder="button.send" />
    </div>
  {:else if node.type === "wait-done-signal"}
    <div class="grid gap-1.5">
      <Label>Kiểu chờ</Label>
      <Select.Root type="single" value={get("type", "stable_text")} onValueChange={(v) => v && set("type", String(v))}>
        <Select.Trigger>{get("type", "stable_text")}</Select.Trigger>
        <Select.Content>
          {#each doneTypes as t (t)}<Select.Item value={t}>{t}</Select.Item>{/each}
        </Select.Content>
      </Select.Root>
    </div>
    <div class="grid gap-1.5">
      <Label>Selector (copy/selector_*)</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} />
    </div>
    <div class="grid grid-cols-2 gap-2">
      <div class="grid gap-1.5">
        <Label>Yên tĩnh (ms)</Label>
        <Input value={getInt("quiet_ms")} oninput={(e) => setInt("quiet_ms", e.currentTarget.value)} />
      </div>
      <div class="grid gap-1.5">
        <Label>Timeout (ms)</Label>
        <Input value={getInt("timeout_ms")} oninput={(e) => setInt("timeout_ms", e.currentTarget.value)} />
      </div>
    </div>
    <div class="grid gap-1.5">
      <Label>Phạm vi copy</Label>
      <Select.Root type="single" value={get("scope", "after")} onValueChange={(v) => v && set("scope", String(v))}>
        <Select.Trigger>{get("scope", "after")}</Select.Trigger>
        <Select.Content>
          {#each scopes as s (s)}<Select.Item value={s}>{s}</Select.Item>{/each}
        </Select.Content>
      </Select.Root>
    </div>
    <label class="flex items-center gap-2 text-sm">
      <Switch checked={getBool("use_copy_result", false)} onCheckedChange={(v) => set("use_copy_result", Boolean(v))} />
      Lấy kết quả từ nút Copy
    </label>
    <div class="grid gap-1.5">
      <Label>Loại trừ / fallback yên tĩnh (ms)</Label>
      <div class="grid grid-cols-2 gap-2">
        <Input value={get("exclude")} oninput={(e) => set("exclude", e.currentTarget.value)} placeholder="exclude" />
        <Input value={getInt("fallback_quiet_ms")} oninput={(e) => setInt("fallback_quiet_ms", e.currentTarget.value)} placeholder="15000" />
      </div>
    </div>
  {:else if node.type === "wait-media" || node.type === "extract-media"}
    <div class="grid gap-1.5">
      <Label>Media selector</Label>
      <Input value={get("media_selector")} oninput={(e) => set("media_selector", e.currentTarget.value)} placeholder="img.result" />
    </div>
    <div class="grid gap-1.5">
      <Label>Copy selector</Label>
      <Input value={get("copy_selector")} oninput={(e) => set("copy_selector", e.currentTarget.value)} />
    </div>
    <div class="grid grid-cols-2 gap-2">
      <div class="grid gap-1.5">
        <Label>Phạm vi</Label>
        <Input value={get("copy_scope", "after")} oninput={(e) => set("copy_scope", e.currentTarget.value)} />
      </div>
      <div class="grid gap-1.5">
        <Label>Loại trừ</Label>
        <Input value={get("copy_exclude")} oninput={(e) => set("copy_exclude", e.currentTarget.value)} />
      </div>
    </div>
  {:else if node.type === "extract-text"}
    <div class="grid gap-1.5">
      <Label>Selector câu trả lời</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} placeholder=".msg" />
    </div>
    <div class="grid gap-1.5">
      <Label>Định dạng</Label>
      <Input value={get("format")} oninput={(e) => set("format", e.currentTarget.value)} placeholder="markdown" />
    </div>
    <label class="flex items-center gap-2 text-sm">
      <Switch checked={getBool("capture_html", false)} onCheckedChange={(v) => set("capture_html", Boolean(v))} />
      Chụp HTML gốc
    </label>
  {:else if node.type === "copy-button"}
    <div class="grid gap-1.5">
      <Label>Selector nút Copy</Label>
      <Input value={get("selector")} oninput={(e) => set("selector", e.currentTarget.value)} />
    </div>
    <label class="flex items-center gap-2 text-sm">
      <Switch checked={getBool("use_copy_result", true)} onCheckedChange={(v) => set("use_copy_result", Boolean(v))} />
      Dùng nội dung clipboard
    </label>
  {:else if node.type === "condition"}
    <div class="grid gap-1.5">
      <Label>Biểu thức rẽ nhánh</Label>
      <Input value={get("expression") || get("value")} oninput={(e) => set("expression", e.currentTarget.value)} placeholder="copied == true" />
      <p class="text-[11px] text-muted-foreground">Tên biến trong ngữ cảnh, hoặc “biến == giá trị”. Nhánh true/false theo handle nối ra.</p>
    </div>
  {:else if node.type === "delay"}
    <div class="grid gap-1.5">
      <Label>Chờ (ms)</Label>
      <Input value={getInt("ms")} oninput={(e) => setInt("ms", e.currentTarget.value)} placeholder="500" />
    </div>
  {:else if node.type === "eval-js"}
    <div class="grid gap-1.5">
      <Label>Mã JS</Label>
      <Textarea value={get("code")} oninput={(e) => set("code", e.currentTarget.value)} rows={4} />
    </div>
    <div class="grid gap-1.5">
      <Label>Lưu vào biến (tùy chọn)</Label>
      <Input value={get("as")} oninput={(e) => set("as", e.currentTarget.value)} />
    </div>
  {:else if node.type === "set-variable"}
    <div class="grid gap-1.5">
      <Label>Tên biến</Label>
      <Input value={get("name")} oninput={(e) => set("name", e.currentTarget.value)} />
    </div>
    <div class="grid gap-1.5">
      <Label>Giá trị (JSON)</Label>
      <Input value={get("value")} oninput={(e) => {
        const raw = e.currentTarget.value;
        try { set("value", JSON.parse(raw)); } catch { set("value", raw); }
      }} />
    </div>
  {:else}
    <p class="text-xs text-muted-foreground">Node {node.type} không có tham số cấu hình.</p>
  {/if}
</div>
