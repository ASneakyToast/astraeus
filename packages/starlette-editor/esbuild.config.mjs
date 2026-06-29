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
