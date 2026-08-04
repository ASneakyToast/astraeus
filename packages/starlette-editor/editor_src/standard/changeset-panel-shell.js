/**
 * changeset-panel-shell.js — Changeset panel for the standard CMS shell.
 *
 * Same UX as the embed ChangesetPanel but uses apiFetch (Bearer auth) and
 * integrates with shell state + localStorage-backed active changeset.
 */

import {
  fetchDirtyDocs,
  fetchOpenChangesets,
  createChangeset,
  addDocToChangeset,
  publishChangeset,
  scheduleChangeset,
  deleteChangeset,
} from '../api.js';
import {
  getActiveChangesetId,
  setActiveChangesetId,
  onActiveChangesetChange,
} from '../changeset-store.js';
import { state, setState } from '../state.js';
import { showToast } from '../components/toast.js';

const PANEL_STYLES = `
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9998;
  width: 320px;
  background: #1e1e2e;
  color: #cdd6f4;
  border: 1px solid #313244;
  border-radius: 12px;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  overflow: hidden;
  max-height: 80vh;
  overflow-y: auto;
`;

const SECTION_HEADING = `
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #89b4fa;
  padding: 8px 14px 4px;
  margin: 0;
`;

const ITEM = `
  padding: 6px 14px;
  border-bottom: 1px solid #181825;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`;

const BTN = `
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: system-ui, -apple-system, sans-serif;
`;

export class ShellChangesetPanel {
  constructor() {
    this.el = null;
    this.visible = false;
    this.dirtyDocs = [];
    this.openChangesets = [];

    onActiveChangesetChange((newId) => {
      setState({ activeChangesetId: newId }, false);
      if (this.visible) this._render();
    });
  }

  mount() {
    this.el = document.createElement('div');
    this.el.setAttribute('data-cms-changeset-panel', '');
    this.el.style.cssText = PANEL_STYLES;
    this.el.style.display = 'none';
    document.body.appendChild(this.el);
  }

  async toggle() {
    this.visible = !this.visible;
    if (this.el) {
      this.el.style.display = this.visible ? 'block' : 'none';
    }
    if (this.visible) {
      await this.refresh();
    }
  }

