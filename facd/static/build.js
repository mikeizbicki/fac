// build.js
//
// This component handles build-related functionality for the targets tree.
// - Build button (🔨) for targets and paths
// - Edit button (✏️) for text files with inline editing
// - Delete button (🗑️) for paths
// - Target build menu with optional prompt textarea

(function() {
    function buildTarget(path, prompt) {
        const params = new URLSearchParams();
        params.append('target', path);
        if (prompt && prompt.trim()) {
            params.append('include_prompt', prompt.trim());
        }

        fetch('/add_target?' + params.toString(), {
            method: 'POST'
        })
        .then(response => {
            if (!response.ok) throw new Error('Failed to queue build');
            return response.json();
        })
        .catch(error => {
            console.error('Error queuing build:', error);
            alert('Failed to queue build: ' + error.message);
        });
    }

    function addHeaderMenu(nodeEl) {
        const header = nodeEl.querySelector('.tree-header');
        if (!header) return;

        const menu = document.createElement('div');
        menu.className = 'header-menu';

        const path = nodeEl.dataset.path;
        const isTarget = nodeEl.dataset.isTarget === 'true';
        const mimeType = nodeEl.dataset.mimeType || '';
        const isTextFile = mimeType.startsWith('text/');

        // Build button
        const buildBtn = document.createElement('button');
        buildBtn.innerHTML = '🔨';
        buildBtn.title = 'Build';
        buildBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            buildTarget(path, '');
        });
        menu.appendChild(buildBtn);

        if (!isTarget) {
            // Edit button for text files
            if (isTextFile) {
                const editBtn = document.createElement('button');
                editBtn.innerHTML = '✏️';
                editBtn.title = 'Edit';
                editBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    startEditing(nodeEl);
                });
                menu.appendChild(editBtn);
            }

            // Delete button
            const deleteBtn = document.createElement('button');
            deleteBtn.innerHTML = '🗑️';
            deleteBtn.title = 'Delete';
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteFile(path);
            });
            menu.appendChild(deleteBtn);
        }

        header.appendChild(menu);
    }

    function addTargetBuildMenu(nodeEl) {
        const path = nodeEl.dataset.path;

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
            buildTarget(path, textarea.value);
        });
        buildMenu.appendChild(submitBtn);

        nodeEl.appendChild(buildMenu);
    }

    function startEditing(nodeEl) {
        const contentWrapper = nodeEl.querySelector('.content-wrapper');
        const contentDiv = contentWrapper?.querySelector('.content');
        if (!contentDiv) return;

        const path = nodeEl.dataset.path;
        const originalContent = nodeEl.dataset.content || '';

        const textarea = document.createElement('textarea');
        textarea.className = 'content-editor';
        textarea.value = originalContent;

        const actions = document.createElement('div');
        actions.className = 'content-actions';

        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'cancel-btn';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            textarea.remove();
            actions.remove();
            contentDiv.style.display = 'block';
        });

        const submitBtn = document.createElement('button');
        submitBtn.className = 'submit-btn';
        submitBtn.textContent = 'Submit';
        submitBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            submitEdit(path, textarea.value, contentWrapper, textarea, actions);
        });

        actions.appendChild(cancelBtn);
        actions.appendChild(submitBtn);

        contentDiv.style.display = 'none';
        contentWrapper.appendChild(textarea);
        contentWrapper.appendChild(actions);
        textarea.focus();
    }

    function submitEdit(path, newContent, contentWrapper, textarea, actions) {
        textarea.disabled = true;
        actions.style.display = 'none';

        const overlay = document.createElement('div');
        overlay.className = 'submitting-overlay';
        const spinner = document.createElement('div');
        spinner.className = 'status-spinner';
        overlay.appendChild(spinner);
        contentWrapper.appendChild(overlay);

        fetch(`/edit_file/${encodeURIComponent(path)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: newContent })
        })
        .then(response => {
            if (!response.ok) throw new Error('Failed to edit file');
            return response.json();
        })
        .catch(error => {
            console.error('Error editing file:', error);
            overlay.remove();
            textarea.disabled = false;
            actions.style.display = 'flex';
            alert('Failed to edit file: ' + error.message);
        });
    }

    function deleteFile(path) {
        if (!confirm(`Are you sure you want to delete "${path}"?`)) return;

        fetch(`/delete_file/${encodeURIComponent(path)}`, { method: 'DELETE' })
        .then(response => {
            if (!response.ok) throw new Error('Failed to delete file');
            return response.json();
        })
        .catch(error => {
            console.error('Error deleting file:', error);
            alert('Failed to delete file: ' + error.message);
        });
    }

    window.registerComponent(function(nodeEl, status, isNew) {
        if (!isNew) return;

        const isTarget = nodeEl.dataset.isTarget === 'true';
        const isPath = nodeEl.classList.contains('path');

        if (isTarget || isPath) {
            addHeaderMenu(nodeEl);
        }

        if (isTarget) {
            addTargetBuildMenu(nodeEl);
        }
    });
})();
