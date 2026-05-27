// This component manages status overlays on tree nodes.
// - fresh: shows a flash overlay ("new" or "modified") that fades after 1s
// - deleted: shows a red flash overlay
// - stale/building/queued: shows a persistent gray overlay with status text
//   and a spinner for building/queued states

(function() {
    function createOverlay(status, isNew) {
        const overlay = document.createElement('div');
        overlay.className = 'status-overlay';

        const textSpan = document.createElement('span');
        textSpan.className = 'status-overlay-text';

        if (status === 'fresh') {
            overlay.classList.add('flash-overlay');
            textSpan.textContent = isNew ? 'new' : 'modified';
        } else if (status === 'deleted') {
            overlay.classList.add('flash-overlay', 'deleted');
            textSpan.textContent = 'deleted';
        } else if (status === 'stale' || status === 'building' || status === 'queued') {
            overlay.classList.add('persistent-overlay');
            textSpan.textContent = status;

            if (status === 'building' || status === 'queued') {
                const spinner = document.createElement('div');
                spinner.className = 'status-spinner';
                overlay.appendChild(textSpan);
                overlay.appendChild(spinner);
                return overlay;
            }
        }

        overlay.appendChild(textSpan);
        return overlay;
    }

    function removeExistingOverlay(nodeEl) {
        const existing = nodeEl.querySelector('.status-overlay');
        if (existing) existing.remove();
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (isNew) {
            // Initial render - only show overlay for non-fresh statuses
            if (status && status !== 'fresh') {
                const overlay = createOverlay(status, false);
                nodeEl.appendChild(overlay);
            }
        } else {
            // Status change
            removeExistingOverlay(nodeEl);

            if (status === 'deleted' || status === 'fresh' ||
                status === 'stale' || status === 'building' || status === 'queued') {
                const overlay = createOverlay(status, isNew);
                nodeEl.appendChild(overlay);

                if (status === 'fresh') {
                    setTimeout(() => overlay.remove(), 1000);
                }
            }
        }
    });
    // =====================================================================
    // Unified state-agnostic overlay handler (v2).
    //
    // Runs after any older handlers in this IIFE and strips their legacy
    // overlay elements so it has the final say on what overlay is attached
    // to each node. A single .node-status-overlay element is used, whose
    // appearance is driven by the [data-status] attribute on the parent
    // .tree-node (see overlay.css). On every status change the 1s flash
    // animation is re-triggered by toggling .status-flash with a forced
    // reflow in between so rapid (<100ms) transitions are still visible.
    // =====================================================================
    function _stripLegacyOverlays(nodeEl) {
        nodeEl.querySelectorAll(
            ':scope > .status-overlay, ' +
            ':scope > .flash-overlay, ' +
            ':scope > .persistent-overlay'
        ).forEach(el => el.remove());
    }
    function _ensureNodeOverlay(nodeEl) {
        let overlay = nodeEl.querySelector(':scope > .node-status-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'node-status-overlay';
            const text = document.createElement('span');
            text.className = 'node-status-overlay-text';
            overlay.appendChild(text);
            nodeEl.appendChild(overlay);
        }
        return overlay;
    }
    function _removeNodeOverlay(nodeEl) {
        const ov = nodeEl.querySelector(':scope > .node-status-overlay');
        if (ov) ov.remove();
    }
    function _isMeaningfulStatus(status) {
        // Placeholder statuses set by nodes.js when no backend status
        // is yet known. We don't flash an overlay for these.
        if (!status) return false;
        if (status === 'unknown') return false;
        if (status === 'target') return false;
        return true;
    }
    window.registerComponent(function(nodeEl, status, isNew) {
        if (!nodeEl || !nodeEl.classList || !nodeEl.classList.contains('tree-node')) {
            return;
        }
        // Status overlays are meaningful only for leaf path nodes.
        const isTarget = nodeEl.dataset.isTarget === 'true';
        const isIntermediate = nodeEl.classList.contains('intermediate');
        _stripLegacyOverlays(nodeEl);
        if (isTarget || isIntermediate) {
            _removeNodeOverlay(nodeEl);
            return;
        }
        if (!_isMeaningfulStatus(status)) {
            // Leave any existing overlay alone but don't flash.
            return;
        }
        nodeEl.dataset.status = status;
        const overlay = _ensureNodeOverlay(nodeEl);
        const textEl = overlay.querySelector('.node-status-overlay-text');
        if (textEl) textEl.textContent = status;
        // Re-trigger the flash animation. Removing and re-adding the
        // class alone is not enough; we must force a reflow between
        // the two operations so the browser restarts the animation.
        overlay.classList.remove('status-flash');
        void overlay.offsetWidth;
        overlay.classList.add('status-flash');
    });
})();
