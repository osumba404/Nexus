// Epicenter Nexus — main JS (vanilla, no frameworks)

// Show the refresh badge after page load
document.addEventListener('DOMContentLoaded', () => {
  const badge = document.getElementById('refresh-badge');
  if (badge) badge.classList.remove('hidden');

  // Animate article cards on first load
  animateCards();
});

// Re-animate cards after every HTMX swap
document.addEventListener('htmx:afterSwap', (evt) => {
  animateCards(evt.target);
});

function animateCards(container) {
  const cards = (container || document).querySelectorAll('article');
  cards.forEach((card, i) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(12px)';
    setTimeout(() => {
      card.style.transition = 'opacity 300ms ease, transform 300ms ease';
      card.style.opacity = '1';
      card.style.transform = 'translateY(0)';
    }, i * 40);
  });
}

// Auto-dismiss flash messages
document.querySelectorAll('[data-autohide]').forEach(el => {
  setTimeout(() => el.remove(), 4000);
});

// Sync continent → country dropdowns (clear country when continent changes)
document.addEventListener('change', (e) => {
  if (e.target.name === 'continent') {
    const countrySelect = document.querySelector('select[name="country"]');
    if (countrySelect) countrySelect.value = '';
  }
});
