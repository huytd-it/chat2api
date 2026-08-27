<script lang="ts">
  import type { Snippet } from "svelte";
  import { cn } from "../utils";

  let {
    title,
    description,
    actions,
    children,
    width = "constrained",
    kicker,
  }: {
    title: string;
    description?: string;
    actions?: Snippet;
    children: Snippet;
    width?: "constrained" | "wide" | "full";
    /** Short label shown above the title — e.g. "Operations" or "Live". */
    kicker?: string;
  } = $props();

  const maxWidth = $derived(
    width === "constrained" ? "max-w-4xl" : width === "wide" ? "max-w-6xl" : "max-w-none",
  );
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class={cn("mx-auto flex w-full flex-col gap-7 p-4 pb-10 md:p-6 md:pb-12 lg:p-8 lg:pb-14", maxWidth)}>
    <header class="grid gap-4 border-b border-foreground/20 pb-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
      <div class="min-w-0">
        {#if kicker}
          <div class="mb-2 flex items-center gap-2 font-data text-[10px] font-medium tracking-[0.1em] text-primary">
            <span class="h-px w-5 bg-primary" aria-hidden="true"></span>
            {kicker}
          </div>
        {/if}
        <h2 class="display-face text-3xl font-semibold leading-none tracking-[-0.035em] text-foreground text-balance md:text-[2.3rem]">
          {title}
        </h2>
        {#if description}
          <p class="mt-2 max-w-[62ch] text-[13.5px] leading-relaxed text-muted-foreground text-pretty">
            {description}
          </p>
        {/if}
      </div>
      {#if actions}
        <div class="flex flex-wrap items-center gap-2 sm:justify-end">
          {@render actions()}
        </div>
      {/if}
    </header>
    {@render children()}
  </div>
</div>
