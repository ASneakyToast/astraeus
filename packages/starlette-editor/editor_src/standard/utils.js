/**
 * standard/utils.js — Pure utility functions (no DOM, no state).
 */

/**
 * Humanize a snake_case doc_type name.
 * "blog_post" → "Blog Posts"
 *
 * @param {string} str
 * @returns {string}
 */
export function humanizeType(str) {
  return str
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/s$/, '') + 's';
}

/**
 * Humanize a snake_case field name.
 * "my_field" → "My Field"
 *
 * @param {string} name
 * @returns {string}
 */
export function humanizeFieldName(name) {
  return name
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

/**
 * Get a display title for a document — prefers title > name > slug > id prefix > "Untitled".
 *
 * @param {object|null} doc
 * @returns {string}
 */
export function docTitle(doc) {
  const body = doc?.body || {};
  return body.title || body.name || body.headline || doc?.slug || doc?.id?.slice(0, 8) || 'Untitled';
}

/**
 * Format an ISO date string for display.
 *
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return '';
  }
}

/**
 * Get ordered field entries from schema + field_meta.
 *
 * @param {object} typeInfo
 * @returns {Array<{name: string, prop: object, meta: object}>}
 */
export function getOrderedFields(typeInfo) {
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
 * Return the default value for a field based on its JSON Schema prop and field_meta.
 *
 * @param {object} prop  — JSON Schema property definition
 * @param {object} meta  — field_meta entry
 * @returns {*}
 */
export function getDefaultValue(prop, meta) {
  if (meta?.default != null) return meta.default;
  if (prop.default != null) return prop.default;
  if (prop.type === 'boolean') return false;
  if (prop.type === 'number' || prop.type === 'integer') return null;
  if (prop.type === 'array') return [];
  if (prop.type === 'object') return {};
  return '';
}

/**
 * Shorthand getElementById.
 *
 * @param {string} id
 * @returns {HTMLElement|null}
 */
export const $ = id => document.getElementById(id);

/**
 * Create a DOM element with attributes and children.
 *
 * @param {string} tag
 * @param {object} attrs
 * @param {...*} children
 * @returns {HTMLElement}
 */
export const el = (tag, attrs = {}, ...children) => {
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
