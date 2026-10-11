/**
 * ALP Table Engine - Universal Reusable Table Controller
 * 
 * Features:
 * - Dynamic Column Resizing (via drag handles on column borders)
 * - Full Column Sorting (Smart numeric, date, and text sorting with arrow indicators ↑ / ↓)
 * - Smooth Horizontal Scrolling with single responsive container support
 * - Non-destructive: preserves native Ember and ME MDM table geometries
 */
(function(window) {
  'use strict';

  const AlpTableEngine = {
    sortStates: new WeakMap(),
    resizingState: null,

    init() {
      this.bindGlobalEvents();
      this.enhanceAll();
      this.setupObserver();
    },

    bindGlobalEvents() {
      document.addEventListener('mousemove', (e) => this.onMouseMove(e));
      document.addEventListener('mouseup', (e) => this.onMouseUp(e));

      // Intuitive horizontal wheel scroll for .table-container
      document.addEventListener('wheel', (e) => {
        const container = e.target.closest('.table-container');
        if (!container) return;
        const maxScroll = container.scrollWidth - container.clientWidth;
        if (maxScroll <= 0) return;

        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
          const isAtStart = container.scrollLeft <= 0 && e.deltaY < 0;
          const isAtEnd = container.scrollLeft >= maxScroll - 1 && e.deltaY > 0;
          if (!isAtStart && !isAtEnd) {
            container.scrollLeft += e.deltaY;
            e.preventDefault();
          }
        }
      }, { passive: false });
    },

    enhanceAll(root) {
      const scope = root && root.querySelectorAll ? root : document;
      
      // 1. If root itself is a table-container
      if (root && root.classList && root.classList.contains('table-container')) {
        this.enhanceEmberTable(root);
      }

      // 2. Enhance all descendant Ember Table containers
      const emberContainers = scope.querySelectorAll('.table-container');
      emberContainers.forEach(c => this.enhanceEmberTable(c));

      // 3. Enhance standard HTML tables
      const standardTables = scope.querySelectorAll('table.tableComponent, table.table, table.alp-table, table.me-table, table.me-authentic-table, .tw > table');
      standardTables.forEach(t => this.enhanceStandardTable(t));
    },

    setupObserver() {
      if (this._observer) return;
      this._observer = new MutationObserver((mutations) => {
        let needsEnhance = false;
        for (const m of mutations) {
          if (m.addedNodes.length > 0) {
            for (const n of m.addedNodes) {
              if (n.nodeType === 1) {
                if (n.classList && (n.classList.contains('table-container') || n.tagName === 'TABLE')) {
                  needsEnhance = true;
                  break;
                }
                if (n.querySelector && (n.querySelector('.table-container') || n.querySelector('table'))) {
                  needsEnhance = true;
                  break;
                }
              }
            }
          }
          if (needsEnhance) break;
        }
        if (needsEnhance) {
          this.enhanceAll();
        }
      });

      const body = document.body || document.documentElement;
      if (body) {
        this._observer.observe(body, { childList: true, subtree: true });
      }
    },

    /* =========================================================================
       1. EMBER TABLES (.table-container > .ember-table-tables-container)
       ========================================================================= */
    enhanceEmberTable(container) {
      if (!container) return;
      
      const tablesContainer = container.querySelector('.ember-table-tables-container');
      const headerRow = container.querySelector('.ember-table-header-row');
      if (!tablesContainer || !headerRow) return;

      const headerCells = headerRow.querySelectorAll('.ember-table-header-cell');
      headerCells.forEach((cell, colIdx) => {
        // Skip selection checkbox cell
        if (cell.classList.contains('rowselection-cell') || cell.querySelector('input[type="checkbox"]')) {
          return;
        }

        // Add sortable styling hook
        cell.classList.add('sortable');

        // Attach resizer handle if not present
        if (!cell.querySelector('.alp-col-resizer')) {
          const resizer = document.createElement('div');
          resizer.className = 'alp-col-resizer';
          resizer.title = 'Drag to resize column';
          resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.startResize(e, cell, colIdx, 'ember', container);
          });
          cell.appendChild(resizer);
        }

        // Attach sorting listener if not present
        if (!cell._alpSortBound) {
          cell._alpSortBound = true;
          cell.addEventListener('click', (e) => {
            if (e.target.closest('.alp-col-resizer') || e.target.closest('input')) return;
            this.sortEmberTable(container, cell, colIdx);
          });
        }
      });
    },

    sortEmberTable(container, headerCell, colIdx) {
      const headerRow = container.querySelector('.ember-table-header-row');
      const bodyContainer = container.querySelector('.ember-table-body-container .lazy-list-container, .ember-table-body-container .ember-table-table-block');
      if (!headerRow || !bodyContainer) return;

      // Determine next sort direction
      const current = this.sortStates.get(container) || { colIndex: -1, dir: 'none' };
      let newDir = 'asc';
      if (current.colIndex === colIdx) {
        newDir = current.dir === 'asc' ? 'desc' : 'asc';
      }
      this.sortStates.set(container, { colIndex: colIdx, dir: newDir });

      // Update header visual indicators
      headerRow.querySelectorAll('.ember-table-header-cell').forEach(c => {
        c.classList.remove('active-sort', 'ember-table-column-sort-asc-indicator', 'ember-table-column-sort-desc-indicator');
        const arrow = c.querySelector('.alp-sort-arrow');
        if (arrow) arrow.remove();
      });

      headerCell.classList.add('active-sort', `ember-table-column-sort-${newDir}-indicator`);
      const arrowSpan = document.createElement('span');
      arrowSpan.className = 'alp-sort-arrow';
      arrowSpan.textContent = newDir === 'asc' ? '↑' : '↓';
      
      const contentContainer = headerCell.querySelector('.ember-table-content') || headerCell;
      contentContainer.appendChild(arrowSpan);

      // Get all table rows
      const rows = Array.from(bodyContainer.querySelectorAll('.ember-table-table-row'));
      if (rows.length <= 1) return;

      // Sort rows
      rows.sort((rowA, rowB) => {
        const cellA = rowA.querySelectorAll('.ember-table-cell')[colIdx];
        const cellB = rowB.querySelectorAll('.ember-table-cell')[colIdx];
        const textA = cellA ? cellA.textContent.trim() : '';
        const textB = cellB ? cellB.textContent.trim() : '';

        return this.compareValues(textA, textB, newDir);
      });

      // Re-position rows with authentic ManageEngine 42px row-height layout
      rows.forEach((row, idx) => {
        row.style.top = (idx * 42) + 'px';
        row.classList.remove('ember-even-row', 'ember-odd-row');
        row.classList.add(idx % 2 === 0 ? 'ember-even-row' : 'ember-odd-row');
        
        // Highlight active sorted column cells subtly
        const cells = row.querySelectorAll('.ember-table-cell');
        cells.forEach((c, cIdx) => {
          c.classList.toggle('sortedColumn', cIdx === colIdx);
        });

        bodyContainer.appendChild(row);
      });
    },

    /* =========================================================================
       2. STANDARD HTML TABLES (table.me-table, table.me-authentic-table)
       ========================================================================= */
    enhanceStandardTable(table) {
      if (!table) return;

      // Ensure wrapped in a horizontally scrolling container
      if (!table.parentElement.classList.contains('tw') && !table.parentElement.classList.contains('table-responsive') && !table.parentElement.classList.contains('alp-table-scroll')) {
        const wrapper = document.createElement('div');
        wrapper.className = 'alp-table-scroll tw';
        wrapper.style.overflowX = 'auto';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);
      }

      const thead = table.querySelector('thead');
      if (!thead) return;
      const ths = thead.querySelectorAll('th');

      ths.forEach((th, colIdx) => {
        // Skip selection checkbox column
        if (th.querySelector('input[type="checkbox"]')) return;

        th.classList.add('sortable');

        // Add resizer handle if not present
        if (!th.querySelector('.alp-col-resizer')) {
          const resizer = document.createElement('div');
          resizer.className = 'alp-col-resizer';
          resizer.title = 'Drag to resize column';
          resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.startResize(e, th, colIdx, 'standard', table);
          });
          th.appendChild(resizer);
        }

        // Add sorting handler if not present
        if (!th._alpSortBound) {
          th._alpSortBound = true;
          th.addEventListener('click', (e) => {
            if (e.target.closest('.alp-col-resizer') || e.target.closest('input')) return;
            this.sortStandardTable(table, th, colIdx);
          });
        }
      });
    },

    sortStandardTable(table, th, colIdx) {
      const tbody = table.querySelector('tbody');
      if (!tbody) return;

      const current = this.sortStates.get(table) || { colIndex: -1, dir: 'none' };
      let newDir = 'asc';
      if (current.colIndex === colIdx) {
        newDir = current.dir === 'asc' ? 'desc' : 'asc';
      }
      this.sortStates.set(table, { colIndex: colIdx, dir: newDir });

      // Visual indicator update
      table.querySelectorAll('thead th').forEach(h => {
        h.classList.remove('active-sort');
        const arrow = h.querySelector('.alp-sort-arrow');
        if (arrow) arrow.remove();
      });

      th.classList.add('active-sort');
      const arrowSpan = document.createElement('span');
      arrowSpan.className = 'alp-sort-arrow';
      arrowSpan.textContent = newDir === 'asc' ? '↑' : '↓';
      th.appendChild(arrowSpan);

      const rows = Array.from(tbody.querySelectorAll('tr'));
      if (rows.length <= 1) return;

      rows.sort((rowA, rowB) => {
        const cellA = rowA.children[colIdx];
        const cellB = rowB.children[colIdx];
        const textA = cellA ? cellA.textContent.trim() : '';
        const textB = cellB ? cellB.textContent.trim() : '';

        return this.compareValues(textA, textB, newDir);
      });

      rows.forEach(r => tbody.appendChild(r));
    },

    /* =========================================================================
       3. COLUMN RESIZING DRAG LOGIC
       ========================================================================= */
    startResize(e, cell, colIdx, type, tableRef) {
      document.body.classList.add('alp-resizing');
      const resizer = cell.querySelector('.alp-col-resizer');
      if (resizer) resizer.classList.add('is-resizing');

      this.resizingState = {
        cell,
        colIdx,
        type,
        tableRef,
        startX: e.clientX,
        startWidth: cell.getBoundingClientRect().width,
        resizer
      };
    },

    onMouseMove(e) {
      if (!this.resizingState) return;
      const { cell, colIdx, type, tableRef, startX, startWidth } = this.resizingState;
      const delta = e.clientX - startX;
      const newWidth = Math.max(50, Math.round(startWidth + delta));

      if (type === 'ember') {
        // 1. Update header cell width
        cell.style.width = newWidth + 'px';
        cell.style.minWidth = newWidth + 'px';

        // 2. Update all corresponding body cells
        const bodyRows = tableRef.querySelectorAll('.ember-table-body-container .ember-table-table-row');
        bodyRows.forEach(row => {
          const bodyCells = row.querySelectorAll('.ember-table-cell');
          const targetCell = bodyCells[colIdx];
          if (targetCell) {
            targetCell.style.width = newWidth + 'px';
            targetCell.style.minWidth = newWidth + 'px';
          }
        });
      } else if (type === 'standard') {
        cell.style.width = newWidth + 'px';
        cell.style.minWidth = newWidth + 'px';
        const tbodyRows = tableRef.querySelectorAll('tbody tr');
        tbodyRows.forEach(row => {
          const td = row.children[colIdx];
          if (td) {
            td.style.width = newWidth + 'px';
            td.style.minWidth = newWidth + 'px';
          }
        });
      }
    },

    onMouseUp() {
      if (!this.resizingState) return;
      document.body.classList.remove('alp-resizing');
      if (this.resizingState.resizer) {
        this.resizingState.resizer.classList.remove('is-resizing');
      }
      this.resizingState = null;
    },

    /* =========================================================================
       4. SMART VALUE COMPARISON
       ========================================================================= */
    compareValues(valA, valB, dir) {
      if (valA === valB) return 0;
      if (!valA && valB) return 1;
      if (valA && !valB) return -1;

      // Extract raw numbers if formatted
      const numA = Number(valA.replace(/[^0-9.-]+/g, ''));
      const numB = Number(valB.replace(/[^0-9.-]+/g, ''));
      const isPureNumA = /^-?\d+(\.\d+)?$/.test(valA.trim());
      const isPureNumB = /^-?\d+(\.\d+)?$/.test(valB.trim());

      let comparison = 0;
      if (isPureNumA && isPureNumB) {
        comparison = numA - numB;
      } else {
        // Check if dates
        const dateA = Date.parse(valA);
        const dateB = Date.parse(valB);
        if (!isNaN(dateA) && !isNaN(dateB) && valA.length > 5 && (valA.includes('/') || valA.includes('-') || valA.includes(','))) {
          comparison = dateA - dateB;
        } else {
          // Standard text comparison
          comparison = valA.localeCompare(valB, undefined, { numeric: true, sensitivity: 'base' });
        }
      }

      return dir === 'asc' ? comparison : -comparison;
    }
  };

  // Auto-init on DOM readiness
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => AlpTableEngine.init());
  } else {
    AlpTableEngine.init();
  }

  window.AlpTableEngine = AlpTableEngine;
})(window);
