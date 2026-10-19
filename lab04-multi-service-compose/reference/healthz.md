# Lab 2 fallback: `/healthz` and the SIGTERM handler

Use this only if `check.sh preflight` says `api/server.js has no /healthz route`. It is Lab 2 step 2.4.

Open `api/server.js`. Under the comment `// Lab 2 (step 2.4): add the GET /healthz route here.` add:

```js
app.get('/healthz', (req, res) => res.status(200).json({ status: 'ok' }));
```

At the end of the file, under `// Lab 2 (step 2.4): add the SIGTERM handler here.`, add:

```js
process.on('SIGTERM', () => {
  console.log('SIGTERM received, closing the server');
  server.close(() => pool.end().then(() => process.exit(0)));
});
```

Then set `Reference files used (Lab 2 fallback): yes` at the top of `lab4/README.md`. It costs no points in Lab 4.
