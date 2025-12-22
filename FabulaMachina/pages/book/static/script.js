document.addEventListener('DOMContentLoaded', function() {
    const frames = document.querySelectorAll('.frame');
    const container = document.getElementById('book-container');
    const level = container.dataset.level;
    const book = container.dataset.book;

    assignFrameColors();
    setTimeout(drawReferenceArrows, 100); // Small delay to ensure layout is complete

    function adjustFrameHeights() {
        frames.forEach(frame => {
            const frameMargin = frame.querySelector('.frame-margin');
            const marginHeight = frameMargin.offsetHeight;
            const currentMinHeight = parseInt(getComputedStyle(frame).minHeight) || 0;

            if (marginHeight > currentMinHeight) {
                frame.style.minHeight = (marginHeight + 20) + 'px';
            }
        });
    }

    function loadFrameJson(frame, textarea) {
        const frameId = frame.dataset.frameId;
        fetch(`/books/${level}/${book}/get_frame_json/${frameId}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    textarea.value = JSON.stringify(data.frame_data, null, 2);
                    textarea.dataset.loaded = 'true';
                }
            })
            .catch(console.error);
    }

    function deleteFrame(frameId, frameElement) {
        fetch(`/books/${level}/${book}/delete_frame`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frame_id: frameId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) frameElement.remove();
            else alert('Error deleting: ' + data.error);
        });
    }

    function addNewFrame(afterFrame) {
        const newId = 'frame_' + Date.now();
        fetch(`/books/${level}/${book}/add_frame`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ frame_id: newId, after_frame: afterFrame.dataset.frameId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) location.reload();
            else alert('Error adding: ' + data.error);
        });
    }

    function mergeWithNext(frame) {
        const nextFrame = frame.nextElementSibling;
        if (!nextFrame || !nextFrame.classList.contains('frame')) {
            alert('No next frame to merge with');
            return;
        }

        if (confirm('Merge this frame with the next one?')) {
            fetch(`/books/${level}/${book}/merge_frames`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    frame_id: frame.dataset.frameId,
                    next_frame_id: nextFrame.dataset.frameId
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) location.reload();
                else alert('Error merging: ' + data.error);
            });
        }
    }

    function exitEditMode(frame) {
        const frameContent = frame.querySelector('.frame-content');
        const frameEdit = frame.querySelector('.frame-edit');
        const frameControls = frame.querySelector('.frame-controls');

        frameContent.style.display = 'block';
        frameEdit.style.display = 'none';
        frameControls.style.display = ''; // Reset to default (CSS will handle hover)
    }

    function enterEditMode(frame) {
        const frameContent = frame.querySelector('.frame-content');
        const frameEdit = frame.querySelector('.frame-edit');
        const frameControls = frame.querySelector('.frame-controls');
        const textarea = frame.querySelector('.frame-textarea');

        // Get content from data attribute
        let content = frame.dataset.rawContent;
        if (!content) {
            content = frame.getAttribute('data-raw-content') || '';
        }

        textarea.value = content;

        // Ensure fountain tab is active and visible when entering edit mode
        const tabButtons = frame.querySelectorAll('.tab-button');
        const tabContents = frame.querySelectorAll('.tab-content');

        // Set fountain tab as active
        tabButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === 'fountain');
        });

        // Show fountain tab content, hide others
        tabContents.forEach(content => {
            if (content.id === 'fountain-tab') {
                content.style.display = 'block';
            } else {
                content.style.display = 'none';
            }
        });

        frameContent.style.display = 'none';
        frameEdit.style.display = 'block';
        frameControls.style.display = 'none';
        textarea.focus();
    }

    adjustFrameHeights();

    const fountainAutocomplete = new FountainAutocomplete();
    const characterLocationPreview = new CharacterLocationPreview();

    // Replace the existing reference_frame dropdown code with this:
    frames.forEach(frame => {
        const frameTypeContainer = frame.querySelector('.frame-type-container');
        const frameTypeValue = frame.querySelector('.frame-type-value');
        const refContainer = frame.querySelector('.reference-frame-container');
        const refValue = frame.querySelector('.reference-frame-value');
        const refDropdown = frame.querySelector('.reference-frame-dropdown');
        const imgContainer = frame.querySelector('.img-container');

        if (!frameTypeValue) return;

        const frameId = frame.dataset.frameId;
        const allFrames = Array.from(document.querySelectorAll('.frame'));
        const currentIndex = allFrames.indexOf(frame);
        const isFirstFrame = currentIndex === 0;

        // Populate reference frame dropdown with previous frames
        refDropdown.innerHTML = '<option value="">none</option>';
        for (let i = 0; i < currentIndex; i++) {
            const option = document.createElement('option');
            option.value = allFrames[i].dataset.frameId;
            option.textContent = allFrames[i].dataset.frameId;
            refDropdown.appendChild(option);
        }

        // Create frame type dropdown
        const frameTypeDropdown = document.createElement('select');
        frameTypeDropdown.className = 'frame-type-dropdown';
        frameTypeDropdown.style.display = 'none';
        frameTypeDropdown.size = 1;

        const cutOption = document.createElement('option');
        cutOption.value = 'cut';
        cutOption.textContent = 'cut';
        frameTypeDropdown.appendChild(cutOption);

        if (!isFirstFrame) {
            const continuousOption = document.createElement('option');
            continuousOption.value = 'continuous';
            continuousOption.textContent = 'continuous';
            frameTypeDropdown.appendChild(continuousOption);

            const callbackOption = document.createElement('option');
            callbackOption.value = 'callback';
            callbackOption.textContent = 'callback';
            frameTypeDropdown.appendChild(callbackOption);
        }

        frameTypeContainer.appendChild(frameTypeDropdown);

        // Function to determine frame type from reference frame
        function getFrameType(referenceFrame) {
            if (isFirstFrame) {
                return 'cut'; // First frame is always cut
            }
            
            if (!referenceFrame || referenceFrame === 'none') {
                return 'cut';
            }
            
            // Check if reference frame is the previous frame
            const previousFrame = currentIndex > 0 ? allFrames[currentIndex - 1] : null;
            if (previousFrame && previousFrame.dataset.frameId === referenceFrame) {
                return 'continuous';
            }
            
            return 'callback';
        }

        // Function to get reference frame from frame type
        function getReferenceFrameForType(frameType) {
            switch (frameType) {
                case 'cut':
                    return '';
                case 'continuous':
                    return currentIndex > 0 ? allFrames[currentIndex - 1].dataset.frameId : '';
                case 'callback':
                    return frame.dataset.referenceFrame || '';
                default:
                    return '';
            }
        }

        // Function to update UI based on frame type
        function updateUIForFrameType(frameType) {
            switch (frameType) {
                case 'cut':
                    imgContainer.style.display = 'block';
                    refContainer.style.display = 'none';
                    break;
                case 'continuous':
                    imgContainer.style.display = 'none';
                    refContainer.style.display = 'none';
                    break;
                case 'callback':
                    imgContainer.style.display = 'none';
                    refContainer.style.display = 'block';
                    break;
            }
        }

        // Initialize frame type
        const currentRefFrame = frame.dataset.referenceFrame || '';
        const currentFrameType = getFrameType(currentRefFrame);
        frameTypeValue.textContent = currentFrameType;
        frameTypeDropdown.value = currentFrameType;
        updateUIForFrameType(currentFrameType);

        // Set reference frame dropdown value
        refDropdown.value = currentRefFrame;
        refValue.textContent = currentRefFrame || 'none';
        refValue.dataset.referenceFrame = currentRefFrame;

        // Handle frame type value click (show dropdown)
        frameTypeValue.addEventListener('click', function() {
            if (isFirstFrame) return; // First frame cannot change type

            // Set the dropdown to the current frame type
            const currentDisplayedType = frameTypeValue.textContent;
            frameTypeDropdown.value = currentDisplayedType;

            // Calculate size (number of options to show)
            const optionCount = frameTypeDropdown.options.length;
            const maxSize = Math.min(optionCount, 8); // Show max 8 options
            frameTypeDropdown.size = maxSize;

            frameTypeDropdown.style.display = 'block';
            frameTypeDropdown.focus();
        });

        // Handle frame type dropdown change
        frameTypeDropdown.addEventListener('change', function() {
            const newFrameType = this.value;
            const oldFrameType = frameTypeValue.textContent;
            
            // Hide dropdown first
            this.style.display = 'none';
            this.size = 1; // Reset size
            
            // If no change, just return
            if (newFrameType === oldFrameType) {
                return;
            }
            
            let newRefFrame = getReferenceFrameForType(newFrameType);

            // Update UI immediately
            frameTypeValue.textContent = newFrameType;
            frame.dataset.referenceFrame = newRefFrame; // Update data attribute immediately
            refDropdown.value = newRefFrame;
            refValue.textContent = newRefFrame || 'none';
            refValue.dataset.referenceFrame = newRefFrame;
            updateUIForFrameType(newFrameType);
            
            // Update colors immediately
            assignFrameColors();
            setTimeout(drawReferenceArrows, 50);

            // For callback type, if no reference frame is set, show reference dropdown
            if (newFrameType === 'callback' && !newRefFrame) {
                return; // Don't commit yet, wait for reference frame selection
            }

            // Update server
            updateReferenceFrameOnServer(frameId, newRefFrame);
        });

        // Also handle click events on individual options to catch cases where change doesn't fire
        frameTypeDropdown.addEventListener('click', function(e) {
            if (e.target.tagName === 'OPTION') {
                // Small delay to let the value update
                setTimeout(() => {
                    const newFrameType = this.value;
                    const oldFrameType = frameTypeValue.textContent;
                    
                    // Hide dropdown
                    this.style.display = 'none';
                    this.size = 1;
                    
                    // If no change, just return
                    if (newFrameType === oldFrameType) {
                        return;
                    }
                    
                    let newRefFrame = getReferenceFrameForType(newFrameType);

                    // Update UI immediately
                    frameTypeValue.textContent = newFrameType;
                    frame.dataset.referenceFrame = newRefFrame; // Update data attribute immediately
                    refDropdown.value = newRefFrame;
                    refValue.textContent = newRefFrame || 'none';
                    refValue.dataset.referenceFrame = newRefFrame;
                    updateUIForFrameType(newFrameType);
                    
                    // Update colors immediately
                    assignFrameColors();
                    setTimeout(drawReferenceArrows, 50);

                    // For callback type, if no reference frame is set, show reference dropdown
                    if (newFrameType === 'callback' && !newRefFrame) {
                        return;
                    }

                    // Update server
                    updateReferenceFrameOnServer(frameId, newRefFrame);
                }, 10);
            }
        });

        frameTypeDropdown.addEventListener('blur', function() {
            this.style.display = 'none';
            this.size = 1; // Reset size
        });


        // Rest of the reference frame handling code remains the same...
        refValue.addEventListener('click', function() {
            if (frameTypeValue.textContent !== 'callback') return;
            
            refDropdown.value = this.dataset.referenceFrame;
            const optionCount = refDropdown.options.length;
            const maxSize = Math.min(optionCount, 8);
            refDropdown.size = maxSize;
            refDropdown.style.display = 'block';
            refDropdown.focus();
        });

        refDropdown.addEventListener('change', function() {
            const newRefFrame = this.value;
            refValue.innerHTML = `${newRefFrame || 'none'} <span style="color: gray;">(updating...)</span>`;
            this.style.display = 'none';
            this.size = 1;

            updateReferenceFrameOnServer(frameId, newRefFrame);
        });

        refDropdown.addEventListener('blur', function() {
            this.style.display = 'none';
            this.size = 1;
        });

        // Function to update server with new reference frame
        function updateReferenceFrameOnServer(frameId, newRefFrame) {
            fetch(`/books/${level}/${book}/update_reference_frame`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    frame_id: frameId,
                    reference_frame: newRefFrame
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Data attributes are already updated above, no need to duplicate
                    // assignFrameColors() was already called above for immediate feedback
                    console.log('Server update successful for frame', frameId);
                } else {
                    alert('Error updating: ' + data.error);
                    // Revert to previous state
                    const oldFrameType = getFrameType(refValue.dataset.referenceFrame);
                    frameTypeValue.textContent = oldFrameType;
                    frame.dataset.referenceFrame = refValue.dataset.referenceFrame;
                    updateUIForFrameType(oldFrameType);
                    assignFrameColors(); // Revert colors
                }
            })
            .catch(error => {
                console.error('Server update failed:', error);
                // Revert to previous state
                const oldFrameType = getFrameType(refValue.dataset.referenceFrame);
                frameTypeValue.textContent = oldFrameType;
                frame.dataset.referenceFrame = refValue.dataset.referenceFrame;
                updateUIForFrameType(oldFrameType);
                assignFrameColors(); // Revert colors
            });
        }
    });



    frames.forEach(frame => {
        const frameContent = frame.querySelector('.frame-content');
        const frameEdit = frame.querySelector('.frame-edit');
        const frameControls = frame.querySelector('.frame-controls');
        const textarea = frame.querySelector('.frame-textarea');
        const jsonTextarea = frame.querySelector('.frame-json-textarea');
        const runButton = frame.querySelector('.run-button');
        const cancelButton = frame.querySelector('.cancel-button');

        // Control buttons
        const editBtn = frame.querySelector('.edit-btn');
        const deleteBtn = frame.querySelector('.delete-btn');
        const addBtn = frame.querySelector('.add-btn');

        // Tab handling
        const tabButtons = frame.querySelectorAll('.tab-button');
        const tabContents = frame.querySelectorAll('.tab-content');

        tabButtons.forEach(button => {
            button.addEventListener('click', function() {
                const tabName = this.dataset.tab;

                // Update active tab
                tabButtons.forEach(btn => btn.classList.remove('active'));
                this.classList.add('active');

                // Show corresponding content
                tabContents.forEach(content => content.style.display = 'none');
                frame.querySelector(`#${tabName}-tab`).style.display = 'block';

                // Load JSON data when switching to JSON tab
                if (tabName === 'json' && !jsonTextarea.dataset.loaded) {
                    loadFrameJson(frame, jsonTextarea);
                }
            });
        });

        // Control button event listeners
        editBtn.addEventListener('click', function() {
            enterEditMode(frame);
        });

        deleteBtn.addEventListener('click', function() {
            if (confirm('Delete this frame?')) {
                deleteFrame(frame.dataset.frameId, frame);
            }
        });

        addBtn.addEventListener('click', function() {
            addNewFrame(frame);
        });

        // Escape key handler for this frame's textareas
        textarea.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                exitEditMode(frame);
            }
        });

        jsonTextarea.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                e.preventDefault();
                exitEditMode(frame);
            }
        });

        // Existing functionality

        frameContent.addEventListener('dblclick', function() {
            enterEditMode(frame);
        });

        cancelButton.addEventListener('click', function() {
            exitEditMode(frame);
        });

        // Updated save button - now saves both fountain and JSON
        runButton.addEventListener('click', function() {
            const frameId = frame.dataset.frameId;
            const fountainContent = textarea.value;
            const jsonContent = jsonTextarea.value || null;

            fetch(`/books/${level}/${book}/save_frame`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    frame_id: frameId,
                    fountain_content: fountainContent,
                    json_content: jsonContent
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    frame.dataset.rawContent = fountainContent;
                    frameContent.innerHTML = data.html;
                    jsonTextarea.dataset.loaded = 'false'; // Reset for next edit
                    exitEditMode(frame);

                    // Update reference frame data attribute if JSON was saved
                    if (jsonContent) {
                        try {
                            const jsonData = JSON.parse(jsonContent);
                            frame.dataset.referenceFrame = jsonData.reference_frame || '';
                        } catch (e) {
                            console.error('Error parsing JSON:', e);
                        }
                    }

                    // Refresh audio controls for updated content
                    if (window.audioControls) {
                        window.audioControls.refresh();
                    }
                } else {
                    alert('Error saving: ' + data.error);
                }
            })
            .catch(error => {
                alert('Error: ' + error);
            });
        });

        const img = frame.querySelector('.frame-image');
        if (img) {
            img.addEventListener('load', adjustFrameHeights);
            img.addEventListener('error', function() {
                this.classList.add('error');
                this.style.display = 'flex'; // Ensure it shows as a box
                adjustFrameHeights();
            });
        }
    });
});


