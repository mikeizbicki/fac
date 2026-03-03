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
})();
