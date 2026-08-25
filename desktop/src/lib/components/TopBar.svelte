<script lang="ts">
  import { currentView, serverStatus, type ViewName } from "../stores";

  function select(view: ViewName) {
    currentView.set(view);
  }

  const healthText: Record<"loading" | "ok" | "error", string> = {
    loading: "Đang kết nối",
    ok: "Server sẵn sàng",
    error: "Mất kết nối",
  };
</script>

<header class="topbar">
  <div class="topbar-inner">
    <div class="brand"><span class="brand-mark">c2a</span><span>chat2api</span></div>
    <nav class="nav-tabs" role="tablist" aria-label="Điều hướng console">
      <button
        class="nav-tab"
        role="tab"
        aria-selected={$currentView === "playground"}
        aria-controls="playground-view"
        onclick={() => select("playground")}
      >
        Playground
      </button>
      <button
        class="nav-tab"
        role="tab"
        aria-selected={$currentView === "integrations"}
        aria-controls="integrations-view"
        onclick={() => select("integrations")}
      >
        Integrate
      </button>
      <button
        class="nav-tab"
        role="tab"
        aria-selected={$currentView === "logs"}
        aria-controls="logs-view"
        onclick={() => select("logs")}
      >
        Logs
      </button>
    </nav>
    <div class="top-actions">
      <span class="health" data-state={$serverStatus.state}>
        <span class="health-dot"></span>
        <span>{healthText[$serverStatus.state]}</span>
      </span>
    </div>
  </div>
</header>