function assignFrameColors() {
    const frames = document.querySelectorAll('.frame');
    const frameColors = new Map();

    // Predefined color palette for root frames (no reference)
    const colorPalette = [
        '#fff740', // Yellow
        '#ff7eb9', // Pink
        '#7afcff', // Light blue
        '#98fb98', // Light green
        '#ffd1dc', // Light pink
        '#ffa07a', // Light salmon
        '#dda0dd', // Plum
        '#f0e68c', // Khaki
        '#87ceeb', // Sky blue
        '#ffefd5'  // Papaya whip
    ];

    let colorIndex = 0;

    frames.forEach(frame => {
        const frameId = frame.dataset.frameId;
        const referenceFrame = frame.dataset.referenceFrame;
        const frameMargin = frame.querySelector('.frame-margin');

        if (!frameMargin) return;

        let color;

        if (!referenceFrame || referenceFrame === 'none' || referenceFrame === '') {
            // Root frame - assign a new color from palette
            color = colorPalette[colorIndex % colorPalette.length];
            colorIndex++;
        } else {
            // Referenced frame - inherit color from reference
            color = frameColors.get(referenceFrame);

            // Fallback if reference frame color not found
            if (!color) {
                console.warn(`Reference frame "${referenceFrame}" not found for frame "${frameId}", using default color`);
                color = '#ffffff'; // Default yellow
            }
        }

        // Store color for this frame
        frameColors.set(frameId, color);

        // Apply color directly with !important to override CSS
        frameMargin.style.setProperty('background-color', color);

        console.log(`Applied color ${color} to frame ${frameId} (ref: ${referenceFrame || 'none'})`);
    });
}

