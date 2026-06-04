// git.js
//
// This component displays the git history as a tab.
// It monitors the /git_events SSE endpoint and redraws the commit graph whenever
// the repository state changes.
//
// Features:
// - Displays commits in a graph format similar to "git log --graph --oneline --decorate --all"
// - Renders branch/merge lines connecting commits in a DAG structure
// - Shows timestamp for each commit
// - Highlights HEAD commit
// - Hover over a commit to see full message and diff stats
// - Click on a commit to checkout that commit

(function() {
  let eventSource = null;
  let commits = [];
  let container = null;
  let isUnloading = false;

  window.addEventListener('beforeunload', () => {
    isUnloading = true;
  });

  // Colors for different branch lanes
  const LANE_COLORS = [
    '#e8b84a', // yellow
    '#4ae88b', // green
    '#4a8be8', // blue
    '#e84a8b', // pink
    '#8b4ae8', // purple
    '#e8584a', // red
    '#4ae8e8', // cyan
    '#e8e84a', // lime
  ];

  function init(tabContainer) {
    container = document.createElement('div');
    container.className = 'git-container';

    const graph = document.createElement('div');
    graph.className = 'git-graph';
    graph.id = 'git-graph';
    container.appendChild(graph);

    tabContainer.appendChild(container);

    connectToGitEvents();
  }

  function connectToGitEvents() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/git_events');

    eventSource.onmessage = function(event) {
      try {
        commits = JSON.parse(event.data);
        renderGraph();
      } catch (e) {
        console.error('Error parsing git events:', e);
      }
    };

    eventSource.onerror = function() {
      if (isUnloading) {
        return;
      }
      console.error('Git events connection error, reconnecting...');
      setTimeout(connectToGitEvents, 3000);
    };
  }

  // Compute lane assignments for each commit to render the DAG
  function computeLanes(commits) {
    if (commits.length === 0) return { laneData: [], maxLanes: 0 };

    // Map from hash to commit index
    const hashToIndex = new Map();
    commits.forEach((c, i) => hashToIndex.set(c.full_hash, i));

    // Track which commits are the first appearance of their lane
    const laneFirstCommit = new Map();

    // Active lanes: each lane holds the hash of the commit it's waiting for
    let activeLanes = [];
    const laneData = [];
    let maxLanes = 0;

    for (let i = 0; i < commits.length; i++) {
      const commit = commits[i];
      const hash = commit.full_hash;
      const parents = commit.parents || [];

      // Find which lane this commit occupies (if any lane is waiting for it)
      let myLane = activeLanes.indexOf(hash);
      
      if (myLane === -1) {
        // This commit starts a new lane - find first empty slot or append
        myLane = activeLanes.indexOf(null);
        if (myLane === -1) {
          myLane = activeLanes.length;
          activeLanes.push(null);
        }
      }

      // Check if this is the first commit in this lane
      const isLaneStart = !laneFirstCommit.has(myLane) || laneFirstCommit.get(myLane) === hash;
      if (!laneFirstCommit.has(myLane)) {
        laneFirstCommit.set(myLane, hash);
      }

      // Record which lanes are continuing through this row (before we modify)
      const continuingLanes = activeLanes.map((h, idx) => h !== null && h !== hash ? idx : -1).filter(x => x >= 0);

      // The lane for this commit now becomes free
      activeLanes[myLane] = null;

      // Track merge lines: which lanes merge into this commit
      const mergeFromLanes = [];
      for (let idx = 0; idx < activeLanes.length; idx++) {
        if (idx !== myLane && activeLanes[idx] === hash) {
          mergeFromLanes.push(idx);
          activeLanes[idx] = null;
        }
      }

      // Assign parents to lanes
      const parentLanes = [];
      for (let p = 0; p < parents.length; p++) {
        const parentHash = parents[p];
        const parentIndex = hashToIndex.get(parentHash);
        
        if (parentIndex === undefined) {
          // Parent not in our list (truncated history)
          continue;
        }

        if (p === 0) {
          // First parent continues in the same lane
          activeLanes[myLane] = parentHash;
          parentLanes.push({ lane: myLane, hash: parentHash });
        } else {
          // Additional parents need new lanes (or reuse empty ones)
          let newLane = activeLanes.indexOf(null);
          if (newLane === -1) {
            newLane = activeLanes.length;
            activeLanes.push(null);
          }
          // Mark that this lane will start fresh with the parent
          if (!laneFirstCommit.has(newLane)) {
            laneFirstCommit.set(newLane, parentHash);
          }
          activeLanes[newLane] = parentHash;
          parentLanes.push({ lane: newLane, hash: parentHash });
        }
      }

      // Trim trailing nulls from activeLanes
      while (activeLanes.length > 0 && activeLanes[activeLanes.length - 1] === null) {
        activeLanes.pop();
      }

      maxLanes = Math.max(maxLanes, activeLanes.length, myLane + 1);

      laneData.push({
        lane: myLane,
        continuingLanes: continuingLanes,
        mergeFromLanes: mergeFromLanes,
        parentLanes: parentLanes,
        totalLanes: Math.max(activeLanes.length, myLane + 1, ...continuingLanes.map(l => l + 1), ...mergeFromLanes.map(l => l + 1)),
        isLaneStart: isLaneStart
      });
    }

    return { laneData, maxLanes };
  }

  function renderGraph() {
    const graphContainer = document.getElementById('git-graph');
    if (!graphContainer) return;

    graphContainer.innerHTML = '';

    const { laneData, maxLanes } = computeLanes(commits);

    for (let i = 0; i < commits.length; i++) {
      const commit = commits[i];
      const lanes = laneData[i];
      const isFirst = (i === 0);
      const isLast = (i === commits.length - 1);
      const commitEl = createCommitElement(commit, lanes, maxLanes, isFirst, isLast);
      graphContainer.appendChild(commitEl);
    }
  }

  function createCommitElement(commit, lanes, maxLanes, isFirst, isLast) {
    const div = document.createElement('div');
    div.className = 'git-commit';
    if (commit.is_head) {
      div.classList.add('is-head');
    }

    // Graph columns
    const graphCols = document.createElement('div');
    graphCols.className = 'git-graph-columns';

    const numCols = Math.max(lanes.totalLanes, 1);
    
    for (let col = 0; col < numCols; col++) {
      const colDiv = document.createElement('div');
      colDiv.className = 'git-graph-column';
      const color = LANE_COLORS[col % LANE_COLORS.length];

      const isCommitLane = (col === lanes.lane);
      const isContinuing = lanes.continuingLanes.includes(col);
      const isMergeSource = lanes.mergeFromLanes.includes(col);
      const isBranchTarget = lanes.parentLanes.some(pl => pl.lane === col && col !== lanes.lane);

      // Check if this lane just started (it's a branch target but wasn't continuing from above)
      const isNewBranch = isBranchTarget && !isContinuing && !isMergeSource;

      // Determine what lines to draw
      let drawTop = false;
      let drawBottom = false;
      let drawNode = false;
      
      if (isCommitLane) {
        drawNode = true;
        // Draw line up if this isn't the start of this lane or if merges come in
        drawTop = !lanes.isLaneStart || lanes.mergeFromLanes.length > 0;
        // Draw line down if there are parents
        drawBottom = lanes.parentLanes.length > 0;
      } else if (isContinuing) {
        drawTop = true;
        drawBottom = true;
      } else if (isNewBranch) {
        // New branch starting here - only draw bottom, not top
        drawTop = false;
        drawBottom = true;
      } else if (isMergeSource) {
        // Line coming from above, ending here with horizontal to commit
        drawTop = true;
        drawBottom = false;
      } else if (isBranchTarget) {
        drawTop = false;
        drawBottom = true;
      }

      // Draw vertical lines
      if (drawTop && drawBottom) {
        const lineFull = document.createElement('div');
        lineFull.className = 'git-graph-line-vertical full';
        lineFull.style.backgroundColor = color;
        colDiv.appendChild(lineFull);
      } else {
        if (drawTop) {
          const lineUp = document.createElement('div');
          lineUp.className = 'git-graph-line-vertical top';
          lineUp.style.backgroundColor = color;
          colDiv.appendChild(lineUp);
        }
        if (drawBottom) {
          const lineDown = document.createElement('div');
          lineDown.className = 'git-graph-line-vertical bottom';
          lineDown.style.backgroundColor = color;
          colDiv.appendChild(lineDown);
        }
      }

      // Draw node
      if (drawNode) {
        const node = document.createElement('div');
        node.className = 'git-graph-node';
        node.style.backgroundColor = color;
        colDiv.appendChild(node);
      }

      // Draw horizontal lines for merges (from right lanes merging into commit lane)
      if (isCommitLane) {
        for (const fromLane of lanes.mergeFromLanes) {
          if (fromLane > col) {
            const mergeLine = document.createElement('div');
            mergeLine.className = 'git-graph-line-horizontal';
            mergeLine.style.backgroundColor = LANE_COLORS[fromLane % LANE_COLORS.length];
            mergeLine.style.left = '8px';
            mergeLine.style.width = ((fromLane - col) * 16) + 'px';
            colDiv.appendChild(mergeLine);
          }
        }

        // Draw horizontal lines for branches (to right lanes for additional parents)
        for (const pl of lanes.parentLanes) {
          if (pl.lane > col) {
            const branchLine = document.createElement('div');
            branchLine.className = 'git-graph-line-horizontal';
            branchLine.style.backgroundColor = LANE_COLORS[pl.lane % LANE_COLORS.length];
            branchLine.style.left = '8px';
            branchLine.style.width = ((pl.lane - col) * 16) + 'px';
            colDiv.appendChild(branchLine);
          }
        }
      }

      graphCols.appendChild(colDiv);
    }

    div.appendChild(graphCols);

    // Commit info
    const info = document.createElement('div');
    info.className = 'git-commit-info';

    // Header line: hash, refs, message
    const header = document.createElement('div');
    header.className = 'git-commit-header';

    // Hash
    const hash = document.createElement('span');
    hash.className = 'git-hash';
    hash.textContent = commit.hash;
    header.appendChild(hash);

    // Refs (branches, tags, HEAD)
    const refs = document.createElement('span');
    refs.className = 'git-refs';

    if (commit.is_head) {
      const headIndicator = document.createElement('span');
      headIndicator.className = 'git-head-indicator';
      headIndicator.textContent = 'HEAD';
      refs.appendChild(headIndicator);
    }

    for (const branch of commit.branches) {
      const branchEl = document.createElement('span');
      branchEl.className = 'git-branch';
      if (branch.startsWith('origin/') || branch.startsWith('remotes/')) {
        branchEl.classList.add('remote');
      }
      branchEl.textContent = branch;
      refs.appendChild(branchEl);
    }

    for (const tag of commit.tags) {
      const tagEl = document.createElement('span');
      tagEl.className = 'git-tag';
      tagEl.textContent = tag;
      refs.appendChild(tagEl);
    }

    if (refs.children.length > 0) {
      header.appendChild(refs);
    }

    // Message (first line only)
    const message = document.createElement('span');
    message.className = 'git-message';
    message.textContent = getFirstLine(commit.message);
    header.appendChild(message);

    info.appendChild(header);

    // Timestamp
    const timestamp = document.createElement('div');
    timestamp.className = 'git-timestamp';
    timestamp.textContent = formatTimestamp(commit.date);
    info.appendChild(timestamp);

    div.appendChild(info);

    // Tooltip for hover
    const tooltip = createTooltip(commit);
    div.appendChild(tooltip);

    // Position tooltip on hover
    div.addEventListener('mouseenter', function(e) {
      const rect = div.getBoundingClientRect();
      tooltip.style.left = (rect.right + 5) + 'px';
      tooltip.style.top = rect.top + 'px';
      // Keep tooltip on screen vertically
      requestAnimationFrame(() => {
        const tooltipRect = tooltip.getBoundingClientRect();
        if (tooltipRect.bottom > window.innerHeight) {
          tooltip.style.top = (window.innerHeight - tooltipRect.height - 10) + 'px';
        }
      });
    });

    // Click handler for checkout
    div.addEventListener('click', function() {
      checkoutCommit(commit.hash);
    });

    return div;
  }

  function createTooltip(commit) {
    const tooltip = document.createElement('div');
    tooltip.className = 'git-commit-tooltip';

    // Header
    const header = document.createElement('div');
    header.className = 'git-tooltip-header';

    const hash = document.createElement('div');
    hash.className = 'git-tooltip-hash';
    hash.textContent = commit.full_hash;
    header.appendChild(hash);

    const author = document.createElement('div');
    author.className = 'git-tooltip-author';
    author.textContent = 'Author: ' + commit.author;
    header.appendChild(author);

    const date = document.createElement('div');
    date.className = 'git-tooltip-date';
    date.textContent = formatFullDate(commit.date);
    header.appendChild(date);

    tooltip.appendChild(header);

    // Full message
    const message = document.createElement('div');
    message.className = 'git-tooltip-message';
    message.textContent = commit.message;
    tooltip.appendChild(message);

    // Diff stats
    if (commit.diff_stats && commit.diff_stats.length > 0) {
      const stats = document.createElement('div');
      stats.className = 'git-tooltip-stats';

      const statsHeader = document.createElement('div');
      statsHeader.className = 'git-tooltip-stats-header';
      statsHeader.textContent = 'Files changed: ' + commit.diff_stats.length;
      stats.appendChild(statsHeader);

      for (const stat of commit.diff_stats) {
        const line = document.createElement('div');
        line.className = 'git-stat-line';

        const path = document.createElement('span');
        path.className = 'git-stat-path';
        path.textContent = stat.path;
        path.title = stat.path;
        line.appendChild(path);

        const changes = document.createElement('span');
        changes.className = 'git-stat-changes';

        const additions = document.createElement('span');
        additions.className = 'git-stat-additions';
        additions.textContent = '+' + stat.additions;
        changes.appendChild(additions);

        const deletions = document.createElement('span');
        deletions.className = 'git-stat-deletions';
        deletions.textContent = '-' + stat.deletions;
        changes.appendChild(deletions);

        line.appendChild(changes);

        // Visual bar
        const total = stat.additions + stat.deletions;
        if (total > 0) {
          const bar = document.createElement('div');
          bar.className = 'git-stat-bar';

          const addWidth = (stat.additions / total) * 100;
          const delWidth = (stat.deletions / total) * 100;

          if (stat.additions > 0) {
            const addBar = document.createElement('div');
            addBar.className = 'git-stat-bar-add';
            addBar.style.width = addWidth + '%';
            bar.appendChild(addBar);
          }

          if (stat.deletions > 0) {
            const delBar = document.createElement('div');
            delBar.className = 'git-stat-bar-del';
            delBar.style.width = delWidth + '%';
            bar.appendChild(delBar);
          }

          line.appendChild(bar);
        }

        stats.appendChild(line);
      }

      tooltip.appendChild(stats);
    }

    return tooltip;
  }

  function getFirstLine(message) {
    if (!message) return '';
    const lines = message.split('\n');
    return lines[0] || '';
  }

  function formatTimestamp(isoDate) {
    try {
      const date = new Date(isoDate);
      const now = new Date();
      const diff = now - date;

      // Less than 24 hours: show relative time
      if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        if (hours < 1) {
          const minutes = Math.floor(diff / 60000);
          return minutes <= 1 ? 'just now' : minutes + ' minutes ago';
        }
        return hours === 1 ? '1 hour ago' : hours + ' hours ago';
      }

      // Less than 7 days: show days ago
      if (diff < 604800000) {
        const days = Math.floor(diff / 86400000);
        return days === 1 ? '1 day ago' : days + ' days ago';
      }

      // Otherwise show date
      return date.toLocaleDateString();
    } catch (e) {
      return isoDate;
    }
  }

  function formatFullDate(isoDate) {
    try {
      const date = new Date(isoDate);
      return date.toLocaleString();
    } catch (e) {
      return isoDate;
    }
  }

  function checkoutCommit(ref) {
    fetch('/git_checkout', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ ref: ref })
    })
    .then(response => response.json())
    .then(data => {
      if (!data.success) {
        alert('Checkout failed: ' + data.message);
      }
    })
    .catch(error => {
      console.error('Checkout error:', error);
      alert('Checkout failed: ' + error.message);
    });
  }

  // Register as a tab
  window.registerTab({
    id: 'git',
    label: 'Git History',
    pane: 'sidebar',
    render: init
  });
})();
