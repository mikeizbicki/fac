// jobs.js
//
// This component displays build jobs from the /monitor_jobs SSE endpoint.
// Shows job status (queued, running, succeeded, failed) with visual indicators,
// job metadata (times, job_id), and the list of paths being built.
// Jobs are sorted by job_id with newest first.

(function() {
    let container = null;
    let eventSource = null;

    function formatTime(isoString) {
        if (!isoString) return '-';
        const date = new Date(isoString);
        return date.toLocaleTimeString();
    }

    function formatDuration(startTime, endTime) {
        if (!startTime) return '';
        const start = new Date(startTime);
        const end = endTime ? new Date(endTime) : new Date();
        const seconds = Math.round((end - start) / 1000);
        if (seconds < 60) return `${seconds}s`;
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${minutes}m ${secs}s`;
    }

    function getStatusIcon(state) {
        switch (state) {
            case 'queued':
            case 'running':
                return '<span class="job-status-icon spinning">◌</span>';
            case 'succeeded':
                return '<span class="job-status-icon success">✓</span>';
            case 'failed':
                return '<span class="job-status-icon failed">✗</span>';
            default:
                return '<span class="job-status-icon">?</span>';
        }
    }

    function getPathStatusClass(status) {
        switch (status) {
            case 'queued': return 'path-queued';
            case 'building': return 'path-building';
            case 'up-to-date': return 'path-uptodate';
            default: return '';
        }
    }

    function getModeClass(mode) {
        switch (mode) {
            case 'dryrun': return 'mode-dryrun';
            case 'overwrite': return 'mode-overwrite';
            case 'build': return 'mode-build';
            default: return '';
        }
    }

    function renderJob(job) {
        const stateClass = `job-${job.state}`;
        const pathsHtml = job.paths.map(p => {
            const statusClass = getPathStatusClass(p.status);
            const modeClass = getModeClass(p.mode);
            return `
                <div class="job-path ${statusClass}">
                    <span class="job-path-name">${escapeHtml(p.path)}</span>
                    <span class="job-path-status">${p.status}</span>
                    <span class="job-path-mode ${modeClass}">${p.mode}</span>
                </div>
            `;
        }).join('');

        const duration = (job.state === 'running' || job.state === 'succeeded' || job.state === 'failed')
            ? formatDuration(job.start_time, job.end_time)
            : '';

        return `
            <div class="job-item ${stateClass}">
                <div class="job-header">
                    ${getStatusIcon(job.state)}
                    <span class="job-id">Job #${job.job_id}</span>
                    <span class="job-state">${job.state}</span>
                    ${duration ? `<span class="job-duration">${duration}</span>` : ''}
                </div>
                <div class="job-times">
                    <span class="job-time-label">Queued:</span>
                    <span class="job-time-value">${formatTime(job.enqueued_time)}</span>
                    ${job.start_time ? `
                        <span class="job-time-label">Started:</span>
                        <span class="job-time-value">${formatTime(job.start_time)}</span>
                    ` : ''}
                    ${job.end_time ? `
                        <span class="job-time-label">Ended:</span>
                        <span class="job-time-value">${formatTime(job.end_time)}</span>
                    ` : ''}
                </div>
                <div class="job-paths">
                    <div class="job-paths-header">Paths (${job.paths.length}):</div>
                    <div class="job-paths-list">
                        ${pathsHtml}
                    </div>
                </div>
            </div>
        `;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function connectSSE() {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource('/monitor_jobs');

        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                
                if (data.error) {
                    console.error('jobs.js: Server error', data.error);
                    if (container) {
                        container.querySelector('.jobs-list').innerHTML = 
                            `<div class="jobs-error">Server error: ${escapeHtml(data.error)}</div>`;
                    }
                    return;
                }

                // Sort by job_id descending (newest first)
                data.sort((a, b) => b.job_id - a.job_id);
                renderJobs(data);
            } catch (error) {
                console.error('jobs.js: Failed to parse SSE data', error);
            }
        };

        eventSource.onerror = function(error) {
            console.error('jobs.js: SSE connection error', error);
            if (container) {
                const jobsList = container.querySelector('.jobs-list');
                if (jobsList && jobsList.children.length === 0) {
                    jobsList.innerHTML = '<div class="jobs-error">Connection lost. Reconnecting...</div>';
                }
            }
        };
    }

    function renderJobs(jobs) {
        if (!container) return;

        const jobsContainer = container.querySelector('.jobs-list');
        if (!jobsContainer) return;

        if (jobs.length === 0) {
            jobsContainer.innerHTML = '<div class="jobs-empty">No jobs</div>';
            return;
        }

        jobsContainer.innerHTML = jobs.map(renderJob).join('');
    }

    function render(containerEl) {
        container = containerEl;
        container.innerHTML = `
            <div class="jobs-container">
                <div class="jobs-list">
                    <div class="jobs-loading">Connecting...</div>
                </div>
            </div>
        `;
    }

    function onActivate() {
        connectSSE();
    }

    function onDeactivate() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    }

    window.registerTab({
        id: 'jobs',
        label: 'Jobs',
        pane: 'sidebar',
        render: render,
        onActivate: onActivate,
        onDeactivate: onDeactivate
    });
})();
