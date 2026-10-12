(function () {
  const $ = (id) => document.getElementById(id);
  const KEY = "outside-bingo-anon-id";
  let anon = localStorage.getItem(KEY);
  if (!anon) {
    anon = crypto.randomUUID ? crypto.randomUUID() :
      "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 3) | 8).toString(16);
      });
    localStorage.setItem(KEY, anon);
  }
  let quest = null;

  async function api(url, body) {
    const res = await fetch(url, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Anon-Id": anon },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch (e) { /* ignore */ }
    if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
    return data;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function setProgress(p) {
    $("xpTotal").textContent = p.xp;
    $("questsTotal").textContent = p.quests_completed;
  }

  function renderDest(q) {
    const box = $("dest");
    box.replaceChildren();
    const d = q.destination || {};
    const rec = d.recommended;
    if (rec) {
      box.append(el("span", "tag", "live search result via SerpApi"));
      box.append(el("h3", null, rec.name));
      if (rec.address) box.append(el("p", null, rec.address));
      const meta = [];
      if (rec.rating != null) meta.push("Rating " + rec.rating + (rec.reviews ? " (" + rec.reviews + " reviews)" : ""));
      if (rec.type) meta.push(rec.type);
      if (meta.length) box.append(el("p", null, meta.join(" · ")));
      const a = el("a", null, "View on Google Maps");
      a.href = rec.link; a.target = "_blank"; a.rel = "noopener noreferrer";
      box.append(a);
      if (d.alternatives && d.alternatives.length) {
        box.append(el("p", null, "Other places to try:"));
        const ul = el("ul");
        d.alternatives.forEach((alt) => {
          const li = el("li");
          const l = el("a", null, alt.name);
          l.href = alt.link; l.target = "_blank"; l.rel = "noopener noreferrer";
          li.append(l);
          if (alt.address) li.append(document.createTextNode(" — " + alt.address));
          ul.append(li);
        });
        box.append(ul);
      }
    } else {
      box.append(el("span", "tag", d.source === "demo" ? "demo mode" : "no destination"));
      box.append(el("h3", null, "Any public green space near " + q.location));
      box.append(el("p", null, d.source === "demo"
        ? "No live search was run, so no specific place is suggested."
        : "No verified destination was returned, so these quests work anywhere outdoors."));
    }
  }

  function sourceLabel(s) {
    return s === "backboard" ? "AI · open-weight via Backboard" : s === "demo" ? "demo card (not AI)" : "fallback card (not AI)";
  }

  function renderGrid() {
    const done = new Set(quest.completed);
    $("sourceTag").textContent = sourceLabel(quest.mission_source);
    $("grid").replaceChildren();
    quest.missions.forEach((m, i) => {
      const li = el("li", "cell" + (done.has(m.id) ? " done" : ""));
      li.style.animationDelay = i * 80 + "ms";
      const check = el("button", "check", "✓");
      check.type = "button";
      check.setAttribute("aria-pressed", done.has(m.id));
      check.setAttribute("aria-label", "Mark \"" + m.title + "\" as done");
      check.addEventListener("click", () => toggle(m, li, !done.has(m.id)));
      li.append(check, el("h4", null, m.title), el("p", null, m.instruction), el("span", "xp", "+" + m.xp + " XP"));
      const rate = el("div", "rate");
      [["like", "👍 Liked it"], ["dislike", "👎 Not for me"]].forEach(([s, label]) => {
        const b = el("button", null, label);
        b.type = "button";
        b.addEventListener("click", async () => {
          try { await api("/api/quests/" + quest.id + "/missions/" + m.id + "/feedback", { sentiment: s }); } catch (e) { return; }
          rate.querySelectorAll("button").forEach((x) => (x.disabled = true));
          b.textContent += " ✓";
        });
        rate.append(b);
      });
      li.append(rate);
      $("grid").append(li);
    });
    const n = quest.completed.length;
    $("doneCount").textContent = n;
    $("questXp").textContent = quest.earned_xp;
    $("barFill").style.width = (n / quest.missions.length) * 100 + "%";
    $("win").hidden = !quest.finished;
  }

  async function toggle(m, li, completed) {
    try {
      const data = await api("/api/quests/" + quest.id + "/missions/" + m.id + "/complete", { completed });
      quest = data.quest;
      setProgress(data.progress);
      renderGrid();
      if (completed) {
        const cell = $("grid").children[quest.missions.findIndex((x) => x.id === m.id)];
        const f = el("span", "float", "+" + m.xp + " XP");
        cell.append(f);
        setTimeout(() => f.remove(), 1000);
        if (quest.finished) $("win").scrollIntoView({ behavior: "smooth", block: "center" });
      }
    } catch (e) { showError(e.message); }
  }

  function showError(msg) {
    $("formError").textContent = msg;
    $("formError").hidden = false;
  }

  function showQuest(q, notices) {
    quest = q;
    $("notices").replaceChildren();
    (notices || []).forEach((n) => $("notices").append(el("p", "notice", n)));
    renderDest(q);
    renderGrid();
    $("adventure").hidden = false;
  }

  $("form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("formError").hidden = true;
    const f = new FormData($("form"));
    const body = {
      location: (f.get("location") || "").trim(),
      minutes: Number(f.get("minutes")),
      activity: f.get("activity"),
      energy: f.get("energy"),
    };
    if (body.location.length < 2) { showError("Please enter a city or locality."); $("location").focus(); return; }
    $("go").disabled = true;
    $("adventure").hidden = true;
    $("loading").hidden = false;
    $("loadingText").textContent = "Scouting the trail and sketching your card…";
    try {
      const data = await api("/api/adventure", body);
      setProgress(data.progress);
      showQuest(data.quest, data.notices);
      $("adventure").scrollIntoView({ behavior: "smooth" });
    } catch (e) {
      showError(e.message);
    } finally {
      $("loading").hidden = true;
      $("go").disabled = false;
    }
  });

  $("again").addEventListener("click", () => {
    $("adventure").hidden = true;
    $("setup").scrollIntoView({ behavior: "smooth" });
  });

  api("/api/state").then((s) => {
    setProgress(s.progress);
    if (s.quest) showQuest(s.quest, []);
  }).catch(() => {});
})();
