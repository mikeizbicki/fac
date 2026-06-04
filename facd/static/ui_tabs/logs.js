// logs.js
//
// This component displays streaming logs from the /logs_stream endpoint
// in a terminal-like interface. Logs are displayed in real-time via SSE
// and can be cleared with a button at the bottom.

(function() {
    let logsOutput = null;
    let eventSource = null;
    let autoScroll = true;
    let isUnloading = false;

    window.addEventListener('beforeunload', () => {
        isUnloading = true;
    });

    function classifyLogLine(line) {
        const lowerLine = line.toLowerCase();
        if (lowerLine.includes('error') || lowerLine.includes('exception') || lowerLine.includes('failed')) {
            return 'logs-error';
        }
        if (lowerLine.includes('warning') || lowerLine.includes('warn')) {
            return 'logs-warning';
        }
        if (lowerLine.includes('success') || lowerLine.includes('complete') || lowerLine.includes('finished')) {
            return 'logs-success';
        }
        if (lowerLine.includes('debug')) {
            return 'logs-debug';
        }
        return 'logs-info';
    }

    function appendLog(text) {
        if (!logsOutput) return;

        const emptyMsg = logsOutput.querySelector('.logs-empty');
        if (emptyMsg) {
            emptyMsg.remove();
        }

        const line = document.createElement('div');
        line.className = 'logs-line ' + classifyLogLine(text);
        line.textContent = text;
        logsOutput.appendChild(line);

        if (autoScroll) {
            logsOutput.scrollTop = logsOutput.scrollHeight;
        }
    }

    function clearLogs() {
        if (!logsOutput) return;
        logsOutput.innerHTML = '<div class="logs-empty">Logs cleared. Waiting for new output...</div>';
    }

    function connectToStream() {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource('/logs_stream');

        eventSource.onmessage = function(event) {
            appendLog(event.data);
        };

        eventSource.onerror = function(err) {
            if (isUnloading) {
                return;
            }
            console.error('logs.js: SSE connection error', err);
            appendLog('[Connection lost. Reconnecting...]');
        };
    }

    function setupScrollDetection() {
        if (!logsOutput) return;

        logsOutput.addEventListener('scroll', function() {
            const isAtBottom = logsOutput.scrollHeight - logsOutput.scrollTop - logsOutput.clientHeight < 50;
            autoScroll = isAtBottom;
        });
    }

    function render(container) {
        container.innerHTML = `
            <div class="logs-container">
                <div class="logs-output">
                    <div class="logs-empty">Connecting to log stream...</div>
                </div>
                <div class="logs-toolbar">
                    <button class="logs-clear-btn">Clear Logs</button>
                </div>
            </div>
        `;

        logsOutput = container.querySelector('.logs-output');
        const clearBtn = container.querySelector('.logs-clear-btn');

        clearBtn.addEventListener('click', clearLogs);
        setupScrollDetection();
        connectToStream();
    }

    function onActivate() {
        if (logsOutput) {
            logsOutput.scrollTop = logsOutput.scrollHeight;
        }
    }

    function onDeactivate() {
        // Nothing special needed on deactivate
    }

    window.registerTab({
        id: 'logs',
        label: 'Logs',
        pane: 'sidebar',
        render: render,
        onActivate: onActivate,
        onDeactivate: onDeactivate
    });
})();
