// tabs.js
//
// This component manages a modular tab system with two panes:
// - Sidebar pane (left): for meta-information like git history
// - Main pane (right): for primary content like targets tree or screenplay
//
// Features:
// - Tabs can be dragged between panes
// - Tabs can be reordered within a pane by dragging
// - Tab positions and order are persisted to localStorage
// - On narrow screens (<768px), sidebar collapses and all tabs show in main pane
// - Easy API to register new tabs from other components
//
// API:
// window.registerTab(options) - Register a new tab
//   options: {
//     id: string,           // Unique identifier for the tab
//     label: string,        // Display label on tab button
//     pane: 'sidebar'|'main', // Which pane to initially place tab in (default if no saved state)
//     render: function(container), // Called to render tab content
//     onActivate: function(),      // Optional: called when tab becomes active
//     onDeactivate: function()     // Optional: called when tab becomes inactive
//   }
//
// window.activateTab(id) - Programmatically activate a tab
// window.getActiveTab(pane) - Get the active tab id for a pane

(function() {
    const STORAGE_KEY = 'tabsState';
    const tabs = {};
    const paneState = {
        sidebar: { tabs: [], activeTab: null },
        main: { tabs: [], activeTab: null }
    };

    let sidebarPane = null;
    let mainPane = null;
    let initialized = false;
    let savedState = null;

    function loadState() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            if (stored) {
                savedState = JSON.parse(stored);
            }
        } catch (e) {
            console.warn('tabs.js: Failed to load state from localStorage', e);
            savedState = null;
        }
    }

    function saveState() {
        try {
            const state = {
                sidebar: {
                    tabs: paneState.sidebar.tabs.slice(),
                    activeTab: paneState.sidebar.activeTab
                },
                main: {
                    tabs: paneState.main.tabs.slice(),
                    activeTab: paneState.main.activeTab
                }
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (e) {
            console.warn('tabs.js: Failed to save state to localStorage', e);
        }
    }

    function init() {
        if (initialized) return;
        initialized = true;

        loadState();

        const container = document.querySelector('.app-container');
        if (!container) {
            console.error('tabs.js: .app-container not found');
            return;
        }

        // Create sidebar pane
        sidebarPane = document.createElement('div');
        sidebarPane.className = 'tab-pane sidebar-pane';
        sidebarPane.innerHTML = `
            <div class="tab-bar" data-pane="sidebar"></div>
            <div class="tab-content-area"></div>
            <div class="pane-resize-handle"></div>
        `;
        container.appendChild(sidebarPane);

        // Create main pane
        mainPane = document.createElement('div');
        mainPane.className = 'tab-pane main-pane';
        mainPane.innerHTML = `
            <div class="tab-bar" data-pane="main"></div>
            <div class="tab-content-area"></div>
        `;
        container.appendChild(mainPane);

        setupResizeHandle();
        setupDragAndDrop();
        setupResponsiveHandler();
    }

    function setupResizeHandle() {
        const handle = sidebarPane.querySelector('.pane-resize-handle');
        let startX, startWidth;

        function onMouseDown(e) {
            startX = e.clientX;
            startWidth = sidebarPane.offsetWidth;
            handle.classList.add('dragging');
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
            e.preventDefault();
        }

        function onMouseMove(e) {
            const delta = e.clientX - startX;
            const newWidth = Math.max(250, Math.min(500, startWidth + delta));
            sidebarPane.style.width = newWidth + 'px';
        }

        function onMouseUp() {
            handle.classList.remove('dragging');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }

        handle.addEventListener('mousedown', onMouseDown);
    }

    function setupDragAndDrop() {
        let draggedTabId = null;

        document.addEventListener('dragstart', (e) => {
            if (e.target.classList.contains('tab-button')) {
                draggedTabId = e.target.dataset.tabId;
                e.target.classList.add('dragging');
                e.dataTransfer.setData('text/plain', draggedTabId);
                e.dataTransfer.effectAllowed = 'move';
            }
        });

        document.addEventListener('dragend', (e) => {
            if (e.target.classList.contains('tab-button')) {
                e.target.classList.remove('dragging');
            }
            draggedTabId = null;
            document.querySelectorAll('.tab-bar').forEach(bar => {
                bar.classList.remove('drag-over');
            });
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('drag-insert-before', 'drag-insert-after');
            });
        });

        document.querySelectorAll('.tab-bar').forEach(bar => {
            bar.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                bar.classList.add('drag-over');

                // Clear previous insert indicators
                bar.querySelectorAll('.tab-button').forEach(btn => {
                    btn.classList.remove('drag-insert-before', 'drag-insert-after');
                });

                // Find insertion point
                const insertInfo = getInsertPosition(bar, e.clientX);
                if (insertInfo.element) {
                    if (insertInfo.position === 'before') {
                        insertInfo.element.classList.add('drag-insert-before');
                    } else {
                        insertInfo.element.classList.add('drag-insert-after');
                    }
                }
            });

            bar.addEventListener('dragleave', (e) => {
                // Only remove drag-over if we're actually leaving the bar
                if (!bar.contains(e.relatedTarget)) {
                    bar.classList.remove('drag-over');
                    bar.querySelectorAll('.tab-button').forEach(btn => {
                        btn.classList.remove('drag-insert-before', 'drag-insert-after');
                    });
                }
            });

            bar.addEventListener('drop', (e) => {
                e.preventDefault();
                bar.classList.remove('drag-over');
                bar.querySelectorAll('.tab-button').forEach(btn => {
                    btn.classList.remove('drag-insert-before', 'drag-insert-after');
                });

                const tabId = e.dataTransfer.getData('text/plain');
                const targetPane = bar.dataset.pane;
                const insertInfo = getInsertPosition(bar, e.clientX);

                moveTabToPane(tabId, targetPane, insertInfo);
            });
        });
    }

    function getInsertPosition(bar, clientX) {
        const buttons = Array.from(bar.querySelectorAll('.tab-button:not(.dragging)'));
        
        if (buttons.length === 0) {
            return { element: null, position: null, index: 0 };
        }

        for (let i = 0; i < buttons.length; i++) {
            const btn = buttons[i];
            const rect = btn.getBoundingClientRect();
            const midpoint = rect.left + rect.width / 2;

            if (clientX < midpoint) {
                return { element: btn, position: 'before', index: i };
            }
        }

        // After all buttons
        return { element: buttons[buttons.length - 1], position: 'after', index: buttons.length };
    }

    function setupResponsiveHandler() {
        const mediaQuery = window.matchMedia('(max-width: 768px)');
        
        function handleResize(e) {
            if (e.matches) {
                // Narrow screen: move sidebar tabs to main visually
                // (They stay registered to sidebar but show in main)
                document.querySelectorAll('.tab-button.sidebar-tab').forEach(btn => {
                    btn.style.display = '';
                });
            }
            updateAllPanes();
        }

        mediaQuery.addEventListener('change', handleResize);
        handleResize(mediaQuery);
    }

    function createTabButton(tabId, label, pane) {
        const btn = document.createElement('button');
        btn.className = 'tab-button';
        btn.dataset.tabId = tabId;
        btn.textContent = label;
        btn.draggable = true;
        
        if (pane === 'sidebar') {
            btn.classList.add('sidebar-tab');
        }

        btn.addEventListener('click', () => {
            activateTab(tabId);
        });

        return btn;
    }

    function createTabContent(tabId) {
        const content = document.createElement('div');
        content.className = 'tab-content';
        content.dataset.tabId = tabId;
        return content;
    }

    function getPane(paneName) {
        return paneName === 'sidebar' ? sidebarPane : mainPane;
    }

    function moveTabToPane(tabId, targetPane, insertInfo) {
        const tab = tabs[tabId];
        if (!tab) return;

        const currentPane = tab.pane;
        const samePane = currentPane === targetPane;

        // Remove from current pane's tab list
        const currentState = paneState[currentPane];
        const currentIndex = currentState.tabs.indexOf(tabId);
        currentState.tabs = currentState.tabs.filter(id => id !== tabId);

        // Calculate insert index
        let insertIndex = insertInfo ? insertInfo.index : paneState[targetPane].tabs.length;
        
        // Adjust index if moving within same pane and moving to a later position
        if (samePane && insertInfo && currentIndex < insertIndex) {
            insertIndex--;
        }

        // Add to target pane at specific position
        const targetState = paneState[targetPane];
        targetState.tabs.splice(insertIndex, 0, tabId);
        tab.pane = targetPane;

        // Handle active tab in current pane if it was moved
        if (!samePane && currentState.activeTab === tabId) {
            currentState.activeTab = currentState.tabs[0] || null;
        }

        // Move DOM elements
        const btn = document.querySelector(`.tab-button[data-tab-id="${tabId}"]`);
        const content = document.querySelector(`.tab-content[data-tab-id="${tabId}"]`);
        const targetBar = getPane(targetPane).querySelector('.tab-bar');
        
        if (btn) {
            btn.classList.toggle('sidebar-tab', targetPane === 'sidebar');
            
            // Insert at correct position in DOM
            const allButtons = Array.from(targetBar.querySelectorAll('.tab-button'));
            const buttonAtIndex = allButtons.filter(b => b !== btn)[insertIndex];
            
            if (buttonAtIndex) {
                targetBar.insertBefore(btn, buttonAtIndex);
            } else {
                targetBar.appendChild(btn);
            }
        }
        
        if (content && !samePane) {
            getPane(targetPane).querySelector('.tab-content-area').appendChild(content);
        }

        // Activate the moved tab in its new pane (if moving between panes)
        if (!samePane) {
            activateTabInPane(tabId, targetPane);
            
            // Update the old pane
            if (currentState.activeTab) {
                activateTabInPane(currentState.activeTab, currentPane);
            }
        }

        updateAllPanes();
        saveState();
    }

    function activateTabInPane(tabId, pane) {
        const state = paneState[pane];
        const paneEl = getPane(pane);

        // Deactivate previous tab
        if (state.activeTab && state.activeTab !== tabId) {
            const prevTab = tabs[state.activeTab];
            if (prevTab && prevTab.onDeactivate) {
                prevTab.onDeactivate();
            }
            const prevBtn = paneEl.querySelector(`.tab-button[data-tab-id="${state.activeTab}"]`);
            const prevContent = paneEl.querySelector(`.tab-content[data-tab-id="${state.activeTab}"]`);
            if (prevBtn) prevBtn.classList.remove('active');
            if (prevContent) prevContent.classList.remove('active');
        }

        // Activate new tab
        state.activeTab = tabId;
        const btn = paneEl.querySelector(`.tab-button[data-tab-id="${tabId}"]`);
        const content = paneEl.querySelector(`.tab-content[data-tab-id="${tabId}"]`);
        if (btn) btn.classList.add('active');
        if (content) content.classList.add('active');

        const tab = tabs[tabId];
        if (tab && tab.onActivate) {
            tab.onActivate();
        }

        saveState();
    }

    function updateAllPanes() {
        ['sidebar', 'main'].forEach(pane => {
            const state = paneState[pane];
            if (state.tabs.length > 0 && !state.activeTab) {
                activateTabInPane(state.tabs[0], pane);
            }
        });
    }

    function getSavedTabInfo(tabId, defaultPane) {
        if (!savedState) return { pane: defaultPane, index: -1 };

        for (const pane of ['sidebar', 'main']) {
            const index = savedState[pane].tabs.indexOf(tabId);
            if (index !== -1) {
                return { pane, index, activeTab: savedState[pane].activeTab };
            }
        }

        return { pane: defaultPane, index: -1 };
    }

    window.registerTab = function(options) {
        if (!initialized) init();

        const { id, label, pane: defaultPane, render, onActivate, onDeactivate } = options;
        
        if (tabs[id]) {
            console.warn(`Tab "${id}" already registered`);
            return;
        }

        // Check saved state for this tab's position
        const savedInfo = getSavedTabInfo(id, defaultPane);
        const pane = savedInfo.pane;

        tabs[id] = { id, label, pane, render, onActivate, onDeactivate };

        // Insert at saved position or append
        const state = paneState[pane];
        if (savedInfo.index !== -1 && savedInfo.index <= state.tabs.length) {
            state.tabs.splice(savedInfo.index, 0, id);
        } else {
            state.tabs.push(id);
        }

        const paneEl = getPane(pane);
        const tabBar = paneEl.querySelector('.tab-bar');
        const contentArea = paneEl.querySelector('.tab-content-area');

        // Create tab button
        const btn = createTabButton(id, label, pane);
        
        // Insert button at correct position
        const existingButtons = tabBar.querySelectorAll('.tab-button');
        const insertIndex = state.tabs.indexOf(id);
        if (insertIndex < existingButtons.length) {
            tabBar.insertBefore(btn, existingButtons[insertIndex]);
        } else {
            tabBar.appendChild(btn);
        }

        // Create tab content
        const content = createTabContent(id);
        contentArea.appendChild(content);

        // Render content
        if (render) {
            render(content);
        }

        // Activate based on saved state or if first tab
        const shouldActivate = (savedInfo.activeTab === id) || 
                               (paneState[pane].tabs.length === 1);
        if (shouldActivate) {
            activateTabInPane(id, pane);
        }
    };

    window.activateTab = function(tabId) {
        const tab = tabs[tabId];
        if (!tab) return;
        activateTabInPane(tabId, tab.pane);
    };

    window.getActiveTab = function(pane) {
        return paneState[pane]?.activeTab || null;
    };

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