function drawReferenceArrows() {
    // Remove existing SVG
    const existingSvg = document.getElementById('arrow-svg');
    if (existingSvg) existingSvg.remove();

    const bookContainer = document.getElementById('book-container');
    if (!bookContainer) return;

    // Create new SVG positioned relative to book container
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.id = 'arrow-svg';
    bookContainer.appendChild(svg);

    // Add definitions for drop shadow and arrow markers
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

    // Create drop shadow filter for lines only
    const lineDropShadowFilter = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    lineDropShadowFilter.setAttribute('id', 'line-drop-shadow');
    lineDropShadowFilter.setAttribute('x', '-50%');
    lineDropShadowFilter.setAttribute('y', '-50%');
    lineDropShadowFilter.setAttribute('width', '200%');
    lineDropShadowFilter.setAttribute('height', '200%');

    const lineDropShadow = document.createElementNS('http://www.w3.org/2000/svg', 'feDropShadow');
    lineDropShadow.setAttribute('dx', '2');
    lineDropShadow.setAttribute('dy', '2');
    lineDropShadow.setAttribute('stdDeviation', '2');
    lineDropShadow.setAttribute('flood-color', 'rgba(0,0,0,0.3)');

    lineDropShadowFilter.appendChild(lineDropShadow);
    defs.appendChild(lineDropShadowFilter);

    svg.appendChild(defs);

    const frames = document.querySelectorAll('.frame');
    const framePositions = new Map();
    const frameColors = new Map();
    const containerRect = bookContainer.getBoundingClientRect();

    // Get frame positions and colors relative to book container
    frames.forEach(frame => {
        const frameId = frame.dataset.frameId;
        const frameRect = frame.getBoundingClientRect();
        const frameMargin = frame.querySelector('.frame-margin');

        // Get the background color from the sticky note
        const backgroundColor = frameMargin ?
            window.getComputedStyle(frameMargin).backgroundColor : '#fff740';

        // Calculate position relative to book container
        const relativeX = frameRect.left - containerRect.left;
        const relativeY = frameRect.top - containerRect.top;

        framePositions.set(frameId, {
            x: relativeX,
            y: relativeY,
            width: frameRect.width,
            height: frameRect.height
        });

        frameColors.set(frameId, backgroundColor);
    });

    // Draw arrows for non-adjacent references
    frames.forEach((frame, index) => {
        const frameId = frame.dataset.frameId;
        const referenceFrame = frame.dataset.referenceFrame;

        if (!referenceFrame || referenceFrame === 'none' || referenceFrame === '') return;

        // Check if reference is not the immediately previous frame
        const previousFrame = frames[index - 1];
        const isPreviousFrame = previousFrame && previousFrame.dataset.frameId === referenceFrame;

        if (!isPreviousFrame) {
            const fromPos = framePositions.get(frameId);
            const toPos = framePositions.get(referenceFrame);
            const arrowColor = frameColors.get(frameId);

            if (fromPos && toPos && arrowColor) {
                // Create unique marker ID for this arrow color
                const markerId = `arrow-head-${frameId.replace(/[^a-zA-Z0-9]/g, '_')}`;
                const shadowMarkerId = `arrow-head-shadow-${frameId.replace(/[^a-zA-Z0-9]/g, '_')}`;

                // Add shadow arrowhead marker (slightly offset, dark)
                const shadowMarker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                shadowMarker.setAttribute('id', shadowMarkerId);
                shadowMarker.setAttribute('markerWidth', '4');
                shadowMarker.setAttribute('markerHeight', '4');
                shadowMarker.setAttribute('refX', '3.2'); // Slightly offset for shadow
                shadowMarker.setAttribute('refY', '1.7'); // Slightly offset for shadow
                shadowMarker.setAttribute('orient', 'auto');
                shadowMarker.setAttribute('markerUnits', 'strokeWidth');

                const shadowArrowHead = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                shadowArrowHead.setAttribute('d', 'M0,0 L0,2.5 L3,1.25 z'); // Half the previous size
                shadowArrowHead.setAttribute('fill', 'rgba(0,0,0,0.3)');
                shadowArrowHead.setAttribute('stroke', 'none');

                shadowMarker.appendChild(shadowArrowHead);
                defs.appendChild(shadowMarker);

                // Add main colored arrowhead marker (smaller)
                const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
                marker.setAttribute('id', markerId);
                marker.setAttribute('markerWidth', '4'); // Half of previous size
                marker.setAttribute('markerHeight', '4'); // Half of previous size
                marker.setAttribute('refX', '3'); // Half of previous size
                marker.setAttribute('refY', '1.25'); // Half of previous size
                marker.setAttribute('orient', 'auto');
                marker.setAttribute('markerUnits', 'strokeWidth');

                const arrowHead = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                arrowHead.setAttribute('d', 'M0,0 L0,2.5 L3,1.25 z'); // Half the previous size
                arrowHead.setAttribute('fill', arrowColor);
                arrowHead.setAttribute('stroke', arrowColor);
                arrowHead.setAttribute('stroke-width', '0.5');

                marker.appendChild(arrowHead);
                defs.appendChild(marker);

                // Calculate taxi-cab path positions
                const stickyRightEdge = fromPos.x + fromPos.width + 450;
                const startX = stickyRightEdge;
                const startY = fromPos.y + 50;

                const targetStickyRightEdge = toPos.x + toPos.width + 450;
                const endX = targetStickyRightEdge;
                const endY = toPos.y + 50;

                // Taxi-cab routing: go east 20px, then north/south, then west
                const eastOffset = 20;
                const corner1X = startX + eastOffset;
                const corner1Y = startY;
                const corner2X = corner1X;
                const corner2Y = endY;
                const corner3X = endX;
                const corner3Y = endY;

                // Create taxi-cab path
                const pathData = `M ${startX} ${startY} L ${corner1X} ${corner1Y} L ${corner2X} ${corner2Y} L ${corner3X} ${corner3Y}`;

                // Create shadow path (slightly offset)
                const shadowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                shadowPath.setAttribute('d', pathData);
                shadowPath.setAttribute('stroke', 'rgba(0,0,0,0.3)');
                shadowPath.setAttribute('stroke-width', '3');
                shadowPath.setAttribute('fill', 'none');
                shadowPath.setAttribute('stroke-linecap', 'round');
                shadowPath.setAttribute('stroke-linejoin', 'round');
                shadowPath.setAttribute('opacity', '0.9');
                shadowPath.setAttribute('marker-end', `url(#${shadowMarkerId})`);
                shadowPath.setAttribute('transform', 'translate(2,2)'); // Offset for shadow

                // Create main path
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('d', pathData);
                path.setAttribute('stroke', arrowColor);
                path.setAttribute('stroke-width', '3');
                path.setAttribute('fill', 'none');
                path.setAttribute('stroke-linecap', 'round');
                path.setAttribute('stroke-linejoin', 'round');
                path.setAttribute('opacity', '0.9');
                path.setAttribute('marker-end', `url(#${markerId})`);

                // Add shadow first, then main path
                svg.appendChild(shadowPath);
                svg.appendChild(path);
            }
        }
    });
}

