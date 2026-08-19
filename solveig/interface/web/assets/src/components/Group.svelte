<script lang="ts">
  let { title, children }: { title: string; children: import("svelte").Snippet } = $props();
</script>

<div class="group">
  <details open>
    <summary>{title}</summary>
    <div class="contents">
      {@render children()}
    </div>
  </details>
</div>

<style>
  .group { border-left: 3px solid var(--box); margin: 0.2rem 0; padding-left: 0.6rem; }
  .contents { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.4rem 0; }
  summary { cursor: pointer; color: var(--muted); font-weight: 600; }
</style>