  async refresh() {
    try {
      const [docsResult, csResult] = await Promise.all([
        fetchDirtyDocs(),
        fetchOpenChangesets(),
      ]);
      this.dirtyDocs = docsResult.documents ?? [];
      this.openChangesets = csResult.changesets ?? [];
    } catch (_err) {
      this.dirtyDocs = [];
      this.openChangesets = [];
    }
    this._render();
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  _render() {
    if (!this.el) return;
    this.el.innerHTML = '';

    const activeId = state.activeChangesetId;

    // Title bar
    const titleBar = document.createElement('div');
    titleBar.style.cssText = `
      padding: 12px 14px 10px;
      border-bottom: 1px solid #313244;
      display: flex; align-items: center; justify-content: space-between;
    `;
    const title = document.createElement('span');
    title.style.cssText = 'font-weight: 700; color: #cdd6f4;';
    title.textContent = '📋 Changesets';

    const closeBtn = document.createElement('button');
    closeBtn.style.cssText = `${BTN} background: transparent; color: #6c7086; font-size: 16px; padding: 0 4px;`;
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', () => this.toggle());

    titleBar.appendChild(title);
    titleBar.appendChild(closeBtn);
    this.el.appendChild(titleBar);

    // Section: Unpublished drafts
    const draftsHeading = document.createElement('p');
    draftsHeading.style.cssText = SECTION_HEADING;
    draftsHeading.textContent = `Unpublished drafts (${this.dirtyDocs.length})`;
    this.el.appendChild(draftsHeading);

    if (this.dirtyDocs.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding: 6px 14px 10px; color: #6c7086; font-size: 12px;';
      empty.textContent = 'No unpublished drafts';
      this.el.appendChild(empty);
    } else {
      this.dirtyDocs.forEach(doc => {
        const row = document.createElement('div');
        row.style.cssText = ITEM;

        const docLabel = document.createElement('span');
        docLabel.style.cssText = 'flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;';
        docLabel.title = `${doc.doc_type}: ${doc.slug}`;
        docLabel.textContent = `${doc.doc_type}: ${doc.slug}`;

        const actionWrap = document.createElement('div');
        actionWrap.style.cssText = 'flex-shrink: 0;';

        if (this.openChangesets.length === 0) {
          const createBtn = document.createElement('button');
          createBtn.style.cssText = `${BTN} background: #313244; color: #cdd6f4;`;
          createBtn.textContent = '+ New changeset';
          createBtn.addEventListener('click', () => this._promptAndCreate(doc.id));
          actionWrap.appendChild(createBtn);
        } else {
          const select = document.createElement('select');
          select.style.cssText = `
            background: #313244; color: #cdd6f4; border: 1px solid #45475a;
            border-radius: 6px; padding: 3px 6px; font-size: 12px; cursor: pointer;
          `;

          const placeholder = document.createElement('option');
          placeholder.value = '';
          placeholder.textContent = '— Add to —';
          placeholder.disabled = true;
          placeholder.selected = true;
          select.appendChild(placeholder);

          this.openChangesets.forEach(cs => {
            const opt = document.createElement('option');
            opt.value = cs.id;
            opt.textContent = `${cs.id === activeId ? '● ' : ''}"${cs.title || 'Untitled'}" (${cs.document_count ?? 0})`;
            select.appendChild(opt);
          });

          const newOpt = document.createElement('option');
          newOpt.value = '__new__';
          newOpt.textContent = 'Create new…';
          select.appendChild(newOpt);

          select.addEventListener('change', async () => {
            const val = select.value;
            if (!val) return;
            if (val === '__new__') {
              await this._promptAndCreate(doc.id);
            } else {
              await this._handleAddToChangeset(doc.id, val);
            }
          });

          actionWrap.appendChild(select);
        }

        row.appendChild(docLabel);
        row.appendChild(actionWrap);
        this.el.appendChild(row);
      });
    }

    // Section: Open changesets
    const csHeading = document.createElement('p');
    csHeading.style.cssText = SECTION_HEADING;
    csHeading.textContent = 'Open changesets';
    this.el.appendChild(csHeading);

    if (this.openChangesets.length === 0) {
      const empty = document.createElement('div');
      empty.style.cssText = 'padding: 6px 14px 10px; color: #6c7086; font-size: 12px;';
      empty.textContent = 'No open changesets';
      this.el.appendChild(empty);
    } else {
      this.openChangesets.forEach(cs => {
        const isActive = cs.id === activeId;
        const row = document.createElement('div');
        row.style.cssText = `${ITEM} flex-wrap: wrap; gap: 6px;${isActive ? ' background: #181825;' : ''}`;

        const csLabel = document.createElement('span');
        csLabel.style.cssText = `flex: 1 1 100%; color: ${isActive ? '#a6e3a1' : '#cdd6f4'};`;
        csLabel.textContent = `${isActive ? '● ' : '○ '}"${cs.title || 'Untitled'}" (${cs.document_count ?? 0} docs)`;

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display: flex; gap: 6px; flex-wrap: wrap;';

        // Set active / Active indicator
        const activeBtn = document.createElement('button');
        if (isActive) {
          activeBtn.style.cssText = `${BTN} background: #a6e3a1; color: #1e1e2e; opacity: 0.7;`;
          activeBtn.textContent = 'Active';
          activeBtn.disabled = true;
        } else {
          activeBtn.style.cssText = `${BTN} background: #313244; color: #cdd6f4;`;
          activeBtn.textContent = 'Set active';
          activeBtn.addEventListener('click', () => {
            setActiveChangesetId(cs.id);
            setState({ activeChangesetId: cs.id }, false);
            this._render();
          });
        }

        const publishBtn = document.createElement('button');
        publishBtn.style.cssText = `${BTN} background: #a6e3a1; color: #1e1e2e;`;
        publishBtn.textContent = 'Publish all';
        publishBtn.addEventListener('click', () => this._handlePublish(cs.id));

        const scheduleBtn = document.createElement('button');
        scheduleBtn.style.cssText = `${BTN} background: #89b4fa; color: #1e1e2e;`;
        scheduleBtn.textContent = 'Schedule';
        scheduleBtn.addEventListener('click', () => this._handleSchedule(cs.id, row));

        const deleteBtn = document.createElement('button');
        deleteBtn.style.cssText = `${BTN} background: #313244; color: #f38ba8;`;
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => this._handleDelete(cs.id));

        btnRow.appendChild(activeBtn);
        btnRow.appendChild(publishBtn);
        btnRow.appendChild(scheduleBtn);
        btnRow.appendChild(deleteBtn);

        row.appendChild(csLabel);
        row.appendChild(btnRow);
        this.el.appendChild(row);
      });
    }

    // Footer: New changeset + Clear active
    const footer = document.createElement('div');
    footer.style.cssText = 'padding: 10px 14px; border-top: 1px solid #313244; display: flex; gap: 6px;';

    const newBtn = document.createElement('button');
    newBtn.style.cssText = `${BTN} background: #313244; color: #cdd6f4; flex: 1; text-align: left;`;
    newBtn.textContent = '+ New changeset';
    newBtn.addEventListener('click', () => this._promptAndCreate(null));
    footer.appendChild(newBtn);

    if (activeId) {
      const clearBtn = document.createElement('button');
      clearBtn.style.cssText = `${BTN} background: #313244; color: #6c7086;`;
      clearBtn.textContent = 'Clear active';
      clearBtn.addEventListener('click', () => {
        setActiveChangesetId(null);
        setState({ activeChangesetId: null }, false);
        this._render();
      });
      footer.appendChild(clearBtn);
    }

    this.el.appendChild(footer);
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  async _promptAndCreate(docId) {
    const title = window.prompt('Changeset name (optional):') ?? '';
    if (title === null) return;
    try {
      const cs = await createChangeset(title);
      setActiveChangesetId(cs.id);
      setState({ activeChangesetId: cs.id }, false);
      if (docId) {
        await addDocToChangeset(cs.id, docId);
      }
      await this.refresh();
    } catch (err) {
      showToast('error', 'Failed to create changeset', err.message);
    }
  }

  async _handleAddToChangeset(docId, changesetId) {
    try {
      await addDocToChangeset(changesetId, docId);
      await this.refresh();
    } catch (err) {
      showToast('error', 'Failed to add to changeset', err.message);
    }
  }

  async _handlePublish(changesetId) {
    try {
      await publishChangeset(changesetId);
      if (state.activeChangesetId === changesetId) {
        setActiveChangesetId(null);
        setState({ activeChangesetId: null }, false);
      }
      showToast('success', 'Published — site rebuilding');
      await this.refresh();
    } catch (err) {
      showToast('error', 'Publish failed', err.message);
    }
  }

  async _handleSchedule(changesetId, rowEl) {
    rowEl.querySelectorAll('[data-schedule-picker]').forEach(el => el.remove());

    const pickerWrap = document.createElement('div');
    pickerWrap.setAttribute('data-schedule-picker', '');
    pickerWrap.style.cssText = 'flex: 1 1 100%; display: flex; gap: 6px; align-items: center; padding-top: 4px;';

    const input = document.createElement('input');
    input.type = 'datetime-local';
    input.style.cssText = `
      background: #313244; color: #cdd6f4; border: 1px solid #45475a;
      border-radius: 6px; padding: 4px 8px; font-size: 12px; flex: 1;
    `;

    const confirmBtn = document.createElement('button');
    confirmBtn.style.cssText = `${BTN} background: #89b4fa; color: #1e1e2e;`;
    confirmBtn.textContent = 'Confirm';
    confirmBtn.addEventListener('click', async () => {
      if (!input.value) return;
      const dt = new Date(input.value).toISOString();
      try {
        await scheduleChangeset(changesetId, dt);
        await this.refresh();
      } catch (err) {
        showToast('error', 'Schedule failed', err.message);
      }
    });

    pickerWrap.appendChild(input);
    pickerWrap.appendChild(confirmBtn);
    rowEl.appendChild(pickerWrap);
  }

  async _handleDelete(changesetId) {
    if (!confirm('Delete this changeset? Documents will not be affected.')) return;
    try {
      await deleteChangeset(changesetId);
      if (state.activeChangesetId === changesetId) {
        setActiveChangesetId(null);
        setState({ activeChangesetId: null }, false);
      }
      await this.refresh();
    } catch (err) {
      showToast('error', 'Delete failed', err.message);
    }
  }
}
