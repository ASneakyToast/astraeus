/**
 * Astraeus CMS Editor — editor.js
 * Vanilla ES6+ SPA. No bundler, no framework.
 *
 * Architecture:
 *   State   → plain JS object, mutated through setState()
 *   Render  → full re-render of each panel on every state change (simple & predictable)
 *   API     → thin fetch wrapper in api.js-style helpers at the top
 *   PM      → ProseMirror loaded from jsDelivr UMD bundles
 *
 * Flow:
 *   boot() → loadSchema() → renderTypeList()
 *           → (click type) → loadDocuments() → renderDocList()
 *           → (click doc | new) → loadDocument() or blank → renderForm()
 *           → (save) → POST/PATCH → reload doc → renderForm()
 */

/* =====================================================================
   1. CONFIG & GLOBALS
   ===================================================================== */

const CONFIG = window.__EDITOR_CONFIG__ || { cmsBase: '', apiKey: null, mountPath: '/editor' };

/** Shared application state — never mutate directly, use setState(). */
let state = {
  schema: null,           // { [doc_type]: { block_type, schema, field_meta } }
  activeType: null,       // string doc_type key
  documents: [],          // array of document objects for the active type
  docsTotal: 0,
  activeDocId: null,      // string id, or null for "new"
  activeDoc: null,        // full document object from API, or null
  formData: {},           // current form field values (in-memory)
  isDirty: false,
  isLoadingSchema: false,
  isLoadingDocs: false,
  isLoadingDoc: false,
  isSaving: false,
  pmInstances: {},        // { fieldName: ProseMirrorView } — keyed by field name
};

/** Pending ProseMirror boot promise — avoid double-loading UMD scripts. */
let pmLoadPromise = null;


/* =====================================================================
   2. API HELPERS
   ===================================================================== */

/**
 * Make an authenticated fetch call to the CMS API.
 * @param {string} path   — e.g. "/api/schema"
 * @param {RequestInit} opts — standard fetch options
 * @returns {Promise<Response>}
 */
async function apiFetch(path, opts = {}) {
  const url = CONFIG.cmsBase + path;
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (CONFIG.apiKey) {
    headers['Authorization'] = `Bearer ${CONFIG.apiKey}`;
  }
  return fetch(url, { ...opts, headers });
}

async function fetchSchema() {
  const res = await apiFetch('/api/schema');
  if (!res.ok) throw new Error(`Schema fetch failed: ${res.status}`);
  return res.json();
}

async function fetchDocuments(docType, { limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams({ type: docType, limit, offset });
  const res = await apiFetch(`/api/documents?${params}`);
  if (!res.ok) throw new Error(`Documents fetch failed: ${res.status}`);
  return res.json();
}

async function fetchDocument(id) {
  const res = await apiFetch(`/api/documents/${id}`);
  if (!res.ok) throw new Error(`Document fetch failed: ${res.status}`);
  return res.json();
}

async function createDocument(docType, body, slug = '') {
  const res = await apiFetch('/api/documents', {
    method: 'POST',
    body: JSON.stringify({ doc_type: docType, body, slug }),
  });
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

async function patchDocument(id, patch) {
  const res = await apiFetch(`/api/documents/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

async function publishDocument(id) {
  const res = await apiFetch(`/api/documents/${id}/publish`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

async function unpublishDocument(id) {
  const res = await apiFetch(`/api/documents/${id}/unpublish`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

async function deleteDocument(id) {
  const res = await apiFetch(`/api/documents/${id}`, { method: 'DELETE' });
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

class ApiError extends Error {
  constructor(status, data) {
    const msg = data?.error || data?.detail?.[0]?.msg || `HTTP ${status}`;
    super(msg);
    this.status = status;
    this.data = data;
  }
}


/* =====================================================================
   3. STATE MANAGEMENT
   ===================================================================== */

function setState(patch, rerender = true) {
  Object.assign(state, patch);
  if (rerender) render();
}


/* =====================================================================
   4. PROSEMIRROR LOADER
   ===================================================================== */

/**
 * Dynamically load ProseMirror via esm.sh (ESM dynamic import).
 * esm.sh re-bundles npm packages as browser-native ES modules — no UMD needed.
 * Resolved modules are stored on window.PM for use by the rest of the file.
 *
 * TODO (next step): Wire up a proper Markdown ↔ ProseMirror serialiser.
 *   The recommended approach is prosemirror-markdown (markdownit-based).
 *   For now we treat the Markdown string as plain text in ProseMirror's
 *   paragraph node model — roundtrip preserves the raw markdown source
 *   but does not render it as formatted nodes. The architecture is
 *   intentionally left open here so that replacing the
 *   markdownToPmDoc / pmDocToMarkdown functions below is the only change
 *   needed once the serialiser is integrated.
 */
function loadProseMirror() {
  if (pmLoadPromise) return pmLoadPromise;

  const ESM = 'https://esm.sh';

  // Also inject ProseMirror's default CSS once
  function loadPmCss() {
    const href = `${ESM}/prosemirror-view/style/prosemirror.css`;
    if (!document.querySelector(`link[href="${href}"]`)) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = href;
      document.head.appendChild(link);
    }
  }

  pmLoadPromise = Promise.all([
    import(`${ESM}/prosemirror-model`),
    import(`${ESM}/prosemirror-state`),
    import(`${ESM}/prosemirror-view`),
    import(`${ESM}/prosemirror-schema-basic`),
    import(`${ESM}/prosemirror-schema-list`),
    import(`${ESM}/prosemirror-commands`),
    import(`${ESM}/prosemirror-history`),
    import(`${ESM}/prosemirror-keymap`),
    import(`${ESM}/prosemirror-inputrules`),
    import(`${ESM}/prosemirror-example-setup`),
  ]).then(([model, state, view, schemaBasic, schemaList, commands, history, keymap, inputrules, exampleSetup]) => {
    // Stash on window.PM so the rest of the file can access them
    window.PM = { model, state, view, schemaBasic, schemaList, commands, history, keymap, inputrules, exampleSetup };
    loadPmCss();
    return true;
  });

  return pmLoadPromise;
}

/**
 * Convert a plain Markdown string into a ProseMirror document node.
 *
 * CURRENT IMPLEMENTATION: stores the raw markdown in paragraph nodes
 * (one paragraph per blank-line-separated block). This preserves the
 * source text faithfully and lets users edit it in the ProseMirror
 * view without any formatting transformation.
 *
 * TODO: Replace with prosemirror-markdown for proper block/inline
 * rendering (headings, bold, italics, code fences, etc.).
 */
function markdownToPmDoc(markdown, schema) {
  const text = (markdown || '').trim();
  if (!text) {
    return schema.nodes.doc.create({}, [schema.nodes.paragraph.create()]);
  }
  // Split on double newlines into paragraphs
  const blocks = text.split(/\n{2,}/).filter(Boolean);
  const paragraphs = blocks.map(block => {
    const line = block.replace(/\n/g, ' ');
    return schema.nodes.paragraph.create({}, line ? [schema.text(line)] : []);
  });
  return schema.nodes.doc.create({}, paragraphs);
}

/**
 * Serialize a ProseMirror document back to a Markdown string.
 *
 * CURRENT IMPLEMENTATION: concatenates paragraph text with double
 * newlines. Inline marks (bold, italic) are preserved as raw
 * ProseMirror marks but not serialised to Markdown syntax here.
 *
 * TODO: Replace with prosemirror-markdown serialiser to produce
 * proper **bold**, _italic_, # heading, - list, ``` code fence, etc.
 */
function pmDocToMarkdown(doc) {
  const lines = [];
  doc.forEach(node => {
    if (node.type.name === 'paragraph') {
      lines.push(node.textContent);
    } else if (node.type.name === 'heading') {
      const level = node.attrs.level || 1;
      lines.push('#'.repeat(level) + ' ' + node.textContent);
    } else if (node.type.name === 'bullet_list' || node.type.name === 'ordered_list') {
      let i = 1;
      node.forEach(item => {
        const bullet = node.type.name === 'ordered_list' ? `${i}. ` : '- ';
        lines.push(bullet + item.textContent);
        i++;
      });
    } else if (node.type.name === 'blockquote') {
      lines.push('> ' + node.textContent);
    } else if (node.type.name === 'code_block') {
      lines.push('```\n' + node.textContent + '\n```');
    } else {
      lines.push(node.textContent);
    }
  });
  return lines.join('\n\n');
}


/* =====================================================================
   5. UTILITY FUNCTIONS
   ===================================================================== */

/**
 * Humanize a snake_case doc_type name.
 * "blog_post" → "Blog Posts"
 */
function humanizeType(str) {
  return str
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/s$/, '') + 's';
}

/** Get a display title for a document — prefers title > name > slug > id. */
function docTitle(doc) {
  const body = doc?.body || {};
  return body.title || body.name || body.headline || doc?.slug || doc?.id?.slice(0, 8) || 'Untitled';
}

/** Format an ISO date string for display. */
function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return '';
  }
}

/** Get ordered field entries from schema + field_meta. */
function getOrderedFields(typeInfo) {
  const props = typeInfo?.schema?.properties || {};
  const fieldMeta = typeInfo?.field_meta || {};

  // slug is managed by the top-level CMS slug field (buildSlugField);
  // block_type is an injected discriminator — neither should appear in the body form.
  const EXCLUDED = new Set(['slug', 'block_type']);

  const entries = Object.entries(props)
    .filter(([name]) => !EXCLUDED.has(name))
    .map(([name, prop]) => ({
      name,
      prop,
      meta: fieldMeta[name] || {},
    }));

  // Sort by display_order if present, then by natural order
  entries.sort((a, b) => {
    const oa = a.meta.display_order ?? 9999;
    const ob = b.meta.display_order ?? 9999;
    return oa - ob;
  });

  return entries;
}

/**
 * Determine what kind of UI widget to use for a field.
 * Returns one of: 'prosemirror' | 'textarea' | 'input' | 'number'
 *                 | 'boolean' | 'select' | 'json'
 *
 * Explicit ``field_type`` from cms:field_meta takes precedence over all
 * heuristics.  Heuristic fallbacks are kept for schemas that pre-date the
 * field_type tag or for fields with no explicit type annotation.
 */
function fieldWidget(name, prop, meta) {
  // --- Authoritative field_type from cms:field_meta (set by Python field classes) ---
  const ft = meta?.field_type;
  if (ft === 'rich_text')    return 'prosemirror';
  if (ft === 'block_list')   return 'block_canvas';
  if (ft === 'block')        return 'block_canvas';  // single nested block — same canvas, 1 card
  if (ft === 'image')        return 'image_picker';
  if (ft === 'select')       return 'select';
  if (ft === 'number')       return 'number';
  if (ft === 'boolean')      return 'boolean';
  if (ft === 'json')         return 'json';
  // url, document_ref, text → fall through to heuristics below

  // --- Legacy heuristics (backwards compat for fields without field_type) ---
  // Explicit ProseMirror fields by name convention
  if (name === 'body_markdown' || name.includes('markdown')) return 'prosemirror';

  const type = prop.type;
  const anyOf = prop.anyOf;

  // SelectField has choices in meta
  if (meta?.choices?.length) return 'select';

  if (type === 'boolean') return 'boolean';
  if (type === 'number' || type === 'integer') return 'number';

  // JSON-like: object/array, or anyOf with null
  if (type === 'object' || type === 'array') return 'json';
  if (Array.isArray(anyOf)) {
    const types = anyOf.map(s => s.type).filter(Boolean);
    if (types.includes('object') || types.includes('array')) return 'json';
    if (types.includes('null') && !types.includes('string') && !types.includes('number')) return 'json';
  }

  // Long text heuristics
  const maxLen = prop.maxLength || meta?.max_length;
  const longNames = ['body', 'description', 'overview', 'summary', 'content', 'excerpt', 'bio', 'text'];
  const isLong = (maxLen && maxLen > 300) || longNames.some(n => name.includes(n));
  if (type === 'string' && isLong) return 'textarea';

  return 'input';
}


/* =====================================================================
   6. DOM HELPERS
   ===================================================================== */

const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...children) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null) continue;
    e.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return e;
};


