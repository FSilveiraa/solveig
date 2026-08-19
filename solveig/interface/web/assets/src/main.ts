import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

import { connect } from "./lib/events";

// Open the conversation stream before mounting so no early-display event is
// missed; the bus replays history to new subscribers, so this is safe even if
// the SPA loads mid-conversation.
connect();

const app = mount(App, { target: document.getElementById("app")! });

export default app;