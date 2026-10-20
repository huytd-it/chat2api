<script lang="ts">
  // Icon nhận diện provider, suy từ public model id (`<slug>/<model>`).
  // Không có asset riêng cho Qwen nên dùng Sparkle; provider lạ rơi về Robot.
  import OpenAiLogo from "phosphor-svelte/lib/OpenAiLogo";
  import Sparkle from "phosphor-svelte/lib/Sparkle";
  import GoogleLogo from "phosphor-svelte/lib/GoogleLogo";
  import Robot from "phosphor-svelte/lib/Robot";

  let { model, size = 13 }: { model: string; size?: number } = $props();

  const slug = $derived(model.split("/", 1)[0].toLowerCase());
</script>

{#if slug.includes("chatgpt") || slug.includes("openai")}
  <OpenAiLogo size={size} class="flex-none" aria-hidden="true" />
{:else if slug.includes("qwen")}
  <Sparkle size={size} weight="fill" class="flex-none text-primary" aria-hidden="true" />
{:else if slug.includes("gemini") || slug.includes("google")}
  <GoogleLogo size={size} class="flex-none" aria-hidden="true" />
{:else}
  <Robot size={size} class="flex-none text-muted-foreground" aria-hidden="true" />
{/if}
