// Lab 5 · OPTIONAL data-layer integration test: db.js against a real PostgreSQL,
// without HTTP and without starting the API.
// Copy it to api/test/ if you want it. It needs the same DB_* variables as the API.

const { pool, ensureSchema } = require('../db');

// Close the connection pool, or Jest waits for it and never exits.
afterAll(() => pool.end());

test('ensureSchema can run twice without an error', async () => {
  await ensureSchema();
  await ensureSchema();
});

test('the todos table has the columns the API uses', async () => {
  const { rows } = await pool.query(
    `SELECT column_name FROM information_schema.columns
      WHERE table_name = 'todos' ORDER BY column_name`
  );
  expect(rows.map((row) => row.column_name)).toEqual(['created_at', 'done', 'id', 'title']);
});

test('a new row gets an id, done = false and a created_at', async () => {
  const { rows } = await pool.query(
    "INSERT INTO todos (title) VALUES ('db-itest') RETURNING id, done, created_at"
  );
  try {
    expect(Number.isInteger(rows[0].id)).toBe(true);
    expect(rows[0].done).toBe(false);
    expect(rows[0].created_at).toBeInstanceOf(Date);
  } finally {
    await pool.query('DELETE FROM todos WHERE id = $1', [rows[0].id]);
  }
});

test('the database refuses a todo without a title', async () => {
  await expect(pool.query('INSERT INTO todos (title) VALUES (NULL)')).rejects.toThrow(
    /null value in column "title"/
  );
});