/* Fountain AutoComplete */
class FountainAutocomplete {
    constructor() {
        this.characters = [];
        this.locations = [];
        this.isVisible = false;
        this.currentTextarea = null;
        this.currentSymbol = null;
        this.selectedIndex = 0;
        this.filteredItems = [];
        this.dropdown = null;

        this.loadCollections();
        this.createDropdown();
    }

    async loadCollections() {
        try {
            // Fetch collections from our new API endpoint
            const collectionsResponse = await fetch('/api/collections');
            const collections = await collectionsResponse.json();

            this.characters = collections.characters || [];
            this.locations = collections.locations || [];
        } catch (error) {
            console.error('Failed to load collections:', error);
        }
    }

    createDropdown() {
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'fountain-autocomplete-dropdown';
        this.dropdown.style.cssText = `
            position: absolute;
            background: white;
            border: 1px solid #ccc;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            max-height: 200px;
            overflow-y: auto;
            z-index: 1000;
            display: none;
            min-width: 200px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
        `;
        document.body.appendChild(this.dropdown);
    }

    attachTo(textarea) {
        textarea.addEventListener('input', (e) => this.handleInput(e));
        textarea.addEventListener('keydown', (e) => this.handleKeydown(e));
        textarea.addEventListener('blur', () => {
            // Add a small delay to allow click events on dropdown items
            setTimeout(() => this.hide(), 150);
        });
    }

