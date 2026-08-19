<script lang="ts">
  import { model } from "../lib/store.svelte";
  import { answerPrompt, cancelPrompt } from "../lib/events";

  let answer = $state(model.prompt?.default ?? "");
  $effect(() => {
    // A new prompt resets the draft to that prompt's default.
    if (model.prompt) answer = model.prompt.default ?? "";
  });

  const prompt = $derived(model.prompt!);

  async function submit() {
    if (!model.prompt) return;
    await answerPrompt(model.prompt.id, answer);
  }
  function pick(choice: string) {
    if (model.prompt) answerPrompt(model.prompt.id, choice);
  }
</script>

{#if model.prompt}
  <aside class="prompt">
    <div class="question">{prompt.question}</div>
    {#if prompt.choices}
      <div class="choices">
        {#each prompt.choices as c}
          <button onclick={() => pick(c)}>{c}</button>
        {/each}
      </div>
    {:else}
      <div class="freeform">
        <input type="text" bind:value={answer} onkeydown={(e) => e.key === "Enter" && submit()} />
        <button onclick={submit}>Answer</button>
      </div>
    {/if}
    <button class="ghost" onclick={() => model.prompt && cancelPrompt(model.prompt.id)}>Cancel</button>
  </aside>
{/if}

<style>
  .prompt { position: sticky; bottom: 0.5rem; margin: 0.5rem 1rem; padding: 0.8rem; border: 1px solid var(--accent); border-radius: 10px; background: var(--assistant-bg); display: flex; flex-direction: column; gap: 0.5rem; }
  .question { font-weight: 600; }
  .choices { display: flex; flex-direction: column; gap: 0.3rem; }
  .freeform { display: flex; gap: 0.4rem; }
  .freeform input { flex: 1; padding: 0.4rem; }
</style>