'use strict';
const $ = (id) => document.getElementById(id);
const types = {login_failed: 'Acceso fallido', login_success: 'Acceso exitoso', role_changed: 'Cambio de permisos'};
const statuses = {pending: 'Pendiente', investigating: 'En investigación', resolved: 'Resuelta'};
let state = {events: [], alerts: []};
let panelToken = '';
let publicDemo = false;
let alertFilter = 'open';
let page = 0;
let busy = false;
let toastTimer;
const pageSize = 8;
const dateFormat = new Intl.DateTimeFormat('es-CL', {day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit'});
const timeFormat = new Intl.DateTimeFormat('es-CL', {hour: '2-digit', minute: '2-digit'});
const esc = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const displayTime = (value) => dateFormat.format(new Date(value));

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = 'toast' + (error ? ' error' : '');
  $('toast').hidden = false;
  toastTimer = setTimeout(() => {$('toast').hidden = true;}, 5500);
}

async function request(path, data) {
  const options = data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Panel-Token': panelToken}, body: JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'No se pudo completar la operación.');
  return result;
}

async function refresh() {
  state = await request('/api/state');
  render();
  $('sync-label').textContent = 'Actualizado a las ' + timeFormat.format(new Date()) + ' · Actualización cada 15 s';
}

function render() {
  const open = state.alerts.filter(a => a.status !== 'resolved');
  $('event-count').textContent = state.events.length.toLocaleString('es-CL');
  $('open-count').textContent = open.length;
  $('high-count').textContent = open.filter(a => a.severity === 'high').length;
  $('resolved-count').textContent = state.alerts.length - open.length;
  $('nav-count').textContent = open.length;
  $('alert-count').textContent = state.alerts.length;
  renderAlerts();
  renderEvents();
}

function renderAlerts() {
  const alerts = state.alerts.filter(a => alertFilter === 'all' || (alertFilter === 'resolved' ? a.status === 'resolved' : a.status !== 'resolved'));
  $('alert-list').innerHTML = alerts.length ? alerts.map(a => `<button class="alert-item" data-alert="${esc(a.id)}" aria-label="Investigar: ${esc(a.title)}, ${esc(a.user)}"><span class="alert-symbol ${esc(a.severity)}" aria-hidden="true">${a.severity === 'high' ? '↗' : '◎'}</span><span class="alert-body"><h3>${esc(a.title)}</h3><span class="alert-user">${esc(a.user)}</span><span class="alert-meta"><span class="badge ${esc(a.severity)}">${a.severity === 'high' ? 'Alta' : 'Media'}</span><span class="status-badge ${esc(a.status)}">${esc(statuses[a.status])}</span><span>${a.evidence.length} ${a.evidence.length === 1 ? 'evento' : 'eventos'} de evidencia</span></span></span><span class="alert-time">${esc(timeFormat.format(new Date(a.occurred_at)))}<span aria-hidden="true">›</span></span></button>`).join('') : `<div class="empty-state"><span class="empty-icon" aria-hidden="true">◎</span><strong>${alertFilter === 'resolved' ? 'Todavía no hay alertas resueltas' : alertFilter === 'all' ? 'Tu laboratorio está listo' : 'Sin alertas abiertas'}</strong>${alertFilter === 'resolved' ? 'Investiga una alerta y guarda su resolución.' : 'Ejecuta una simulación para explorar las detecciones.'}</div>`;
}

function localDate(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
}

function renderEvents() {
  const query = $('event-search').value.trim().toLowerCase();
  const type = $('event-type').value;
  const date = $('event-date').value;
  const events = state.events.filter(e => (type === 'all' || e.type === type) && (!date || localDate(e.occurred_at) === date) && (!query || [e.user, e.source_ip, e.event_id].some(v => v.toLowerCase().includes(query))));
  const pages = Math.max(1, Math.ceil(events.length / pageSize));
  page = Math.max(0, Math.min(page, pages - 1));
  $('visible-count').textContent = `${events.length} DE ${state.events.length} EVENTOS`;
  $('page-label').textContent = `${page + 1} / ${pages}`;
  $('previous-page').disabled = page === 0;
  $('next-page').disabled = page >= pages - 1;
  $('event-rows').innerHTML = events.length ? events.slice(page * pageSize, (page + 1) * pageSize).map(e => `<tr><td>${esc(displayTime(e.occurred_at))}</td><td><span class="event-label"><span class="event-dot ${esc(e.type)}" aria-hidden="true"></span>${esc(types[e.type])}</span></td><td>${esc(e.user)}</td><td class="mono">${esc(e.source_ip)}</td><td class="mono event-id" title="${esc(e.event_id)}">${esc(e.event_id.slice(0, 10))}…</td></tr>`).join('') : `<tr><td colspan="5"><div class="empty-state">${state.events.length ? 'No hay eventos que coincidan con los filtros.' : 'Aún no hay eventos. Elige un escenario para empezar.'}</div></td></tr>`;
}

function openAlert(id) {
  const alert = state.alerts.find(a => a.id === id);
  if (!alert) return;
  const evidence = alert.evidence.map(id => state.events.find(e => e.event_id === id)).filter(Boolean);
  $('detail-content').innerHTML = `<span class="badge ${esc(alert.severity)}">Prioridad ${alert.severity === 'high' ? 'alta' : 'media'}</span><h2 id="detail-title" class="detail-title">${esc(alert.title)}</h2><div class="detail-user">${esc(alert.user)} · ${esc(displayTime(alert.occurred_at))}</div><p class="detail-description">${esc(alert.explanation)}</p><h3 class="evidence-title">EVIDENCIA · ${evidence.length} EVENTOS</h3><ol class="evidence-list">${evidence.map(e => `<li>${esc(types[e.type])} · ${esc(displayTime(e.occurred_at))}<small>${esc(e.source_ip)} · ${esc(e.event_id)}</small>${e.type === 'role_changed' ? `<span class="evidence-role">${esc(e.metadata.old_role)} → ${esc(e.metadata.new_role)}</span>` : ''}</li>`).join('')}</ol>`;
  $('detail-id').value = alert.id;
  $('detail-status').value = alert.status;
  $('detail-note').value = alert.note;
  $('alert-dialog').showModal();
}

$('alert-list').addEventListener('click', e => {
  const target = e.target.closest('[data-alert]');
  if (target) openAlert(target.dataset.alert);
});
document.querySelectorAll('[data-status]').forEach(button => button.addEventListener('click', () => {
  alertFilter = button.dataset.status;
  document.querySelectorAll('[data-status]').forEach(b => {b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button));});
  renderAlerts();
}));
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  document.querySelectorAll('[data-scenario]').forEach(b => {b.disabled = true;});
  try {
    const result = await request('/api/simulate', {scenario: button.dataset.scenario});
    page = 0;
    await refresh();
    toast(`${result.inserted} ${result.inserted === 1 ? 'evento guardado' : 'eventos guardados'}. ${button.dataset.scenario === 'normal' ? 'La actividad habitual no genera alertas.' : button.dataset.scenario === 'role' ? 'Se generó una alerta de cambio de permisos.' : 'Se generaron dos alertas para investigar.'}`);
  } catch (error) { toast(error.message, true); }
  finally { busy = false; document.querySelectorAll('[data-scenario]').forEach(b => {b.disabled = false;}); }
}));
$('investigation-form').addEventListener('submit', async e => {
  e.preventDefault();
  $('save-button').disabled = true;
  try {
    await request('/api/alerts/update', {id: $('detail-id').value, status: $('detail-status').value, note: $('detail-note').value});
    $('alert-dialog').close();
    await refresh();
    toast(publicDemo ? 'Investigación guardada en SQLite para tu sesión de demo.' : 'Investigación guardada en tu base de datos local.');
  } catch (error) {toast(error.message, true);}
  finally {$('save-button').disabled = false;}
});
['event-search', 'event-type', 'event-date'].forEach(id => $(id).addEventListener(id === 'event-search' ? 'input' : 'change', () => {page = 0; renderEvents();}));
$('clear-filters').addEventListener('click', () => {$('event-search').value = ''; $('event-type').value = 'all'; $('event-date').value = ''; page = 0; renderEvents();});
$('previous-page').addEventListener('click', () => {page--; renderEvents();});
$('next-page').addEventListener('click', () => {page++; renderEvents();});
$('rules-button').addEventListener('click', () => $('rules-dialog').showModal());
document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => $(button.dataset.close).close()));
$('export-button').addEventListener('click', async () => {
  try {
    const data = await request('/api/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify({exported_at: new Date().toISOString(), ...data}, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url; link.download = 'vigia-eventos-' + localDate(new Date()) + '.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast('Exportación descargada. No incluye credenciales de ingesta.');
  } catch (error) {toast(error.message, true);}
});
$('timezone').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone;
async function connect() {
  try {
    const bootstrap = await request('/api/bootstrap');
    panelToken = bootstrap.panel_token;
    publicDemo = bootstrap.mode === 'public_demo';
    if (publicDemo) {
      $('environment-label').textContent = 'DEMO';
      $('lab-mode').textContent = 'Demo pública';
      $('lab-title').textContent = 'Python y SQLite, funcionando en el servidor';
      $('lab-description').textContent = 'Datos ficticios y sesión propia. Caduca a las 24 horas. No ingreses información personal ni credenciales.';
      $('simulation-description').textContent = 'Cada escenario se procesa en Python y se guarda en SQLite para tu sesión.';
      $('reset-demo').hidden = false;
    }
    await refresh();
  } catch (error) {
    $('sync-label').textContent = 'Sin conexión · Reintentando en 15 s';
    toast('No se pudo conectar. Comprueba que el servidor siga ejecutándose.', true);
  }
}
connect();
setInterval(async () => {
  if (busy || $('alert-dialog').open || $('rules-dialog').open || $('reset-dialog').open) return;
  await connect();
}, 15000);

$('reset-demo').addEventListener('click', () => $('reset-dialog').showModal());
$('confirm-reset').addEventListener('click', async () => {
  if (busy) return;
  busy = true;
  $('confirm-reset').disabled = true;
  try {
    await request('/api/reset', {});
    $('reset-dialog').close();
    page = 0;
    $('event-search').value = '';
    $('event-type').value = 'all';
    $('event-date').value = '';
    await refresh();
    toast('Tu demo se reinició. Puedes probar otro escenario.');
  } catch (error) { toast(error.message, true); }
  finally { busy = false; $('confirm-reset').disabled = false; }
});
