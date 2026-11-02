// Prints one line when the API starts, so the container log shows which version is running.
const { name, version } = require('./package.json');

console.log(`${name} ${version} starting (Node.js ${process.version})`);