/* =====================================================================
   7. TOAST SYSTEM
   ===================================================================== */

function getToastArea() {
  let area = document.querySelector('.toast-area');
  if (!area) {
    area = el('div', { class: 'toast-area' });
    document.body.appendChild(area);
  }
  return area;
}

const TOAST_ICONS = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };

function showToast(type, title, message, duration = 3500) {
  const area = getToastArea();
  const toast = el('div', { class: `toast toast--${type}` },
    el('span', { class: 'toast__icon' }, TOAST_ICONS[type] || '•'),
    el('div', { class: 'toast__body' },
      el('div', { class: 'toast__title' }, title),
      message ? el('div', { class: 'toast__msg' }, message) : null
    )
  );
  area.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('is-leaving');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  }, duration);
}


/* =====================================================================
   8. CONFIRM DIALOG
   ===================================================================== */

function showConfirm(title, body) {
  return new Promise(resolve => {
    const backdrop = el('div', { class: 'overlay-backdrop' },
      el('div', { class: 'overlay-dialog' },
        el('div', { class: 'overlay-dialog__title' }, title),
        el('div', { class: 'overlay-dialog__body' }, body),
        el('div', { class: 'overlay-dialog__actions' },
          el('button', {
            class: 'btn btn--ghost',
            onclick: () => { backdrop.remove(); resolve(false); }
          }, 'Cancel'),
          el('button', {
            class: 'btn btn--danger',
            onclick: () => { backdrop.remove(); resolve(true); }
          }, 'Delete')
        )
      )
    );
    document.body.appendChild(backdrop);
  });
}


/* =====================================================================
   9. RENDER FUNCTIONS
   ===================================================================== */

/* ---- 9a. Type Sidebar ---- */

function renderTypeList() {
  const container = $('type-list');
  if (!container) return;
  container.innerHTML = '';

  if (state.isLoadingSchema) {
    container.appendChild(el('div', { class: 'sidebar-types__item' },
      el('div', { class: 'loading-spinner' })
    ));
    return;
  }

  if (!state.schema) {
    container.appendChild(el('div', { class: 'sidebar-types__item' }, 'No types found'));
    return;
  }

  for (const [typeKey] of Object.entries(state.schema)) {
    const item = el('div', {
      class: `sidebar-types__item${state.activeType === typeKey ? ' is-active' : ''}`,
      onclick: () => selectType(typeKey),
    },
      el('span', { class: 'sidebar-types__item-icon' }, typeIcon(typeKey)),
      el('span', {}, humanizeType(typeKey))
    );
    container.appendChild(item);
  }
}

function typeIcon(typeKey) {
  // Simple emoji-based icons based on common type names
  if (typeKey.includes('blog') || typeKey.includes('post')) return '📝';
  if (typeKey.includes('page')) return '📄';
  if (typeKey.includes('project')) return '🗂';
  if (typeKey.includes('experience') || typeKey.includes('job')) return '💼';
  if (typeKey.includes('product') || typeKey.includes('item')) return '📦';
  if (typeKey.includes('user') || typeKey.includes('author')) return '👤';
  if (typeKey.includes('category') || typeKey.includes('tag')) return '🏷';
  if (typeKey.includes('media') || typeKey.includes('image')) return '🖼';
  return '◻';
}

