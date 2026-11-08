import { build } from 'esbuild';
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const source = new URL('./embedded.js', import.meta.url);
const result = await build({
  entryPoints: [fileURLToPath(source)],
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  minify: true,
  legalComments: 'inline',
  write: false,
});
const markup = await readFile(new URL('../../web/index.html', import.meta.url), 'utf8');
const styles = await readFile(new URL('../../web/style.css', import.meta.url), 'utf8');
const template = markup.replace('<html lang="zh-CN">', '<html lang="zh-CN" data-embedded>')
  .replace('href="/"', 'href="#main"')
  .replace('<link rel="stylesheet" href="/style.css">', () => `<style>${styles}</style>`)
  .replace('<script src="/app.js" defer></script>', '')
  .replace('</body>', '<!-- APP_BUNDLE --></body>');
const script = result.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
// The SDK contains literal "$&" and "$`" strings. A replacement string would
// interpret them as substitutions and corrupt the JavaScript inside the HTML.
const html = template.replace('<!-- APP_BUNDLE -->', () => `<script type="module">${script}</script>`);
await writeFile(new URL('./launcher.html', import.meta.url), html);
console.log(`Built self-contained MCP App: ${Buffer.byteLength(html)} bytes`);
