/* HarvestLink UI — progressive enhancement, never blocks basic form usage. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Brief, unobtrusive intro. Hidden even when DOM images or external fonts don't load.
  function dismissLoader() {
    const loader = $('#page-loader');
    if (!loader) return;
    loader.classList.add('is-hidden');
    setTimeout(() => loader.remove(), 700);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => setTimeout(dismissLoader, reduceMotion ? 0 : 450), { once: true });
  } else setTimeout(dismissLoader, reduceMotion ? 0 : 450);
  window.addEventListener('pageshow', (event) => { if (event.persisted) dismissLoader(); });

  // Navigation
  const menu = $('#menu-toggle'), mobileNav = $('#mobile-nav');
  menu?.addEventListener('click', () => {
    const open = mobileNav.classList.toggle('is-open');
    menu.setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  });
  $$('#mobile-nav a').forEach(a => a.addEventListener('click', () => {
    mobileNav.classList.remove('is-open');
    menu?.setAttribute('aria-expanded','false');
  }));

  // Scroll entrances
  if ('IntersectionObserver' in window && !reduceMotion) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) { entry.target.classList.add('in-view'); observer.unobserve(entry.target); }
      });
    }, { threshold: .07, rootMargin: '0px 0px -10px 0px' });
    $$('.reveal').forEach((el, index) => {
      el.style.transitionDelay = `${Math.min(index % 3, 2) * 85}ms`;
      observer.observe(el);
    });
  } else $$('.reveal').forEach(el => el.classList.add('in-view'));

  // Restrained depth on mouse and stylus. Avoid moving forms/buttons.
  if (!reduceMotion && window.matchMedia('(pointer: fine)').matches) {
    $$('[data-tilt]').forEach(el => {
      let raf = 0;
      el.addEventListener('pointermove', e => {
        const rect = el.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width - .5) * 2;
        const y = ((e.clientY - rect.top) / rect.height - .5) * 2;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
          if (el.classList.contains('float-card')) el.style.transform = `rotate(${6 + x * 3}deg) translate3d(${x * 7}px,${y * 7}px,0)`;
          else el.style.transform = `perspective(900px) rotateY(${x * 2.2}deg) rotateX(${-y * 2.2}deg) translateY(-3px)`;
        });
      });
      el.addEventListener('pointerleave', () => {
        cancelAnimationFrame(raf);
        el.style.transform = '';
      });
    });
    const landscape = $('.hero-landscape');
    const hero = $('[data-parallax]');
    hero?.addEventListener('pointermove', e => {
      if (!landscape) return;
      const x = (e.clientX / window.innerWidth - .5) * -13;
      const y = (e.clientY / window.innerHeight - .5) * -9;
      landscape.style.transform = `scale(1.06) translate3d(${x}px,${y}px,0)`;
    });
    hero?.addEventListener('pointerleave', () => { if (landscape) landscape.style.transform = 'scale(1.05)'; });
  }

  // Dialogs, accessible escape & backdrop closing.
  let activeModal = null;
  function showModal(id) {
    const modal = document.getElementById(id);
    if (!modal) return;
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden','false');
    document.body.classList.add('modal-open');
    activeModal = modal;
    modal.querySelector('input:not([type=hidden]),button')?.focus();
  }
  function hideModal() {
    if (!activeModal) return;
    activeModal.classList.remove('is-open');
    activeModal.setAttribute('aria-hidden','true');
    document.body.classList.remove('modal-open');
    activeModal = null;
  }
  $$('[data-modal-open]').forEach(el => el.addEventListener('click', () => showModal(el.dataset.modalOpen)));
  $$('[data-modal-close]').forEach(el => el.addEventListener('click', hideModal));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hideModal(); });

  // Crop calendar default guidance
  const cropName = $('#crop-name'), maturity = $('#maturity-days');
  cropName?.addEventListener('change', () => {
    const choice = cropName.options[cropName.selectedIndex];
    if (choice?.dataset.days && maturity) maturity.value = choice.dataset.days;
  });

  // Client-side order estimate (server always revalidates actual stock).
  const quantity = $('[data-quantity]'), total = $('[data-order-total]');
  if (quantity && total) {
    const update = () => {
      const qty = Math.max(0, Number(quantity.value) || 0);
      const price = Number(quantity.dataset.price) || 0;
      total.textContent = (qty * price).toLocaleString('en', { maximumFractionDigits: 2 });
    };
    quantity.addEventListener('input', update); update();
  }

  // Activity list client filtering
  $$('[data-filter-container]').forEach(group => {
    const buttons = $$('[data-filter]', group);
    const items = $$('[data-item-status]');
    buttons.forEach(button => button.addEventListener('click', () => {
      buttons.forEach(b => b.classList.toggle('active', b === button));
      items.forEach(item => { item.hidden = button.dataset.filter !== 'all' && item.dataset.itemStatus !== button.dataset.filter; });
    }));
  });

  // Share links without relying on third-party services
  $$('[data-copy]').forEach(button => button.addEventListener('click', async () => {
    const value = button.dataset.copy;
    const old = button.innerHTML;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
      else {
        const field = document.createElement('textarea');
        field.value=value; document.body.append(field); field.select();
        document.execCommand('copy'); field.remove();
      }
      button.textContent = 'Copied link ✓';
    } catch { window.prompt('Copy this link:', value); }
    setTimeout(() => { button.innerHTML = old; }, 2300);
  }));

  // Intentional confirmation on demo-only manual payment and cancellation.
  $$('[data-confirm]').forEach(button => button.addEventListener('click', e => {
    if (!window.confirm(button.dataset.confirm)) e.preventDefault();
  }));

  const dateLabel = $('[data-live-date]');
  if (dateLabel) dateLabel.textContent = new Intl.DateTimeFormat('en', { weekday:'short', day:'numeric', month:'short', year:'numeric' }).format(new Date());
})();
