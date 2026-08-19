<script lang="ts">
  import type { Block } from "../lib/store.svelte";
  let { block }: { block: Block } = $props();

  // Most non-message blocks carry text; a print is a styled line.
  const text = $derived(
    block.kind === "print"
      ? block.text
      : block.kind === "file-metadata"
        ? `${block.prefix ?? ""} ${block.path}`.trim()
        : block.kind === "todos"
          ? block.todos.map((t) => `${t.marker} ${t.content}`).join("\n")
          : ""
  );
  const cls = $derived(
    block.kind === "print" ? "print " + block.cls : block.kind === "todos" ? "print" : "print muted"
  );
</script>

<pre class={cls}>{text}</pre>

<style>
  .print { white-space: pre-wrap; word-break: break-word; margin: 0.1rem 0; }
  .print.error { color: var(--error); }
  .print.warning { color: var(--warning); }
  .print.success { color: var(--success); }
  .print.info { color: var(--info); }
  .muted { color: var(--muted); }
</style>