// jobs.js
//
// This component displays build jobs from the /get_jobs endpoint.
// Shows job status (queued, running, succeeded, failed) with visual indicators,
// job metadata (times, job_id), and the list of paths being built.
// Jobs are sorted by job_id with newest first.

(function() {
    let container = null;
    let pollInterval = null;

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

    async function fetchJobs() {
        try {
            const response = await fetch('/get_jobs');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const jobs = await response.json();
            
            // Sort by job_id descending (newest first)
            jobs.sort((a, b) => b.job_id - a.job_id);
            
            renderJobs(jobs);
        } catch (error) {
            console.error('jobs.js: Failed to fetch jobs', error);
            if (container) {
                container.innerHTML = `<div class="jobs-error">Failed to load jobs: ${escapeHtml(error.message)}</div>`;
            }
        }
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
                <div class="jobs-list"></div>
            </div>
        `;
        fetchJobs();
    }

    function onActivate() {
        fetchJobs();
        pollInterval = setInterval(fetchJobs, 1000);
    }

    function onDeactivate() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
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
