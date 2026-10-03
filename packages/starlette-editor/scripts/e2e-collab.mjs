/**
 * End-to-end collab harness (ADR 024 spike): the editor's REAL CollabConnection
 * and prosemirror-collab, against a live server, with no browser.
 *
 *   cd packages/starlette-editor
 *   node scripts/e2e-collab.mjs [verify|legacy|bug34 ...] [--fuzz-ops=300] [--seed=24]
 *
 * Scenarios (acceptance-suite ids from ADR 024):
 *   T1  an autocorrect-style batch (several steps in one transaction)
 *   T3  a client edits offline while another moves the server on, then reconnects
 *   T4  four clients, random edits, random disconnects; all must converge
 *
 * Each scenario also checks that no uniquely tagged insertion appears twice (the
 * #34 symptom). Run against `legacy` and `bug34` to see the harness fail where
 * it should: that is what shows the passes under `verify` mean something.
 */
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { EditorState, TextSelection } from 'prosemirror-state'
import { collab, sendableSteps, getVersion } from 'prosemirror-collab'
import { joinPoint } from 'prosemirror-transform'
import { schemaWithLists as schema } from '../editor_src/prosemirror/schema.js'

// ── browser globals the editor modules expect ────────────────────────────────
const store = new Map()
globalThis.localStorage = {
  getItem: (k) => store.get(k) ?? null,
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
}
globalThis.window = { dispatchEvent() {} }
globalThis.StorageEvent = class { constructor(type, init) { Object.assign(this, init) } }
const { CollabConnection } = await import('../editor_src/collab.js')
let currentTab = null
const originalConnect = CollabConnection.prototype._connect
CollabConnection.prototype._connect = function () {
  originalConnect.call(this)
  const tab = this.__tab ??= currentTab
  const ws = this.ws
  if (!ws || !tab) return
  const send = ws.send.bind(ws)
  ws.send = (data) => { tab.log.push({ t: Date.now(), dir: '>', data }); return send(data) }
  // Node's WebSocket (undici) re-fires `error` synchronously when close() is called on a
  // socket that is still connecting, so the editor's `onerror -> close()` recurses until
  // the stack overflows. Browsers treat close() on a closing socket as a no-op. Guard it.
  const onerror = ws.onerror
  let inside = false
  ws.onerror = (event) => { if (inside) return; inside = true; try { onerror?.(event) } finally { inside = false } }
}

const here = dirname(fileURLToPath(import.meta.url))
const cmsDir = resolve(here, '../../starlette-cms')
const args = process.argv.slice(2)
const flag = (name, dflt) => Number((args.find((a) => a.startsWith(`--${name}=`)) ?? '').split('=')[1] ?? dflt)
const modes = args.filter((a) => !a.startsWith('--'))
const FUZZ_OPS = flag('fuzz-ops', 300)
const SEED = flag('seed', 24)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
function rng(seed) { // mulberry32
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
async function freePort() {
  return new Promise((res) => {
    const s = createServer().listen(0, () => { const { port } = s.address(); s.close(() => res(port)) })
  })
}
async function until(cond, ms, what) {
  const end = Date.now() + ms
  while (Date.now() < end) { if (await cond()) return true; await sleep(25) }
  throw new Error(`timed out waiting for ${what}`)
}

// ── server ──────────────────────────────────────────────────────────────────
async function startServer(mode) {
  const dir = mkdtempSync(join(tmpdir(), 'collab-e2e-'))
  const port = await freePort()
  const proc = spawn('uv', ['run', 'python', 'tests/e2e/serve_collab.py', '--mode', mode, '--port', String(port), '--db', join(dir, 'c.db')],
    { cwd: cmsDir, stdio: ['ignore', 'pipe', 'pipe'] })
  let stderr = ''
  proc.stderr.on('data', (d) => { stderr += d })
  proc.stdout.on('data', (d) => { stderr += d })
  const base = `http://127.0.0.1:${port}`
  await until(async () => { try { return (await fetch(`${base}/api/documents`)).ok } catch { return false } }, 30000, `server (${mode})`)
    .catch((e) => { throw new Error(`${e.message}\n${stderr}`) })
  return { base, stderr: () => stderr, dump: () => proc.kill('SIGUSR1'), stop: () => { proc.kill(); rmSync(dir, { recursive: true, force: true }) } }
}
async function createDoc(base, slug, text) {
  const body = { title: slug, body: { type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] } }
  const res = await fetch(`${base}/api/documents`, { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ doc_type: 'article', slug, body }) })
  if (res.status !== 201) throw new Error(`create failed: ${res.status} ${await res.text()}`)
  return (await res.json()).id
}
async function serverDoc(base, id) {
  const res = await fetch(`${base}/api/documents/${id}?draft=true`)
  const body = (await res.json()).body
  return schema.nodeFromJSON((typeof body === 'string' ? JSON.parse(body) : body).body)
}

