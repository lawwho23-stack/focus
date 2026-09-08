const form = document.getElementById("capture");
const text = document.getElementById("text");
const list = document.getElementById("list");
const errorLine = document.getElementById("error");
const dateLabel = document.getElementById("date");
const primaryBox = document.getElementById("primary");
const slots = document.getElementById("slots");

async function api(path, options) {
    const res = await fetch(path, options);
    const raw = await res.text();

    if (!res.ok) {
        let message = raw;
        try {
            const detail = JSON.parse(raw).detail;
            if (typeof detail === "string") message = detail;
            else if (Array.isArray(detail)) message = detail.map((d) => d.msg).join(", ");
        } catch {
            // not JSON - show the raw text instead
        }
        throw new Error(message);
    }
    return JSON.parse(raw);
}

function showError(err) {
    errorLine.textContent = err.message;
    errorLine.hidden = false;
}
async function post(path, body) {
    const options = {method: "POST" };
    if (body !== undefined) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
    }
    return api(path, options);
}
function button(label, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", onClick);
    return b;
}
async function act(fn) {
    try {
        errorLine.hidden = true;
        await fn();
        }catch (err) {
            showError(err);
            return;
        }
        refresh();
}
async function loadToday() {
    const today = await api("/api/today");
    dateLabel.textContent = today.date;
    const primaryId = today.primary ? today.primary.id : null;

    primaryBox.innerHTML = "";
    if (today.primary) {
        const title = document.createElement("p");
        title.className = "primary-title";
        title.textContent = today.primary.title;

        const doneWhen = document.createElement("p");
        doneWhen.className = "done-when";
        doneWhen.textContent = "done when: " + today.primary.done_when;

        primaryBox.append(title, doneWhen);
    } else {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "No primary yet.";
        primaryBox.append(empty);
    }

    slots.innerHTML = "";
    for (const slot of [1, 2, 3]) {
        const held = today.active.find((c) => c.active_slot === slot);

        const li = document.createElement("li");

        const row = document.createElement("div");
        row.className = "row"

        const number = document.createElement("span");
        number.className = "slot";
        number.textContent = slot;

        const body = document.createElement("span");
        body.className = "body";
        body.textContent = held ? held.title : "empty";
        if (!held) li.className = "free";

        const lane = document.createElement("span");
        lane.className = "lane";
        lane.textContent = held ? held.lane : "";

        row.append(number, body, lane);
        li.append(row);
        
        if (held) {
            const actions = document.createElement("div");
            actions.className = "actions";

            if (held.id === primaryId) {
                const chip = document.createElement("span");
                chip.className = "is-primary";
                chip.textContent = "today's one thing";
                actions.append(chip);
            } else {
                actions.append(
                    button("make primary", () =>
                    act(() => post("/api/today/primary", { commitment_id: held.id})),
                ),
                );
            }
            actions.append(
                button("finish", () => act(() => post(`/api/commitments/${held.id}/finish`))),
                button("kill", () => {
                    const reason = prompt(`Kill "${held.title}" - why?`);
                    if (reason === null) return;
                    act(() => post(`/api/commitments/${held.id}/kill`, { reason }));
                }),
            );
            li.append(actions);
        }
        slots.append(li);
    }
}
function promoteForm(idea) {
    const wrap = document.createElement("div");
    wrap.className = "promote-form";

    const doneWhen = document.createElement("input");
    doneWhen.placeholder = "done when? (the finish line)";
    doneWhen.autocomplete = "off";

    const lanes = document.createElement("div");
    lanes.className = "lanes";
    for (const lane of ["learning", "income", "client"]) {
        lanes.append(
            button(lane, () =>
            act(() =>
            post(`/api/ideas/${idea.id}/promote`, {
                done_when: doneWhen.value.trim(), lane,
            }),
        ),
    ),
);
    }
    wrap.append(doneWhen, lanes, button("cancel", () => wrap.remove()));
    return wrap;
}

async function loadIdeas() {
    const ideas = await api("/api/ideas");

    list.innerHTML = "";
    for (const idea of ideas) {
        const li = document.createElement("li");

        const row = document.createElement("div");
        row.className = "row";

        const body = document.createElement("span");
        body.className = "body";
        body.textContent = idea.text;

        const tag = document.createElement("span");
        tag.className = idea.ready ? "ready" : "frozen";
        tag.textContent = idea.ready
            ? "ready"
            : "frozen until " + idea.unfreeze_at.slice(0,10);
        
        row.append(body, tag);
        if (idea.ready) {
            row.append(
                button("promote", () => {
                    if (li.querySelector(".promote-form")) return;
                    li.append(promoteForm(idea));
                }),
            );
        }

        li.append(row);
        list.append(li);
    }
}

async function refresh() {
    try {
        errorLine.hidden = true;
        await loadToday();
        await loadIdeas();
    } catch (err) {
        showError(err);
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const value = text.value.trim();
    if (!value) return;

    try {
        errorLine.hidden = true;
        await api("/api/ideas", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: value }),
        });
    } catch (err) {
        showError(err);
        return;
    }

    text.value = "";
    refresh();
});

refresh();
