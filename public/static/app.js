const root = document.documentElement;
const themeButton = document.querySelector('#theme');
function setTheme(theme) {
  root.dataset.theme = theme;
  themeButton.textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
}
try { setTheme(localStorage.getItem('grind75-theme') || 'dark'); } catch (_) {}
themeButton.addEventListener('click', () => {
  const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(theme);
  try { localStorage.setItem('grind75-theme', theme); } catch (_) {}
});
// Every form has a unique server-side action token. Disable its submit control
// while navigating; repeated requests with the same token remain harmless.
document.querySelectorAll('form[method="post"]').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) { button.disabled = true; button.textContent = 'Saving…'; }
  });
});
window.addEventListener('pageshow', () => document.querySelectorAll('button:disabled').forEach(b => { b.disabled = false; location.reload(); }));