    handleInput(e) {
        const textarea = e.target;
        const cursorPos = textarea.selectionStart;
        const text = textarea.value;

        // Look for @ or # before cursor
        let triggerPos = -1;
        let symbol = null;

        for (let i = cursorPos - 1; i >= 0; i--) {
            const char = text[i];
            if (char === '@' || char === '#') {
                triggerPos = i;
                symbol = char;
                break;
            } else if (char === ' ' || char === '\n' || char === '\t') {
                break;
            }
        }

        if (triggerPos !== -1) {
            const query = text.substring(triggerPos + 1, cursorPos);
            this.show(textarea, triggerPos, symbol, query);
        } else {
            this.hide();
        }
    }

    handleKeydown(e) {
        if (!this.isVisible) return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.selectedIndex = Math.min(this.selectedIndex + 1, this.filteredItems.length - 1);
                this.updateSelection();
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
                this.updateSelection();
                break;
            case 'Enter':
            case 'Tab':
                e.preventDefault();
                this.insertSelection();
                break;
            case 'Escape':
                e.preventDefault();
                this.hide();
                break;
        }
    }

    show(textarea, triggerPos, symbol, query) {
        this.currentTextarea = textarea;
        this.currentSymbol = symbol;
        this.triggerPos = triggerPos;

        const items = symbol === '@' ? this.characters : this.locations;
        this.filteredItems = items.filter(item =>
            item.name.toLowerCase().includes(query.toLowerCase())
        );

        if (this.filteredItems.length === 0) {
            this.hide();
            return;
        }

        this.selectedIndex = 0;
        this.renderDropdown();
        this.positionDropdown(textarea, triggerPos);
        this.isVisible = true;
        this.dropdown.style.display = 'block';
    }

    hide() {
        this.isVisible = false;
        if (this.dropdown) {
            this.dropdown.style.display = 'none';
        }
        this.currentTextarea = null;
    }

    renderDropdown() {
        this.dropdown.innerHTML = '';

        this.filteredItems.forEach((item, index) => {
            const option = document.createElement('div');
            option.className = 'autocomplete-option';
            option.style.cssText = `
                padding: 8px 12px;
                cursor: pointer;
                border-bottom: 1px solid #eee;
                ${index === this.selectedIndex ? 'background: #e3f2fd;' : ''}
            `;
            option.textContent = `${this.currentSymbol}${item.name}`;

            option.addEventListener('mousedown', (e) => {
                e.preventDefault(); // Prevent blur event
                this.selectedIndex = index;
                this.insertSelection();
            });

            this.dropdown.appendChild(option);
        });
    }

    updateSelection() {
        const options = this.dropdown.querySelectorAll('.autocomplete-option');
        options.forEach((option, index) => {
            option.style.background = index === this.selectedIndex ? '#e3f2fd' : '';
        });
    }

    positionDropdown(textarea, triggerPos) {
        // Calculate position based on cursor position
        const rect = textarea.getBoundingClientRect();

        // Create a temporary span to measure text width
        const tempSpan = document.createElement('span');
        tempSpan.style.cssText = `
            visibility: hidden;
            position: absolute;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            white-space: pre;
        `;

        // Get text up to trigger position
        const lines = textarea.value.substring(0, triggerPos).split('\n');
        const currentLine = lines[lines.length - 1];

        tempSpan.textContent = currentLine;
        document.body.appendChild(tempSpan);

        const textWidth = tempSpan.offsetWidth;
        const lineHeight = 16; // Approximate line height for 12px font

        document.body.removeChild(tempSpan);

        this.dropdown.style.left = (rect.left + textWidth) + 'px';
        this.dropdown.style.top = (rect.top + (lines.length - 1) * lineHeight + lineHeight) + 'px';
    }

    insertSelection() {
        if (!this.currentTextarea || this.selectedIndex >= this.filteredItems.length) return;

        const item = this.filteredItems[this.selectedIndex];
        const textarea = this.currentTextarea;
        const cursorPos = textarea.selectionStart;
        const text = textarea.value;

        // Replace from trigger position to cursor with the selected item
        const before = text.substring(0, this.triggerPos);
        const after = text.substring(cursorPos);
        const insertion = `${this.currentSymbol}${item.name}`;

        textarea.value = before + insertion + after;
        textarea.selectionStart = textarea.selectionEnd = this.triggerPos + insertion.length;

        this.hide();
        textarea.focus();
    }
}

