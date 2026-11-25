'use strict';

const byId = id => document.getElementById(id);
const settings = document.body.dataset;
const threshold = Number(settings.threshold);
const radius = Number(settings.fleeRadius);
const gradeMax = Number(settings.gradeMax);
const arena = byId('arena');
const dialog = byId('dialog');
const form = byId('form');

// Plus la note est haute, plus elle est facile à atteindre.
const mix = (from, to, ratio) => from + (to - from) * ratio;
// Bonnes notes : de petite (au seuil) à énorme (la note maximale).
const goodSize = grade => Math.round(mix(60, 132,
  gradeMax === threshold ? 1 : (grade - threshold) / (gradeMax - threshold)));
// Mauvaises notes : plus elles sont basses, plus elles sont petites et craintives.
const badRatio = grade => (threshold <= 1 ? 0 : grade / (threshold - 1));
const runaways = [];
const dodgers = [];
const buttons = [];
let pointer = null;
let pendingEscapes = {};
let chosen = null;

// ---------- Boutons ----------

for (let grade = 0; grade <= gradeMax; grade++) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'grade';
  button.textContent = grade;
  const size = grade >= threshold ? goodSize(grade) : Math.round(mix(40, 54, badRatio(grade)));
  button.style.width = button.style.height = `${size}px`;
  button.style.fontSize = `${Math.round(size * 0.36)}px`;
  const item = { button, grade, size, home: { x: 0, y: 0 }, x: 0, y: 0, scared: false };
  if (grade >= threshold) {
    button.classList.add('good');
    button.addEventListener('click', () => openDialog(grade));
    button.style.zIndex = grade + 1; // la meilleure note reste au-dessus
    // La note maximale ne bouge pas ; chaque point en dessous ajoute une esquive, plus longue.
    const rank = gradeMax - grade;
    item.maxHops = Math.min(rank, 6);
    item.hopLength = Math.min(35 + 25 * rank, 180);
    item.hops = 0;
    item.movedAt = 0;
    if (rank > 0) dodgers.push(item);
  } else {
    button.classList.add('bad');
    button.tabIndex = -1; // pas de triche au clavier
    button.setAttribute('aria-disabled', 'true');
    const modes = ['flee', 'vanish', 'shrink'];
    item.radius = Math.max(size + 20, radius * mix(1.35, 0.8, badRatio(grade)));
    item.mode = settings.fleeMode === 'chaos' ? modes[grade % modes.length] : settings.fleeMode;
    runaways.push(item);
  }
  buttons.push(item);
  arena.append(button);
}

function place(item, x, y) {
  item.x = x;
  item.y = y;
  item.button.style.left = `${x}px`;
  item.button.style.top = `${y}px`;
}

function layout() {
  const gap = 18;
  const rows = [];
  let row = null;
  // Les tailles varient : on remplit les lignes une à une, puis on les centre.
  for (const item of buttons) {
    if (!row || row.width + gap + item.size > arena.clientWidth - 2 * gap) {
      row = { items: [], width: -gap, height: 0 };
      rows.push(row);
    }
    row.items.push(item);
    row.width += gap + item.size;
    row.height = Math.max(row.height, item.size);
  }
  // Marge verticale pour que les notes aient de la place pour fuir.
  let top = 60;
  for (const { items, width: rowWidth, height } of rows) {
    let left = (arena.clientWidth - rowWidth) / 2;
    for (const item of items) {
      item.home.x = left;
      item.home.y = top + (height - item.size) / 2;
      left += item.size + gap;
    }
    top += height + gap;
  }
  arena.style.height = `${top + 60}px`;
  buttons.forEach(item => place(item, item.home.x, item.home.y));
}

// Distance entre la souris et le centre de la note si elle était placée en (x, y).
const distance = (item, x, y) =>
  Math.hypot(x + item.size / 2 - pointer.x, y + item.size / 2 - pointer.y);
const clamp = (value, max) => Math.min(Math.max(value, 0), max);

function runAway(item) {
  const half = item.size / 2;
  const maxX = arena.clientWidth - item.size;
  const maxY = arena.clientHeight - item.size;
  const angle = Math.atan2(item.y + half - pointer.y, item.x + half - pointer.x);
  let x = clamp(pointer.x + Math.cos(angle) * (item.radius + 20) - half, maxX);
  let y = clamp(pointer.y + Math.sin(angle) * (item.radius + 20) - half, maxY);
  // Coincée contre un bord : téléportation au point le plus éloigné parmi plusieurs essais.
  if (distance(item, x, y) < item.radius) {
    for (let attempt = 0; attempt < 12; attempt++) {
      const tryX = Math.random() * maxX;
      const tryY = Math.random() * maxY;
      if (distance(item, tryX, tryY) > distance(item, x, y)) [x, y] = [tryX, tryY];
    }
  }
  place(item, x, y);
}

