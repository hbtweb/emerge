"""
Unified Emerge Viewer Template - Combines traditional viewer features with WebSocket real-time updates.

Features:
- Bootstrap 5 UI with dark mode
- D3 force-directed graph (canvas-based)
- Node search with semantic option
- Cluster hulls (Louvain modularity)
- Heatmaps (normal, hybrid, churn, hotspot)
- Force/zoom controls
- Statistics and metrics modals
- Real-time WebSocket updates
"""

# Authors: Grzegorz Lato <grzegorz.lato@gmail.com>
# License: MIT


def generate_unified_viewer_html(ws_port: int) -> str:
    """Generate the unified viewer HTML with all features."""
    return f'''<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Emerge - Unified Graph Viewer</title>
    <!-- Bootstrap 5 -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css" rel="stylesheet">
    <!-- D3.js -->
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <!-- Hull.js for cluster hulls -->
    <script src="https://cdn.jsdelivr.net/npm/hull.js@1.0.2/dist/hull.min.js"></script>
    <!-- simpleheat for heatmaps -->
    <script src="https://cdn.jsdelivr.net/npm/simpleheat@0.4.0/simpleheat.min.js"></script>
    <style>
        :root {{
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-tertiary: #0f3460;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --accent: #3b82f6;
            --accent-hover: #2563eb;
            --success: #4ade80;
            --warning: #fbbf24;
            --danger: #f87171;
        }}
        [data-theme="light"] {{
            --bg-primary: #f8f9fa;
            --bg-secondary: #e9ecef;
            --bg-tertiary: #dee2e6;
            --text-primary: #212529;
            --text-secondary: #6c757d;
        }}
        body {{
            margin: 0;
            font-family: system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            overflow: hidden;
        }}
        #container {{
            display: flex;
            height: 100vh;
        }}
        #graphDiv {{
            flex: 1;
            position: relative;
            overflow: hidden;
        }}
        #mainCanvas {{
            display: block;
        }}
        #toolbar {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 100;
            display: flex;
            gap: 5px;
            flex-wrap: wrap;
            max-width: calc(100% - 320px);
        }}
        #sidebar {{
            width: 300px;
            background: var(--bg-secondary);
            padding: 15px;
            overflow-y: auto;
            border-left: 1px solid var(--bg-tertiary);
        }}
        .toolbar-group {{
            display: flex;
            gap: 3px;
            background: var(--bg-secondary);
            padding: 5px;
            border-radius: 6px;
        }}
        .btn-toolbar {{
            padding: 5px 10px;
            font-size: 12px;
            border: none;
            border-radius: 4px;
            background: var(--bg-tertiary);
            color: var(--text-primary);
            cursor: pointer;
        }}
        .btn-toolbar:hover {{
            background: var(--accent);
        }}
        .btn-toolbar.active {{
            background: var(--accent);
        }}
        .status-bar {{
            padding: 8px 12px;
            background: var(--bg-tertiary);
            border-radius: 6px;
            margin-bottom: 15px;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .status-indicator {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--danger);
        }}
        .status-indicator.connected {{
            background: var(--success);
        }}
        .sidebar-section {{
            margin-bottom: 20px;
        }}
        .sidebar-section h6 {{
            color: var(--accent);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
        }}
        .form-select, .form-control {{
            background: var(--bg-tertiary);
            border: 1px solid var(--bg-tertiary);
            color: var(--text-primary);
            font-size: 12px;
        }}
        .form-select:focus, .form-control:focus {{
            background: var(--bg-tertiary);
            border-color: var(--accent);
            color: var(--text-primary);
            box-shadow: none;
        }}
        .form-check-input {{
            background-color: var(--bg-tertiary);
            border-color: var(--text-secondary);
        }}
        .form-check-input:checked {{
            background-color: var(--accent);
            border-color: var(--accent);
        }}
        .form-check-label {{
            font-size: 12px;
        }}
        .node-info {{
            font-size: 12px;
        }}
        .node-info h5 {{
            font-size: 14px;
            word-break: break-all;
            color: var(--accent);
        }}
        .node-info .metric {{
            display: flex;
            justify-content: space-between;
            padding: 3px 0;
            border-bottom: 1px solid var(--bg-tertiary);
        }}
        .cluster-hulls {{
            display: flex;
            flex-wrap: wrap;
            gap: 3px;
        }}
        .cluster-hull-node {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            cursor: pointer;
            border: 1px solid var(--text-secondary);
            transition: transform 0.2s;
        }}
        .cluster-hull-node:hover {{
            transform: scale(1.3);
        }}
        .cluster-hull-node.selected {{
            border: 2px solid var(--warning);
        }}
        .tooltip {{
            position: absolute;
            background: var(--bg-secondary);
            border: 1px solid var(--bg-tertiary);
            border-radius: 6px;
            padding: 10px;
            font-size: 11px;
            pointer-events: none;
            z-index: 1000;
            max-width: 300px;
        }}
        .search-results {{
            max-height: 200px;
            overflow-y: auto;
            font-size: 11px;
        }}
        .search-result-item {{
            padding: 5px 8px;
            cursor: pointer;
            border-radius: 4px;
        }}
        .search-result-item:hover {{
            background: var(--bg-tertiary);
        }}
        .keyboard-shortcuts {{
            font-size: 11px;
        }}
        .keyboard-shortcuts kbd {{
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 10px;
        }}
        /* Toast styles */
        .toast-container {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 1100;
        }}
    </style>
</head>
<body>
<div id="container">
    <div id="graphDiv">
        <div id="toolbar">
            <!-- Graph Selection -->
            <div class="toolbar-group">
                <select id="graphSelect" class="form-select form-select-sm" style="width: 200px;"></select>
            </div>
            <!-- Zoom Controls -->
            <div class="toolbar-group">
                <button class="btn-toolbar" onclick="zoomIn()" title="Zoom In"><i class="bi bi-zoom-in"></i></button>
                <button class="btn-toolbar" onclick="zoomOut()" title="Zoom Out"><i class="bi bi-zoom-out"></i></button>
                <button class="btn-toolbar" onclick="resetView()" title="Reset View"><i class="bi bi-arrows-fullscreen"></i></button>
            </div>
            <!-- Force Controls -->
            <div class="toolbar-group">
                <button class="btn-toolbar" onclick="decreaseForce()" title="Increase Repulsion">-</button>
                <span class="btn-toolbar" style="cursor: default;"><i class="bi bi-magnet"></i> <span id="forceValue">-500</span></span>
                <button class="btn-toolbar" onclick="increaseForce()" title="Decrease Repulsion">+</button>
            </div>
            <!-- Node Labels -->
            <div class="toolbar-group">
                <button class="btn-toolbar" id="btnLabels" onclick="toggleLabels()" title="Toggle Labels"><i class="bi bi-tag"></i></button>
            </div>
            <!-- Heatmap Toggle -->
            <div class="toolbar-group">
                <button class="btn-toolbar" id="btnHeatmap" onclick="cycleHeatmap()" title="Cycle Heatmap Mode"><i class="bi bi-thermometer-half"></i> Off</button>
            </div>
            <!-- Dark Mode -->
            <div class="toolbar-group">
                <button class="btn-toolbar" onclick="toggleDarkMode()" title="Toggle Dark Mode"><i class="bi bi-moon-stars"></i></button>
            </div>
        </div>
    </div>

    <div id="sidebar">
        <!-- Connection Status -->
        <div class="status-bar">
            <div class="status-indicator" id="statusIndicator"></div>
            <span id="statusText">Connecting...</span>
        </div>

        <!-- Search -->
        <div class="sidebar-section">
            <h6>Search</h6>
            <div class="input-group input-group-sm mb-2">
                <input type="text" class="form-control" id="searchInput" placeholder="Search nodes...">
                <button class="btn btn-outline-secondary" type="button" onclick="clearSearch()"><i class="bi bi-x"></i></button>
            </div>
            <div class="form-check form-check-inline">
                <input class="form-check-input" type="checkbox" id="semanticSearch">
                <label class="form-check-label" for="semanticSearch">Semantic</label>
            </div>
            <div id="searchResults" class="search-results mt-2"></div>
            <div id="searchCount" class="text-muted mt-1" style="font-size: 11px;"></div>
        </div>

        <!-- Node Info -->
        <div class="sidebar-section">
            <h6>Node Info</h6>
            <div id="nodeInfo" class="node-info">
                <p class="text-muted">Click or hover a node</p>
            </div>
        </div>

        <!-- Cluster Hulls -->
        <div class="sidebar-section">
            <h6>Cluster Hulls <span class="badge bg-secondary" id="clusterCount">0</span></h6>
            <div id="clusterHulls" class="cluster-hulls"></div>
        </div>

        <!-- Graph Stats -->
        <div class="sidebar-section">
            <h6>Statistics</h6>
            <div id="graphStats" class="node-info">
                <div class="metric"><span>Nodes</span><span id="statNodes">-</span></div>
                <div class="metric"><span>Edges</span><span id="statEdges">-</span></div>
                <div class="metric"><span>Density</span><span id="statDensity">-</span></div>
                <div class="metric"><span>Components</span><span id="statComponents">-</span></div>
            </div>
        </div>

        <!-- Keyboard Shortcuts -->
        <div class="sidebar-section">
            <h6>Shortcuts</h6>
            <div class="keyboard-shortcuts">
                <div><kbd>Shift+S</kbd> Select/deselect node</div>
                <div><kbd>Shift+R</kbd> Reset selection</div>
                <div><kbd>Shift+E</kbd> Expand selection</div>
                <div><kbd>Shift+H</kbd> Expand hovered</div>
                <div><kbd>Shift+F</kbd> Fade unselected</div>
                <div><kbd>Esc</kbd> Clear search</div>
            </div>
        </div>

        <!-- Version -->
        <div class="text-muted" style="font-size: 10px; margin-top: auto;">
            Emerge Unified Viewer v2.0
        </div>
    </div>
</div>

<!-- Toast Container -->
<div class="toast-container">
    <div id="toast" class="toast" role="alert">
        <div class="toast-body" id="toastBody"></div>
    </div>
</div>

<script>
// ============================================
// Configuration and State
// ============================================
const WS_URL = 'ws://localhost:{ws_port}';
let ws = null;
let reconnectAttempts = 0;

// Graph state
let currentGraph = {{ nodes: [], links: [] }};
let graphData = {{}};
let currentGraphType = '';
let simulation = null;
let transform = d3.zoomIdentity;

// UI state
let darkMode = true;
let nodeLabelsEnabled = false;
let heatmapMode = 'off'; // off, normal, hybrid, churn, hotspot
let currentChargeForce = -500;
let selectedNodesMap = {{}};
let fadeUnselectedNodes = false;
let unselectedNodesOpacity = 0.2;
let closeNode = null;

// Cluster state
let clusterMap = {{}};
let clusterMetricsMap = {{}};
let selectedClusterHullIds = [];
let hoveredClusterHullId = null;

// Search state
let isSearching = false;
let searchTerms = [];
let searchResults = [];

// Config from server
let analysisConfig = {{}};

// Canvas setup
const graphDiv = document.getElementById('graphDiv');
const graphWidth = graphDiv.clientWidth * 2;
const height = window.innerHeight * 2;
const radius = 7;

// ============================================
// Canvas and D3 Setup
// ============================================
const canvas = d3.select('#graphDiv')
    .append('canvas')
    .attr('id', 'mainCanvas')
    .attr('width', graphWidth + 'px')
    .attr('height', height + 'px')
    .node();

const context = canvas.getContext('2d');

// Fix blurry canvas
canvas.style.height = (height / 2) + "px";
canvas.style.width = (graphWidth / 2) + "px";
context.scale(2, 2);

// Heatmap (simpleheat)
const heat = simpleheat(canvas);

// Color scheme
const schemeCategory20 = "1f77b4aec7e8ff7f0effbb782ca02c98df8ad62728ff98969467bdc5b0d58c564bc49c94e377c2f7b6d27f7f7fc7c7c7bcbd22dbdb8d17becf9edae5";
function d3ColorExport(specifier) {{
    let n = specifier.length / 6 | 0, colors = new Array(n), i = 0;
    while (i < n) colors[i] = "#" + specifier.slice(i * 6, ++i * 6);
    return colors;
}}
const color = d3.scaleOrdinal(d3ColorExport(schemeCategory20)).domain(d3.range(20));

// ============================================
// WebSocket Connection
// ============================================
function connect() {{
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {{
        reconnectAttempts = 0;
        document.getElementById('statusIndicator').classList.add('connected');
        document.getElementById('statusText').textContent = 'Connected';
        showToast('Connected to Emerge server');
    }};

    ws.onclose = () => {{
        document.getElementById('statusIndicator').classList.remove('connected');
        document.getElementById('statusText').textContent = 'Disconnected';
        if (reconnectAttempts < 5) {{
            reconnectAttempts++;
            setTimeout(connect, 2000 * reconnectAttempts);
        }}
    }};

    ws.onmessage = (e) => {{
        const msg = JSON.parse(e.data);
        handleMessage(msg);
    }};

    ws.onerror = (e) => {{
        console.error('WebSocket error:', e);
    }};
}}

function send(type, data = {{}}) {{
    if (ws && ws.readyState === WebSocket.OPEN) {{
        ws.send(JSON.stringify({{ type, ...data }}));
    }}
}}

function handleMessage(msg) {{
    switch (msg.type) {{
        case 'connected':
            populateGraphSelect(msg.data.graphs);
            if (msg.data.graphs.length > 0) {{
                loadGraph(msg.data.graphs[0]);
            }}
            // Request config
            send('get_config');
            break;

        case 'full_graph':
            currentGraphType = msg.data.graph;
            currentGraph = {{
                nodes: msg.data.nodes.map(n => ({{ ...n, radius: radius }})),
                links: msg.data.links
            }};
            initializeGraph();
            // Request additional data
            send('get_statistics', {{ graph: currentGraphType }});
            send('get_clusters', {{ graph: currentGraphType }});
            break;

        case 'statistics':
            updateStatistics(msg.data.statistics);
            break;

        case 'clusters':
            updateClusters(msg.data.clusters, msg.data.cluster_metrics);
            break;

        case 'config':
            analysisConfig = msg.data.config;
            break;

        case 'metrics':
            if (msg.data.node) {{
                updateNodeInfo(msg.data);
            }}
            break;

        case 'search_results':
            displaySearchResults(msg.data.results, msg.data.count);
            break;

        case 'graph_update':
            showToast(`Graph updated: ${{msg.data.change_type}}`);
            loadGraph(currentGraphType);
            break;

        case 'error':
            console.error('Server error:', msg.data.error);
            showToast(msg.data.error, 'danger');
            break;
    }}
}}

// ============================================
// Graph Initialization
// ============================================
function populateGraphSelect(graphs) {{
    const select = document.getElementById('graphSelect');
    select.innerHTML = graphs.map(g =>
        `<option value="${{g}}">${{g.replace(/_/g, ' ')}}</option>`
    ).join('');
    select.onchange = () => loadGraph(select.value);
}}

function loadGraph(name) {{
    currentGraphType = name;
    document.getElementById('graphSelect').value = name;
    send('get_graph', {{ graph: name }});
}}

function initializeGraph() {{
    // Reset state
    selectedNodesMap = {{}};
    closeNode = null;

    // Setup clusters from node metrics
    setupClusters();

    // Create simulation
    if (simulation) simulation.stop();

    simulation = d3.forceSimulation(currentGraph.nodes)
        .force("center", d3.forceCenter(graphWidth / 4, height / 4))
        .force("charge", d3.forceManyBody().strength(currentChargeForce))
        .force("link", d3.forceLink(currentGraph.links)
            .id(d => d.id)
            .distance(20)
            .strength(1))
        .force("x", d3.forceX(graphWidth / 2).strength(0.1))
        .force("y", d3.forceY(height / 2).strength(0.1))
        .alphaDecay(0.05)
        .on("tick", simulationUpdate);

    // Setup interactions
    setupInteractions();

    // Initial zoom out
    zoomOut();
}}

function setupClusters() {{
    clusterMap = {{}};
    const modularityKeys = [
        'metric_file_result_dependency_graph_louvain_modularity_in_file',
        'metric_entity_result_dependency_graph_louvain_modularity_in_entity',
        'metric_entity_result_inheritance_graph_louvain_modularity_in_entity',
        'metric_entity_result_complete_graph_louvain_modularity_in_entity'
    ];

    currentGraph.nodes.forEach(node => {{
        let clusterId = '0';
        for (const key of modularityKeys) {{
            if (node[key] !== undefined) {{
                clusterId = String(node[key]);
                break;
            }}
        }}
        if (!clusterMap[clusterId]) clusterMap[clusterId] = [];
        clusterMap[clusterId].push(node);
    }});
}}

// ============================================
// Canvas Rendering
// ============================================
function simulationUpdate() {{
    context.save();
    context.clearRect(0, 0, graphWidth, height);
    context.translate(transform.x, transform.y);
    context.scale(transform.k, transform.k);

    // Draw heatmap
    if (heatmapMode !== 'off') drawHeatmap();

    // Draw cluster hulls
    drawHulls();

    // Draw edges
    drawEdges();

    // Draw nodes
    drawNodes();

    context.restore();
}}

function drawEdges() {{
    const activeColor = darkMode ? 'rgba(136,136,136,0.8)' : 'rgba(170,170,170,1.0)';
    const passiveColor = darkMode ? 'rgba(136,136,136,0.2)' : 'rgba(170,170,170,0.2)';

    currentGraph.links.forEach(link => {{
        const source = typeof link.source === 'object' ? link.source : currentGraph.nodes.find(n => n.id === link.source);
        const target = typeof link.target === 'object' ? link.target : currentGraph.nodes.find(n => n.id === link.target);
        if (!source || !target) return;

        let edgeColor = passiveColor;
        if (isSearching && edgeBetweenSearchTerms(source, target)) {{
            edgeColor = activeColor;
        }} else if (!isSearching) {{
            edgeColor = activeColor;
        }}

        context.beginPath();
        context.moveTo(source.x, source.y);
        context.lineTo(target.x, target.y);
        context.strokeStyle = edgeColor;
        context.lineWidth = 0.5;
        context.stroke();
    }});
}}

function drawNodes() {{
    const activeLabelColor = darkMode ? 'rgba(221,221,221,0.6)' : 'rgba(51,51,51,0.6)';
    const passiveLabelColor = darkMode ? 'rgba(221,221,221,0.2)' : 'rgba(51,51,51,0.2)';

    currentGraph.nodes.forEach(node => {{
        let nodeOpacity = 1.0;
        let isHighlighted = false;

        // Check if node matches search
        if (isSearching) {{
            isHighlighted = searchTerms.some(term => node.id.toLowerCase().includes(term));
            nodeOpacity = isHighlighted ? 1.0 : 0.2;
        }}

        // Check selection
        if (fadeUnselectedNodes && Object.keys(selectedNodesMap).length > 0) {{
            if (!selectedNodesMap[node.id.toLowerCase()]) {{
                nodeOpacity = unselectedNodesOpacity;
            }}
        }}

        // Highlight selected nodes
        const isSelected = selectedNodesMap[node.id.toLowerCase()];

        // Draw node
        context.beginPath();
        context.arc(node.x, node.y, node.radius || radius, 0, 2 * Math.PI);
        context.globalAlpha = nodeOpacity;
        context.fillStyle = nodeColorByModularity(node);
        context.fill();

        if (isSelected) {{
            context.strokeStyle = '#FF0000';
            context.lineWidth = 2;
            context.stroke();
        }} else if (closeNode && closeNode.id === node.id) {{
            context.strokeStyle = '#FFFFFF';
            context.lineWidth = 1.5;
            context.stroke();
        }}

        context.globalAlpha = 1.0;

        // Draw label
        if (nodeLabelsEnabled || isHighlighted || isSelected) {{
            context.fillStyle = isHighlighted || isSelected ? activeLabelColor : passiveLabelColor;
            context.font = '10px sans-serif';
            const label = node.label || node.id.split('/').pop();
            context.fillText(label, node.x + (node.radius || radius) + 3, node.y + 3);
        }}
    }});
}}

function nodeColorByModularity(node, alpha = 1.0) {{
    const modularityKeys = [
        'metric_file_result_dependency_graph_louvain_modularity_in_file',
        'metric_entity_result_dependency_graph_louvain_modularity_in_entity'
    ];

    let modValue = 0;
    for (const key of modularityKeys) {{
        if (node[key] !== undefined) {{
            modValue = node[key];
            break;
        }}
    }}

    const baseColor = color(modValue % 20);
    if (alpha < 1.0) {{
        const r = parseInt(baseColor.slice(1,3), 16);
        const g = parseInt(baseColor.slice(3,5), 16);
        const b = parseInt(baseColor.slice(5,7), 16);
        return `rgba(${{r}},${{g}},${{b}},${{alpha}})`;
    }}
    return baseColor;
}}

// ============================================
// Heatmap
// ============================================
function drawHeatmap() {{
    if (heatmapMode === 'off') return;

    const config = analysisConfig.heatmap || {{ score: {{ base: 10, limit: 500 }} }};
    heat.max(config.score.limit);
    heat.clear();

    currentGraph.nodes.forEach(node => {{
        const score = calculateHeatmapScore(node);
        heat.add([node.x, node.y, score]);
    }});

    heat.draw();
    context.globalAlpha = 1;
}}

function calculateHeatmapScore(node) {{
    let score = 10;

    if (heatmapMode === 'normal' || heatmapMode === 'hybrid') {{
        const sloc = node.metric_sloc_in_file || node.metric_sloc_in_entity || 0;
        const fanout = node.metric_fan_out_dependency_graph || 0;
        score += sloc * 0.3 + fanout * 5;
    }} else if (heatmapMode === 'churn') {{
        const churn = node.metric_git_code_churn || 0;
        score += churn * 0.1;
    }} else if (heatmapMode === 'hotspot') {{
        const churn = node.metric_git_code_churn || 0;
        const complexity = node.metric_git_ws_complexity || 0;
        score += churn * 0.05 + complexity * 0.01;
    }}

    return Math.min(score, 500);
}}

function cycleHeatmap() {{
    const modes = ['off', 'normal', 'hybrid', 'churn', 'hotspot'];
    const idx = modes.indexOf(heatmapMode);
    heatmapMode = modes[(idx + 1) % modes.length];
    document.getElementById('btnHeatmap').innerHTML = `<i class="bi bi-thermometer-half"></i> ${{heatmapMode.charAt(0).toUpperCase() + heatmapMode.slice(1)}}`;
    simulationUpdate();
}}

// ============================================
// Cluster Hulls
// ============================================
function drawHulls() {{
    // Draw hovered hull
    if (hoveredClusterHullId !== null) {{
        drawHull(hoveredClusterHullId);
    }}

    // Draw selected hulls
    selectedClusterHullIds.forEach(id => drawHull(id));
}}

function drawHull(clusterId) {{
    const clusterNodes = clusterMap[clusterId];
    if (!clusterNodes || clusterNodes.length < 3) return;

    const points = clusterNodes.map(n => [n.x, n.y]);
    try {{
        const hullPoints = hull(points, 60);
        if (!hullPoints || hullPoints.length < 3) return;

        context.beginPath();
        context.moveTo(hullPoints[0][0], hullPoints[0][1]);
        hullPoints.forEach(p => context.lineTo(p[0], p[1]));
        context.closePath();

        context.fillStyle = nodeColorByModularity(clusterNodes[0], 0.2);
        context.fill();
    }} catch (e) {{
        // Hull calculation failed, skip
    }}
}}

function updateClusters(clusters, metrics) {{
    clusterMetricsMap = metrics;
    const container = document.getElementById('clusterHulls');
    const clusterIds = Object.keys(clusters).slice(0, 20);

    document.getElementById('clusterCount').textContent = clusterIds.length;

    container.innerHTML = clusterIds.map(id => {{
        const firstNode = clusters[id][0];
        const nodeData = currentGraph.nodes.find(n => n.id === firstNode) || {{}};
        const clusterColor = nodeColorByModularity(nodeData);
        return `<div class="cluster-hull-node ${{selectedClusterHullIds.includes(id) ? 'selected' : ''}}"
                     style="background: ${{clusterColor}}"
                     data-cluster="${{id}}"
                     onmouseover="hoverCluster('${{id}}')"
                     onmouseout="unhoverCluster()"
                     onclick="toggleCluster('${{id}}')"
                     title="Cluster ${{id}}: ${{clusters[id].length}} nodes"></div>`;
    }}).join('');
}}

function hoverCluster(id) {{
    hoveredClusterHullId = id;
    simulationUpdate();
}}

function unhoverCluster() {{
    hoveredClusterHullId = null;
    simulationUpdate();
}}

function toggleCluster(id) {{
    const idx = selectedClusterHullIds.indexOf(id);
    if (idx > -1) {{
        selectedClusterHullIds.splice(idx, 1);
    }} else {{
        selectedClusterHullIds.push(id);
    }}
    // Update UI
    document.querySelectorAll('.cluster-hull-node').forEach(el => {{
        el.classList.toggle('selected', selectedClusterHullIds.includes(el.dataset.cluster));
    }});
    simulationUpdate();
}}

// ============================================
// Search
// ============================================
const searchInput = document.getElementById('searchInput');
searchInput.addEventListener('input', debounce(handleSearch, 300));
document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') clearSearch();
}});

function handleSearch() {{
    const query = searchInput.value.trim();
    if (query.length < 2) {{
        clearSearch();
        return;
    }}

    searchTerms = query.toLowerCase().split(' ').filter(Boolean);
    isSearching = true;

    const semantic = document.getElementById('semanticSearch').checked;
    send('search_nodes', {{ query, graph: currentGraphType, semantic }});

    simulationUpdate();
}}

function displaySearchResults(results, count) {{
    searchResults = results;
    document.getElementById('searchCount').textContent = `${{count}} nodes found`;

    const container = document.getElementById('searchResults');
    container.innerHTML = results.slice(0, 20).map(r =>
        `<div class="search-result-item" onclick="focusNode('${{r.id}}')">
            <span class="badge bg-${{r.match_type === 'semantic' ? 'warning' : 'primary'}} me-1">${{r.match_type}}</span>
            ${{r.label || r.id.split('/').pop()}}
        </div>`
    ).join('');
}}

function clearSearch() {{
    searchInput.value = '';
    searchTerms = [];
    isSearching = false;
    searchResults = [];
    document.getElementById('searchResults').innerHTML = '';
    document.getElementById('searchCount').textContent = '';
    simulationUpdate();
}}

function edgeBetweenSearchTerms(source, target) {{
    return searchTerms.some(term =>
        source.id.toLowerCase().includes(term) && target.id.toLowerCase().includes(term)
    );
}}

function focusNode(nodeId) {{
    const node = currentGraph.nodes.find(n => n.id === nodeId);
    if (node) {{
        // Center view on node
        const scale = transform.k;
        transform = d3.zoomIdentity
            .translate(graphWidth/4 - node.x * scale, height/4 - node.y * scale)
            .scale(scale);
        simulationUpdate();

        // Select the node
        selectedNodesMap[nodeId.toLowerCase()] = true;
        send('get_node', {{ node: nodeId, graph: currentGraphType }});
    }}
}}

// ============================================
// Interactions
// ============================================
function setupInteractions() {{
    const zoomHandler = d3.zoom()
        .scaleExtent([0.1, 8])
        .on("zoom", (event) => {{
            transform = event.transform;
            simulationUpdate();
        }});

    d3.select(canvas)
        .call(zoomHandler)
        .call(d3.drag()
            .subject(dragSubject)
            .on("start", dragStarted)
            .on("drag", dragged)
            .on("end", dragEnded))
        .on("mousemove", handleMouseMove)
        .on("click", handleClick);

    // Keyboard shortcuts
    d3.select('body').on('keydown', handleKeyDown);
}}

function dragSubject(event) {{
    const x = transform.invertX(event.x);
    const y = transform.invertY(event.y);

    for (let i = currentGraph.nodes.length - 1; i >= 0; --i) {{
        const node = currentGraph.nodes[i];
        const dx = x - node.x;
        const dy = y - node.y;
        if (dx * dx + dy * dy < radius * radius) {{
            node.x = transform.applyX(node.x);
            node.y = transform.applyY(node.y);
            return node;
        }}
    }}
}}

function dragStarted(event) {{
    if (!event.active) simulation.alphaTarget(0.3).restart();
    event.subject.fx = transform.invertX(event.x);
    event.subject.fy = transform.invertY(event.y);
}}

function dragged(event) {{
    event.subject.fx = transform.invertX(event.x);
    event.subject.fy = transform.invertY(event.y);
}}

function dragEnded(event) {{
    if (!event.active) simulation.alphaTarget(0);
    event.subject.fx = null;
    event.subject.fy = null;
}}

function handleMouseMove(event) {{
    const [px, py] = d3.pointer(event);
    const x = transform.invertX(px);
    const y = transform.invertY(py);

    const found = simulation.find(x, y);
    if (found && Math.abs(found.x - x) < radius && Math.abs(found.y - y) < radius) {{
        closeNode = found;
    }} else {{
        closeNode = null;
    }}

    simulationUpdate();
}}

function handleClick(event) {{
    if (closeNode) {{
        send('get_node', {{ node: closeNode.id, graph: currentGraphType }});
    }}
}}

function handleKeyDown(event) {{
    if (event.key === 'S' && event.shiftKey && closeNode) {{
        const id = closeNode.id.toLowerCase();
        if (selectedNodesMap[id]) delete selectedNodesMap[id];
        else selectedNodesMap[id] = true;
        simulationUpdate();
    }} else if (event.key === 'R' && event.shiftKey) {{
        selectedNodesMap = {{}};
        simulationUpdate();
    }} else if (event.key === 'E' && event.shiftKey) {{
        expandSelection();
    }} else if (event.key === 'H' && event.shiftKey && closeNode) {{
        expandFromNode(closeNode);
    }} else if (event.key === 'F' && event.shiftKey) {{
        fadeUnselectedNodes = !fadeUnselectedNodes;
        simulationUpdate();
    }}
}}

function expandSelection() {{
    const newSelected = {{ ...selectedNodesMap }};
    currentGraph.links.forEach(link => {{
        const sourceId = (typeof link.source === 'object' ? link.source.id : link.source).toLowerCase();
        const targetId = (typeof link.target === 'object' ? link.target.id : link.target).toLowerCase();
        if (selectedNodesMap[sourceId] || selectedNodesMap[targetId]) {{
            newSelected[sourceId] = true;
            newSelected[targetId] = true;
        }}
    }});
    selectedNodesMap = newSelected;
    simulationUpdate();
}}

function expandFromNode(node) {{
    selectedNodesMap[node.id.toLowerCase()] = true;
    currentGraph.links.forEach(link => {{
        const sourceId = (typeof link.source === 'object' ? link.source.id : link.source);
        const targetId = (typeof link.target === 'object' ? link.target.id : link.target);
        if (sourceId === node.id || targetId === node.id) {{
            selectedNodesMap[sourceId.toLowerCase()] = true;
            selectedNodesMap[targetId.toLowerCase()] = true;
        }}
    }});
    simulationUpdate();
}}

// ============================================
// UI Controls
// ============================================
function zoomIn() {{
    transform = transform.scale(1.5);
    simulationUpdate();
}}

function zoomOut() {{
    transform = transform.scale(0.67);
    simulationUpdate();
}}

function resetView() {{
    transform = d3.zoomIdentity;
    simulationUpdate();
}}

function increaseForce() {{
    if (currentChargeForce < -50) {{
        currentChargeForce += 50;
        updateForce();
    }}
}}

function decreaseForce() {{
    currentChargeForce -= 50;
    updateForce();
}}

function updateForce() {{
    document.getElementById('forceValue').textContent = currentChargeForce;
    simulation.force("charge", d3.forceManyBody().strength(currentChargeForce));
    simulation.alpha(1).restart();
}}

function toggleLabels() {{
    nodeLabelsEnabled = !nodeLabelsEnabled;
    document.getElementById('btnLabels').classList.toggle('active', nodeLabelsEnabled);
    simulationUpdate();
}}

function toggleDarkMode() {{
    darkMode = !darkMode;
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
    simulationUpdate();
}}

function updateStatistics(stats) {{
    document.getElementById('statNodes').textContent = stats.number_of_nodes || '-';
    document.getElementById('statEdges').textContent = stats.number_of_edges || '-';
    document.getElementById('statDensity').textContent = stats.density || '-';
    document.getElementById('statComponents').textContent = stats.number_of_connected_components || '-';
}}

function updateNodeInfo(data) {{
    const info = document.getElementById('nodeInfo');
    info.innerHTML = `
        <h5>${{data.node.split('/').pop()}}</h5>
        <p class="text-muted" style="font-size: 10px; word-break: break-all;">${{data.node}}</p>
        <div class="metric"><span>Fan In</span><span>${{data.fan_in}}</span></div>
        <div class="metric"><span>Fan Out</span><span>${{data.fan_out}}</span></div>
        <div class="mt-2">
            <strong>Dependencies (${{data.dependencies.length}})</strong>
            <div style="max-height: 100px; overflow-y: auto; font-size: 10px;">
                ${{data.dependencies.slice(0, 10).map(d => `<div>${{d.split('/').pop()}}</div>`).join('')}}
            </div>
        </div>
    `;
}}

function showToast(message, type = 'info') {{
    const toast = document.getElementById('toast');
    const body = document.getElementById('toastBody');
    body.textContent = message;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
}}

// ============================================
// Utilities
// ============================================
function debounce(func, wait) {{
    let timeout;
    return function(...args) {{
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    }};
}}

// ============================================
// Initialize
// ============================================
connect();

// Handle window resize
window.addEventListener('resize', () => {{
    canvas.style.width = (graphDiv.clientWidth) + "px";
    simulationUpdate();
}});
</script>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>'''
