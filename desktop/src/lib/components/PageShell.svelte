<script lang="ts">
  import type { Snippet } from "svelte";
  import { cn } from "../utils";

  let {
    title,
    description,
    actions,
    children,
    width = "constrained",
  }: {
    title: string;
    description?: string;
    actions?: Snippet;
    children: Snippet;
    width?: "constrained" | "wide" | "full";
  } = $props();

  const maxWidth = $derived(
    width === "constrained" ? "max-w-4xl" : width === "wide" ? "max-w-6xl" : "max-w-none",
  );
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class={cn("mx-auto flex w-full flex-col gap-6 p-4 md:p-6", maxWidth)}>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 space-y-1">
        <h2 class="text-xl font-semibold tracking-tight text-foreground">{title}</h2>
        {#if description}
          <p class="text-sm text-muted-foreground">{description}</p>
        {/if}
      </div>
      {#if actions}
        <div class="flex flex-wrap items-center gap-2">
          {@render actions()}
        </div>
      {/if}
    </div>
    {@render children()}
  </div>
</div>
