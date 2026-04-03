/**
 * STYLING.AI — Main JavaScript
 * Handles: outfit generation, wardrobe filtering, item deletion, premium modal
 */

document.addEventListener("DOMContentLoaded", () => {

  /* ─────────────────────────────────────────────
     1. Outfit Generator
  ───────────────────────────────────────────── */
  const generateBtn       = document.getElementById("generateBtn");
  const outfitDisplay     = document.getElementById("outfitDisplay");
  const outfitError       = document.getElementById("outfitError");
  const styleContextInput = document.getElementById("styleContextInput");
  const outfitNote        = document.getElementById("outfitNote");
  const tryOnBtn          = document.getElementById("tryOnBtn");
  const tryOnError        = document.getElementById("tryOnError");
  const tryOnResult       = document.getElementById("tryOnResult");
  const tryOnSelectionCount = document.getElementById("tryOnSelectionCount");
  const occasionSelect    = document.getElementById("occasionSelect");
  const styleVibeSelect   = document.getElementById("styleVibeSelect");
  const stylingGoalInput  = document.getElementById("stylingGoalInput");
  const recentPreviews    = document.getElementById("recentPreviews");
  const selectedTryOnItems = new Map();
  let tryOnTimeoutId = null;

  if (generateBtn) {
    generateBtn.addEventListener("click", async () => {
      generateBtn.classList.add("btn--loading");
      generateBtn.textContent = "Styling…";
      if (outfitError) outfitError.style.display = "none";
      if (outfitNote) outfitNote.style.display = "none";

      try {
        const formData = new FormData();
        if (styleContextInput) {
          formData.append("context", styleContextInput.value);
        }

        const res  = await fetch(window.APP.generateUrl, { 
          method: "POST", 
          body: formData 
        });
        const data = await res.json();

        if (!res.ok || data.error) {
          showOutfitError(data.error || "Something went wrong. Try again.");
          return;
        }

        renderOutfit(data.outfit);
        
        if (outfitNote && data.note) {
          outfitNote.textContent = data.note;
          outfitNote.style.display = "block";
        }

      } catch (err) {
        showOutfitError("Network error — please try again.");
      } finally {
        generateBtn.classList.remove("btn--loading");
        generateBtn.textContent = "Generate Outfit";
      }
    });
  }

  /**
   * Renders the three outfit slots (top, bottom, shoes) into the grid.
   * If a category has no item, renders a placeholder slot.
   */
  function renderOutfit(outfit) {
    const slots = [
      { key: "top",    label: "Top" },
      { key: "bottom", label: "Bottom" },
      { key: "shoes",  label: "Shoes" },
    ];

    outfitDisplay.classList.remove("outfit-grid--empty");
    outfitDisplay.innerHTML = "";

    slots.forEach(({ key, label }) => {
      const item = outfit[key];
      const card = document.createElement("div");

      if (item) {
        card.className = "outfit-card";
        card.innerHTML = `
          <img
            src="${window.APP.uploadsBase}${item.image_path}"
            alt="${item.name}"
            class="outfit-card__img"
          />
          <div class="outfit-card__info">
            <span class="outfit-card__category">${label}</span>
            <span class="outfit-card__name">${item.name}</span>
            <span class="outfit-card__color">${item.color}</span>
          </div>
        `;
      } else {
        card.className = "outfit-card outfit-card--empty";
        card.innerHTML = `<p>No ${label.toLowerCase()} in wardrobe</p>`;
      }

      outfitDisplay.appendChild(card);
    });
  }

  function showOutfitError(msg) {
    outfitError.textContent = msg;
    outfitError.style.display = "block";
    outfitDisplay.classList.add("outfit-grid--empty");
    outfitDisplay.innerHTML = `
      <div class="outfit-placeholder"><p>${msg}</p></div>
    `;
  }

  function showTryOnError(msg) {
    if (!tryOnError || !tryOnResult) return;
    tryOnError.textContent = msg;
    tryOnError.style.display = "block";
    tryOnResult.classList.add("tryon-result--empty");
  }

  function clearTryOnError() {
    if (!tryOnError) return;
    tryOnError.textContent = "";
    tryOnError.style.display = "none";
  }

  function updateTryOnCount() {
    if (!tryOnSelectionCount) return;
    const count = selectedTryOnItems.size;
    tryOnSelectionCount.textContent = `${count} item${count === 1 ? "" : "s"} selected`;
  }

  function renderTryOnResult(imageUrl, items, meta = {}) {
    if (!tryOnResult) return;
    const itemMarkup = items.map(item => (
      `<li>${item.category}: ${item.name} (${item.color})</li>`
    )).join("");
    const notesMarkup = (meta.notes || []).map(note => `<li>${note}</li>`).join("");
    tryOnResult.classList.remove("tryon-result--empty");
    tryOnResult.innerHTML = `
      <img src="${imageUrl}" alt="AI try-on preview" class="tryon-result__image" />
      <div class="tryon-result__info">
        <h3 class="tryon-result__title">Preview complete</h3>
        <p class="tryon-result__body">This is an AI styling visualization of how the selected outfit may look on a model.</p>
        <div class="tryon-result__meta">
          <span class="badge">${meta.style_vibe || "Styled"}</span>
          <span>${meta.occasion || "Everyday polish"}</span>
        </div>
        <ul class="tryon-result__items">${itemMarkup}</ul>
        ${notesMarkup ? `<div class="tryon-result__notes-wrap"><h4 class="tryon-result__subtitle">Why it works</h4><ul class="tryon-result__notes">${notesMarkup}</ul></div>` : ""}
      </div>
    `;
  }

  function renderRecentPreviews(previews) {
    if (!recentPreviews || !Array.isArray(previews)) return;
    if (!previews.length) {
      recentPreviews.innerHTML = `
        <div class="wardrobe-empty">
          <p>No looks saved yet.</p>
          <span>Generate your first AI preview and it will appear here.</span>
        </div>
      `;
      return;
    }

    recentPreviews.innerHTML = previews.map(preview => {
      const items = (preview.items || []).map(item => `<li>${item.category}: ${item.name}</li>`).join("");
      const notes = (preview.notes || []).map(note => `<li>${note}</li>`).join("");
      return `
        <article class="preview-history__card">
          <div class="preview-history__head">
            <span class="badge">${preview.style_vibe}</span>
            <span class="preview-history__occasion">${preview.occasion}</span>
          </div>
          <p class="preview-history__goal">${preview.styling_goal || "No specific styling goal saved."}</p>
          <ul class="preview-history__items">${items}</ul>
          <ul class="preview-history__notes">${notes}</ul>
        </article>
      `;
    }).join("");
  }

  function hasValidTryOnSelection() {
    if (selectedTryOnItems.size < 2) return false;
    const categories = new Set(Array.from(selectedTryOnItems.values(), item => item.category));
    return categories.has("tops") && categories.has("bottoms");
  }

  async function requestTryOnPreview() {
    if (!hasValidTryOnSelection()) {
      showTryOnError("Select at least one top and one bottom to generate the preview.");
      return;
    }

    clearTryOnError();
    tryOnBtn?.classList.add("btn--loading");
    if (tryOnBtn) tryOnBtn.textContent = "Rendering…";

    const formData = new FormData();
    selectedTryOnItems.forEach(item => formData.append("item_ids", item.id));
    formData.append("occasion", occasionSelect?.value || "");
    formData.append("style_vibe", styleVibeSelect?.value || "");
    formData.append("styling_goal", stylingGoalInput?.value || "");

    try {
      const response = await fetch(window.APP.previewUrl, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      if (!response.ok || data.error) {
        showTryOnError(data.error || "Something went wrong creating the preview.");
        return;
      }

      renderTryOnResult(data.image_data_url, data.selected_items || [], data);
      renderRecentPreviews(data.recent_previews || []);
    } catch {
      showTryOnError("Network error while creating the preview.");
    } finally {
      tryOnBtn?.classList.remove("btn--loading");
      if (tryOnBtn) tryOnBtn.textContent = "Regenerate Preview";
    }
  }

  function scheduleTryOnPreview() {
    if (tryOnTimeoutId) clearTimeout(tryOnTimeoutId);
    if (!hasValidTryOnSelection()) return;
    tryOnTimeoutId = setTimeout(() => {
      requestTryOnPreview();
    }, 450);
  }


  /* ─────────────────────────────────────────────
     2. Wardrobe Category Filter Tabs
  ───────────────────────────────────────────── */
  const filterTabs  = document.querySelectorAll(".filter-tab");
  const wardrobeCards = document.querySelectorAll(".wardrobe-card");
  const tryOnSelectButtons = document.querySelectorAll(".wardrobe-card__select");

  filterTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const cat = tab.dataset.cat;

      // Update active tab
      filterTabs.forEach(t => t.classList.remove("filter-tab--active"));
      tab.classList.add("filter-tab--active");

      // Show/hide cards
      wardrobeCards.forEach(card => {
        const match = cat === "all" || card.dataset.category === cat;
        card.classList.toggle("is-hidden", !match);
      });
    });
  });

  tryOnSelectButtons.forEach(button => {
    button.addEventListener("click", () => {
      const itemId = button.dataset.itemId;
      const category = button.dataset.category;
      const parentCard = button.closest(".wardrobe-card");

      if (selectedTryOnItems.has(itemId)) {
        selectedTryOnItems.delete(itemId);
        parentCard?.classList.remove("wardrobe-card--selected");
        button.textContent = "Select for AI";
        updateTryOnCount();
        return;
      }

      for (const [existingId, selected] of selectedTryOnItems.entries()) {
        if (selected.category === category) {
          selectedTryOnItems.delete(existingId);
          const existingButton = document.querySelector(`.wardrobe-card__select[data-item-id="${existingId}"]`);
          existingButton?.closest(".wardrobe-card")?.classList.remove("wardrobe-card--selected");
          if (existingButton) existingButton.textContent = "Select for AI";
        }
      }

      if (selectedTryOnItems.size >= 4) {
        showTryOnError("Select up to four items for one preview.");
        return;
      }

      clearTryOnError();
      selectedTryOnItems.set(itemId, {
        id: itemId,
        category,
        name: button.dataset.name,
      });
      parentCard?.classList.add("wardrobe-card--selected");
      button.textContent = "Selected";
      updateTryOnCount();
      scheduleTryOnPreview();
    });
  });

  if (tryOnBtn) {
    tryOnBtn.addEventListener("click", async () => {
      requestTryOnPreview();
    });
  }

  [occasionSelect, styleVibeSelect].forEach(control => {
    control?.addEventListener("change", () => {
      if (hasValidTryOnSelection()) scheduleTryOnPreview();
    });
  });

  stylingGoalInput?.addEventListener("change", () => {
    if (hasValidTryOnSelection()) scheduleTryOnPreview();
  });


  /* ─────────────────────────────────────────────
     3. Delete Wardrobe Item
  ───────────────────────────────────────────── */
  document.querySelectorAll(".wardrobe-card__delete").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id   = btn.dataset.id;
      const card = btn.closest(".wardrobe-card");

      if (!confirm("Remove this item from your wardrobe?")) return;

      try {
        const res = await fetch(`${window.APP.deleteUrlBase}${id}`, { method: "POST" });
        if (res.ok) {
          card.style.opacity = "0";
          card.style.transition = "opacity .2s ease";
          setTimeout(() => card.remove(), 200);
        } else {
          alert("Could not delete item. Please try again.");
        }
      } catch {
        alert("Network error. Please try again.");
      }
    });
  });


  /* ─────────────────────────────────────────────
     4. Premium Modal
  ───────────────────────────────────────────── */
  const premiumBtn  = document.getElementById("premiumBtn");
  const modal       = document.getElementById("premiumModal");
  const closeModal  = document.getElementById("closeModal");
  const stripeBtn   = document.getElementById("stripeBtn");
  const backdrop    = modal?.querySelector(".modal__backdrop");

  function openModal()  { modal.classList.add("is-open"); document.body.style.overflow = "hidden"; }
  function closeModalFn() { modal.classList.remove("is-open"); document.body.style.overflow = ""; }

  if (premiumBtn && modal) {
    premiumBtn.addEventListener("click", openModal);
    closeModal.addEventListener("click", closeModalFn);
    backdrop.addEventListener("click", closeModalFn);

    document.addEventListener("keydown", e => {
      if (e.key === "Escape") closeModalFn();
    });
  }

  document.querySelectorAll(".premium-trigger").forEach(btn => {
    if (btn) btn.addEventListener("click", openModal);
  });

  // Stripe CTA — records intent and redirects to Stripe checkout when configured
  if (stripeBtn) {
    stripeBtn.addEventListener("click", async () => {
      stripeBtn.classList.add("btn--loading");
      stripeBtn.textContent = "Redirecting…";

      try {
        const res  = await fetch(window.APP.upgradeUrl, { method: "POST" });
        const data = await res.json();

        if (data.checkout_url) {
          // Stripe is configured → redirect to hosted checkout page
          window.location.href = data.checkout_url;
        } else {
          // Stripe not yet wired up → show placeholder message
          stripeBtn.textContent = "Stripe Not Yet Configured";
          stripeBtn.classList.remove("btn--loading");
          setTimeout(() => { stripeBtn.textContent = "Upgrade to Pro — $20/mo"; }, 2500);
        }
      } catch {
        stripeBtn.textContent = "Something went wrong";
        stripeBtn.classList.remove("btn--loading");
      }
    });
  }


  /* ─────────────────────────────────────────────
     5. Auto-dismiss Flash Messages
  ───────────────────────────────────────────── */
  document.querySelectorAll(".flash").forEach(flash => {
    setTimeout(() => {
      flash.style.transition = "opacity .4s ease";
      flash.style.opacity = "0";
      setTimeout(() => flash.remove(), 400);
    }, 4000);
  });

  /* ─────────────────────────────────────────────
     6. AI Closet Analyst
  ───────────────────────────────────────────── */
  const analyzeBtn = document.getElementById("analyzeBtn");
  const analystResult = document.getElementById("analystResult");
  const analystError = document.getElementById("analystError");

  if (analyzeBtn) {
    analyzeBtn.addEventListener("click", async () => {
      analyzeBtn.classList.add("btn--loading");
      analyzeBtn.textContent = "Analyzing…";
      
      if (analystError) analystError.style.display = "none";
      if (analystResult) analystResult.style.display = "none";

      try {
        const res  = await fetch(window.APP.analyzeUrl, { method: "POST" });
        const data = await res.json();

        if (!res.ok || data.error) {
          if (analystError) {
            analystError.textContent = data.error || "Analysis failed.";
            analystError.style.display = "block";
          }
          return;
        }

        if (analystResult) {
          analystResult.innerHTML = data.analysis;
          analystResult.style.display = "block";
        }

      } catch (err) {
        if (analystError) {
          analystError.textContent = "Network error while analyzing.";
          analystError.style.display = "block";
        }
      } finally {
        analyzeBtn.classList.remove("btn--loading");
        analyzeBtn.textContent = "Analyze My Wardrobe";
      }
    });
  /* ─────────────────────────────────────────────
     7. Digital Style Board
  ───────────────────────────────────────────── */
  const board = document.getElementById("styleBoardDropzone");
  const hint = document.getElementById("styleBoardHint");
  const clearBtn = document.getElementById("clearBoardBtn");

  if (board) {
    let zIndexCounter = 1;

    document.querySelectorAll('.drag-item').forEach(item => {
      item.addEventListener('dragstart', (e) => {
        e.dataTransfer.setData('src', e.target.src);
        e.dataTransfer.setData('offsetX', e.offsetX);
        e.dataTransfer.setData('offsetY', e.offsetY);
      });
    });

    board.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
    });

    board.addEventListener('drop', (e) => {
      e.preventDefault();
      const src = e.dataTransfer.getData('src');
      if (!src) return;

      if (hint) hint.style.display = 'none';

      const offsetX = parseInt(e.dataTransfer.getData('offsetX') || 50, 10);
      const offsetY = parseInt(e.dataTransfer.getData('offsetY') || 50, 10);
      
      const rect = board.getBoundingClientRect();
      const x = e.clientX - rect.left - offsetX;
      const y = e.clientY - rect.top - offsetY;

      const wrapper = document.createElement('div');
      wrapper.style.position = 'absolute';
      wrapper.style.left = `${x}px`;
      wrapper.style.top = `${y}px`;
      wrapper.style.width = '150px';
      wrapper.style.height = 'auto';
      wrapper.style.cursor = 'move';
      wrapper.style.zIndex = zIndexCounter++;
      
      wrapper.style.resize = 'both';
      wrapper.style.overflow = 'hidden';
      wrapper.style.border = '2px solid transparent';
      wrapper.style.padding = '4px';
      wrapper.style.borderRadius = '8px';
      wrapper.style.boxShadow = '0 4px 12px rgba(0,0,0,0.1)';
      wrapper.style.background = 'transparent';

      const img = document.createElement('img');
      img.src = src;
      img.style.width = '100%';
      img.style.height = '100%';
      img.style.objectFit = 'contain';
      img.style.pointerEvents = 'none';

      wrapper.appendChild(img);
      board.appendChild(wrapper);

      let isDragging = false;
      let startX, startY, initialX, initialY;

      wrapper.addEventListener('mousedown', (ev) => {
        const wrapRect = wrapper.getBoundingClientRect();
        if (ev.clientX > wrapRect.right - 15 && ev.clientY > wrapRect.bottom - 15) return;

        isDragging = true;
        wrapper.style.zIndex = zIndexCounter++;
        wrapper.style.border = '2px solid var(--accent)';
        startX = ev.clientX;
        startY = ev.clientY;
        initialX = parseFloat(wrapper.style.left);
        initialY = parseFloat(wrapper.style.top);
        ev.preventDefault();
      });

      document.addEventListener('mousemove', (ev) => {
        if (!isDragging) return;
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;
        wrapper.style.left = `${initialX + dx}px`;
        wrapper.style.top = `${initialY + dy}px`;
      });

      document.addEventListener('mouseup', () => {
        if (isDragging) {
           isDragging = false;
           wrapper.style.border = '2px solid transparent';
        }
      });
      
      wrapper.addEventListener('dblclick', () => {
        wrapper.remove();
        if (board.querySelectorAll('div').length === 0 && hint) {
            hint.style.display = 'block';
        }
      });
    });

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        board.querySelectorAll('div').forEach(div => div.remove());
        if (hint) hint.style.display = 'block';
      });
    }
  }

  /* ─────────────────────────────────────────────
     8. Simulated Real-Time Activity Ticker
  ───────────────────────────────────────────── */
  if (window.location.pathname === '/' || window.location.pathname === '/dashboard') {
    const toastContainer = document.createElement("div");
    toastContainer.style.position = "fixed";
    toastContainer.style.bottom = "20px";
    toastContainer.style.right = "20px";
    toastContainer.style.display = "flex";
    toastContainer.style.flexDirection = "column";
    toastContainer.style.gap = "10px";
    toastContainer.style.zIndex = "9999";
    toastContainer.style.pointerEvents = "none";
    document.body.appendChild(toastContainer);

    const activities = [
      "Sarah in NY just styled a 'Coffee Date' look ✨",
      "Mike just unlocked Pro Analyst 💎",
      "Emma uploaded 5 new vintage items 📸",
      "A new 'Smart Casual' outfit was built in London 🎨",
      "James exported his wardrobe analytics 📊",
      "Chloe found 3 missing wardrobe essentials 🧠"
    ];

    function showActivity() {
      const toast = document.createElement("div");
      toast.style.background = "var(--white)";
      toast.style.color = "var(--black)";
      toast.style.padding = "12px 20px";
      toast.style.borderRadius = "8px";
      toast.style.boxShadow = "var(--shadow-lg)";
      toast.style.borderLeft = "4px solid var(--accent)";
      toast.style.fontSize = "0.85rem";
      toast.style.fontWeight = "500";
      toast.style.transform = "translateX(120%)";
      toast.style.transition = "transform 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275), opacity 0.5s ease";
      toast.style.opacity = "0";
      toast.textContent = activities[Math.floor(Math.random() * activities.length)];
      
      toastContainer.appendChild(toast);
      
      setTimeout(() => {
        toast.style.transform = "translateX(0)";
        toast.style.opacity = "1";
      }, 100);

      setTimeout(() => {
        toast.style.transform = "translateX(120%)";
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 500);
      }, 5000);
      
      setTimeout(showActivity, 15000 + Math.random() * 20000);
    }
    
    setTimeout(showActivity, 3000);
  }

});
