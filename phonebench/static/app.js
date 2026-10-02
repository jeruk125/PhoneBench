document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.matches('select[name="movement_type"]')) {
    const adjustment = document.querySelector('input[name="adjustment"]');
    if (adjustment) adjustment.disabled = event.target.value !== "ADJUSTMENT";
  }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const input = document.querySelector(button.dataset.copy);
  if (!input) return;
  input.select();
  await navigator.clipboard.writeText(input.value);
  button.textContent = "Copied";
});
