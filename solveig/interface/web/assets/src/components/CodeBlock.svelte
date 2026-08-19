<script lang="ts">
  // A block with rich content: reasoning (collapsed), a code/text box, a diff,
  // or a directory tree. Renders its payload as preformatted text for now; a
  // proper syntax-highlighted / tree view is a follow-up.
  let {
    title,
    text,
    language,
    collapsed,
    diffOld,
    diffNew,
    tree,
  }: {
    title?: string | null;
    text?: string | null;
    language?: string | null;
    collapsed?: boolean;
    diffOld?: string | null;
    diffNew?: string | null;
    tree?: Record<string, unknown> | null;
  } = $props();

  // Initial collapse is read once at mount: a block's collapse state is set
  // when it's drawn and never changes, so capturing the first value is right.
  let open = $state(!(collapsed ?? false));

  const header = $derived(title ?? (language ? language : "content"));
  const bodyText = $derived(text ?? renderTree(tree ?? null));

  function renderTree(m: Record<string, unknown> | null): string {
    if (!m) return "";
    const lines: string[] = [];
    const walk = (node: Record<string, unknown>, prefix: string) => {
      const name = (node.path as string) ?? "";
      const dir = node.is_directory as boolean;
      lines.push(`${prefix}${dir ? "📁" : "📄"} ${name}`);
      const listing = node.listing as Record<string, Record<string, unknown>> | null;
      if (listing) for (const k of Object.keys(listing)) walk(listing[k], prefix + "  ");
    };
    walk(m, "");
    return lines.join("\n");
  }

  const typeText = $derived(
    diffOld !== null ? `\n${diffOld}\n\n→\n\n${diffNew}` : bodyText
  );
</script>

<div class="codebox">
  <button class="head" onclick={() => (open = !open)}>
    <span class="chevron">{open ? "▼" : "▶"}</span>
    <span class="head-title">{header}</span>
    {#if !open && (diffOld !== null || text)}<span class="head-preview">…</span>{/if}
  </button>
  {#if open}
    <pre><code>{typeText}</code></pre>
  {/if}
</div>

<style>
  .codebox { border: 1px solid var(--box); border-radius: 8px; overflow: hidden; }
  .head { display: flex; width: 100%; gap: 0.5rem; padding: 0.4rem 0.7rem; background: var(--assistant-bg); color: inherit; font: inherit; border: none; cursor: pointer; align-items: center; }
  .chevron { color: var(--muted); font-size: 0.75em; }
  .head-preview { color: var(--muted); }
  pre { margin: 0; padding: 0.7rem; overflow-x: auto; white-space: pre-wrap; word-break: break-word; background: var(--code-bg); font-family: ui-monospace, monospace; font-size: 0.9em; }
</style>