let targets = {};

function buildTree(paths) {
    const tree = {};
    for (const path in paths) {
        const parts = path.split('/');
        let current = tree;
        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            if (!current[part]) {
                current[part] = {};
            }
            current = current[part];
        }
    }
    return tree;
}

function renderTree(tree, container) {
    for (const key in tree) {
        const div = document.createElement('div');
        div.className = 'tree-node';

        const label = document.createElement('span');
        label.className = 'tree-label';
        label.textContent = key;
        div.appendChild(label);

        const children = Object.keys(tree[key]);
        if (children.length > 0) {
            const childContainer = document.createElement('div');
            renderTree(tree[key], childContainer);
            div.appendChild(childContainer);
        }

        container.appendChild(div);
    }
}

fetch('/list_targets')
    .then(response => response.json())
    .then(data => {
        targets = data;
        const tree = buildTree(targets);
        const container = document.getElementById('targets-container');
        renderTree(tree, container);
    });