// Character/Location hover preview system
// Character/Location hover preview system
class CharacterLocationPreview {
    constructor() {
        this.previewElements = new Map(); // Map of type/name -> preview element
        this.hoverTimeout = null;
        this.hideTimeout = null; // Timer for delayed hiding
        this.characterNames = [];
        this.locationNames = [];
        this.currentPreview = null;
        this.setupEventListeners();
        this.loadCollectionNames();
    }

    async loadCollectionNames() {
        try {
            const collectionsResponse = await fetch('/api/collections');
            const collections = await collectionsResponse.json();

            this.characterNames = (collections.characters || []).map(c => c.name);
            this.locationNames = (collections.locations || []).map(l => l.name);

            // Create all preview elements at once
            this.createAllPreviewElements();
        } catch (error) {
            console.error('Failed to load collection names:', error);
        }
    }

    createAllPreviewElements() {
        // Create preview elements for all characters
        this.characterNames.forEach(name => {
            this.createPreviewElement(name, 'characters');
        });

        // Create preview elements for all locations
        this.locationNames.forEach(name => {
            this.createPreviewElement(name, 'locations');
        });

        console.log(`Created ${this.previewElements.size} preview elements`);
    }

    createPreviewElement(name, type) {
        const cacheKey = `${type}/${name}`;

        // Create the preview element
        const preview = document.createElement('div');
        preview.className = 'character-location-preview';

        const facTarget = `${type}/${name}/${type === 'characters' ? 'character_sheet.png' : 'reference.png'}`;
        const imagePath = `/${facTarget}`;

        // Create image 
        // FIXME:
        // this should have the auto-updater and fac-build classes,
        // but that results in an infinite loop right now
        const img = document.createElement('img');
        img.src = imagePath;
        img.className = 'preview-image';
        img.setAttribute('data-fac-target', facTarget);

        preview.appendChild(img);

        // Add to DOM but keep hidden initially
        preview.style.display = 'none';
        preview.style.position = 'absolute';
        preview.style.zIndex = '2000';
        document.body.appendChild(preview);

        // Store in our map
        this.previewElements.set(cacheKey, preview);

        return preview;
    }

