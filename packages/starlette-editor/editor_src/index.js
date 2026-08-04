/**
 * Astraeus CMS Editor — index.js
 *
 * Entry point. Wires state, render, and actions together, then boots the SPA.
 *
 * Architecture:
 *   state.js   → shared state object, mutated through setState()
 *   render.js  → full re-render of each panel on every state change
 *   api.js     → thin fetch wrapper
 *   actions.js → async user interactions → API calls → setState
 *   mount.js   → ProseMirror lifecycle (npm-bundled, no CDN)
 */

import { state, setState, setRenderFn } from './state.js'
import { fetchSchema } from './api.js'
import { showToast } from './components/toast.js'
import { ChatPanel } from './embed/chat-panel.js'
import { ShellChangesetPanel } from './standard/changeset-panel-shell.js'
import { getActiveChangesetId } from './changeset-store.js'
import {
  renderTypeList,
  renderDocList,
  renderHeader,
  renderForm,
} from './standard/render.js'
import {
  selectType,
  selectDoc,
  openNewDoc,
  onFieldChange,
  saveDocument,
  togglePublish,
  deleteActiveDoc,
} from './standard/actions.js'
import { el } from './standard/utils.js'

/**
 * Top-level render orchestrator — called by setState() on every state change.
 */
function render() {
  renderTypeList(selectType);
  renderDocList(selectDoc, openNewDoc);
  renderHeader(togglePublish, saveDocument, deleteActiveDoc);
  renderForm(onFieldChange, render);
}

// Wire render into state so setState() can call it
setRenderFn(render);

/**
 * Build the initial HTML shell structure inside #app.
 */
function buildShell() {
  const root = document.getElementById('app');
  root.innerHTML = '';

  const typeSidebar = el('aside', { class: 'sidebar-types' },
    el('div', { class: 'sidebar-types__header' },
      el('span', { class: 'sidebar-types__logo' }, 'Astraeus')
    ),
    el('nav', { class: 'sidebar-types__list', id: 'type-list' })
  );

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

  const main = el('main', { class: 'main-content' },
    el('header', { class: 'editor-header' },
      el('div', { class: 'editor-header__title-wrap' },
        el('h1', { class: 'editor-header__title', id: 'header-title' }, 'CMS Editor'),
        el('span', { class: 'editor-header__dirty-dot', id: 'dirty-dot', title: 'Unsaved changes' })
      ),
      el('div', { class: 'editor-header__actions' },
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
    el('div', { class: 'editor-scroll' },
      el('div', { id: 'form-area' })
    )
  );

  root.appendChild(typeSidebar);
  root.appendChild(docSidebar);
  root.appendChild(main);
}

/**
 * Boot the editor SPA: build shell, load schema, render.
 */
async function boot() {
  buildShell();
  render(); // Show initial empty state

  setState({ isLoadingSchema: true }, false);
  renderTypeList(selectType);

  try {
    const schema = await fetchSchema();
    setState({ schema, isLoadingSchema: false });
  } catch (err) {
    setState({ isLoadingSchema: false });
    showToast('error', 'Failed to load schema', err.message);
    render();
  }

  // Mount ChatPanel — reads config from __EDITOR_CONFIG__ injected by the shell template.
  // cmsBase is "" when the shell is served same-origin (routes.py injects "" for relative
  // API calls). Resolve to origin so ChatPanel can build absolute URLs for the chat API.
  // ChatAPI is mounted at /chat, so chatBase = resolvedBase + '/chat'.
  const cfg = window.__EDITOR_CONFIG__ || {}
  const resolvedCmsBase = cfg.cmsBase || window.location.origin
  const chatPanel = new ChatPanel(resolvedCmsBase + '/chat', null, {
    apiKey: cfg.apiKey || null,
    getDocContext: () => {
      if (!state.activeDocId) return null
      // Use the first collab connection for version/draft_body if available
      const conn = Object.values(state.collabConnections)[0] || null
      return {
        doc_id: state.activeDocId,
        version: conn?.currentVersion?.() ?? 0,
        draft_body: conn?.currentDoc?.() ?? null,
        selection: conn?.currentSelection?.() ?? null,
        active_changeset_id: state.activeChangesetId ?? null,
      }
    },
  })
  chatPanel.mount()
  setState({ chatPanel }, false)  // store without re-render (header re-renders on doc select)

  // Mount ChangesetPanel
  const changesetPanel = new ShellChangesetPanel()
  changesetPanel.mount()
  const initialCsId = getActiveChangesetId()
  setState({ changesetPanel, activeChangesetId: initialCsId }, false)
}

// Start when the DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
