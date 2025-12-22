class Sidebar {
    constructor() {
        this.historyEventSource = null;
        this.consoleEventSource = null;
        this.currentTab = 'history';
        this.isCollapsed = window.innerWidth <= 768;
        this.isResizing = false;
        this.sidebarWidth = 320;
        this.showRelativeTime = localStorage.getItem('showRelativeTime') !== 'false'; // Default true
        this.currentBranch = 'main'; // Will be updated from server

        this.initializeElements();
        this.setupEventListeners();
        this.connectHistoryStream();
        this.connectConsoleStream();
        this.loadHistory();
        this.loadBranches();

        // Auto-collapse on mobile
        if (this.isCollapsed) {
            this.toggleSidebar(false);
        }
    }

    initializeElements() {
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebar-toggle');
        this.mainContent = document.getElementById('main-content');
        this.historyList = document.getElementById('history-list');
        this.consoleOutput = document.getElementById('console-output');
        this.clearConsoleBtn = document.getElementById('clear-console');
        this.resizeHandle = document.querySelector('.sidebar-resize-handle');
        this.branchSelect = document.getElementById('branch-select');
        this.newBranchBtn = document.getElementById('new-branch-btn');
        this.relativeTimeCheckbox = document.getElementById('relative-time-checkbox');
    }

    setupEventListeners() {
        // Tab switching
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.switchTab(btn.dataset.tab);
            });
        });

        // Sidebar toggle
        this.sidebarToggle.addEventListener('click', () => {
            this.toggleSidebar();
        });

        // Clear console
        this.clearConsoleBtn.addEventListener('click', () => {
            this.clearConsole();
        });

        // Branch selection
        this.branchSelect.addEventListener('change', (e) => {
            this.switchBranch(e.target.value);
        });

        // New branch button
        this.newBranchBtn.addEventListener('click', () => {
            this.createNewBranch();
        });

        // Relative time checkbox
        this.relativeTimeCheckbox.checked = this.showRelativeTime;
        this.relativeTimeCheckbox.addEventListener('change', (e) => {
            this.showRelativeTime = e.target.checked;
            localStorage.setItem('showRelativeTime', this.showRelativeTime.toString());
            this.loadHistory(); // Refresh history display
        });

        // Resize handling
        this.setupResizeHandling();

        // Responsive handling
        window.addEventListener('resize', () => {
            if (window.innerWidth <= 768 && !this.isCollapsed) {
                this.toggleSidebar(false);
            }
        });
    }

    setupResizeHandling() {
        let startX, startWidth;

        this.resizeHandle.addEventListener('mousedown', (e) => {
            this.isResizing = true;
            startX = e.clientX;
            startWidth = this.sidebarWidth;

            document.addEventListener('mousemove', handleMouseMove);
            document.addEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';

            e.preventDefault();
        });

        const handleMouseMove = (e) => {
            if (!this.isResizing) return;

            const newWidth = Math.max(200, Math.min(window.innerWidth * 0.5, startWidth + (e.clientX - startX)));
            this.setSidebarWidth(newWidth);
        };

        const handleMouseUp = () => {
            this.isResizing = false;
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        };
    }

    setSidebarWidth(width) {
        this.sidebarWidth = width;
        this.sidebar.style.width = width + 'px';
        if (!this.isCollapsed) {
            this.mainContent.style.marginLeft = width + 'px';
        }
    }

    switchTab(tabName) {
        // Update buttons
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}-tab`);
        });

        this.currentTab = tabName;
    }

    toggleSidebar(show = null) {
        const shouldShow = show !== null ? show : this.sidebar.classList.contains('collapsed');

        this.sidebar.classList.toggle('collapsed', !shouldShow);
        this.sidebarToggle.classList.toggle('collapsed', !shouldShow);
        this.mainContent.classList.toggle('sidebar-collapsed', !shouldShow);

        // Update main content margin
        if (shouldShow) {
            this.mainContent.style.marginLeft = this.sidebarWidth + 'px';
        } else {
            this.mainContent.style.marginLeft = '0px';
        }

        this.sidebarToggle.innerHTML = shouldShow ? '◀' : '▶';
        this.sidebarToggle.title = shouldShow ? 'Hide Sidebar' : 'Show Sidebar';

        this.isCollapsed = !shouldShow;
    }

    connectHistoryStream() {
        if (this.historyEventSource) {
            this.historyEventSource.close();
        }

        this.historyEventSource = new EventSource('/api/git/history/events');

        this.historyEventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            switch (data.type) {
                case 'new_commit':
                    this.loadHistory(); // Refresh history when new commit
                    break;
                case 'checkout':
                    this.loadHistory(); // Refresh to show current commit
                    this.addConsoleLine(`Checked out: ${data.data.message}`, 'info');
                    break;
                case 'branch_switched':
                    this.currentBranch = data.data.branch;
                    this.loadHistory();
                    this.loadBranches(); // Refresh branch list
                    break;
            }
        };

        this.historyEventSource.onerror = () => {
            setTimeout(() => this.connectHistoryStream(), 5000);
        };
    }

    connectConsoleStream() {
        if (this.consoleEventSource) {
            this.consoleEventSource.close();
        }

        this.consoleEventSource = new EventSource('/api/fac/console/events');

        this.consoleEventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            switch (data.type) {
                case 'console_log':
                case 'console_command':
                case 'console_output':
                    // Use the formatted message to preserve tree structure and colors
                    // Don't add timestamp prefix for formatted console output
                    this.addConsoleLineRaw(data.message, data.level.toLowerCase());
                    break;
                case 'clear_console':
                    this.consoleOutput.innerHTML = '';
                    break;
            }
        };

        this.consoleEventSource.onerror = () => {
            setTimeout(() => this.connectConsoleStream(), 5000);
        };
    }


    async loadBranches() {
        try {
            const response = await fetch('/api/git/branches');
            const data = await response.json();

            if (data.success) {
                this.renderBranches(data.branches, data.current_branch);
            }
        } catch (error) {
            console.error('Failed to load git branches:', error);
        }
    }
    renderBranches(branches, currentBranch, detachedInfo) {
        this.currentBranch = currentBranch;
        this.branchSelect.innerHTML = '';
        
        if (detachedInfo) {
            // Show detached HEAD state
            const option = document.createElement('option');
            option.value = '';
            option.textContent = detachedInfo;
            option.selected = true;
            option.disabled = true;
            option.style.fontStyle = 'italic';
            option.style.color = '#666';
            this.branchSelect.appendChild(option);
            
            // Add separator
            const separator = document.createElement('option');
            separator.disabled = true;
            separator.textContent = '────────────────';
            this.branchSelect.appendChild(separator);
        }
        
        branches.forEach(branch => {
            const option = document.createElement('option');
            option.value = branch;
            option.textContent = branch;
            option.selected = branch === currentBranch && !detachedInfo;
            this.branchSelect.appendChild(option);
        });
    }

    async switchBranch(branchName) {
        if (branchName === this.currentBranch) return;

        try {
            const response = await fetch('/api/git/switch-branch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ branch_name: branchName })
            });

            const data = await response.json();

            if (data.success) {
                this.addConsoleLine(`✓ Switched to branch: ${branchName}`, 'info');
                this.currentBranch = branchName;
                this.loadHistory();
            } else {
                this.addConsoleLine(`✗ Failed to switch branch: ${data.error}`, 'error');
                // Reset dropdown to current branch
                this.branchSelect.value = this.currentBranch;
            }
        } catch (error) {
            this.addConsoleLine(`✗ Branch switch error: ${error.message}`, 'error');
            this.branchSelect.value = this.currentBranch;
        }
    }

    async createNewBranch() {
        const branchName = prompt('Enter new branch name:');
        if (!branchName || !branchName.trim()) return;

        try {
            const response = await fetch('/api/git/create-branch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ branch_name: branchName.trim() })
            });

            const data = await response.json();

            if (data.success) {
                this.addConsoleLine(`✓ Created and switched to branch: ${branchName}`, 'info');
                this.loadBranches(); // Refresh branch list
                this.loadHistory(); // Refresh history
            } else {
                this.addConsoleLine(`✗ Failed to create branch: ${data.error}`, 'error');
            }
        } catch (error) {
            this.addConsoleLine(`✗ Branch creation error: ${error.message}`, 'error');
        }
    }

    async loadHistory() {
        try {
            const response = await fetch(`/api/git/history?branch=${encodeURIComponent(this.currentBranch)}`);
            const data = await response.json();

            if (data.success) {
                this.renderHistory(data.commits);
            }
        } catch (error) {
            console.error('Failed to load git history:', error);
        }
    }

    formatTimeDisplay(timestamp) {
        const now = new Date();
        const commitDate = new Date(timestamp * 1000);

        if (this.showRelativeTime) {
            return this.getRelativeTimeString(now, commitDate);
        } else {
            // Check if commit is from today
            const isToday = now.toDateString() === commitDate.toDateString();

            if (isToday) {
                return commitDate.toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } else {
                return commitDate.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric'
                });
            }
        }
    }

    getRelativeTimeString(now, past) {
        const diffMs = now.getTime() - past.getTime();
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);
        const diffWeek = Math.floor(diffDay / 7);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin} minute${diffMin === 1 ? '' : 's'} ago`;
        if (diffHour < 24) return `${diffHour} hour${diffHour === 1 ? '' : 's'} ago`;
        if (diffDay < 7) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
        if (diffWeek < 4) return `${diffWeek} week${diffWeek === 1 ? '' : 's'} ago`;

        // For longer periods, show the actual date
        return past.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: past.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
        });
    }

    renderHistory(commits) {
        this.historyList.innerHTML = '';

        commits.forEach(commit => {
            const item = document.createElement('div');
            item.className = 'history-item';
            if (commit.is_current) {
                item.classList.add('current-commit');
            }
            item.dataset.hash = commit.full_hash;

            const timeStr = this.formatTimeDisplay(commit.date);

            item.innerHTML = `
                <span class="commit-time">* ${timeStr}</span>
                <span class="commit-message">${commit.message}</span>
            `;

            item.addEventListener('click', () => {
                this.checkoutCommit(commit.full_hash);
            });

            this.historyList.appendChild(item);
        });

        // Clean up any lingering loading states
        this.cleanupLoadingStates();
    }

    cleanupLoadingStates() {
        // Remove loading states from any items that might still have them
        const loadingItems = this.historyList.querySelectorAll('[style*="italic"]');
        loadingItems.forEach(item => {
            if (!item.classList.contains('current-commit')) {
                item.style.fontStyle = '';
                const commitMessage = item.querySelector('.commit-message');
                if (commitMessage && commitMessage.dataset.originalText) {
                    commitMessage.textContent = commitMessage.dataset.originalText;
                    delete commitMessage.dataset.originalText;
                }
            }
        });
    }

    async checkoutCommit(hash) {
        // Find the history item element and add loading state
        const historyItem = document.querySelector(`[data-hash="${hash}"]`);
        if (historyItem) {
            historyItem.style.fontStyle = 'italic';
            const commitMessage = historyItem.querySelector('.commit-message');
            if (commitMessage) {
                const originalText = commitMessage.textContent;
                commitMessage.textContent = '(loading...) ' + originalText;
                commitMessage.dataset.originalText = originalText;
            }
        }

        try {
            const response = await fetch('/api/git/checkout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ commit_hash: hash })
            });

            const data = await response.json();

            if (data.success) {
                this.addConsoleLine(`✓ ${data.message}`, 'info');
                // History will be refreshed automatically via SSE, but we can also update branch display immediately
                this.updateBranchForDetachedHead(hash);
            } else {
                this.addConsoleLine(`✗ Checkout failed: ${data.error}`, 'error');
                // Restore original state on error
                if (historyItem) {
                    historyItem.style.fontStyle = '';
                    const commitMessage = historyItem.querySelector('.commit-message');
                    if (commitMessage && commitMessage.dataset.originalText) {
                        commitMessage.textContent = commitMessage.dataset.originalText;
                        delete commitMessage.dataset.originalText;
                    }
                }
            }
        } catch (error) {
            this.addConsoleLine(`✗ Checkout error: ${error.message}`, 'error');
            // Restore original state on error
            if (historyItem) {
                historyItem.style.fontStyle = '';
                const commitMessage = historyItem.querySelector('.commit-message');
                if (commitMessage && commitMessage.dataset.originalText) {
                    commitMessage.textContent = commitMessage.dataset.originalText;
                    delete commitMessage.dataset.originalText;
                }
            }
        }
    }

    updateBranchForDetachedHead(hash) {
        // Update branch select to show detached HEAD
        const shortHash = hash.substring(0, 7);
        const detachedOption = document.createElement('option');
        detachedOption.value = '';
        detachedOption.textContent = `detached HEAD at ${shortHash}`;
        detachedOption.selected = true;
        detachedOption.disabled = true;
        
        // Remove any existing detached HEAD option
        const existingDetached = this.branchSelect.querySelector('option[disabled]');
        if (existingDetached) {
            existingDetached.remove();
        }
        
        // Insert at the beginning
        this.branchSelect.insertBefore(detachedOption, this.branchSelect.firstChild);
    }


    addConsoleLine(message, level = 'info') {
        const line = document.createElement('div');
        line.className = `console-line ${level}`;
        line.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;

        this.consoleOutput.appendChild(line);
        this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
    }

    addConsoleLineRaw(formattedMessage, level = 'info') {
        const line = document.createElement('div');
        line.className = `console-line ${level}`;

        // Use innerHTML to render the HTML formatting from ANSI conversion
        // Don't add timestamp prefix - the message is already formatted
        line.innerHTML = formattedMessage;

        this.consoleOutput.appendChild(line);
        // Auto-scroll to bottom
        this.consoleOutput.scrollTop = this.consoleOutput.scrollHeight;
    }

    async clearConsole() {
        try {
            await fetch('/api/fac/console/clear', { method: 'POST' });
            this.consoleOutput.innerHTML = '';
        } catch (error) {
            console.error('Failed to clear console:', error);
        }
    }
}

// Initialize sidebar when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.sidebar = new Sidebar();
});