/* ---- 9b. Document List ---- */

function renderDocList() {
  const titleEl = $('doc-list-title');
  const newBtn = $('doc-new-btn');
  const listEl = $('doc-list');

  if (titleEl) titleEl.textContent = state.activeType ? humanizeType(state.activeType) : '—';
  if (newBtn) newBtn.style.display = state.activeType ? '' : 'none';
  if (!listEl) return;

  listEl.innerHTML = '';

  if (!state.activeType) {
    listEl.appendChild(el('div', { class: 'sidebar-docs__empty' }, 'Select a type'));
    return;
  }

  if (state.isLoadingDocs) {
    listEl.appendChild(el('div', { class: 'sidebar-docs__empty' },
      el('div', { class: 'loading-spinner', style: 'margin: 0 auto;' })
    ));
    return;
  }

  if (!state.documents.length) {
    listEl.appendChild(el('div', { class: 'sidebar-docs__empty' }, 'No documents yet'));
    return;
  }

  for (const doc of state.documents) {
    const isActive = doc.id === state.activeDocId;
    const item = el('div', {
      class: `sidebar-docs__item${isActive ? ' is-active' : ''}`,
      onclick: () => selectDoc(doc.id),
    },
      el('span', { class: 'sidebar-docs__item-title' }, docTitle(doc)),
      el('div', { class: 'sidebar-docs__item-meta' },
        el('span', { class: `badge ${doc.published ? 'badge--published' : 'badge--draft'}` },
          doc.published ? 'Published' : 'Draft'
        ),
        el('span', { class: 'sidebar-docs__item-date' }, formatDate(doc.updated_at || doc.created_at))
      )
    );
    listEl.appendChild(item);
  }
}

/* ---- 9c. Header ---- */

function renderHeader() {
  const titleEl = $('header-title');
  const dirtyDot = $('dirty-dot');
  const publishWrap = $('publish-wrap');
  const saveBtn = $('save-btn');
  const deleteBtn = $('delete-btn');

  if (!titleEl) return;

  if (!state.activeType) {
    titleEl.textContent = 'CMS Editor';
    if (dirtyDot) dirtyDot.classList.remove('is-visible');
    if (publishWrap) publishWrap.style.display = 'none';
    if (saveBtn) saveBtn.style.display = 'none';
    if (deleteBtn) deleteBtn.style.display = 'none';
    return;
  }

  const isNew = state.activeDocId === null && state.activeType !== null;
  const doc = state.activeDoc;

  titleEl.textContent = isNew ? `New ${humanizeType(state.activeType).replace(/s$/, '')}` : docTitle(doc || {});
  if (dirtyDot) dirtyDot.classList.toggle('is-visible', state.isDirty);
  if (publishWrap) publishWrap.style.display = doc ? '' : 'none';
  if (saveBtn) saveBtn.style.display = '';
  if (deleteBtn) deleteBtn.style.display = doc ? '' : 'none';

  // Update publish toggle
  const toggleInput = $('publish-toggle-input');
  const toggleLabel = $('publish-toggle-label');
  if (toggleInput && doc) {
    toggleInput.checked = !!doc.published;
  }
  if (toggleLabel && doc) {
    toggleLabel.textContent = doc.published ? 'Published' : 'Draft';
  }

  // Save button state
  if (saveBtn) {
    saveBtn.disabled = state.isSaving;
    saveBtn.textContent = state.isSaving ? 'Saving…' : 'Save';
  }
}

/* ---- 9d. Form ---- */

function renderForm() {
  const formArea = $('form-area');
  if (!formArea) return;
  formArea.innerHTML = '';

  if (!state.activeType) {
    formArea.appendChild(
      el('div', { class: 'empty-state' },
        el('div', { class: 'empty-state__icon' }, '◻'),
        el('div', { class: 'empty-state__title' }, 'Select a content type'),
        el('div', { class: 'empty-state__body' }, 'Choose a type from the left sidebar to browse and edit documents.')
      )
    );
    return;
  }

  if (state.isLoadingDoc) {
    formArea.appendChild(
      el('div', { class: 'empty-state' },
        el('div', { class: 'loading-spinner', style: 'margin: 0 auto;' })
      )
    );
    return;
  }

  if (state.activeDocId === null && Object.keys(state.formData).length === 0) {
    // No doc selected — show prompt if we have docs, "new" hint if none
    if (state.documents.length > 0) {
      formArea.appendChild(
        el('div', { class: 'empty-state' },
          el('div', { class: 'empty-state__icon' }, '←'),
          el('div', { class: 'empty-state__title' }, 'Select a document'),
          el('div', { class: 'empty-state__body' }, 'Or click + to create a new one.')
        )
      );
      return;
    }
  }

  const typeInfo = state.schema?.[state.activeType];
  if (!typeInfo) {
    formArea.appendChild(el('div', { class: 'empty-state' }, 'Schema not found for this type.'));
    return;
  }

  const form = el('div', { class: 'doc-form', id: 'doc-form' });

  // Slug field (always present)
  const slugGroup = buildSlugField();
  form.appendChild(slugGroup);

  // Schema-driven fields
  const fields = getOrderedFields(typeInfo);
  for (const { name, prop, meta } of fields) {
    const group = buildFieldGroup(name, prop, meta);
    if (group) form.appendChild(group);
  }

  // Meta panel — only for existing documents
  if (state.activeDoc) {
    form.appendChild(buildMetaPanel(state.activeDoc));
  }

  formArea.appendChild(form);

  // Mount ProseMirror editors after the DOM is in place
  mountProseMirrorEditors(fields);
}

function buildSlugField() {
  const group = el('div', { class: 'field-group' });
  group.appendChild(el('label', { class: 'field-label', for: 'field-slug' }, 'Slug'));
  const input = el('input', {
    class: 'field-input',
    id: 'field-slug',
    type: 'text',
    placeholder: 'my-document-slug',
    value: state.activeDoc?.slug || state.formData.__slug || '',
    oninput: e => onFieldChange('__slug', e.target.value),
  });
  group.appendChild(input);
  group.appendChild(el('span', { class: 'field-help' }, 'URL-safe identifier for this document'));
  return group;
}

