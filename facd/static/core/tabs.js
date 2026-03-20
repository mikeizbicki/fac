// tabs.js
//
// This component manages a modular tab system with two panes:
// - Sidebar pane (left): for meta-information like git history
// - Main pane (right): for primary content like targets tree or screenplay
//
// Features:
// - Tabs can be dragged between panes
// - On narrow screens (<768px), sidebar collapses and all tabs show in main pane
// - Easy API to register new tabs from other components
//
// API:
// window.registerTab(options) - Register a new tab
//   options: {
//     id: string,           // Unique identifier for the tab
//     label: string,        // Display label on tab button
//     pane: 'sidebar'|'main', // Which pane to initially place tab in
//     render: function(container), // Called to render tab content
//     onActivate: function(),      // Optional: called when tab becomes active
//     onDeactivate: function()     // Optional: called when tab becomes inactive
//   }
//
// window.activateTab(id) - Programmatically activate a tab
// window.getActiveTab(pane) - Get the active tab id for a pane

(function() {
    const tabs = {};
    const paneState = {
        sidebar: { tabs: [], activeTab: null },
        main: { tabs: [], activeTab: null }
    };

    let sidebarPane = null;
    let mainPane = null;
    let initialized = false;

    function init() {
        if (initialized) return;
        initialized = true;

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
        document.addEventListener('dragstart', (e) => {
            if (e.target.classList.contains('tab-button')) {
                e.target.classList.add('dragging');
                e.dataTransfer.setData('text/plain', e.target.dataset.tabId);
                e.dataTransfer.effectAllowed = 'move';
            }
        });

        document.addEventListener('dragend', (e) => {
            if (e.target.classList.contains('tab-button')) {
                e.target.classList.remove('dragging');
            }
            document.querySelectorAll('.tab-bar').forEach(bar => {
                bar.classList.remove('drag-over');
            });
        });

        document.querySelectorAll('.tab-bar').forEach(bar => {
            bar.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                bar.classList.add('drag-over');
            });

            bar.addEventListener('dragleave', () => {
                bar.classList.remove('drag-over');
            });

            bar.addEventListener('drop', (e) => {
                e.preventDefault();
                bar.classList.remove('drag-over');
                const tabId = e.dataTransfer.getData('text/plain');
                const targetPane = bar.dataset.pane;
                moveTabToPane(tabId, targetPane);
            });
        });
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

    function moveTabToPane(tabId, targetPane) {
        const tab = tabs[tabId];
        if (!tab) return;

        const currentPane = tab.pane;
        if (currentPane === targetPane) return;

        // Remove from current pane
        const currentState = paneState[currentPane];
        currentState.tabs = currentState.tabs.filter(id => id !== tabId);
        if (currentState.activeTab === tabId) {
            currentState.activeTab = currentState.tabs[0] || null;
        }

        // Add to target pane
        const targetState = paneState[targetPane];
        targetState.tabs.push(tabId);
        tab.pane = targetPane;

        // Move DOM elements
        const btn = document.querySelector(`.tab-button[data-tab-id="${tabId}"]`);
        const content = document.querySelector(`.tab-content[data-tab-id="${tabId}"]`);
        
        if (btn) {
            btn.classList.toggle('sidebar-tab', targetPane === 'sidebar');
            getPane(targetPane).querySelector('.tab-bar').appendChild(btn);
        }
        
        if (content) {
            getPane(targetPane).querySelector('.tab-content-area').appendChild(content);
        }

        // Activate the moved tab in its new pane
        activateTabInPane(tabId, targetPane);
        
        // Update the old pane
        if (currentState.activeTab) {
            activateTabInPane(currentState.activeTab, currentPane);
        }
        updateAllPanes();
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
    }

    function updateAllPanes() {
        ['sidebar', 'main'].forEach(pane => {
            const state = paneState[pane];
            if (state.tabs.length > 0 && !state.activeTab) {
                activateTabInPane(state.tabs[0], pane);
            }
        });
    }

    window.registerTab = function(options) {
        if (!initialized) init();

        const { id, label, pane, render, onActivate, onDeactivate } = options;
        
        if (tabs[id]) {
            console.warn(`Tab "${id}" already registered`);
            return;
        }

        tabs[id] = { id, label, pane, render, onActivate, onDeactivate };
        paneState[pane].tabs.push(id);

        const paneEl = getPane(pane);
        const tabBar = paneEl.querySelector('.tab-bar');
        const contentArea = paneEl.querySelector('.tab-content-area');

        // Create tab button
        const btn = createTabButton(id, label, pane);
        tabBar.appendChild(btn);

        // Create tab content
        const content = createTabContent(id);
        contentArea.appendChild(content);

        // Render content
        if (render) {
            render(content);
        }

        // Activate if first tab in pane
        if (paneState[pane].tabs.length === 1) {
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
