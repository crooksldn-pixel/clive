/* CLIVE Preorders storefront block. No framework; follows the selected variant through the
 * product form's `id` field, which every Online Store 2.0 theme keeps current. A theme that
 * empties that field for a size it can't sell (the CROOKS "Product Record" section does) names
 * the chosen size in a `data-clive-variant` attribute inside the section instead.
 *
 * Themes like Horizon re-render the product area when the size changes (they fetch the section
 * and morph it in), which can replace the form, its `id` field and the button, and drop inputs
 * they didn't render. So nothing is remembered between checks: each check finds the add-to-cart
 * form and the size afresh and puts the selling plan and the button label back if they went;
 * and the plan is checked once more as the form is sent. */
(() => {
  "use strict";

  // The add-to-cart form, not another /cart/add form (a price block's payment-terms form).
  function cartForm(section) {
    const forms = [...section.querySelectorAll('form[action*="/cart/add"]')];
    return (
      forms.find((f) => f.dataset.type === "add-to-cart-form") ||
      forms.find((f) => f.querySelector('[name="add"]')) ||
      forms.find((f) => f.querySelector('[type="submit"]')) ||
      null
    );
  }

  function setup(root) {
    if (root.dataset.cliveReady) return;
    root.dataset.cliveReady = "1";
    let variants = [];
    try {
      variants = JSON.parse(root.querySelector("[data-clive-variants]").textContent);
    } catch (e) {
      return; // no data: leave the theme exactly as it was
    }
    const section = root.closest(".shopify-section, section") || document;
    const preorder = root.querySelector('[data-clive-panel="preorder"]');
    const notify = root.querySelector('[data-clive-panel="notify"]');
    const strings = (root.querySelector("[data-clive-strings]")?.content.textContent || "").split("|")
      .map((s) => { try { return JSON.parse(s); } catch (e) { return ""; } });
    const [okText, errText, buttonText] = strings;
    let current = null;
    let state = "unknown";
    let plan = null;
    let original = null; // the theme's own button words, to put back

    // AUTO: shelf stock first; then preorder while the plan is offered; then Notify me.
    function stateOf(v) {
      if (!v) return "unknown";
      const shelf = !v.tracked || v.quantity > 0;
      // Shopify must also let it be bought (CONTINUE): a plan left on a size set to DENY
      // (a sync in progress or failing) would otherwise show a button that can't work.
      if (v.plan && !shelf && v.available) return "preorder";
      if (v.available) return "in_stock";
      return "notify";
    }

    function label(form) {
      const button = form.querySelector('[name="add"], [type="submit"]:not([data-clive-submit])');
      return button && (button.querySelector("span") || button);
    }

    // The selling plan on the form exactly when this size is a preorder; never otherwise.
    function syncForm(form) {
      let input = form.querySelector('input[name="selling_plan"]');
      if (state === "preorder" && plan) {
        if (!input) {
          input = document.createElement("input");
          input.type = "hidden";
          input.name = "selling_plan";
          form.appendChild(input);
        }
        input.value = plan;
      } else if (input) {
        input.remove();
      }
      const host = label(form);
      if (!host || !buttonText) return;
      const button = host.closest("button") || host;
      // A disabled button is the theme's to word ("Adding…", "Sold out"): leave it alone.
      if (state === "preorder" && !button.disabled && host.textContent.trim() !== buttonText) {
        original = host.textContent;
        host.textContent = buttonText;
      } else if (state !== "preorder" && original !== null && host.textContent.trim() === buttonText) {
        host.textContent = original;
        original = null;
      }
    }

    function tick() {
      if (!root.isConnected) return clearInterval(timer); // re-rendered: the new copy takes over
      const form = cartForm(section) || cartForm(document);
      if (!form) return;
      const id =
        Number(form.querySelector('[name="id"]')?.value) ||
        Number(section.querySelector("[data-clive-variant]")?.getAttribute("data-clive-variant")) ||
        0;
      if (id !== current) {
        // No size chosen (0) or one this block doesn't know: no panel, no plan.
        current = id;
        const v = variants.find((x) => x.id === id);
        state = stateOf(v);
        plan = state === "preorder" ? String(v.plan.id) : null;
        preorder.hidden = state !== "preorder";
        notify.hidden = state !== "notify";
        if (state === "preorder") {
          root.querySelector("[data-clive-date]").textContent =
            (v.plan.description || v.plan.name).split(".")[0] + ".";
          root.querySelector("[data-clive-price]").textContent = v.plan.price;
          const was = root.querySelector("[data-clive-was]");
          was.hidden = !v.plan.compare;
          was.textContent = v.plan.compare || "";
        }
        root.querySelector("[data-clive-message]").hidden = true;
      }
      syncForm(form);
    }

    // As the form is sent (capture: before the theme's own submit handler reads it).
    document.addEventListener("submit", (ev) => {
      if (!root.isConnected) return;
      const form = ev.target;
      if (form instanceof HTMLFormElement && form === (cartForm(section) || cartForm(document))) {
        current = null; // read the size afresh
        tick();
      }
    }, true);
    section.addEventListener("change", () => setTimeout(tick, 0));
    const timer = setInterval(tick, 300);
    tick();

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
        // Only the app's own answer counts as success (a theme or error page can answer 200).
        const ok = res.ok && ["joined", "already", "available"].includes(data.status);
        message.textContent = ok ? (data.message || okText) : (data.message || errText);
        message.hidden = false;
        if (ok) signup.hidden = true;
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
  // The theme editor, and themes that morph the product area, re-render the block in place.
  document.addEventListener("shopify:section:load", run);
  setInterval(run, 1000);
})();