    setupEventListeners() {
        document.addEventListener('mouseover', (e) => {
            if (e.target.classList.contains('character-location-link')) {
                this.showPreview(e.target, e);
            }
        });

        document.addEventListener('mouseout', (e) => {
            if (e.target.classList.contains('character-location-link')) {
                this.scheduleHidePreview(e);
            }
        });

        // Also schedule hide when mouse leaves the preview
        document.addEventListener('mouseout', (e) => {
            if (this.currentPreview && this.currentPreview.contains(e.target)) {
                this.scheduleHidePreview(e);
            }
        });

        // Cancel hide when mouse enters preview
        document.addEventListener('mouseover', (e) => {
            if (this.currentPreview && this.currentPreview.contains(e.target)) {
                this.cancelHidePreview();
            }
        });
    }

    isInGraceArea(element, mouseEvent) {
        if (!this.currentPreview || !element) return false;

        const linkRect = element.getBoundingClientRect();
        const previewRect = this.currentPreview.getBoundingClientRect();

        // Create a grace area that includes both the link and preview with some padding
        const graceArea = {
            left: Math.min(linkRect.left, previewRect.left) - 10,
            right: Math.max(linkRect.right, previewRect.right) + 10,
            top: Math.min(linkRect.top, previewRect.top) - 10,
            bottom: Math.max(linkRect.bottom, previewRect.bottom) + 10
        };

        const mouseX = mouseEvent.clientX;
        const mouseY = mouseEvent.clientY;

        return mouseX >= graceArea.left && mouseX <= graceArea.right &&
               mouseY >= graceArea.top && mouseY <= graceArea.bottom;
    }

