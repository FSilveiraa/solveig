<script lang="ts">
  import { sendPrompt, cancelWork } from "../lib/events";
  import { model } from "../lib/store.svelte";

  let text = $state("");

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed) return;
    text = "";
    await sendPrompt(trimmed);
  }
  function keydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }
</script>

<div class="inputbar">
  <input
    type="text"
    placeholder={model.prompt ? "Answer the pending question above…" : "Message solveig…"}
    bind:value={text}
    onkeydown={keydown}
    disabled={model.prompt !== null}
  />
  <button onclick={submit} disabled={!text.trim() || model.prompt !== null}>Send</button>
  <button class="ghost" onclick={cancelWork} title="Cancel current work">✕</button>
</div>

<style>
  .inputbar { display: flex; gap: 0.5rem; }
  input { flex: 1; padding: 0.5rem 0.7rem; border-radius: 8px; border: 1px solid var(--box); background: var(--input-bg); color: inherit; font: inherit; }
  input:focus { outline: none; border-color: var(--accent); }
</style>