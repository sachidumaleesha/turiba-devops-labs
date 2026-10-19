// Runs in your browser. It calls the API at the address below.
const API = '/api/todos';
const list = document.getElementById('list');
const statusLine = document.getElementById('status');

async function load() {
  try {
    const res = await fetch(API);
    if (!res.ok) throw new Error(`GET ${API} answered ${res.status}`);
    list.replaceChildren(...(await res.json()).map((t) => {
      const li = document.createElement('li');
      li.textContent = t.title;
      return li;
    }));
    statusLine.textContent = '';
  } catch (err) {
    statusLine.textContent = err.message;
  }
}

document.getElementById('add').onsubmit = async (e) => {
  e.preventDefault();
  const input = document.getElementById('title');
  await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                     body: JSON.stringify({ title: input.value }) }).catch(() => {});
  input.value = '';
  load();
};

load();
