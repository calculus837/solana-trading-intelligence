/**
 * Graph Visualization using force-graph
 * 
 * Features:
 * - Visualizes wallet connections from Neo4j
 * - Falls back to demo data if Neo4j is unavailable
 * - Loading states and error handling
 */

let graphInstance = null;

export async function renderGraph(address) {
    const container = document.getElementById('graph-view');

    // Show loading state
    container.innerHTML = `
        <div class="graph-loading">
            <div class="spinner"></div>
            <p>Loading graph for ${address ? address.substring(0, 8) + '...' : 'demo'}...</p>
        </div>
    `;

    try {
        let data;

        if (address === 'demo' || !address) {
            // Load demo data
            console.log('Loading demo graph...');
            const response = await fetch('/api/graph/demo');
            data = await response.json();
        } else {
            // Try real API first
            console.log(`Fetching graph for ${address}...`);
            const response = await fetch(`/api/graph/wallet/${address}`);

            if (!response.ok) {
                // Fallback to demo on error
                console.warn('Graph API failed, loading demo data...');
                const demoResponse = await fetch('/api/graph/demo');
                data = await demoResponse.json();
                showGraphMessage(container, 'info',
                    `Neo4j not available. Showing demo graph instead.`);
            } else {
                data = await response.json();
            }
        }

        if (!data.nodes || data.nodes.length === 0) {
            showGraphMessage(container, 'warn',
                'No connections found for this wallet. Try searching a different address or click "Load Demo".');
            return;
        }

        // Clear loading state
        container.innerHTML = '';

        // Initialize Force Graph
        graphInstance = ForceGraph()(container)
            .graphData(data)
            .nodeLabel(node => `${node.id}\n(${node.label})`)
            .nodeColor(node => {
                if (node.label === 'Wallet') return '#14F195'; // Solana Green
                if (node.label === 'Cabal') return '#ff3b30';  // Red for cabals
                if (node.label === 'Token') return '#9945FF';  // Purple for tokens
                return '#ffffff';
            })
            .nodeRelSize(8)
            .linkColor(link => {
                if (link.type === 'MEMBER_OF') return 'rgba(255, 59, 48, 0.5)';
                if (link.type === 'TRADED_WITH') return 'rgba(20, 241, 149, 0.5)';
                if (link.type === 'HOLDS') return 'rgba(153, 69, 255, 0.5)';
                return 'rgba(255,255,255,0.2)';
            })
            .linkWidth(2)
            .linkDirectionalParticles(2)
            .linkDirectionalParticleSpeed(0.005)
            .backgroundColor('transparent')
            .width(container.clientWidth)
            .height(container.clientHeight || 400);

        // Custom node rendering with labels
        graphInstance.nodeCanvasObject((node, ctx, globalScale) => {
            const label = node.id.length > 8 ? node.id.substring(0, 6) + '...' : node.id;
            const fontSize = Math.max(10, 14 / globalScale);
            ctx.font = `${fontSize}px 'JetBrains Mono', monospace`;

            // Draw node circle
            ctx.beginPath();
            ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI);
            ctx.fillStyle = node.color || '#14F195';
            ctx.fill();

            // Draw label
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillStyle = '#ffffff';
            ctx.fillText(label, node.x, node.y + 8);
        });

        // Click handler
        graphInstance.onNodeClick(node => {
            console.log('Clicked:', node);
            // Could expand to show more details
        });

        console.log(`Graph rendered: ${data.nodes.length} nodes, ${data.links.length} links`);

    } catch (err) {
        console.error("Graph render failed:", err);
        showGraphMessage(container, 'error',
            `Failed to load graph: ${err.message}`);
    }
}

function showGraphMessage(container, type, message) {
    const colors = {
        error: '#ff3b30',
        warn: '#ffcc00',
        info: '#14F195'
    };

    container.innerHTML = `
        <div class="graph-message" style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: ${colors[type] || '#fff'};
            text-align: center;
            padding: 2rem;
        ">
            <p style="margin-bottom: 1rem;">${message}</p>
            <button onclick="window.renderGraph('demo')" style="
                background: linear-gradient(135deg, #9945FF, #14F195);
                border: none;
                padding: 0.75rem 1.5rem;
                border-radius: 8px;
                color: white;
                cursor: pointer;
                font-weight: 600;
            ">Load Demo Graph</button>
        </div>
    `;
}

// Resize handler
window.addEventListener('resize', () => {
    if (graphInstance) {
        const container = document.getElementById('graph-view');
        graphInstance.width(container.clientWidth);
        graphInstance.height(container.clientHeight);
    }
});

// Global expose for dashboard.js to call
window.renderGraph = renderGraph;