// ── a simulated editor tab ──────────────────────────────────────────────────
const closeTimes = []
let stuckCloses = 0
const toolbar = { setState() {}, clearSaveError() {}, setSaveError() {}, updatePeers() {}, setAiEditing() {} }

class Tab {
  constructor(name, base, docId) { Object.assign(this, { name, base, docId, inits: 0, rejects: 0, errors: [], resyncs: 0, log: [] }) }
  async start() {
    this.clientID = `${this.name}-${Math.random().toString(36).slice(2, 8)}`
    const tab = this
    this.view = {
      state: EditorState.create({ schema, doc: schema.node('doc', null, [schema.node('paragraph')]),
        plugins: [collab({ version: 0, clientID: this.clientID })] }),
      dispatch(tr) { this.state = this.state.apply(tr) },
      updateState(s) { this.state = s },
    }
    currentTab = this
    this.conn = new CollabConnection({ view: this.view, schema, documentId: this.docId, field: 'body',
      cmsBase: this.base, initialVersion: 0, toolbar, clientID: this.clientID })
    const handle = this.conn._handleMessage.bind(this.conn)
    this.conn._handleMessage = (msg) => {
      tab.log.push({ t: Date.now(), dir: '<', data: JSON.stringify(msg) })
      if (msg.type === 'init') tab.inits++
      if (msg.type === 'reject') tab.rejects++
      if (msg.type === 'error') tab.errors.push(msg)
      if (msg.type === 'resync_required') tab.resyncs++
      try { return handle(msg) } catch (e) { tab.errors.push({ threw: `${e.name}: ${e.message}`, on: msg.type }) }
    }
    this.conn._reconnectDelay = 40
    await until(() => this.inits > 0, 10000, `${this.name} init`)
  }
  get doc() { return this.view.state.doc }
  edit(build) {
    const tr = this.view.state.tr
    build(tr)
    if (!tr.docChanged) return false
    this.view.dispatch(tr)
    this.conn.onTransaction()
    return true
  }
  /** Drop the socket and wait until it is really closed, so a tab never has two. */
  async goOffline() {
    if (this.offline) return
    this.offline = true
    this.conn._destroyed = true
    const ws = this.conn.ws
    const t0 = Date.now()
    ws?.close()
    try {
      await until(() => !ws || ws.readyState === 3, 1500, 'close')
      closeTimes.push(Date.now() - t0)
    } catch {
      // The server never finished the close handshake (seen on `legacy` and
      // `verify` alike). A tab on a bad network has half-dead sockets too, so
      // abandon this one: ignore anything it still delivers, and carry on.
      stuckCloses++
      if (ws) ws.onmessage = ws.onclose = ws.onerror = null
    }
    await sleep(20)
  }
  comeOnline() {
    if (!this.offline) return
    this.offline = false
    this.conn._destroyed = false
    this.conn._reconnectDelay = 40
    this.conn._connect()
  }
  settled() { return !sendableSteps(this.view.state) }
  stop() { this.conn.destroy() }
}

