/* Progressive enhancement only. Server forms remain the source of truth. */
const root = document.documentElement;
const themeButton = document.querySelector('#theme');
function setTheme(theme) {
  root.dataset.theme = theme === 'light' ? 'light' : 'dark';
  if (themeButton) {
    themeButton.textContent = root.dataset.theme === 'dark' ? 'Light mode' : 'Dark mode';
    themeButton.setAttribute('aria-pressed', String(root.dataset.theme === 'dark'));
    themeButton.setAttribute('aria-description', `Current theme: ${root.dataset.theme}`);
  }
}
try { setTheme(localStorage.getItem('grind75-theme') || 'dark'); } catch (_) { setTheme('dark'); }
if (themeButton) themeButton.addEventListener('click', () => {
  setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark');
  try { localStorage.setItem('grind75-theme', root.dataset.theme); } catch (_) {}
});
const nav = document.querySelector('.nav-disclosure');
if (nav) {
  const mobile = matchMedia('(max-width:1000px)');
  const adaptNav = () => { nav.open = !mobile.matches; };
  adaptNav(); mobile.addEventListener('change', adaptNav);
}
document.querySelectorAll('[data-js-only]').forEach(el => { el.hidden = false; });
const dirtyForms = new Set();
document.querySelectorAll('form[method="post"]').forEach(form => {
  if (form.hasAttribute('data-dirty-guard')) {
    form.addEventListener('input', () => {
      dirtyForms.add(form);
      const state = form.querySelector('[data-save-state]');
      if (state) state.textContent = 'Unsaved changes';
    });
  }
  form.addEventListener('submit', async event => {
    if (form.hasAttribute('data-exact-record')) event.preventDefault();
    if (form.hasAttribute('data-exact-record')) dirtyForms.add(form);
    else dirtyForms.delete(form);
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) {
      button.dataset.originalText = button.textContent;
      button.disabled = true; button.setAttribute('aria-busy', 'true');
      button.textContent = form.enctype === 'multipart/form-data' ? 'Validating…' : 'Saving…';
    }
    if (form.hasAttribute('data-exact-record')) {
      // Native form encoding normalizes line endings. Encode the field strings
      // explicitly, preserving original CRLF/leading whitespace when unchanged.
      const data = new URLSearchParams(new FormData(form));
      form.querySelectorAll('textarea[data-original]').forEach(field => {
        const original = JSON.parse(field.dataset.original);
        const normalized = original.replace(/\r\n?/g, '\n');
        data.set(field.name, field.value === normalized ? original : field.value);
      });
      try {
        const response = await fetch(form.action, {method:'POST', body:data, credentials:'same-origin', redirect:'manual'});
        if (response.type !== 'opaqueredirect') throw new Error('Save rejected');
        dirtyForms.delete(form);
        // A fragment-only assign would leave the old button/flash in place.
        history.replaceState(null, '', form.dataset.returnUrl);
        location.reload();
      } catch (_) {
        dirtyForms.add(form);
        form.querySelector('[data-save-state]').textContent = 'Could not save. Your text is still here. Check your connection and sign-in, then try again.';
        button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = button.dataset.originalText;
      }
    }
  });
});
window.addEventListener('beforeunload', event => {
  if (dirtyForms.size) { event.preventDefault(); event.returnValue = ''; }
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('button[aria-busy="true"]').forEach(b => {
    b.disabled = false; b.removeAttribute('aria-busy');
    if (b.dataset.originalText) b.textContent = b.dataset.originalText;
  });
});
const exportForm = document.querySelector('#group-export');
if (exportForm) {
  const boxes = [...exportForm.querySelectorAll('input[name="problem_id"]:not(:disabled)')];
  const updateSelection = () => {
    const count = boxes.filter(b => b.checked).length;
    document.querySelector('#selection-count').textContent = `${count} saved record${count === 1 ? '' : 's'} selected`;
    exportForm.querySelector('[data-export-selected]').disabled = count === 0;
  };
  exportForm.addEventListener('change', updateSelection);
  document.querySelectorAll('[data-select-records]').forEach(button => button.addEventListener('click', () => {
    boxes.forEach(b => { b.checked = button.dataset.selectRecords === 'all'; }); updateSelection();
  }));
  updateSelection();
}
const preview = document.querySelector('[data-preview-form]');
if (preview) {
  const updateDecision = () => {
    let records = 0, fresh = 0, replace = 0;
    preview.querySelectorAll('[data-import-entry]').forEach(entry => {
      const skipped = entry.querySelector('input[name="skip"]').checked;
      entry.classList.toggle('is-skipped', skipped);
      if (!skipped) {
        records++; fresh += Number(entry.dataset.newCount);
        replace += entry.querySelectorAll('input[name^="replace_"]:checked').length;
      }
    });
    document.querySelector('#decision-summary').textContent = `${records} problems included · ${fresh} new fields · ${replace} replacements approved. All other existing values stay.`;
  };
  preview.addEventListener('change', updateDecision); updateDecision();
  document.querySelector('[data-expand-comparisons]').addEventListener('click', event => {
    const open = event.currentTarget.getAttribute('aria-pressed') !== 'true';
    preview.querySelectorAll('details[data-full-values]').forEach(d => { d.open = open; });
    event.currentTarget.setAttribute('aria-pressed', String(open));
    event.currentTarget.textContent = open ? 'Collapse full comparisons' : 'Expand full comparisons';
  });
}
document.querySelectorAll('[data-copy-code]').forEach(button => {
  if (!navigator.clipboard) return;
  button.hidden = false;
  button.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(document.querySelector(button.dataset.copyCode).textContent); button.textContent = 'Copied'; }
    catch (_) { button.textContent = 'Select code to copy'; }
  });
});

// Count Unicode characters, rather than UTF-16 units, to match server limits.
document.querySelectorAll('textarea[data-character-limit]').forEach(field => {
  const validate = () => field.setCustomValidity(field.value.includes('\0') ? 'Remove the null character from this field.' : Array.from(field.value).length > Number(field.dataset.characterLimit) ? 'Use at most 8,000 characters in this field.' : '');
  field.addEventListener('input', validate); validate();
});
