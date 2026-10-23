// Lab 5 · integration test: the API, started from source, with a real PostgreSQL.
// Copy this file to api/test/. Don't change it: the grader runs the course copy too.
//
// This test does not start anything. The API must already run and be connected
// to a database:
//   in CI:            the steps "Start the API" and "Wait for the API" in ci.yml
//   on your laptop:   bash lab05-ci-pipeline/itest.sh
//
// Only these tests:     npx jest --testPathPatterns=integration
// Only the unit tests:  npx jest --testPathIgnorePatterns=integration

const API_URL = process.env.API_URL || 'http://localhost:5000';

// Every title starts with this tag, so the tests only touch their own rows.
const TAG = `itest-${Date.now()}`;

// One HTTP request. Returns the status code and the JSON body (null if empty).
async function call(method, path, body) {
  const res = await fetch(API_URL + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  return { status: res.status, body: text ? JSON.parse(text) : null };
}

// Remove what the tests created, also when a test failed.
afterAll(async () => {
  const { status, body } = await call('GET', '/api/todos');
  if (status !== 200) return;
  for (const todo of body) {
    if (todo.title.startsWith(TAG)) await call('DELETE', `/api/todos/${todo.id}`);
  }
});

test('GET /api/todos answers 200 with a list', async () => {
  const res = await call('GET', '/api/todos');
  expect(res.status).toBe(200);
  expect(Array.isArray(res.body)).toBe(true);
});

test('POST stores a todo in the database, and GET returns it', async () => {
  const created = await call('POST', '/api/todos', { title: `  ${TAG} buy milk  ` });
  expect(created.status).toBe(201);
  expect(created.body.title).toBe(`${TAG} buy milk`); // the API trims the title
  expect(created.body.done).toBe(false); // the column default in db.js

  const list = await call('GET', '/api/todos');
  expect(list.body.map((todo) => todo.id)).toContain(created.body.id);
});

test('PATCH marks a todo as done and keeps its title', async () => {
  const { body: todo } = await call('POST', '/api/todos', { title: `${TAG} patch me` });
  const res = await call('PATCH', `/api/todos/${todo.id}`, { done: true });
  expect(res.status).toBe(200);
  expect(res.body.done).toBe(true);
  expect(res.body.title).toBe(`${TAG} patch me`);
});

test('DELETE removes a todo, and a second DELETE answers 404', async () => {
  const { body: todo } = await call('POST', '/api/todos', { title: `${TAG} delete me` });
  expect((await call('DELETE', `/api/todos/${todo.id}`)).status).toBe(204);
  expect((await call('DELETE', `/api/todos/${todo.id}`)).status).toBe(404);
});

test('POST with a blank title answers 400 and stores nothing', async () => {
  const res = await call('POST', '/api/todos', { title: '   ' });
  expect(res.status).toBe(400);
  expect(res.body.error).toMatch(/required/);

  const list = await call('GET', '/api/todos');
  expect(list.body.some((todo) => todo.title.trim() === '')).toBe(false);
});
