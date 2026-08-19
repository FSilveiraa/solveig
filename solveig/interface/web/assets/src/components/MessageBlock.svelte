<script lang="ts">
  import type { MessageBlock } from "../lib/store.svelte";
  import { runAction } from "../lib/events";

  let { block }: { block: MessageBlock } = $props();

  let editing = $state(false);
  let draft = $state("");

  const isUser = $derived(block.role === "user");

  function startEdit() {
    draft = block.text;
    editing = true;
  }
  async function commitEdit() {
    await runAction(block.id, "edit", draft);
    editing = false;
  }
  function cancelEdit() {
    editing = false;
  }
</script>

<div class="message user" class:user={isUser} class:assistant={!isUser}>
  <div class="role">{isUser ? "you" : "solveig"}</div>
  {#if editing}
    <textarea bind:value={draft} rows="4"></textarea>
    <div class="actions">
      <button onclick={commitEdit}>Save</button>
      <button class="ghost" onclick={cancelEdit}>Cancel</button>
    </div>
  {:else}
    <div class="body">{block.text}</div>
    <div class="actions">
      {#if block.actions.includes("edit")}<button class="ghost" onclick={startEdit}>Edit</button>{/if}
      {#if block.actions.includes("retry")}<button class="ghost" onclick={() => runAction(block.id, "retry")}>Retry</button>{/if}
      {#if block.actions.includes("delete")}<button class="ghost" onclick={() => runAction(block.id, "delete")}>Delete</button>{/if}
      {#if block.actions.includes("branch")}<button class="ghost" onclick={() => runAction(block.id, "branch")}>Branch</button>{/if}
      <button class="ghost" onclick={() => navigator.clipboard?.writeText(block.text)}>Copy</button>
    </div>
  {/if}
</div>

<style>
  .message { padding: 0.6rem 0.9rem; border-radius: 8px; max-width: 78%; }
  .user { align-self: flex-end; background: var(--user-bg); border: 1px solid var(--box); }
  .assistant { align-self: flex-start; background: var(--assistant-bg); border: 1px solid var(--box); }
  .role { font-size: 0.75em; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 0.25rem; }
  .body { white-space: pre-wrap; word-break: break-word; }
  .actions { display: flex; gap: 0.4rem; margin-top: 0.4rem; flex-wrap: wrap; }
  textarea { width: 100%; margin: 0.3rem 0; font: inherit; }
</style>