function buildFieldGroup(name, prop, meta) {
  const widget = fieldWidget(name, prop, meta);
  const label = meta.label || humanizeFieldName(name);
  const isRequired = (prop.required || []).includes(name) ||
    (state.schema?.[state.activeType]?.schema?.required || []).includes(name);

  const group = el('div', { class: 'field-group' });
  const labelEl = el('label', {
    class: `field-label${isRequired ? ' field-label--required' : ''}`,
    for: `field-${name}`,
  }, label);
  group.appendChild(labelEl);

  if (meta.help_text) {
    group.appendChild(el('span', { class: 'field-help' }, meta.help_text));
  }

  const currentVal = state.formData[name] ?? getDefaultValue(prop, meta);

  switch (widget) {
    case 'block_canvas':
      group.appendChild(buildBlockCanvas(name, prop, meta, state.schema?.[state.activeType]?.schema, currentVal));
      break;

    case 'image_picker':
      group.appendChild(buildImagePickerField(name, currentVal));
      break;

    case 'prosemirror':
      group.appendChild(buildProseMirrorPlaceholder(name, currentVal));
      break;

    case 'textarea': {
      const ta = el('textarea', {
        class: 'field-textarea',
        id: `field-${name}`,
        placeholder: meta.placeholder || '',
        oninput: e => onFieldChange(name, e.target.value),
      });
      ta.value = currentVal || '';
      group.appendChild(ta);
      break;
    }

    case 'json': {
      const ta = el('textarea', {
        class: 'field-textarea field-textarea--json',
        id: `field-${name}`,
        placeholder: '{}',
        onblur: e => {
          try {
            const pretty = JSON.stringify(JSON.parse(e.target.value), null, 2);
            e.target.value = pretty;
            onFieldChange(name, JSON.parse(pretty));
          } catch {
            // Leave as-is if invalid JSON — validation will surface it on save
          }
        },
        oninput: e => {
          try { onFieldChange(name, JSON.parse(e.target.value)); } catch { /* ignore */ }
        },
      });
      const rawVal = typeof currentVal === 'string' ? currentVal
        : currentVal != null ? JSON.stringify(currentVal, null, 2) : '';
      ta.value = rawVal;
      group.appendChild(ta);
      break;
    }

    case 'select': {
      const sel = el('select', {
        class: 'field-select',
        id: `field-${name}`,
        onchange: e => onFieldChange(name, e.target.value),
      });
      if (!isRequired) sel.appendChild(el('option', { value: '' }, '— Select —'));
      for (const choice of (meta.choices || [])) {
        const opt = el('option', { value: choice }, choice);
        if (currentVal === choice) opt.setAttribute('selected', 'true');
        sel.appendChild(opt);
      }
      group.appendChild(sel);
      break;
    }

    case 'boolean': {
      const wrap = el('div', { class: 'field-bool' });
      const toggleLabel = el('label', { class: 'toggle-switch', for: `field-${name}` });
      const input = el('input', {
        type: 'checkbox',
        id: `field-${name}`,
        onchange: e => onFieldChange(name, e.target.checked),
      });
      if (currentVal) input.setAttribute('checked', 'true');
      const track = el('span', { class: 'toggle-track' });
      const thumb = el('span', { class: 'toggle-thumb' });
      toggleLabel.appendChild(input);
      toggleLabel.appendChild(track);
      toggleLabel.appendChild(thumb);
      wrap.appendChild(toggleLabel);
      wrap.appendChild(el('span', { class: 'field-bool__label' }, label));
      // Replace the label we added above since bool shows it inline
      labelEl.textContent = '';
      labelEl.style.display = 'none';
      group.appendChild(wrap);
      break;
    }

    case 'number': {
      const input = el('input', {
        class: 'field-input',
        id: `field-${name}`,
        type: 'number',
        placeholder: meta.placeholder || '0',
        value: currentVal != null ? String(currentVal) : '',
        oninput: e => onFieldChange(name, e.target.value === '' ? null : Number(e.target.value)),
      });
      if (meta.min_value != null) input.setAttribute('min', meta.min_value);
      if (meta.max_value != null) input.setAttribute('max', meta.max_value);
      group.appendChild(input);
      break;
    }

    default: { // 'input'
      const input = el('input', {
        class: 'field-input',
        id: `field-${name}`,
        type: 'text',
        placeholder: meta.placeholder || '',
        value: currentVal || '',
        oninput: e => onFieldChange(name, e.target.value),
      });
      if (prop.maxLength) input.setAttribute('maxlength', prop.maxLength);
      group.appendChild(input);
      break;
    }
  }

  return group;
}

/** Build a placeholder div for ProseMirror — actual mount happens after DOM insertion. */
function buildProseMirrorPlaceholder(name, currentValue) {
  const wrap = el('div', { class: 'pm-editor-wrap' });
  const toolbar = el('div', { class: 'pm-toolbar', id: `pm-toolbar-${name}` },
    el('button', { class: 'pm-toolbar__btn', title: 'Bold', 'data-cmd': 'toggleBold' }, 'B'),
    el('button', { class: 'pm-toolbar__btn', title: 'Italic', 'data-cmd': 'toggleItalic' }, 'I'),
    el('button', { class: 'pm-toolbar__btn pm-toolbar__btn--mono', title: 'Inline code', 'data-cmd': 'toggleCode' }, '`'),
    el('span', { class: 'pm-toolbar__sep' }),
    el('button', { class: 'pm-toolbar__btn', title: 'Heading 1', 'data-cmd': 'h1' }, 'H1'),
    el('button', { class: 'pm-toolbar__btn', title: 'Heading 2', 'data-cmd': 'h2' }, 'H2'),
    el('span', { class: 'pm-toolbar__sep' }),
    el('button', { class: 'pm-toolbar__btn', title: 'Bullet list', 'data-cmd': 'bulletList' }, '•≡'),
    el('button', { class: 'pm-toolbar__btn', title: 'Ordered list', 'data-cmd': 'orderedList' }, '1≡'),
    el('span', { class: 'pm-toolbar__sep' }),
    el('button', { class: 'pm-toolbar__btn', title: 'Blockquote', 'data-cmd': 'blockquote' }, '❝'),
  );
  const editorDiv = el('div', { class: 'pm-editor', id: `pm-mount-${name}`, 'data-field': name });
  wrap.appendChild(toolbar);
  wrap.appendChild(editorDiv);
  return wrap;
}

/** Mount ProseMirror on all .pm-editor elements in the form. */
async function mountProseMirrorEditors(fields) {
  const pmFields = fields.filter(({ name, prop, meta }) => fieldWidget(name, prop, meta) === 'prosemirror');
  if (!pmFields.length) return;

  try {
    await loadProseMirror();
  } catch (err) {
    console.warn('[editor] ProseMirror failed to load:', err);
    for (const { name } of pmFields) {
      const mount = document.getElementById(`pm-mount-${name}`);
      if (mount) {
        mount.innerHTML = '<p style="color:var(--red);padding:8px">Rich text editor failed to load. Check your internet connection.</p>';
      }
    }
    return;
  }

  const { EditorState, Plugin, PluginKey } = window.PM.state;
  const { EditorView } = window.PM.view;
  const { schema: basicSchema } = window.PM.schemaBasic;
  const { Schema } = window.PM.model;
  const { exampleSetup } = window.PM.exampleSetup;
  const { toggleMark, setBlockType, wrapIn } = window.PM.commands;
  const { addListNodes } = window.PM.schemaList;

  // Build a schema that includes list nodes
  const schemaWithLists = new Schema({
    nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
    marks: basicSchema.spec.marks,
  });

  // Destroy any existing PM instances for this render cycle
  for (const [, view] of Object.entries(state.pmInstances)) {
    try { view.destroy(); } catch { /* already destroyed */ }
  }
  state.pmInstances = {};

  for (const { name } of pmFields) {
    const mountEl = document.getElementById(`pm-mount-${name}`);
    if (!mountEl) continue;

    const rawValue = state.formData[name];
    // If the stored value is already a ProseMirror JSON doc object (RichTextField),
    // restore it directly; otherwise fall back to the plain-text markdown path.
    let doc;
    if (rawValue && typeof rawValue === 'object' && rawValue.type === 'doc') {
      try {
        doc = PM.model.Node.fromJSON(schemaWithLists, rawValue);
      } catch (e) {
        console.warn('[editor] Failed to restore PM doc from JSON, falling back to markdown:', e);
        doc = markdownToPmDoc('', schemaWithLists);
      }
    } else {
      doc = markdownToPmDoc(rawValue || '', schemaWithLists);
    }

    const pmState = EditorState.create({
      doc,
      plugins: exampleSetup({ schema: schemaWithLists, menuBar: false }),
    });

    const view = new EditorView(mountEl, {
      state: pmState,
      dispatchTransaction(transaction) {
        const newState = view.state.apply(transaction);
        view.updateState(newState);
        // Refresh toolbar active state on every transaction (selection moves too)
        const toolbar = document.getElementById(`pm-toolbar-${name}`);
        updateToolbarState(view, toolbar);
        if (transaction.docChanged) {
          // Store as PM JSON when this field is a RichTextField (field_type === 'rich_text'),
          // otherwise serialise to markdown for backwards compatibility.
          const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};
          const value = fieldMeta.field_type === 'rich_text'
            ? newState.doc.toJSON()
            : pmDocToMarkdown(newState.doc);
          onFieldChange(name, value);
        }
      },
    });

    state.pmInstances[name] = view;

    // Wire up toolbar buttons
    const toolbar = document.getElementById(`pm-toolbar-${name}`);
    if (toolbar) {
      toolbar.addEventListener('mousedown', e => {
        e.preventDefault(); // prevent blur on editor
        const btn = e.target.closest('[data-cmd]');
        if (!btn) return;
        const cmd = btn.getAttribute('data-cmd');
        execPmCommand(view, schemaWithLists, cmd, { toggleMark, setBlockType, wrapIn });
      });
    }
  }
}

