// Suggestions under a text field from a long list: only the matches of what has been typed
const sources = new Map();
const MIN = 2, MAX = 50;

export function setSuggestions(listId, options, empty = []) {
  sources.set(listId, { options, empty });
}

export function isSuggestion(listId, value) {
  const v = value.trim().toLowerCase();
  const src = sources.get(listId);
  return !!src && [...src.empty, ...src.options].some(([o]) => o.toLowerCase() === v);
}

function matches(options, q) {
  const first = [], rest = [];
  for (const o of options) {
    const v = o[0].toLowerCase(), l = (o[1] || '').toLowerCase();
    if (v.startsWith(q) || l.startsWith(q)) first.push(o);
    else if (rest.length < MAX && (v.includes(q) || l.includes(q))) rest.push(o);
    if (first.length >= MAX) break;
  }
  return first.concat(rest).slice(0, MAX);
}

function fill(input) {
  const id = input.getAttribute('list');
  const src = id && sources.get(id);
  const dl = id && document.getElementById(id);
  if (!src || !dl) return;
  const q = input.value.trim().toLowerCase();
  dl.replaceChildren(...(q.length < MIN ? src.empty : matches(src.options, q)).map(([v, l]) => new Option(l || '', v)));
}

export function suggest(input, listId) {
  if (listId) input.setAttribute('list', listId); else input.removeAttribute('list');
  if (input.dataset.suggest) return;
  input.dataset.suggest = '1';
  input.addEventListener('input', () => fill(input));
  input.addEventListener('focus', () => fill(input));
}
