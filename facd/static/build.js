// build.js
//
// This component handles build-related functionality for the targets tree.
// It provides:
// - Build button (🔨) in the header menu for both targets and paths
// - Edit button (✏️) for text files to enable inline editing
// - Delete button (🗑️) for paths to remove files
// - Target build menu with optional prompt textarea
//
// File editing:
// - Text files can be edited inline by clicking the edit button
// - Shows a textarea with submit/cancel buttons
// - Submitting shows a spinner overlay until the file update is confirmed
//
// This component registers with targets.js via window.registerTargetsComponent()

(function() {
    function createBuildButton(path) {
        const btn = document.createElement('button');
        btn.innerHTML = '🔨';
        btn.title = 'Build';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            window.buildTarget(path, '');
        });
        return btn;
    }

    function createEditButton(path, metadata) {
        const btn = document.createElement('button');
        btn.innerHTML = '✏️';
        btn.title = 'Edit';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const nodeEl = window.getNodeElement(path);
            if (nodeEl) {
                const contentWrapper = nodeEl.querySelector('.content-wrapper');
                if (contentWrapper) {
                    startEditing(path, contentWrapper, metadata.content);
                }
            }
        });
        return btn;
    }

    function createDeleteButton(path) {
        const btn = document.createElement('button');
        btn.innerHTML = '🗑️';
        btn.title = 'Delete';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteFile(path);
        });
        return btn;
    }

    function startEditing(path, contentWrapper, originalContent) {
        const contentDiv = contentWrapper.querySelector('.content');
        if (!contentDiv) return;

        const textarea = document.createElement('textarea');
        textarea.className = 'content-editor';
        textarea.value = originalContent || '';

        const actions = document.createElement('div');
        actions.className = 'content-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            cancelEditing(contentWrapper);
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'submit-btn';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitEdit(path, textarea.value, contentWrapper);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);

        contentDiv.style.display = 'none';
        contentWrapper.appendChild(textarea);
        contentWrapper.appendChild(actions);
        textarea.focus();
    }

    function cancelEditing(contentWrapper) {
        const textarea = contentWrapper.querySelector('.content-editor');
        const actions = contentWrapper.querySelector('.content-actions');
        const contentDiv = contentWrapper.querySelector('.content');

        if (textarea) textarea.remove();
        if (actions) actions.remove();
        if (contentDiv) contentDiv.style.display = 'block';
    }

    function submitEdit(path, newContent, contentWrapper) {
        const textarea = contentWrapper.querySelector('.content-editor');
        const actions = contentWrapper.querySelector('.content-actions');

        if (textarea) textarea.disabled = true;
        if (actions) actions.style.display = 'none';

        const overlay = document.createElement('div');
        overlay.className = 'submitting-overlay';
        const spinner = document.createElement('div');
        spinner.className = 'status-spinner';
        overlay.appendChild(spinner);
        contentWrapper.appendChild(overlay);

        window.pendingEdits.add(path);

        fetch(`/edit_file/${encodeURIComponent(path)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content: newContent })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to edit file');
            }
            return response.json();
        })
        .catch(error => {
            console.error('Error editing file:', error);
            window.pendingEdits.delete(path);
            overlay.remove();
            if (textarea) textarea.disabled = false;
            if (actions) actions.style.display = 'flex';
            alert('Failed to edit file: ' + error.message);
        });
    }

    function deleteFile(path) {
        if (!confirm(`Are you sure you want to delete "${path}"?`)) {
            return;
        }

        fetch(`/delete_file/${encodeURIComponent(path)}`, {
            method: 'DELETE'
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to delete file');
            }
            return response.json();
        })
        .catch(error => {
            console.error('Error deleting file:', error);
            alert('Failed to delete file: ' + error.message);
        });
    }

    function createTargetBuildMenu(fullPath) {
        const buildMenu = document.createElement('div');
        buildMenu.className = 'target-build-menu';

        const textarea = document.createElement('textarea');
        textarea.className = 'build-prompt-input';
        textarea.placeholder = 'Enter build prompt (optional)...';
        buildMenu.appendChild(textarea);

        const submitBtn = document.createElement('button');
        submitBtn.className = 'build-submit-btn';
        submitBtn.textContent = 'Build';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            window.buildTarget(fullPath, textarea.value);
        });
        buildMenu.appendChild(submitBtn);

        return buildMenu;
    }

    // Register the build component
    window.registerTargetsComponent({
        name: 'build',

        renderHeaderButtons: function(ctx) {
            const buttons = [];
            const { path, isTarget, mimeType, metadata } = ctx;

            // Build button for both targets and paths
            buttons.push(createBuildButton(path));

            if (!isTarget && metadata) {
                const isTextFile = mimeType && mimeType.startsWith('text/');

                // Edit button for text files
                if (isTextFile) {
                    buttons.push(createEditButton(path, metadata));
                }

                // Delete button for all paths
                buttons.push(createDeleteButton(path));
            }

            return buttons;
        },

        renderNodeContent: function(ctx) {
            const { isTarget, path } = ctx;

            // Add build menu only for targets
            if (isTarget) {
                return createTargetBuildMenu(path);
            }

            return null;
        },

        onStatusChange: function(ctx) {
            // Currently no special handling needed
        }
    });
})();
