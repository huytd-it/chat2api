<script lang="ts">
  import { Check, CircleNotch, X } from "phosphor-svelte";

  interface Props {
    /** Trạng thái thô của job (running/waiting_login/resuming/ok/failed/...). */
    status: string;
  }

  let { status }: Props = $props();

  const terminalErrorStatuses = ["failed", "cancelled", "login_timeout"];

  const steps = [
    { key: "running", label: "Phân tích trang" },
    { key: "waiting_login", label: "Chờ đăng nhập" },
    { key: "resuming", label: "Tạo recipe" },
    { key: "done", label: "Hoàn tất" },
  ];

  function stepIndexFor(s: string): number {
    if (s === "idle") return -1; // chưa bắt đầu — không bước nào active
    if (s === "running") return 0;
    if (s === "waiting_login") return 1;
    if (s === "resuming") return 2;
    return 3; // ok/failed/cancelled/login_timeout
  }

  const currentIndex = $derived(stepIndexFor(status));
  const isError = $derived(terminalErrorStatuses.includes(status));
</script>

<ol class="flex items-center gap-1" aria-label="Tiến trình tích hợp">
  {#each steps as step, i (step.key)}
    {@const isLast = i === steps.length - 1}
    {@const isDone = i < currentIndex || (i === currentIndex && i === 3 && !isError)}
    {@const isCurrent = i === currentIndex && !(i === 3 && isError) && !isDone}
    {@const isFailed = i === 3 && i === currentIndex && isError}
    <li class="flex flex-1 items-center gap-1">
      <div class="flex flex-col items-center gap-1 text-center">
        <span
          class={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-medium ${
            isFailed
              ? "bg-destructive text-destructive-foreground"
              : isDone
                ? "bg-success text-white"
                : isCurrent
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground"
          }`}
        >
          {#if isFailed}<X size={13} />{:else if isDone}<Check size={13} />{:else if isCurrent}<CircleNotch size={13} class="animate-spin" />{:else}{i + 1}{/if}
        </span>
        <span class={`hidden text-[11px] leading-tight sm:block ${isCurrent || isDone || isFailed ? "text-foreground" : "text-muted-foreground"}`}>
          {isFailed && isLast ? "Lỗi" : step.label}
        </span>
      </div>
      {#if !isLast}<span class={`h-px flex-1 ${i < currentIndex ? "bg-success" : "bg-border"}`}></span>{/if}
    </li>
  {/each}
</ol>
