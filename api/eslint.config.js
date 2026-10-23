// ESLint configuration for the course API (Lab 5).
// The API is CommonJS (require/module.exports) on Node.js 24. Tests use Jest.
const js = require('@eslint/js');
const globals = require('globals');

module.exports = [
  // Never lint generated files (jest --coverage writes coverage/).
  { ignores: ['coverage/'] },

  // ESLint's recommended rules: likely bugs only, no formatting rules.
  js.configs.recommended,

  // Every .js file: CommonJS, Node.js globals (process, console, require ...).
  {
    files: ['**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
      globals: { ...globals.node },
    },
    rules: {
      // Express finds an error handler by counting its 4 parameters
      // (err, req, res, next), so `next` must stay even when unused.
      // Names that start with _ are allowed to be unused too.
      'no-unused-vars': ['error', { argsIgnorePattern: '^_|^next$' }],
    },
  },

  // Test files also get the Jest globals (test, expect, describe ...).
  {
    files: ['test/**/*.js'],
    languageOptions: {
      globals: { ...globals.jest },
    },
  },
];
