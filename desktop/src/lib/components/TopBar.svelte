<script lang="ts">
  import { page } from "$app/state";
  import { serverStatus } from "../stores";

  // Mỗi vùng làm việc giờ là một route thật, nên trạng thái "đang ở đâu" đọc từ
  // URL thay vì một store riêng — back/forward và deep link đều đúng.
  const links = [
    { href: "/", label: "Tổng quan" },
    { href: "/playground", label: "Playground" },
    { href: "/recipes", label: "Recipes" },
    { href: "/accounts", label: "Accounts" },
    { href: "/integrations", label: "Integrate" },
    { href: "/logs", label: "Logs" },
    { href: "/settings", label: "Settings" },
  ];

  const healthText: Record<"loading" | "ok" | "error", string> = {
    loading: "Đang kết nối",
    ok: "Server sẵn sàng",
    error: "Mất kết nối",
  };

  function isActive(href: string): boolean {
    const path = page.url.pathname.replace(/\/+$/, "") || "/";
    return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  }
</script>

<header class="topbar">
  <div class="topbar-inner">
    <div class="brand"><span class="brand-mark">c2a</span><span>chat2api</span></div>
    <nav class="nav-tabs" aria-label="Điều hướng console">
      {#each links as link (link.href)}
        <a
          class="nav-tab"
          href={link.href}
          aria-current={isActive(link.href) ? "page" : undefined}
        >
          {link.label}
        </a>
      {/each}
    </nav>
    <div class="top-actions">
      <span class="health" data-state={$serverStatus.state}>
        <span class="health-dot"></span>
        <span>{healthText[$serverStatus.state]}</span>
      </span>
    </div>
  </div>
</header>
