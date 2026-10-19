// This page runs in your browser, not in Docker. It calls the API on the same origin
// (/api/todos), and nginx in the web container forwards the request to api:5000 (slide 26).
const API = '/api/todos';
const list = document.getElementById('list');
const statusLine = document.getElementById('status');

async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${url} answered ${res.status}`);
  return res.status === 204 ? null : res.json();
}

function show(todos) {
  list.replaceChildren(...todos.map((t) => {
    const li = document.createElement('li');
    li.className = t.done ? 'done' : '';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = t.done;
    box.onchange = () => refresh(() => call('PATCH', `${API}/${t.id}`, { done: box.checked }));
    const text = document.createElement('span');
    text.textContent = t.title;
    const del = document.createElement('button');
    del.textContent = 'Delete';
    del.onclick = () => refresh(() => call('DELETE', `${API}/${t.id}`));
    li.append(box, text, del);
    return li;
  }));
}

async function refresh(action) {
  try {
    if (action) await action();
    show(await call('GET', API));
    statusLine.textContent = '';
  } catch (err) {
    statusLine.textContent = `${err.message}. Is the API running, and can it reach the database?`;
  }
}

document.getElementById('add').onsubmit = (e) => {
  e.preventDefault();
  const input = document.getElementById('title');
  refresh(() => call('POST', API, { title: input.value })).then(() => { input.value = ''; });
};

refresh();
