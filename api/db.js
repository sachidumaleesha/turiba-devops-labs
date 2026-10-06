// PostgreSQL connection pool. The pool connects lazily, on the first query,
// so the API starts even when no database is running.
const { Pool } = require('pg');

const pool = new Pool({
  host: process.env.DB_HOST || 'db',
  port: Number(process.env.DB_PORT) || 5432,
  user: process.env.DB_USER || 'todo',
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME || 'todo',
  connectionTimeoutMillis: 3000,
});

// An idle connection that breaks must not crash the API.
pool.on('error', (err) => {
  console.error(`Database connection lost: ${describeError(err)}`);
});

async function ensureSchema() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS todos (
      id         SERIAL PRIMARY KEY,
      title      TEXT NOT NULL,
      done       BOOLEAN NOT NULL DEFAULT false,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )`);
}

// Connection errors can arrive as an AggregateError (one error per address
// tried) with an empty message. Show what actually failed.
function describeError(err) {
  if (err.message) return err.message;
  if (Array.isArray(err.errors) && err.errors.length > 0) {
    return err.errors.map((e) => e.message).join('; ');
  }
  return err.code || String(err);
}

module.exports = { pool, ensureSchema, describeError };