/** Execute a named ProseMirror command from the toolbar. */
function execPmCommand(view, schema, cmd, { toggleMark, setBlockType, wrapIn }) {
  const { state, dispatch } = view;
  const { toggleList } = window.PM.schemaList;
  const cmds = {
    toggleBold:    toggleMark(schema.marks.strong),
    toggleItalic:  toggleMark(schema.marks.em),
    toggleCode:    schema.marks.code ? toggleMark(schema.marks.code) : () => false,
    h1:            setBlockType(schema.nodes.heading, { level: 1 }),
    h2:            setBlockType(schema.nodes.heading, { level: 2 }),
    paragraph:     setBlockType(schema.nodes.paragraph),
    // Use toggleList so clicking an active list unwraps it
    bulletList:    toggleList(schema.nodes.bullet_list, schema.nodes.list_item),
    orderedList:   toggleList(schema.nodes.ordered_list, schema.nodes.list_item),
    blockquote:    wrapIn(schema.nodes.blockquote),
  };
  const fn = cmds[cmd];
  if (fn) fn(state, dispatch);
  view.focus();
}

/** Return true if the given mark type is active in the current selection. */
function hasMark(pmState, markTypeName) {
  const schema = pmState.schema;
  const markType = schema.marks[markTypeName];
  if (!markType) return false;
  const { from, $from, to, empty } = pmState.selection;
  if (empty) return !!markType.isInSet(pmState.storedMarks || $from.marks());
  return pmState.doc.rangeHasMark(from, to, markType);
}

/** Return true if the cursor is inside a list node of the given type. */
function isInList(pmState, listTypeName) {
  const schema = pmState.schema;
  const listType = schema.nodes[listTypeName];
  if (!listType) return false;
  const { $from } = pmState.selection;
  for (let d = $from.depth; d >= 0; d--) {
    if ($from.node(d).type === listType) return true;
  }
  return false;
}

/** Refresh toolbar button active states based on current ProseMirror selection. */
function updateToolbarState(view, toolbar) {
  if (!toolbar) return;
  const { state: pmState } = view;
  const { $from } = pmState.selection;
  const parentType = $from.parent.type.name;
  const parentLevel = $from.parent.attrs?.level;

  toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
    const cmd = btn.getAttribute('data-cmd');
    let active = false;
    switch (cmd) {
      case 'toggleBold':   active = hasMark(pmState, 'strong'); break;
      case 'toggleItalic': active = hasMark(pmState, 'em'); break;
      case 'toggleCode':   active = hasMark(pmState, 'code'); break;
      case 'h1':           active = parentType === 'heading' && parentLevel === 1; break;
      case 'h2':           active = parentType === 'heading' && parentLevel === 2; break;
      case 'blockquote':   active = parentType === 'blockquote'; break;
      case 'bulletList':   active = isInList(pmState, 'bullet_list'); break;
      case 'orderedList':  active = isInList(pmState, 'ordered_list'); break;
    }
    btn.classList.toggle('is-active', active);
  });
}

function humanizeFieldName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}


/* =====================================================================
   BLOCK CANVAS — renders ListField / BlockField arrays as interactive cards
   ===================================================================== */

/**
 * Extract block type metadata for a list/block field from the JSON Schema.
 * Returns [{name, registeredType, schema}].
 *
 * Handles both homogeneous ($ref) and polymorphic (anyOf) lists.
 */