    scheduleHidePreview(mouseEvent) {
        // Clear any existing hide timeout
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
        }

        // Check if mouse is still in grace area
        const link = document.querySelector('.character-location-link:hover');

        if (link && this.isInGraceArea(link, mouseEvent)) {
            return; // Don't hide if still in grace area
        }

        // Schedule hide after delay
        this.hideTimeout = setTimeout(() => {
            this.hidePreview();
        }, 500); // 500ms grace period
    }

    cancelHidePreview() {
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }
    }

    showPreview(element, event) {
        const name = element.dataset.name;
        const type = element.dataset.type;
        const cacheKey = `${type}/${name}`;

        // Clear any existing timeouts
        if (this.hoverTimeout) {
            clearTimeout(this.hoverTimeout);
        }
        this.cancelHidePreview();

        // Hide any currently visible preview immediately
        if (this.currentPreview) {
            this.currentPreview.style.display = 'none';
        }

        // Get the pre-created preview element
        const preview = this.previewElements.get(cacheKey);
        if (!preview) {
            console.warn(`No preview element found for ${cacheKey}`);
            return;
        }

        // Show preview immediately
        this.hoverTimeout = setTimeout(() => {
            this.currentPreview = preview;
            this.positionPreview(element);
            preview.style.display = 'block';
        }, 100); // Minimal delay to prevent flickering
    }

    hidePreview() {
        if (this.hoverTimeout) {
            clearTimeout(this.hoverTimeout);
            this.hoverTimeout = null;
        }
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }
        if (this.currentPreview) {
            this.currentPreview.style.display = 'none';
            this.currentPreview = null;
        }
    }

    positionPreview(linkElement) {
        if (!this.currentPreview) return;

        const linkRect = linkElement.getBoundingClientRect();
        const previewRect = this.currentPreview.getBoundingClientRect();
        const viewportHeight = window.innerHeight;
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        // Position directly below the link with minimal gap
        let top = linkRect.bottom + scrollTop + 2; // Reduced gap to 2px
        let left = linkRect.left + scrollLeft;

        // If there's not enough space below, position above
        if (linkRect.bottom + previewRect.height + 20 > viewportHeight) {
            top = linkRect.top + scrollTop - previewRect.height - 2; // Reduced gap to 2px
        }

        // Make sure it doesn't go off the left or right edge
        const viewportWidth = window.innerWidth;
        if (left + previewRect.width > viewportWidth) {
            left = viewportWidth - previewRect.width - 10;
        }
        if (left < 0) {
            left = 10;
        }

        this.currentPreview.style.left = left + 'px';
        this.currentPreview.style.top = top + 'px';
    }
}

