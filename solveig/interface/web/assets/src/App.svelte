<script lang="ts">
  import { model } from "./lib/store.svelte";
  import InputBar from "./components/InputBar.svelte";
  import Blockchain from "./components/Blockchain.svelte";
  import PromptCard from "./components/PromptCard.svelte";
</script>

<header class="topbar">
  <span class="brand">solveig</span>
  <span class="status">
    {#if !model.connected}● disconnected{/if}
    <span class="status-text">{model.status ?? ""}</span>
  </span>
  <span class="stats">
    {#each model.stats as s}<span class="stat">{s.label}: {s.text}</span>{/each}
  </span>
</header>

<main class="transcript">
  <Blockchain blocks={model.blocks} />
</main>

{#if model.prompt}
  <PromptCard />
{/if}

<footer class="inputbar">
  <InputBar />
</footer>

<style>
  .topbar {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--box);
    background: var(--bg);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .brand { font-weight: 700; letter-spacing: 0.05em; }
  .status { color: var(--muted); display: flex; gap: 0.5rem; align-items: center; flex: 1; }
  .stats { display: flex; gap: 1rem; color: var(--muted); font-size: 0.85em; }
  .stat { white-space: nowrap; }
  .transcript {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .inputbar {
    border-top: 1px solid var(--box);
    padding: 0.6rem 1rem;
    background: var(--bg);
  }
</style>