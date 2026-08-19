<script lang="ts">
  // One block, any kind, rendered in place. Recursion into a group happens
  // here too, so the whole transcript is one tree of these.
  import type { Block } from "../lib/store.svelte";
  import MessageBlock from "./MessageBlock.svelte";
  import CodeBlock from "./CodeBlock.svelte";
  import Leaf from "./Leaf.svelte";
  import Group from "./Group.svelte";
  import Blockchain from "./Blockchain.svelte";

  let { blocks }: { blocks: Block[] } = $props();
</script>

{#each blocks as b (b.id)}
  {#if b.kind === "message"}
    <MessageBlock block={b} />
  {:else if b.kind === "reasoning"}
    <CodeBlock title="Reasoning" text={b.text} collapsed />
  {:else if b.kind === "textbox"}
    <CodeBlock title={b.title} text={b.text} language={b.language} collapsed={b.collapsed} />
  {:else if b.kind === "diff"}
    <CodeBlock title={b.title} diffOld={b.old} diffNew={b.new} />
  {:else if b.kind === "tree"}
    <CodeBlock title={b.title} tree={b.metadata} />
  {:else if b.kind === "group"}
    <Group title={b.title}>
      <Blockchain blocks={b.children} />
    </Group>
  {:else}
    <Leaf block={b} />
  {/if}
{/each}