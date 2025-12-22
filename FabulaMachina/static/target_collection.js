
// Updated target_collection.js with better element finding
document.addEventListener('DOMContentLoaded', function() {
    console.log('target_collection.js DOMContentLoaded executing');

    function waitForJSONEditor(callback, maxAttempts = 50) {
        let attempts = 0;
        const checkInterval = setInterval(() => {
            attempts++;
            console.log(`Checking for JSONEditor, attempt ${attempts}`);

            if (typeof JSONEditor !== 'undefined') {
                console.log('JSONEditor is available!');
                clearInterval(checkInterval);
                callback();
            } else if (attempts >= maxAttempts) {
                console.error('JSONEditor failed to load after', maxAttempts, 'attempts');
                clearInterval(checkInterval);
                document.querySelectorAll('.json-editor-container').forEach(container => {
                    container.innerHTML = `
                        <div style="padding: 20px; background: #ffeeee; border: 1px solid #ff0000;">
                            <strong>Error:</strong> JSONEditor failed to load from CDN.
                        </div>
                    `;
                });
            }
        }, 100);
    }

    const container = document.getElementById('item-container');
    if (!container) {
        console.error('item-container not found');
        return;
    }

    const collectionName = container.dataset.collectionName;
    const itemName = container.dataset.itemName;

    console.log('Target collection page loaded:', { collectionName, itemName });

    waitForJSONEditor(() => {
        initializeJSONEditors();
    });

    function initializeJSONEditors() {
        const jsonSections = document.querySelectorAll('.json-section');
        console.log('Found JSON sections:', jsonSections.length);

        const jsonEditors = {};

        jsonSections.forEach((section, index) => {
            console.log('Processing JSON section:', index, section);

            const filename = section.dataset.filename;
            // Try multiple ways to find the editor container
            let editorContainer = section.querySelector(`#json-editor-${index + 1}`);
            if (!editorContainer) {
                editorContainer = section.querySelector('.json-editor-container');
            }
            const jsonDataElement = section.querySelector('.json-data');

            console.log('Section details:', {
                filename,
                hasEditorContainer: !!editorContainer,
                hasJsonData: !!jsonDataElement,
                editorContainerId: editorContainer?.id || 'no-id',
                editorContainerClass: editorContainer?.className || 'no-class'
            });

            if (!editorContainer) {
                console.error('No editor container found for section', index);
                console.log('Available elements in section:', section.innerHTML);
                return;
            }

            if (!jsonDataElement) {
                console.error('No JSON data element found for section', index);
                return;
            }

            try {
                const rawData = jsonDataElement.textContent.trim();
                console.log('Raw JSON for', filename, ':', rawData.substring(0, 200) + '...');

                if (!rawData) {
                    throw new Error('No JSON data found');
                }

                const jsonData = JSON.parse(rawData);
                console.log('Parsed JSON data for', filename, ':', jsonData);

                // Clear the container
                editorContainer.innerHTML = '';

                const options = {
                    mode: 'form',
                    modes: ['form', 'tree', 'code', 'text'],
                    onChange: function() {
                        console.log('Editor changed for', filename);
                    },
                    onError: function(error) {
                        console.error('JSONEditor error for', filename, ':', error);
                    }
                };

                console.log('Creating JSONEditor for', filename);
                const editor = new JSONEditor(editorContainer, options);

                console.log('Setting data in editor for', filename);
                editor.set(jsonData);

                // Add save button
                const saveButton = document.createElement('button');
                saveButton.textContent = 'Save';
                saveButton.className = 'save-button';
                saveButton.style.marginTop = '10px';
                saveButton.addEventListener('click', () => saveJSON(filename, editor));

                section.appendChild(saveButton);

                jsonEditors[filename] = editor;
                console.log('Successfully created editor for', filename);

            } catch (error) {
                console.error('Error creating JSON editor for', filename, ':', error);
                editorContainer.innerHTML = `
                    <div style="padding: 15px; background: #ffeeee; border: 1px solid #ff0000; margin: 10px 0; border-radius: 4px;">
                        <strong>JSON Editor Error:</strong> ${error.message}
                        <details style="margin-top: 10px;">
                            <summary>Raw JSON Data</summary>
                            <pre style="background: #f5f5f5; padding: 10px; margin-top: 5px; font-size: 11px; overflow: auto; max-height: 200px;">${jsonDataElement.textContent}</pre>
                        </details>
                    </div>
                `;
            }
        });
    }

    function saveJSON(filename, editor) {
        try {
            const data = editor.get();
            const content = JSON.stringify(data, null, 2);

            fetch(`/${collectionName}/${itemName}/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: filename,
                    content: content
                })
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    console.log('Saved successfully:', filename);
                    showMessage('Saved successfully!', 'success');
                } else {
                    throw new Error(result.error || 'Save failed');
                }
            })
            .catch(error => {
                console.error('Save error:', error);
                showMessage('Save failed: ' + error.message, 'error');
            });
        } catch (error) {
            console.error('Error getting JSON from editor:', error);
            showMessage('Invalid JSON: ' + error.message, 'error');
        }
    }

    function showMessage(message, type) {
        const messageDiv = document.createElement('div');
        messageDiv.textContent = message;
        messageDiv.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 10000;
            padding: 10px 20px; border-radius: 4px; color: white;
            background: ${type === 'success' ? '#28a745' : '#dc3545'};
        `;
        document.body.appendChild(messageDiv);

        setTimeout(() => {
            messageDiv.remove();
        }, 3000);
    }
});

document.addEventListener('DOMContentLoaded', function() {
    console.log('target_collection.js DOMContentLoaded executing');

    const container = document.getElementById('item-container');
    if (!container) {
        console.error('item-container not found');
        return;
    }

    const collectionName = container.dataset.collectionName;
    const itemName = container.dataset.itemName;

    console.log('Target collection page loaded:', { collectionName, itemName });

    // Initialize text editing for all text sections
    const textSections = document.querySelectorAll('.text-section');
    console.log('Found text sections:', textSections.length);

    textSections.forEach(section => {
        setupTextEditor(section);
    });

    function setupTextEditor(section) {
        const textContent = section.querySelector('.text-content');
        const textDisplay = section.querySelector('.text-display');
        const textEdit = section.querySelector('.text-edit');
        const textarea = section.querySelector('.text-textarea');
        const saveButton = section.querySelector('.save-button');
        const cancelButton = section.querySelector('.cancel-button');
        const editBtn = section.querySelector('.edit-btn');
        const filename = section.dataset.filename;

        if (!textDisplay || !textEdit || !textarea || !saveButton || !cancelButton || !editBtn) {
            console.error('Missing elements in text section for', filename);
            return;
        }

        // Double-click to edit
        textDisplay.addEventListener('dblclick', function() {
            enterEditMode();
        });

        // Edit button click
        editBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            enterEditMode();
        });

        // Cancel button
        cancelButton.addEventListener('click', function() {
            exitEditMode();
        });

        // Save button
        saveButton.addEventListener('click', function() {
            saveText();
        });

        // Escape key to cancel
        textarea.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                exitEditMode();
            }
        });

        function enterEditMode() {
            // Set textarea content to current display content
            textarea.value = textDisplay.textContent;

            // Switch visibility
            textContent.style.display = 'none';
            textEdit.style.display = 'block';

            // Focus textarea
            textarea.focus();
        }

        function exitEditMode() {
            // Switch visibility back
            textContent.style.display = 'block';
            textEdit.style.display = 'none';
        }

        function saveText() {
            const content = textarea.value;

            // Validate JSON if it's a JSON file
            if (filename.endsWith('.json')) {
                try {
                    JSON.parse(content);
                } catch (error) {
                    showMessage('Invalid JSON: ' + error.message, 'error');
                    return;
                }
            }

            fetch(`/${collectionName}/${itemName}/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filename: filename,
                    content: content
                })
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    // Update display with new content
                    textDisplay.textContent = content;
                    exitEditMode();
                    showMessage('Saved successfully!', 'success');
                } else {
                    throw new Error(result.error || 'Save failed');
                }
            })
            .catch(error => {
                console.error('Save error:', error);
                showMessage('Save failed: ' + error.message, 'error');
            });
        }
    }

    function showMessage(message, type) {
        const messageDiv = document.createElement('div');
        messageDiv.textContent = message;
        messageDiv.style.cssText = `
            position: fixed; top: 20px; right: 20px; z-index: 10000;
            padding: 10px 20px; border-radius: 4px; color: white;
            background: ${type === 'success' ? '#28a745' : '#dc3545'};
            font-family: 'Courier New', monospace;
        `;
        document.body.appendChild(messageDiv);

        setTimeout(() => {
            messageDiv.remove();
        }, 3000);
    }
});
