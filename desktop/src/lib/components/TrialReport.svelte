<script lang="ts">
  import { Check, MinusCircle, Warning, X } from "phosphor-svelte";
  import { FLOW_LABELS, type TrialResult, type TrialStep } from "../api";

  interface Props {
    result: TrialResult;
  }
  let { result }: Props = $props();

  /** Bước hỏng đầu tiên — chỗ người sửa recipe phải nhìn trước hết. */
  const broken = $derived((result.steps ?? []).find((s) => s.status === "fail") ?? null);
  const warned = $derived((result.steps ?? []).filter((s) => s.status === "warn").length);

  function tone(status: TrialStep["status"]) {
    if (status === "fail") return "text-destructive";
    if (status === "warn") return "text-warning";
    if (status === "skip") return "text-muted-foreground";
    return "text-success";
  }

  /** Nhãn `matches` chỉ có nghĩa khi đã đếm được; `null` là chưa đếm (sai cú
   * pháp) hoặc bước không phải phép đếm (gửi bằng phím). */
  function matchText(s: TrialStep): string {
    if (s.matches === null || s.matches === undefined) return "";
    return s.matches === 1 ? "1 khớp" : `${s.matches} khớp`;
  }
</script>

<div
  class={`grid gap-3 rounded-lg border p-3 text-sm ${
    result.ok ? "border-success/30 bg-success/5" : "border-destructive/30 bg-destructive/5"
  }`}
  role="status"
>
  <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
    <span class={result.ok ? "font-medium text-success" : "font-medium text-destructive"}>
      {result.ok ? "Chạy thử thành công" : "Chạy thử thất bại"}
    </span>
    {#if result.flow}
      <span class="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
        {FLOW_LABELS[result.flow] ?? result.flow}
      </span>
    {/if}
    {#if result.ms !== undefined}
      <span class="text-xs text-muted-foreground">{(result.ms / 1000).toFixed(1)}s</span>
    {/if}
    {#if warned > 0}
      <span class="text-xs text-warning">{warned} selector mơ hồ</span>
    {/if}
  </div>

  {#if broken}
    <p class="text-destructive">
      Hỏng ở <span class="font-data">{broken.label}</span>{broken.detail ? ` — ${broken.detail}` : ""}
    </p>
  {:else if result.error}
    <p class="text-destructive">{result.error}</p>
  {/if}

  {#if result.steps?.length}
    <ol class="grid gap-1">
      {#each result.steps as step, i (`${i}-${step.label}`)}
        <li class="flex items-start gap-2">
          <span class={`mt-0.5 shrink-0 ${tone(step.status)}`}>
            {#if step.status === "fail"}<X size={13} weight="bold" />
            {:else if step.status === "warn"}<Warning size={13} weight="bold" />
            {:else if step.status === "skip"}<MinusCircle size={13} />
            {:else}<Check size={13} weight="bold" />{/if}
          </span>
          <span class="min-w-0 flex-1">
            <span class="font-data text-xs">{step.label}</span>
            {#if step.selector}
              <span class="ml-1 break-all font-data text-xs text-muted-foreground">{step.selector}</span>
            {/if}
            {#if matchText(step)}
              <span class={`ml-1 text-xs ${tone(step.status)}`}>({matchText(step)})</span>
            {/if}
            {#if step.detail && step.status !== "ok"}
              <span class="ml-1 text-xs text-muted-foreground">— {step.detail}</span>
            {/if}
          </span>
        </li>
      {/each}
    </ol>
  {/if}

  {#if result.reply}
    <p class="text-muted-foreground">Phản hồi: “{result.reply}”</p>
  {/if}
  {#if result.media !== undefined && result.media > 0}
    <p class="text-muted-foreground">Nhận được {result.media} file media.</p>
  {/if}
</div>
