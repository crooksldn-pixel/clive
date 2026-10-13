/* CLIVE Preorders storefront block. No framework; follows the selected variant through the
 * product form's `id` field, which every Online Store 2.0 theme keeps current. */
(() => {
  "use strict";

  function setup(root) {
    if (root.dataset.cliveReady) return;
    root.dataset.cliveReady = "1";
    let variants = [];
    try {
      variants = JSON.parse(root.querySelector("[data-clive-variants]").textContent);
    } catch (e) {
      return; // no data: leave the theme exactly as it was
    }
    const section = root.closest("section, .shopify-section") || document;
    const form = section.querySelector('form[action*="/cart/add"]') ||
      document.querySelector('form[action*="/cart/add"]');
    if (!form) return;
    const idField = form.querySelector('[name="id"]');
    const submit = form.querySelector('[name="add"], [type="submit"]:not([data-clive-submit])');
    const labelHost = submit && (submit.querySelector("span") || submit);
    const original = labelHost ? labelHost.textContent : "";
    const preorder = root.querySelector('[data-clive-panel="preorder"]');
    const notify = root.querySelector('[data-clive-panel="notify"]');
    const strings = (root.querySelector("[data-clive-strings]")?.content.textContent || "").split("|")
      .map((s) => { try { return JSON.parse(s); } catch (e) { return ""; } });
    const [okText, errText, buttonText] = strings;
    let current = null;

    function planInput() {
      let input = form.querySelector('input[name="selling_plan"]');
      if (!input) {
        input = document.createElement("input");
        input.type = "hidden";
        input.name = "selling_plan";
        form.appendChild(input);
      }
      return input;
    }

    // AUTO: shelf stock first; then preorder while the plan is offered; then Notify me.
    function stateOf(v) {
      if (!v) return "unknown";
      const shelf = !v.tracked || v.quantity > 0;
      if (v.plan && !shelf) return "preorder";
      if (v.available) return "in_stock";
      return "notify";
    }

    function apply() {
      const id = Number(idField && idField.value);
      if (!id || id === current) return;
      current = id;
      const v = variants.find((x) => x.id === id);
      const state = stateOf(v);
      preorder.hidden = state !== "preorder";
      notify.hidden = state !== "notify";
      if (state === "preorder") {
        planInput().value = String(v.plan.id);
        root.querySelector("[data-clive-date]").textContent =
          (v.plan.description || v.plan.name).split(".")[0] + ".";
        root.querySelector("[data-clive-price]").textContent = v.plan.price;
        const was = root.querySelector("[data-clive-was]");
        was.hidden = !v.plan.compare;
        was.textContent = v.plan.compare || "";
        if (labelHost && buttonText) labelHost.textContent = buttonText;
      } else {
        const input = form.querySelector('input[name="selling_plan"]');
        if (input) input.remove();
        if (labelHost && labelHost.textContent !== original &&
            labelHost.textContent === buttonText) labelHost.textContent = original;
      }
      root.querySelector("[data-clive-message]").hidden = true;
    }

    form.addEventListener("change", () => setTimeout(apply, 0));
    if (idField) {
      new MutationObserver(apply).observe(idField, { attributes: true, attributeFilter: ["value"] });
    }
    // Themes that set the value by property don't fire either: check cheaply now and then.
    setInterval(apply, 400);
    apply();

    const open = root.querySelector("[data-clive-open]");
    const signup = root.querySelector("[data-clive-form]");
    const message = root.querySelector("[data-clive-message]");
    const email = signup.querySelector("input");
    const send = signup.querySelector("[data-clive-submit]");
    open.addEventListener("click", () => {
      signup.hidden = false;
      open.setAttribute("aria-expanded", "true");
      open.hidden = true;
      email.focus();
    });
    async function join() {
      if (!email.checkValidity()) {
        email.reportValidity();
        return;
      }
      send.disabled = true;
      try {
        const res = await fetch(`${root.dataset.proxy}/waitlist`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ variant_id: String(current), email: email.value.trim() }),
        });
        const data = await res.json().catch(() => ({}));
        message.textContent = res.ok ? (data.message || okText) : (data.message || errText);
        message.hidden = false;
        if (res.ok) signup.hidden = true;
      } catch (e) {
        message.textContent = errText;
        message.hidden = false;
      } finally {
        send.disabled = false;
      }
    }
    send.addEventListener("click", join);
    // Enter in the field joins the list instead of submitting the theme's product form.
    email.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        join();
      }
    });
  }

  const run = () => document.querySelectorAll("[data-clive-preorder]").forEach(setup);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
  // The theme editor re-renders sections in place.
  document.addEventListener("shopify:section:load", run);
})();
