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

  const entries = Object.entries(props).map(([name, prop]) => ({
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
  if (ft === 'select')       return 'select';
  if (ft === 'number')       return 'number';
  if (ft === 'boolean')      return 'boolean';
  if (ft === 'json')         return 'json';
  // image, url, document_ref, text → fall through to heuristics below
  // (image/url/document_ref all render as text input for now)

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
  const cmds = {
    toggleBold: toggleMark(schema.marks.strong),
    toggleItalic: toggleMark(schema.marks.em),
    h1: setBlockType(schema.nodes.heading, { level: 1 }),
    h2: setBlockType(schema.nodes.heading, { level: 2 }),
    paragraph: setBlockType(schema.nodes.paragraph),
    bulletList: wrapIn(schema.nodes.bullet_list),
    orderedList: wrapIn(schema.nodes.ordered_list),
    blockquote: wrapIn(schema.nodes.blockquote),
  };
  const fn = cmds[cmd];
  if (fn) fn(state, dispatch);
  view.focus();
}

function humanizeFieldName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
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

  // Flush PM editor content to formData before saving
  for (const [name, view] of Object.entries(state.pmInstances)) {
    bodyFields[name] = pmDocToMarkdown(view.state.doc);
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