/** Wait until every tab has nothing pending and all have the same version and document. */
async function converge(tabs, ms = 15000) {
  await until(() => tabs.every((t) => t.settled() && t.conn.ws?.readyState === 1) &&
    new Set(tabs.map((t) => getVersion(t.view.state))).size === 1 &&
    tabs.every((t) => t.doc.eq(tabs[0].doc)), ms, 'convergence')
}
const text = (doc) => doc.textBetween(0, doc.content.size, '\n', '\u0000')
function duplicates(doc, tags) {
  const t = text(doc)
  return [...tags].filter((tag) => t.split(tag).length - 1 > 1)
}

/** Replay the server's whole accepted-step log and report where a tag first appears twice. */
async function whereDuplicated(env, id, tag, startText) {
  const { Step } = await import('prosemirror-transform')
  const ws = new WebSocket(`${env.base.replace('http', 'ws')}/api/documents/${id}/collab?field=body`)
  const log = await new Promise((resolve, reject) => {
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.type === 'init') ws.send(JSON.stringify({ type: 'catch_up', version: 0 }))
      else if (m.type === 'steps' || m.type === 'resync_required') resolve(m)
    }
    setTimeout(() => reject(new Error('no catch-up reply')), 5000)
  })
  ws.close()
  if (log.type !== 'steps') return [`(server could not serve the full log: ${log.type})`]
  let doc = schema.node('doc', null, [schema.node('paragraph', null, schema.text(startText))])
  const out = []
  const inserts = log.steps.map((st, i) => [i, st]).filter(([, st]) => JSON.stringify(st).includes(tag))
  out.push(`accepted steps that insert ${tag}: ${inserts.map(([i]) => `#${i} (v${i + 1}, ${log.clientIDs[i]})`).join(', ') || 'none'}`)
  for (let i = 0; i < log.steps.length; i++) {
    const before = text(doc).split(tag).length - 1
    const res = Step.fromJSON(schema, log.steps[i]).apply(doc)
    if (!res.doc) { out.push(`step ${i} failed on replay: ${res.failed}`); break }
    doc = res.doc
    const after = text(doc).split(tag).length - 1
    if (before < 2 && after >= 2) {
      const st = log.steps[i]
      const around = (d) => { const t = text(d); const idx = []; let at = -1; while ((at = t.indexOf(tag, at + 1)) >= 0) idx.push(JSON.stringify(t.slice(Math.max(0, at - 25), at + tag.length + 25))); return idx.join('  ||  ') }
      out.push(`   text after step: ${around(doc)}`)
      out.push(`first duplicated by accepted step #${i} (version ${i + 1}) from ${log.clientIDs[i]}: ${st.stepType}@${st.from}-${st.to} ${st.slice ? JSON.stringify(st.slice).slice(0, 200) : ''}`)
      for (let k = Math.max(0, i - 3); k <= i; k++) { const q = log.steps[k]; out.push(`   #${k} ${log.clientIDs[k]} ${q.stepType}@${q.from}-${q.to} ${q.slice ? JSON.stringify(q.slice.content).slice(0, 120) : ''}`) }
      break
    }
  }
  return out
}

// ── scenarios ────────────────────────────────────────────────────────────────
async function t1(env) {
  const id = await createDoc(env.base, 't1', 'teh quick brown fox')
  const a = new Tab('a', env.base, id); const b = new Tab('b', env.base, id)
  await a.start(); await b.start()
  const tag = '⟦t1⟧'
  // One transaction, three steps: what autocorrect and paste produce.
  a.edit((tr) => { tr.delete(1, 4); tr.insertText('the', 1); tr.insertText(tag, 4); tr.addMark(1, 4, schema.marks.em.create()) })
  await converge([a, b])
  const server = await serverDoc(env.base, id)
  const expected = `the${tag} quick brown fox`
  const problems = []
  if (text(a.doc) !== expected) problems.push(`sender sees "${text(a.doc)}", expected "${expected}"`)
  if (text(b.doc) !== expected) problems.push(`peer sees "${text(b.doc)}"`)
  if (text(server) !== expected) problems.push(`server stored "${text(server)}"`)
  a.stop(); b.stop()
  return problems
}

