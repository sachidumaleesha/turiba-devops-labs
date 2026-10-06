// Course API: a small REST API for todos, stored in PostgreSQL.
// All configuration comes from environment variables (see .env.example).

// Load .env if there is one. Real deployments set the variables instead.
try {
  process.loadEnvFile();
} catch (err) {
  if (err.code !== 'ENOENT') throw err;
}

const express = require('express');
const { pool, ensureSchema, describeError } = require('./db');
const { validateTitle } = require('./validate');
const { version } = require('./package.json');

const PORT = process.env.PORT || 5000;
const app = express();
app.use(express.json());

app.get('/', (req, res) => {
  res.json({ name: 'course-api', version });
});

// Lab 2 (step 2.4): add the GET /healthz route here.

app.get('/api/todos', async (req, res) => {
  const { rows } = await pool.query(
    'SELECT id, title, done, created_at FROM todos ORDER BY id'
  );
  res.json(rows);
});

app.post('/api/todos', async (req, res) => {
  const error = validateTitle(req.body?.title);
  if (error) return res.status(400).json({ error });
  const { rows } = await pool.query(
    'INSERT INTO todos (title) VALUES ($1) RETURNING id, title, done, created_at',
    [req.body.title.trim()]
  );
  res.status(201).json(rows[0]);
});

app.patch('/api/todos/:id', async (req, res) => {
  const { title, done } = req.body ?? {};
  if (title !== undefined) {
    const error = validateTitle(title);
    if (error) return res.status(400).json({ error });
  }
  if (done !== undefined && typeof done !== 'boolean') {
    return res.status(400).json({ error: 'done must be true or false' });
  }
  const { rows } = await pool.query(
    `UPDATE todos
        SET title = COALESCE($2, title), done = COALESCE($3, done)
      WHERE id = $1
      RETURNING id, title, done, created_at`,
    [req.params.id, title?.trim(), done]
  );
  if (rows.length === 0) return res.status(404).json({ error: 'todo not found' });
  res.json(rows[0]);
});

app.delete('/api/todos/:id', async (req, res) => {
  const { rowCount } = await pool.query('DELETE FROM todos WHERE id = $1', [req.params.id]);
  if (rowCount === 0) return res.status(404).json({ error: 'todo not found' });
  res.status(204).end();
});

// Unknown routes
app.use((req, res) => {
  res.status(404).json({ error: 'not found' });
});

// Errors, for example when the database is not reachable
app.use((err, req, res, next) => {
  console.error(`${req.method} ${req.path} failed: ${describeError(err)}`);
  res.status(500).json({ error: 'internal error' });
});

const server = app.listen(PORT, () => {
  console.log(`API listening on port ${PORT}`);
});

ensureSchema()
  .then(() => console.log('Database ready'))
  .catch((err) => {
    console.warn(
      `Database not reachable (${describeError(err)}). ` +
        'The API keeps running; /api/todos answers 500 until a database is available.'
    );
  });

// Lab 2 (step 2.4): add the SIGTERM handler here.
