import * as esbuild from 'esbuild'

const dev = process.argv.includes('--dev')

await esbuild.build({
  entryPoints: ['editor_src/index.js'],
  bundle: true,
  minify: !dev,
  sourcemap: dev ? 'inline' : false,
  outfile: 'starlette_editor/static/editor.js',
  format: 'iife',
  globalName: 'AstraeusEditor',
  target: ['es2020'],
})

console.log(`Built starlette_editor/static/editor.js (${dev ? 'dev' : 'prod'})`)

await esbuild.build({
  entryPoints: ['editor_src/embed/index.js'],
  bundle: true,
  minify: !dev,
  sourcemap: dev ? 'inline' : false,
  outfile: 'starlette_editor/static/embed.js',
  format: 'iife',
  target: ['es2020'],
  // No globalName — the embed script is self-contained, exports nothing
})

console.log(`Built starlette_editor/static/embed.js (${dev ? 'dev' : 'prod'})`)
