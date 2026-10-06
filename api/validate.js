// Input checks for todos. Kept separate from server.js so they can be tested
// without a web server or a database.

const MAX_TITLE_LENGTH = 200;

function validateTitle(title) {
  if (typeof title !== 'string' || title.trim() === '') {
    return 'title is required';
  }
  if (title.trim().length > MAX_TITLE_LENGTH) {
    return `title must be at most ${MAX_TITLE_LENGTH} characters`;
  }
  return null;
}

module.exports = { validateTitle, MAX_TITLE_LENGTH };