async function t3(env) {
  const id = await createDoc(env.base, 't3', 'start')
  const a = new Tab('a', env.base, id); const b = new Tab('b', env.base, id)
  await a.start(); await b.start()
  await b.goOffline(); await sleep(100)
  const offline = ['⟦b1⟧', '⟦b2⟧']
  b.edit((tr) => tr.insertText(offline[0], 1)); b.edit((tr) => tr.insertText(offline[1], 1))
  const online = ['⟦a1⟧', '⟦a2⟧', '⟦a3⟧']
  for (const t of online) { a.edit((tr) => tr.insertText(t, a.doc.content.size - 1)); await sleep(30) }
  b.comeOnline()
  const problems = []
  try { await converge([a, b], 8000) } catch (e) { problems.push(e.message + ` (b has pending steps: ${!b.settled()}, a=${getVersion(a.view.state)} b=${getVersion(b.view.state)})`) }
  const server = await serverDoc(env.base, id)
  for (const t of [...offline, ...online]) if (!text(server).includes(t)) problems.push(`server lost ${t}`)
  const dup = duplicates(server, [...offline, ...online])
  if (dup.length) problems.push(`duplicated: ${dup.join(' ')}`)
  a.stop(); b.stop()
  return problems
}

async function t4(env) {
  const rand = rng(SEED)
  const pick = (arr) => arr[Math.floor(rand() * arr.length)]
  const id = await createDoc(env.base, 't4', 'alpha beta gamma delta')
  const tabs = ['a', 'b', 'c', 'd'].map((n) => new Tab(n, env.base, id))
  for (const t of tabs) await t.start()
  const tags = new Set()
  // Random fixed-width ids: deleting characters from one tag must never be able to spell another.
  const newTag = (name) => `⟦${name}-${Array.from({ length: 6 }, () => 'abcdefghjkmnpqrstuvwxyz23456789'[Math.floor(rand() * 31)]).join('')}⟧`
  const textPositions = (doc) => {
    const out = []
    doc.descendants((node, pos) => { if (node.isTextblock) out.push([pos + 1, pos + 1 + node.content.size]) })
    return out
  }
  const applyOp = (t) => {
    const [from0, end] = pick(textPositions(t.doc))
    const at = from0 + Math.floor(rand() * (end - from0 + 1))
    const kind = rand()
    if (kind < 0.45) { const tag = newTag(t.name); tags.add(tag); return t.edit((tr) => tr.insertText(tag, at)) }
    if (kind < 0.6) return t.edit((tr) => { const to = Math.min(end, at + 1 + Math.floor(rand() * 3)); if (to > at) tr.delete(at, to) })
    if (kind < 0.7) return t.edit((tr) => { const to = Math.min(end, at + 1 + Math.floor(rand() * 6)); if (to > at) tr.addMark(at, to, rand() < 0.5 ? schema.marks.strong.create() : schema.marks.em.create()) })
    if (kind < 0.8) return t.edit((tr) => tr.split(at))
    if (kind < 0.88) return t.edit((tr) => { const j = joinPoint(tr.doc, at); if (j != null) tr.join(j) })
    // an autocorrect-style batch
    const tag = newTag(t.name); tags.add(tag)
    return t.edit((tr) => { if (at > from0) tr.delete(at - 1, at); tr.insertText(tag, tr.mapping.map(at) ) })
  }
  const offline = new Set()
  for (let i = 0; i < FUZZ_OPS; i++) {
    const t = pick(tabs)
    const roll = rand()
    if (roll < 0.06 && !offline.has(t) && offline.size < 2) { await t.goOffline(); offline.add(t) }
    else if (roll < 0.14 && offline.has(t)) { t.comeOnline(); offline.delete(t) }
    else applyOp(t)
    if (rand() < 0.5) await sleep(Math.floor(rand() * 15))
  }
  for (const t of offline) t.comeOnline()
  const problems = []
  try { await converge(tabs, 20000) } catch (e) {
    problems.push(`${e.message}: ` + tabs.map((t) => `${t.name}{v=${getVersion(t.view.state)} pending=${!t.settled()}}`).join(' '))
  }
  const threw = tabs.flatMap((t) => t.errors.map((e) => `${t.name}: ${JSON.stringify(e)}`))
  if (threw.length) problems.push(`${threw.length} client error(s), first: ${threw[0]}`)
  const server = await serverDoc(env.base, id)
  if (!problems.length) {
    if (!server.eq(tabs[0].doc)) problems.push('server document differs from the clients\' converged document')
    const dup = duplicates(server, tags)
    if (dup.length) {
      problems.push(`${dup.length} insertion(s) appear twice, e.g. ${dup.slice(0, 3).join(' ')}`)
      if (process.env.E2E_DEBUG) {
        for (const line of await whereDuplicated(env, id, dup[0], 'alpha beta gamma delta')) problems.push(line)
        const t0 = Math.min(...tabs.flatMap((t) => t.log.map((l) => l.t)))
        const events = tabs.flatMap((t) => t.log.filter((l) => { try { return JSON.stringify(JSON.parse(l.data).steps ?? []).includes(dup[0]) } catch { return false } }).map((l) => ({ ...l, tab: t.name })))
          .sort((x, y) => x.t - y.t)
        for (const e of events) {
          const m = JSON.parse(e.data)
          const brief = (m.steps ?? []).map((st) => `${st.stepType}@${st.from}-${st.to}${st.slice ? ':' + JSON.stringify(st.slice.content).slice(0, 70) : ''}`)
          problems.push(`  ${String(e.t - t0).padStart(6)}ms ${e.tab} ${e.dir} ${m.type} v=${m.version} ${JSON.stringify(m.clientIDs?.length ? [...new Set(m.clientIDs)] : m.clientID)} ${brief.join(' | ')}`)
        }
      }
    }
  }
  const stats = tabs.map((t) => `${t.name}:inits=${t.inits},rejects=${t.rejects},resync=${t.resyncs}`).join(' ')
  tabs.forEach((t) => t.stop())
  const slow = `; clean closes: ${closeTimes.length}, close handshakes that never finished: ${stuckCloses}`
  problems.note = `${tags.size} tagged inserts; ${stats}${slow}`
  return problems
}

// ── run ──────────────────────────────────────────────────────────────────────
const scenarios = [['T1 autocorrect batch', t1], ['T3 offline then reconnect', t3], ['T4 four tabs, random edits, disconnects', t4]]
let unexpected = 0
for (const mode of modes.length ? modes : ['verify']) {
  const env = await startServer(mode)
  console.log(`\n== server mode: ${mode} ==`)
  for (const [name, fn] of scenarios) {
    let problems
    try { problems = await fn(env) } catch (e) { problems = [`threw: ${e.message}`] }
    const pass = problems.length === 0
    console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${problems.note ? `  [${problems.note}]` : ''}`)
    for (const p of problems) console.log(`      - ${p}`)
    if (!pass && process.env.E2E_DEBUG) {
      const alive = await fetch(`${env.base}/api/documents`, { signal: AbortSignal.timeout(3000) }).then((r) => `HTTP ${r.status}`, (e) => `no answer (${e.name})`)
      env.dump(); await sleep(800)
      console.log(`      server health probe: ${alive}\n      server tasks:\n${env.stderr().slice(-6000)}`)
    }
    if (mode === 'verify' && !pass) unexpected++
  }
  env.stop()
}
process.exit(unexpected ? 1 : 0)