function getBlockTypesMeta(prop, typeSchema) {
  const defs = typeSchema?.$defs || {};
  const result = [];

  function resolveRef(ref) {
    // ref is something like "#/$defs/HeroBlock"
    const name = ref?.replace(/^#\/\$defs\//, '');
    return name ? defs[name] : null;
  }

  function extractEntry(className, schemaDef) {
    if (!schemaDef) return null;
    const constProp = schemaDef?.properties?.block_type?.const;
    return {
      name: className,
      registeredType: constProp || className,
      schema: schemaDef,
    };
  }

  const items = prop?.items;
  if (!items) return result;

  if (items.$ref) {
    // Homogeneous
    const className = items.$ref.replace(/^#\/\$defs\//, '');
    const entry = extractEntry(className, resolveRef(items.$ref));
    if (entry) result.push(entry);
  } else if (Array.isArray(items.anyOf)) {
    // Polymorphic
    for (const variant of items.anyOf) {
      if (variant.$ref) {
        const className = variant.$ref.replace(/^#\/\$defs\//, '');
        const entry = extractEntry(className, resolveRef(variant.$ref));
        if (entry) result.push(entry);
      }
    }
  } else if (items.properties) {
    // Inline schema — treat as single anonymous block type
    result.push({ name: 'Block', registeredType: 'block', schema: items });
  }

  return result;
}

/**
 * Build the block type picker dropdown for a field.
 * Returns a <div class="block-type-picker"> element that is initially hidden.
 * Keyboard navigation: ArrowUp/ArrowDown move focus; Enter selects; Escape closes.
 */
function buildBlockTypePicker(fieldName, availableTypes) {
  const picker = el('div', {
    class: 'block-type-picker',
    role: 'listbox',
    'aria-label': 'Select block type',
  });
  picker.style.display = 'none';

  for (const typeInfo of availableTypes) {
    const item = el('div', {
      class: 'block-type-picker__item',
      role: 'option',
      tabindex: '-1',
      onclick: () => {
        addBlock(fieldName, typeInfo);
        picker.style.display = 'none';
      },
      onkeydown: e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          addBlock(fieldName, typeInfo);
          picker.style.display = 'none';
        } else if (e.key === 'ArrowDown') {
          e.preventDefault();
          const next = item.nextElementSibling;
          if (next) next.focus();
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          const prev = item.previousElementSibling;
          if (prev) prev.focus();
          else picker.previousElementSibling?.focus(); // back to "Add block" button
        } else if (e.key === 'Escape') {
          picker.style.display = 'none';
          picker.previousElementSibling?.focus();
        }
      },
    }, humanizeFieldName(typeInfo.registeredType));
    picker.appendChild(item);
  }

  return picker;
}

/** Create a new empty block and append it to the field array. */
function addBlock(fieldName, typeInfo) {
  const current = Array.isArray(state.formData[fieldName]) ? [...state.formData[fieldName]] : [];
  // Build default values for known fields
  const defaults = {};
  const props = typeInfo.schema?.properties || {};
  for (const [k, v] of Object.entries(props)) {
    if (k === 'block_type') continue;
    if (v.type === 'boolean') defaults[k] = false;
    else if (v.type === 'number' || v.type === 'integer') defaults[k] = null;
    else if (v.type === 'array') defaults[k] = [];
    else if (v.type === 'object') defaults[k] = {};
    else defaults[k] = '';
  }
  current.push({ block_type: typeInfo.registeredType, ...defaults });
  state.formData = { ...state.formData, [fieldName]: current };
  state.isDirty = true;
  render();
}

/** Remove the block at the given index from the field array. */
function removeBlock(fieldName, index) {
  const current = Array.isArray(state.formData[fieldName]) ? [...state.formData[fieldName]] : [];
  current.splice(index, 1);
  state.formData = { ...state.formData, [fieldName]: current };
  state.isDirty = true;
  render();
}

/** Move a block from one index to another within the field array. */
function moveBlock(fieldName, fromIndex, toIndex) {
  if (fromIndex === toIndex) return;
  const current = Array.isArray(state.formData[fieldName]) ? [...state.formData[fieldName]] : [];
  const [item] = current.splice(fromIndex, 1);
  current.splice(toIndex, 0, item);
  state.formData = { ...state.formData, [fieldName]: current };
  state.isDirty = true;
  render();
}

/** Update a single field within a block at the given index. */
function updateBlockField(fieldName, index, blockFieldName, value) {
  const current = Array.isArray(state.formData[fieldName]) ? [...state.formData[fieldName]] : [];
  current[index] = { ...current[index], [blockFieldName]: value };
  state.formData = { ...state.formData, [fieldName]: current };
  state.isDirty = true;
  // Partial update — only update dirty dot, no full re-render to preserve focus
  const dot = $('dirty-dot');
  if (dot) dot.classList.add('is-visible');
}

/**
 * Build a single block card element.
 */
function buildBlockCard(fieldName, blockData, blockSchema, index, availableTypes, allDefs) {
  let isDragging = false;
  let dragOverActive = false;

  const card = el('div', {
    class: 'block-card',
    draggable: 'true',
  });

  // Header
  const header = el('div', { class: 'block-card__header', title: 'Click to expand/collapse' },
    el('span', { class: 'block-card__drag-handle', 'aria-label': 'Drag to reorder' }, '⠿'),
    el('span', { class: 'block-card__type-label' }, humanizeFieldName(blockData.block_type || 'Block')),
    el('button', {
      class: 'block-card__delete',
      title: 'Remove block',
      onclick: e => { e.stopPropagation(); removeBlock(fieldName, index); },
    }, '✕')
  );
  card.appendChild(header);

  // Body (collapsible)
  const body = el('div', { class: 'block-card__body' });

  const props = blockSchema?.properties || {};
  const orderedEntries = Object.entries(props)
    .filter(([k]) => k !== 'block_type')
    .sort((a, b) => {
      const oa = a[1].display_order ?? 9999;
      const ob = b[1].display_order ?? 9999;
      return oa - ob;
    });

  for (const [bFieldName, bProp] of orderedEntries) {
    const bMeta = {};  // block schema fields don't carry field_meta in this context
    const widget = fieldWidget(bFieldName, bProp, bMeta);
    const bLabel = humanizeFieldName(bFieldName);
    const bVal = blockData[bFieldName] ?? getDefaultValue(bProp, bMeta);

    const bGroup = el('div', { class: 'field-group field-group--nested' });
    bGroup.appendChild(el('label', { class: 'field-label', for: `block-${fieldName}-${index}-${bFieldName}` }, bLabel));

    // Render scalar widgets inline (no recursive block_canvas for nested blocks)
    switch (widget) {
      case 'textarea': {
        const ta = el('textarea', {
          class: 'field-textarea',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          placeholder: '',
          oninput: e => updateBlockField(fieldName, index, bFieldName, e.target.value),
        });
        ta.value = bVal || '';
        bGroup.appendChild(ta);
        break;
      }
      case 'boolean': {
        const toggleLabel = el('label', { class: 'toggle-switch', for: `block-${fieldName}-${index}-${bFieldName}` });
        const input = el('input', {
          type: 'checkbox',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          onchange: e => updateBlockField(fieldName, index, bFieldName, e.target.checked),
        });
        if (bVal) input.setAttribute('checked', 'true');
        toggleLabel.appendChild(input);
        toggleLabel.appendChild(el('span', { class: 'toggle-track' }));
        toggleLabel.appendChild(el('span', { class: 'toggle-thumb' }));
        bGroup.appendChild(el('div', { class: 'field-bool' }, toggleLabel, el('span', { class: 'field-bool__label' }, bLabel)));
        break;
      }
      case 'number': {
        const input = el('input', {
          class: 'field-input',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          type: 'number',
          value: bVal != null ? String(bVal) : '',
          oninput: e => updateBlockField(fieldName, index, bFieldName, e.target.value === '' ? null : Number(e.target.value)),
        });
        bGroup.appendChild(input);
        break;
      }
      case 'select': {
        const sel = el('select', {
          class: 'field-select',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          onchange: e => updateBlockField(fieldName, index, bFieldName, e.target.value),
        });
        for (const choice of (bMeta.choices || [])) {
          const opt = el('option', { value: choice }, choice);
          if (bVal === choice) opt.setAttribute('selected', 'true');
          sel.appendChild(opt);
        }
        bGroup.appendChild(sel);
        break;
      }
      case 'json': {
        const ta = el('textarea', {
          class: 'field-textarea field-textarea--json',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          oninput: e => {
            try { updateBlockField(fieldName, index, bFieldName, JSON.parse(e.target.value)); } catch { /* ignore */ }
          },
        });
        ta.value = bVal != null ? JSON.stringify(bVal, null, 2) : '';
        bGroup.appendChild(ta);
        break;
      }
      default: { // input / image_picker / prosemirror → plain input in nested context
        const input = el('input', {
          class: 'field-input',
          id: `block-${fieldName}-${index}-${bFieldName}`,
          type: 'text',
          placeholder: '',
          value: typeof bVal === 'string' ? bVal : (bVal != null ? String(bVal) : ''),
          oninput: e => updateBlockField(fieldName, index, bFieldName, e.target.value),
        });
        bGroup.appendChild(input);
        break;
      }
    }

    body.appendChild(bGroup);
  }

  card.appendChild(body);

  // Toggle open/collapse on header click
  header.addEventListener('click', e => {
    if (e.target.closest('.block-card__delete')) return;
    card.classList.toggle('is-open');
  });

  // Drag-and-drop reorder
  card.addEventListener('dragstart', e => {
    isDragging = true;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(index));
    card.classList.add('is-dragging');
  });

  card.addEventListener('dragend', () => {
    isDragging = false;
    card.classList.remove('is-dragging');
  });

  card.addEventListener('dragover', e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!dragOverActive) {
      dragOverActive = true;
      card.classList.add('drag-over');
    }
  });

  card.addEventListener('dragleave', () => {
    dragOverActive = false;
    card.classList.remove('drag-over');
  });

  card.addEventListener('drop', e => {
    e.preventDefault();
    dragOverActive = false;
    card.classList.remove('drag-over');
    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (!isNaN(fromIndex) && fromIndex !== index) {
      moveBlock(fieldName, fromIndex, index);
    }
  });

  return card;
}

/**
 * Build the full block canvas widget for a ListField/BlockField.
 */
