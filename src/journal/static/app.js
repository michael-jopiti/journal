// Autosave for the daily entry form (entry page only) and the Close button
// (every page). The form is read into the JSON shape the server expects
// ({color, sections: {section: {field: value}}}) and PUT.
(() => {
  const form = document.getElementById("entry");
  const status = document.getElementById("status");
  const day = document.body.dataset.day;
  const DEBOUNCE_MS = 600;
  let timer = null;

  function collect() {
    const sections = {};
    form.querySelectorAll("[data-section]").forEach((el) => {
      const { section, field, index } = el.dataset;
      const fields = (sections[section] ??= {});
      if ("photos" in el.dataset) {
        fields[field] = [...el.querySelectorAll(".photo")].map((p) => ({
          file: p.dataset.file,
          caption: p.querySelector(".caption").value,
        }));
      } else if (el.type === "radio") {
        if (el.checked) fields[field] = Number(el.value);
      } else if (el.type === "checkbox") {
        const chosen = (fields[field] ??= []);
        if (el.checked) chosen.push(el.value);
      } else if (el.type === "number") {
        fields[field] = el.value === "" ? null : Number(el.value);
      } else if (index !== undefined) {
        (fields[field] ??= [])[Number(index)] = el.value;
      } else {
        fields[field] = el.value;
      }
    });
    const color = form.querySelector('input[name="color"]:checked');
    return { color: color ? color.value : null, sections };
  }

  function setStatus(text, state = "") {
    status.textContent = text;
    status.dataset.state = state;
  }

  async function save(keepalive = false) {
    clearTimeout(timer);
    timer = null;
    setStatus("Saving…", "saving");
    try {
      const res = await fetch(`/api/entries/${day}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collect()),
        keepalive,
      });
      if (!res.ok) throw new Error(res.status);
      setStatus("Saved");
      return true;
    } catch {
      setStatus("Not saved – retrying on next change", "error");
      return false;
    }
  }

  function schedule() {
    setStatus("Unsaved…", "saving");
    clearTimeout(timer);
    timer = setTimeout(save, DEBOUNCE_MS);
  }

  // Pictures: upload each file, then add it to the list and autosave.
  async function addPhoto(file) {
    const body = new FormData();
    body.append("file", file);
    try {
      const res = await fetch(`/api/entries/${day}/images`, { method: "POST", body });
      if (!res.ok) throw new Error(res.status);
      const { file: name } = await res.json();
      const el = document.getElementById("photo-tpl").content.firstElementChild.cloneNode(true);
      el.dataset.file = name;
      el.querySelector("img").src = `/images/${day}/${name}`;
      form.querySelector(".photos").append(el);
      schedule();
    } catch {
      setStatus(`Could not add ${file.name} (JPEG, PNG, GIF, WebP up to 25 MB)`, "error");
    }
  }

  const zone = form && form.querySelector(".dropzone");
  if (zone) {
    const input = document.getElementById(zone.htmlFor);
    const addAll = (files) => [...files].filter((f) => f.type.startsWith("image/")).forEach(addPhoto);
    input.addEventListener("change", () => { addAll(input.files); input.value = ""; });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("over"));
    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("over");
      addAll(e.dataTransfer.files);
    });
    form.addEventListener("click", (e) => {
      if (e.target.classList.contains("remove")) {
        e.target.closest(".photo").remove();
        schedule();
      }
    });
  }

  if (form) {
    form.addEventListener("input", schedule);
    form.addEventListener("change", (e) => {
      if (e.target.name === "color") document.body.dataset.color = e.target.value;
      schedule();
    });
    // Flush pending edits when leaving the page.
    addEventListener("pagehide", () => timer && save(true));
  }

  // Close: save one last time, then stop the server. Stay open if the save fails.
  document.getElementById("close")?.addEventListener("click", async () => {
    if (form && !(await save())) return;
    await fetch("/api/shutdown", { method: "POST", headers: { "X-Journal": "1" } });
    document.body.innerHTML = '<div class="page"><h1 class="display">[Closed]</h1><p class="meta">Everything is saved. You can close this tab.</p></div>';
    window.close(); // only works for tabs opened by script; harmless otherwise
  });

  // Export: save first so the PDF page shows the latest text.
  document.getElementById("export")?.addEventListener("click", async (e) => {
    e.preventDefault();
    const href = e.currentTarget.href;
    if (await save()) location.href = href;
  });
})();
