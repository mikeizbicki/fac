// build.js
//
// This component adds a build action menu to each leaf node in the target tree.
// It provides buttons for: build, build with prompt, edit, and delete.
// Edit and delete are only available for path nodes.
// For target nodes, a form is displayed to specify variables used in the target.
// Build actions call the /add_target endpoint with appropriate parameters.

function extractVariables(targetName) {
    const regex = /\$([A-Z_][A-Z0-9_]*)/g;
    const variables = [];
    let match;
    while ((match = regex.exec(targetName)) !== null) {
        if (!variables.includes(match[1])) {
            variables.push(match[1]);
        }
    }
    return variables;
}

function createBuildMenu(node, fullPath, isTarget) {
    const menu = document.createElement('div');
    menu.className = 'build-menu';

    const actions = document.createElement('div');
    actions.className = 'build-actions';

    // Build button
    const buildBtn = document.createElement('button');
    buildBtn.className = 'build-btn build';
    buildBtn.textContent = 'Build';
    buildBtn.addEventListener('click', () => handleBuild(menu, fullPath, isTarget, false));
    actions.appendChild(buildBtn);

    // Build with prompt button
    const buildPromptBtn = document.createElement('button');
    buildPromptBtn.className = 'build-btn build-prompt';
    buildPromptBtn.textContent = 'Build with Prompt';
    buildPromptBtn.addEventListener('click', () => togglePromptInput(menu));
    actions.appendChild(buildPromptBtn);

    // Edit button (path only)
    const editBtn = document.createElement('button');
    editBtn.className = 'build-btn edit';
    editBtn.textContent = 'Edit';
    if (!isTarget) {
        editBtn.addEventListener('click', () => handleEdit(fullPath));
    } else {
        editBtn.disabled = true;
    }
    actions.appendChild(editBtn);

    // Delete button (path only)
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'build-btn delete';
    deleteBtn.textContent = 'Delete';
    if (!isTarget) {
        deleteBtn.addEventListener('click', () => handleDelete(fullPath));
    } else {
        deleteBtn.disabled = true;
    }
    actions.appendChild(deleteBtn);

    menu.appendChild(actions);

    // Variables form for targets
    if (isTarget) {
        const variables = extractVariables(fullPath);
        if (variables.length > 0) {
            const varsContainer = document.createElement('div');
            varsContainer.className = 'build-variables';

            const varsTitle = document.createElement('div');
            varsTitle.className = 'build-variables-title';
            varsTitle.textContent = 'Variables';
            varsContainer.appendChild(varsTitle);

            for (const varName of variables) {
                const row = document.createElement('div');
                row.className = 'build-variable-row';

                const label = document.createElement('label');
                label.className = 'build-variable-label';
                label.textContent = '$' + varName;
                row.appendChild(label);

                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'build-variable-input';
                input.dataset.variable = varName;
                input.placeholder = 'Enter value...';
                row.appendChild(input);

                varsContainer.appendChild(row);
            }

            menu.appendChild(varsContainer);
        }
    }

    // Prompt input container
    const promptContainer = document.createElement('div');
    promptContainer.className = 'build-prompt-container';

    const promptLabel = document.createElement('div');
    promptLabel.className = 'build-prompt-label';
    promptLabel.textContent = 'Build Prompt';
    promptContainer.appendChild(promptLabel);

    const promptInput = document.createElement('textarea');
    promptInput.className = 'build-prompt-input';
    promptInput.placeholder = 'Enter additional prompt...';
    promptContainer.appendChild(promptInput);

    const submitPromptBtn = document.createElement('button');
    submitPromptBtn.className = 'build-btn build-prompt';
    submitPromptBtn.textContent = 'Submit';
    submitPromptBtn.style.marginTop = '8px';
    submitPromptBtn.addEventListener('click', () => handleBuild(menu, fullPath, isTarget, true));
    promptContainer.appendChild(submitPromptBtn);

    menu.appendChild(promptContainer);

    // Status message area
    const status = document.createElement('div');
    status.className = 'build-status';
    menu.appendChild(status);

    return menu;
}

function togglePromptInput(menu) {
    const promptContainer = menu.querySelector('.build-prompt-container');
    promptContainer.classList.toggle('visible');
}

function resolveTargetPath(menu, targetPath) {
    const variables = extractVariables(targetPath);
    let resolvedPath = targetPath;

    for (const varName of variables) {
        const input = menu.querySelector(`input[data-variable="${varName}"]`);
        if (input && input.value) {
            resolvedPath = resolvedPath.replace(new RegExp('\\$' + varName, 'g'), input.value);
        }
    }

    return resolvedPath;
}

function handleBuild(menu, fullPath, isTarget, withPrompt) {
    const status = menu.querySelector('.build-status');
    status.textContent = 'Building...';
    status.className = 'build-status';

    let targetToUse = fullPath;

    // For targets, resolve any variable values
    if (isTarget) {
        targetToUse = resolveTargetPath(menu, fullPath);
    }

    const params = new URLSearchParams();
    params.append('target', targetToUse);

    if (withPrompt) {
        const promptInput = menu.querySelector('.build-prompt-input');
        if (promptInput && promptInput.value) {
            params.append('include_prompt', promptInput.value);
        }
    }

    fetch('/add_target?' + params.toString(), {
        method: 'POST'
    })
    .then(response => {
        if (response.ok) {
            return response.json();
        }
        throw new Error('Build request failed');
    })
    .then(data => {
        status.textContent = 'Build request submitted successfully';
        status.className = 'build-status success';
    })
    .catch(error => {
        status.textContent = 'Error: ' + error.message;
        status.className = 'build-status error';
    });
}

function handleEdit(path) {
    alert('Edit feature is not yet implemented.\n\nPath: ' + path);
}

function handleDelete(path) {
    alert('Delete feature is not yet implemented.\n\nPath: ' + path);
}

// Export function for use by targets.js
window.createBuildMenu = createBuildMenu;
