const { validateTitle, MAX_TITLE_LENGTH } = require('../validate');

test('accepts a normal title', () => {
  expect(validateTitle('Buy milk')).toBeNull();
});

test('rejects a missing title', () => {
  expect(validateTitle(undefined)).toBe('title is required');
});

test('rejects a title of only spaces', () => {
  expect(validateTitle('   ')).toBe('title is required');
});

test('rejects a title that is not text', () => {
  expect(validateTitle(42)).toBe('title is required');
});

test('rejects a title that is too long', () => {
  expect(validateTitle('x'.repeat(MAX_TITLE_LENGTH + 1))).toMatch(/at most/);
});