function buildBlockCanvas(fieldName, prop, meta, typeSchema, currentValue) {
  const availableTypes = getBlockTypesMeta(prop, typeSchema);
  const blocks = Array.isArray(currentValue) ? currentValue : (currentValue ? [currentValue] : []);
  const allDefs = typeSchema?.$defs || {};

  const canvas = el('div', { class: 'block-canvas' });

  // Render existing block cards
  for (let i = 0; i < blocks.length; i++) {
    const blockData = blocks[i];
    // Find schema for this block's type
    const typeInfo = availableTypes.find(t => t.registeredType === blockData.block_type)
      || availableTypes[0];
    const blockSchema = typeInfo?.schema || {};
    const card = buildBlockCard(fieldName, blockData, blockSchema, i, availableTypes, allDefs);
    canvas.appendChild(card);
  }

  // "Add block" section
  const addWrap = el('div', { class: 'block-canvas__add-wrap' });

  if (availableTypes.length === 1) {
    // Single type — direct add button, no picker
    const addBtn = el('button', {
      class: 'block-canvas__add btn btn--ghost',
      onclick: () => addBlock(fieldName, availableTypes[0]),
    }, '+ Add block');
    addWrap.appendChild(addBtn);
  } else if (availableTypes.length > 1) {
    // Multiple types — show picker dropdown
    const addBtn = el('button', {
      class: 'block-canvas__add btn btn--ghost',
      'aria-haspopup': 'listbox',
      onclick: () => {
        picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
        if (picker.style.display === 'block') {
          const first = picker.querySelector('.block-type-picker__item');
          if (first) first.focus();
        }
      },
      onkeydown: e => {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          picker.style.display = 'block';
          const first = picker.querySelector('.block-type-picker__item');
          if (first) first.focus();
        }
      },
    }, '+ Add block ▾');
    const picker = buildBlockTypePicker(fieldName, availableTypes);
    addWrap.appendChild(addBtn);
    addWrap.appendChild(picker);

    // Close picker when clicking outside
    document.addEventListener('click', e => {
      if (!addWrap.contains(e.target)) {
        picker.style.display = 'none';
      }
    }, { capture: false });
  }

  if (availableTypes.length > 0) {
    canvas.appendChild(addWrap);
  }

  return canvas;
}


/* =====================================================================
   META PANEL — shows document metadata for existing documents
   ===================================================================== */

function buildMetaPanel(doc) {
  const panel = el('details', { class: 'doc-meta' });
  panel.appendChild(el('summary', { class: 'doc-meta__summary' }, 'Document info'));

  function metaRow(key, valueNode) {
    return el('div', { class: 'doc-meta__row' },
      el('span', { class: 'doc-meta__key' }, key),
      typeof valueNode === 'string'
        ? el('span', { class: 'doc-meta__val' }, valueNode)
        : valueNode
    );
  }

  // ID — monospace, copy on click
  const idVal = el('span', {
    class: 'doc-meta__val doc-meta__copy',
    title: 'Click to copy',
    onclick: () => {
      navigator.clipboard?.writeText(doc.id).then(() => showToast('info', 'Copied', doc.id));
    },
  }, doc.id || '—');
  panel.appendChild(metaRow('ID', idVal));

  if (doc.created_at) panel.appendChild(metaRow('Created', formatDate(doc.created_at)));
  if (doc.updated_at) panel.appendChild(metaRow('Updated', formatDate(doc.updated_at)));
  if (doc.published_at) panel.appendChild(metaRow('Published at', formatDate(doc.published_at)));
  if (doc.import_ref) panel.appendChild(metaRow('import_ref', doc.import_ref));
  if (doc.singleton_status) panel.appendChild(metaRow('Singleton', doc.singleton_status));

  return panel;
}


/* =====================================================================
   IMAGE PICKER — inline picker with optional Mediakit iframe modal
   ===================================================================== */

/** Tracks which field the open picker modal is for. */
let currentPickerField = null;

/** Close and remove the picker modal. */
function closePickerModal() {
  const modal = document.querySelector('.picker-modal');
  if (modal) modal.remove();
  window.removeEventListener('message', onPickerMessage);
  currentPickerField = null;
}

/** Handle postMessage events from the Mediakit picker iframe. */
function onPickerMessage(event) {
  const data = event.data;
  if (!data) return;
  const type = typeof data === 'string' ? data : data.type;
  if (type === 'mediakit:asset-selected') {
    const value = (typeof data === 'object' ? (data.key || data.url) : null) || '';
    if (currentPickerField) {
      onFieldChange(currentPickerField, value);
      // Update the preview thumbnail synchronously (if it's visible)
      const preview = document.getElementById(`img-preview-${currentPickerField}`);
      if (preview && value) { preview.src = value; preview.style.display = ''; }
      else if (preview) preview.style.display = 'none';
      const valEl = document.getElementById(`img-val-${currentPickerField}`);
      if (valEl) valEl.value = value;
    }
    closePickerModal();
  } else if (type === 'mediakit:picker-cancelled') {
    closePickerModal();
  }
}

/** Open the Mediakit picker iframe in a modal. */
function openImagePicker(fieldName) {
  currentPickerField = fieldName;
  const iframeSrc = `${CONFIG.mediaBase}/admin?picker=1`;

  const modal = el('div', { class: 'picker-modal' },
    el('div', { class: 'picker-modal__inner' },
      el('button', {
        class: 'picker-modal__close btn btn--ghost',
        title: 'Close',
        onclick: closePickerModal,
      }, '✕'),
      el('iframe', { class: 'picker-modal__iframe', src: iframeSrc })
    )
  );

  document.body.appendChild(modal);
  window.addEventListener('message', onPickerMessage);
}

/**
 * Build the image picker widget for an ImageField.
 * Shows an iframe-based Mediakit picker when media_base is configured,
 * otherwise falls back to a plain text input.
 */
function buildImagePickerField(fieldName, currentValue) {
  const wrap = el('div', { class: 'image-picker' });

  if (CONFIG.mediaBase) {
    // Thumbnail preview
    const img = el('img', {
      class: 'image-picker__preview',
      id: `img-preview-${fieldName}`,
      src: currentValue || '',
      alt: '',
    });
    img.style.display = currentValue ? '' : 'none';

    // Hidden text input keeps the value in sync
    const hiddenInput = el('input', {
      type: 'hidden',
      id: `img-val-${fieldName}`,
      value: currentValue || '',
    });

    const chooseBtn = el('button', {
      class: 'btn btn--ghost',
      onclick: () => openImagePicker(fieldName),
    }, 'Choose Image');

    const clearBtn = el('button', {
      class: 'btn btn--ghost',
      style: currentValue ? '' : 'display:none',
      onclick: () => {
        onFieldChange(fieldName, '');
        img.src = '';
        img.style.display = 'none';
        hiddenInput.value = '';
        clearBtn.style.display = 'none';
      },
    }, 'Clear');

    wrap.appendChild(img);
    wrap.appendChild(hiddenInput);
    wrap.appendChild(chooseBtn);
    wrap.appendChild(clearBtn);
  } else {
    // Fallback — plain text input
    const input = el('input', {
      class: 'field-input',
      id: `field-${fieldName}`,
      type: 'text',
      placeholder: 'https://…',
      value: currentValue || '',
      oninput: e => onFieldChange(fieldName, e.target.value),
    });
    wrap.appendChild(input);
    wrap.appendChild(el('span', { class: 'field-help' }, '(configure media_base on Editor to enable image picker)'));
  }

  return wrap;
}

function getDefaultValue(prop, meta) {
  if (meta?.default != null) return meta.default;
  if (prop.default != null) return prop.default;
  if (prop.type === 'boolean') return false;
  if (prop.type === 'number' || prop.type === 'integer') return null;
  if (prop.type === 'array') return [];
  if (prop.type === 'object') return {};
  return '';
}


/* =====================================================================
   10. MAIN RENDER ORCHESTRATOR
   ===================================================================== */

function render() {
  renderTypeList();
  renderDocList();
  renderHeader();
  renderForm();
}


/* =====================================================================
   11. ACTIONS (user interactions → state changes → API calls)
   ===================================================================== */