// Une bonne note esquive quelques fois puis se fatigue : elle reste toujours attrapable.
function dodge(item) {
  if (item.hops >= item.maxHops || performance.now() - item.movedAt < 250
      || distance(item, item.x, item.y) > item.size / 2 + 10) return;
  const half = item.size / 2;
  const maxX = arena.clientWidth - item.size;
  const maxY = arena.clientHeight - item.size;
  const away = Math.atan2(item.y + half - pointer.y, item.x + half - pointer.x);
  let best = null;
  // À l'opposé de la souris ; contre un bord, on essaie des directions de plus en plus écartées.
  for (const turn of [0, 1, -1, 2, -2, 3, -3, 4]) {
    const angle = away + turn * Math.PI / 4;
    const x = clamp(item.x + Math.cos(angle) * item.hopLength, maxX);
    const y = clamp(item.y + Math.sin(angle) * item.hopLength, maxY);
    const gap = distance(item, x, y);
    if (!best || gap > best.gap) best = { x, y, gap };
    if (gap > half + 10) break;
  }
  item.hops++;
  item.movedAt = performance.now();
  place(item, best.x, best.y);
}

function react() {
  if (pointer) dodgers.forEach(dodge);
  for (const item of runaways) {
    const gap = pointer ? distance(item, item.x, item.y) : Infinity;
    const near = gap < item.radius;
    if (near && !item.scared) {
      pendingEscapes[item.grade] = Math.min((pendingEscapes[item.grade] || 0) + 1, 1000);
    }
    item.scared = near;
    if (item.mode === 'flee') {
      if (near) runAway(item);
    } else {
      // 0 quand la souris est proche, 1 à la limite du rayon.
      const factor = near ? Math.max(0, (gap - item.size) / (item.radius - item.size)) : 1;
      if (item.mode === 'vanish') item.button.style.opacity = factor;
      else item.button.style.transform = `scale(${factor})`;
    }
  }
}

function track(event) {
  const box = arena.getBoundingClientRect();
  pointer = { x: event.clientX - box.left, y: event.clientY - box.top };
  react();
}

arena.addEventListener('pointermove', track);
arena.addEventListener('pointerdown', track); // écrans tactiles
arena.addEventListener('pointerleave', () => {
  pointer = null;
  react();
  for (const item of [...runaways, ...dodgers]) place(item, item.home.x, item.home.y);
  dodgers.forEach(item => { item.hops = 0; });
});

let width = 0;
new ResizeObserver(() => {
  if (arena.clientWidth !== width) {
    width = arena.clientWidth;
    layout();
  }
}).observe(arena);

// ---------- Base de données ----------

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || `Erreur ${response.status}`);
  return data;
}

function show(id, message) {
  const element = byId(id);
  element.textContent = message || '';
  element.hidden = !message;
}

const formatDate = iso => iso
  ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' })
  : '–';

// textContent uniquement : les noms et commentaires viennent des visiteurs.
function element(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function render(state) {
  const { grades, escapes, instance } = state;
  byId('average').textContent = grades.average === null
    ? '–' : grades.average.toLocaleString('fr-FR');
  byId('total').textContent = grades.total;
  byId('visits').textContent = state.visits;
  byId('escape-total').textContent = escapes.reduce((sum, row) => sum + row.total, 0);
  byId('instance').textContent = instance.name;
  byId('started').textContent = formatDate(instance.started_at);
  byId('before-start').textContent = grades.before_start;
  byId('first').textContent = formatDate(grades.first_at);

  byId('history').replaceChildren(...grades.history.map(row => {
    const entry = document.createElement('li');
    const text = document.createElement('div');
    text.append(element('strong', row.juror));
    if (row.comment) text.append(element('p', row.comment));
    text.append(element('small', `#${row.id} · ${formatDate(row.created_at)} · ${row.instance}`));
    entry.append(element('b', row.grade, 'badge'), text);
    return entry;
  }));
  if (!grades.history.length) {
    byId('history').append(element('li', 'Aucune note pour le moment.'));
  }

  byId('escapes').replaceChildren(...escapes.slice(0, 5).map(row =>
    element('li', `Le ${row.grade}/${gradeMax} s'est échappé ${row.total} fois`)));
}

async function refresh() {
  const sending = pendingEscapes;
  pendingEscapes = {};
  try {
    if (Object.keys(sending).length) {
      try {
        await api('/api/escapes', { counts: sending });
      } catch (problem) {
        for (const [grade, count] of Object.entries(sending)) {
          pendingEscapes[grade] = Math.min((pendingEscapes[grade] || 0) + count, 1000);
        }
        throw problem;
      }
    }
    render(await api('/api/state'));
    show('database-error', '');
  } catch (problem) {
    show('database-error', problem.message);
  }
}

// ---------- Formulaire ----------

function openDialog(grade) {
  chosen = grade;
  byId('chosen').textContent = grade;
  show('form-error', '');
  dialog.showModal();
}

byId('cancel').addEventListener('click', () => dialog.close());

form.addEventListener('submit', async event => {
  event.preventDefault();
  const submit = form.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    await api('/api/grades', { grade: chosen, ...Object.fromEntries(new FormData(form)) });
    dialog.close();
    form.reset();
    show('toast', `Merci ! Le ${chosen}/${gradeMax} est gravé dans PostgreSQL.`);
    setTimeout(() => show('toast', ''), 5000);
    await refresh();
  } catch (problem) {
    show('form-error', problem.message);
  } finally {
    submit.disabled = false;
  }
});

async function start() {
  try {
    await api('/api/visits', {});
  } catch (_) { /* refresh() affiche la panne */ }
  // Réactualisation périodique : les notes des autres jurés apparaissent en direct.
  const loop = async () => {
    await refresh();
    setTimeout(loop, 4000);
  };
  loop();
}

start();
