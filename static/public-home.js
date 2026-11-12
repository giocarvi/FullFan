(() => {
  'use strict';

  const page = document.body;
  const mobileMenu = document.querySelector('.mobile-nav');
  mobileMenu.addEventListener('click', (event) => {
    if (event.target.closest('nav a')) mobileMenu.open = false;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobileMenu.open) {
      mobileMenu.open = false;
      mobileMenu.querySelector('summary').focus();
    }
  });

  // The price and checkout links originate from the same server-rendered plan.
  const currency = document.getElementById('currency-country');
  const currencyNote = document.getElementById('currency-note');
  const currencyByRegion = { GT: 'GT', HN: 'HN', NI: 'NI', CR: 'CR', MX: 'MX', SV: 'US', PA: 'US', US: 'US' };
  const referenceRates = {
    HN: ['L', 26.2, 'es-HN'],
    NI: ['C$', 36.8, 'es-NI'],
    CR: ['₡', 506, 'es-CR'],
    MX: ['MX$', 18.5, 'es-MX']
  };
  const options = new Map([...document.querySelectorAll('[data-option]')].map(el => [el.dataset.option, el]));
  const announcement = document.getElementById('plan-announcement');

  function price(option) {
    const { gtq, usd } = option.dataset;
    if (currency.value === 'GT' && gtq) return 'Q' + Number(gtq).toLocaleString('es-GT');
    if (Number(usd) <= 0 || !Number.isFinite(Number(usd))) return null;
    const rate = referenceRates[currency.value];
    if (!rate) return 'US$' + Number(usd).toFixed(2);
    const [symbol, multiplier, locale] = rate;
    return '≈ ' + symbol + Math.round(Number(usd) * multiplier).toLocaleString(locale);
  }

  function updatePlan(announce = false) {
    const mode = document.querySelector('[name=plan-mode]:checked').value;
    const term = document.querySelector('[name=plan-term]:checked').value;
    const selected = options.get(mode + '-' + term);
    for (const option of options.values()) option.hidden = option !== selected;
    document.querySelectorAll('[data-months]').forEach(el => {
      el.querySelector('[data-term-price]').textContent = price(options.get(mode + '-' + el.dataset.months)) || 'Consultar';
    });
    const amount = price(selected) || 'Precio a consultar';
    selected.querySelector('[data-checkout-price]').textContent = amount;
    currencyNote.textContent = referenceRates[currency.value]
      ? 'Conversión orientativa. Revisa la moneda y el importe en la plataforma de pago.'
      : currency.value === 'GT'
        ? 'Precios en quetzales para Guatemala. PayPal cobra en dólares.'
        : 'Precios en dólares. Confirma la moneda y el importe antes de pagar.';
    if (announce) announcement.textContent = selected.dataset.label + '. ' + amount;
  }

  const region = (navigator.language || '').split('-').find((part, i) => i > 0 && /^[a-z]{2}$/i.test(part));
  currency.value = currencyByRegion[region?.toUpperCase()] || 'GT';
  document.querySelector('.planner-options').addEventListener('change', () => updatePlan(true));
  updatePlan();

  const demoInterest = 'Demo gratis de 3 horas';
  let interest = demoInterest;
  const form = document.getElementById('lead-form');
  const title = document.getElementById('lead-title');
  const description = document.getElementById('lead-description');
  const interestLabel = document.getElementById('lead-interest');
  const resetDemo = document.getElementById('reset-demo');
  const preview = document.getElementById('lead-preview');
  const isPreview = page.hasAttribute('data-preview');

  function setInterest(plan) {
    interest = plan || demoInterest;
    const demo = interest === demoInterest;
    title.textContent = demo ? 'Prueba Fénix durante 3 horas' : 'Consulta sobre tu plan';
    description.textContent = demo
      ? 'Cuéntanos desde dónde nos escribes y en qué equipo quieres probarlo. No necesitas pagar para solicitar la demo.'
      : 'Envíanos el plan que elegiste y tu dispositivo. Te ayudamos a resolver dudas antes de pagar.';
    interestLabel.textContent = interest;
    resetDemo.hidden = demo;
    preview.hidden = true;
  }

  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-demo], [data-plan-inquiry]');
    if (action) {
      setInterest(action.dataset.planInquiry);
      if (action === resetDemo) title.focus({ preventScroll: true });
    }
    if (isPreview && event.target.closest('[data-external-action]')) {
      event.preventDefault();
      window.alert('Este enlace se abrirá en la página publicada. La vista previa no inicia pagos ni envía mensajes.');
    }
  });

  const country = document.getElementById('lead-country');
  country.addEventListener('input', () => country.setCustomValidity(''));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const from = country.value.trim();
    if (!from) {
      country.setCustomValidity('Indica tu país.');
      country.reportValidity();
      return;
    }
    const device = document.getElementById('lead-device').value;
    const notes = document.getElementById('lead-notes').value.trim();
    const message = [
      'Hola, Fénix Digital TV.',
      'Me interesa: ' + interest,
      'País: ' + from,
      'Dispositivo: ' + device,
      ...(notes ? ['Mensaje: ' + notes] : [])
    ].join('\n');
    if (isPreview) {
      preview.hidden = false;
      preview.textContent = 'Mensaje preparado, no enviado: ' + message.replace(/\n/g, ' · ');
      return;
    }
    const url = new URL(page.dataset.whatsapp);
    url.searchParams.set('text', message);
    window.location.assign(url.href);
  });

  let sdkPromise;
  function loadPayPal() {
    if (window.paypal?.HostedButtons) return Promise.resolve(window.paypal);
    if (!sdkPromise) {
      sdkPromise = new Promise((resolve, reject) => {
        const sdk = document.createElement('script');
        const query = new URLSearchParams({
          'client-id': page.dataset.paypalClient,
          components: 'hosted-buttons',
          'disable-funding': 'venmo',
          currency: 'USD'
        });
        sdk.src = 'https://www.paypal.com/sdk/js?' + query;
        sdk.async = true;
        const failed = () => {
          clearTimeout(timer);
          sdk.remove();
          reject(new Error('PayPal no está disponible'));
        };
        const timer = setTimeout(failed, 12000);
        sdk.onerror = failed;
        sdk.onload = () => {
          clearTimeout(timer);
          if (window.paypal?.HostedButtons) resolve(window.paypal);
          else failed();
        };
        document.head.appendChild(sdk);
      }).catch(error => {
        sdkPromise = null;
        throw error;
      });
    }
    return sdkPromise;
  }

  document.querySelectorAll('[data-paypal-button]').forEach(button => {
    const panel = document.getElementById(button.getAttribute('aria-controls'));
    const status = panel.querySelector('[role=status]');
    const host = panel.querySelector('[data-paypal-host]');
    let rendered = false;
    let busy = false;
    button.addEventListener('click', async () => {
      panel.hidden = !panel.hidden;
      button.setAttribute('aria-expanded', String(!panel.hidden));
      button.textContent = panel.hidden ? 'Mostrar PayPal (USD)' : 'Ocultar PayPal';
      if (panel.hidden || rendered || busy) return;
      if (isPreview) {
        status.textContent = 'Aquí se mostrará PayPal en dólares para el plan elegido.';
        return;
      }
      busy = true;
      status.textContent = 'Cargando PayPal…';
      try {
        const paypal = await loadPayPal();
        await paypal.HostedButtons({ hostedButtonId: panel.dataset.hostedId }).render('#' + host.id);
        status.textContent = '';
        rendered = true;
      } catch {
        host.replaceChildren();
        status.textContent = 'No se pudo cargar PayPal. Intenta de nuevo o consulta por WhatsApp.';
      } finally {
        busy = false;
      }
    });
  });
})();