async function selectType(typeKey) {
  if (state.activeType === typeKey) return;

  // Destroy PM instances when switching away
  destroyPmInstances();

  setState({
    activeType: typeKey,
    documents: [],
    docsTotal: 0,
    activeDocId: null,
    activeDoc: null,
    formData: {},
    isDirty: false,
    isLoadingDocs: true,
  });

  try {
    const result = await fetchDocuments(typeKey);
    setState({
      documents: result.documents || [],
      docsTotal: result.total || 0,
      isLoadingDocs: false,
    });
  } catch (err) {
    setState({ isLoadingDocs: false });
    showToast('error', 'Failed to load documents', err.message);
  }
}

async function selectDoc(docId) {
  if (state.activeDocId === docId) return;

  destroyPmInstances();

  setState({
    activeDocId: docId,
    activeDoc: null,
    formData: {},
    isDirty: false,
    isLoadingDoc: true,
  });

  try {
    const doc = await fetchDocument(docId);
    setState({
      activeDoc: doc,
      formData: { ...(doc.body || {}), __slug: doc.slug || '' },
      isLoadingDoc: false,
      isDirty: false,
    });
  } catch (err) {
    setState({ isLoadingDoc: false });
    showToast('error', 'Failed to load document', err.message);
  }
}

function openNewDoc() {
  if (!state.activeType) return;
  destroyPmInstances();
  setState({
    activeDocId: null,
    activeDoc: null,
    formData: { __slug: '' },
    isDirty: false,
  });
}

function onFieldChange(name, value) {
  state.formData = { ...state.formData, [name]: value };
  state.isDirty = true;
  // Only update the dirty indicator — no full re-render to preserve focus
  const dot = $('dirty-dot');
  if (dot) dot.classList.add('is-visible');
}

async function saveDocument() {
  if (!state.activeType) return;
  if (state.isSaving) return;

  setState({ isSaving: true });

  // Extract slug and body from formData
  const { __slug, ...bodyFields } = state.formData;
  const slug = __slug || '';

  // Flush PM editor content to formData before saving.
  // RichTextField fields store PM JSON; legacy markdown fields serialise to markdown.
  for (const [name, view] of Object.entries(state.pmInstances)) {
    const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};
    bodyFields[name] = fieldMeta.field_type === 'rich_text'
      ? view.state.doc.toJSON()
      : pmDocToMarkdown(view.state.doc);
  }

  try {
    let savedDoc;
    if (state.activeDocId) {
      // Update existing document
      savedDoc = await patchDocument(state.activeDocId, { body: bodyFields, slug });
    } else {
      // Create new document
      savedDoc = await createDocument(state.activeType, bodyFields, slug);
    }

    // Refresh the documents list
    const result = await fetchDocuments(state.activeType);

    setState({
      isSaving: false,
      activeDocId: savedDoc.id,
      activeDoc: savedDoc,
      formData: { ...(savedDoc.body || {}), __slug: savedDoc.slug || '' },
      isDirty: false,
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    showToast('success', 'Saved', docTitle(savedDoc));
  } catch (err) {
    setState({ isSaving: false });
    showToast('error', 'Save failed', err.message);
  }
}

async function togglePublish() {
  const doc = state.activeDoc;
  if (!doc) return;

  try {
    let updated;
    if (doc.published) {
      updated = await unpublishDocument(doc.id);
      showToast('info', 'Unpublished', docTitle(doc));
    } else {
      updated = await publishDocument(doc.id);
      showToast('success', 'Published', docTitle(doc));
    }

    // Refresh list and doc
    const result = await fetchDocuments(state.activeType);
    setState({
      activeDoc: updated,
      formData: { ...(updated.body || {}), __slug: updated.slug || '' },
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });
  } catch (err) {
    showToast('error', 'Failed to change publish state', err.message);
  }
}

async function deleteActiveDoc() {
  const doc = state.activeDoc;
  if (!doc) return;

  const confirmed = await showConfirm(
    'Delete document',
    `Are you sure you want to delete "${docTitle(doc)}"? This cannot be undone.`
  );
  if (!confirmed) return;

  try {
    await deleteDocument(doc.id);

    destroyPmInstances();

    const result = await fetchDocuments(state.activeType);
    setState({
      activeDocId: null,
      activeDoc: null,
      formData: {},
      isDirty: false,
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    showToast('success', 'Deleted', docTitle(doc));
  } catch (err) {
    showToast('error', 'Delete failed', err.message);
  }
}

function destroyPmInstances() {
  for (const [, view] of Object.entries(state.pmInstances)) {
    try { view.destroy(); } catch { /* already destroyed */ }
  }
  state.pmInstances = {};
}


/* =====================================================================
   12. INITIAL HTML SCAFFOLD
   ===================================================================== */

function buildShell() {
  const root = document.getElementById('app');
  root.innerHTML = '';

  // Type sidebar
  const typeSidebar = el('aside', { class: 'sidebar-types' },
    el('div', { class: 'sidebar-types__header' },
      el('span', { class: 'sidebar-types__logo' }, 'Astraeus')
    ),
    el('nav', { class: 'sidebar-types__list', id: 'type-list' })
  );

  // Doc list sidebar
  const docSidebar = el('aside', { class: 'sidebar-docs' },
    el('div', { class: 'sidebar-docs__header' },
      el('span', { class: 'sidebar-docs__title', id: 'doc-list-title' }, '—'),
      el('button', {
        class: 'sidebar-docs__new-btn',
        id: 'doc-new-btn',
        title: 'New document',
        style: 'display:none',
        onclick: openNewDoc,
      }, '+')
    ),
    el('div', { class: 'sidebar-docs__list', id: 'doc-list' },
      el('div', { class: 'sidebar-docs__empty' }, 'Select a type')
    )
  );

  // Main content area
  const main = el('main', { class: 'main-content' },
    // Header bar
    el('header', { class: 'editor-header' },
      el('div', { class: 'editor-header__title-wrap' },
        el('h1', { class: 'editor-header__title', id: 'header-title' }, 'CMS Editor'),
        el('span', { class: 'editor-header__dirty-dot', id: 'dirty-dot', title: 'Unsaved changes' })
      ),
      el('div', { class: 'editor-header__actions' },
        // Publish toggle (hidden until a doc is loaded)
        el('div', { class: 'publish-toggle', id: 'publish-wrap', style: 'display:none' },
          el('label', { class: 'toggle-switch', for: 'publish-toggle-input' },
            el('input', {
              type: 'checkbox',
              id: 'publish-toggle-input',
              onchange: togglePublish,
            }),
            el('span', { class: 'toggle-track' }),
            el('span', { class: 'toggle-thumb' })
          ),
          el('span', { class: 'publish-toggle__label', id: 'publish-toggle-label' }, 'Draft')
        ),
        el('button', {
          class: 'btn btn--danger',
          id: 'delete-btn',
          style: 'display:none',
          onclick: deleteActiveDoc,
        }, 'Delete'),
        el('button', {
          class: 'btn btn--primary',
          id: 'save-btn',
          style: 'display:none',
          onclick: saveDocument,
        }, 'Save')
      )
    ),
    // Scrollable form area
    el('div', { class: 'editor-scroll' },
      el('div', { id: 'form-area' })
    )
  );

  root.appendChild(typeSidebar);
  root.appendChild(docSidebar);
  root.appendChild(main);
}


/* =====================================================================
   13. BOOT
   ===================================================================== */

async function boot() {
  buildShell();
  render(); // Show loading state

  setState({ isLoadingSchema: true }, false);
  renderTypeList();

  try {
    const schema = await fetchSchema();
    setState({ schema, isLoadingSchema: false });
  } catch (err) {
    setState({ isLoadingSchema: false });
    showToast('error', 'Failed to load schema', err.message);
    render();
  }
}

// Start when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
