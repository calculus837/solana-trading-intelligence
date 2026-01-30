/**
 * Dashboard Logic - Real-time updates via Socket.io
 * 
 * Connects to the backend API server which bridges Redis Pub/Sub to the browser.
 */

// Determine WebSocket URL based on environment
const WS_URL = window.location.origin.replace(/^http/, 'ws');

// Initialize Socket.io
const socket = io({
    path: '/socket.io/',
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionAttempts: 10,
});

// DOM Elements
const termFeed = document.getElementById('terminal-feed');
const statLatency = document.getElementById('stat-latency');
const statTps = document.getElementById('stat-tps');
const statAlerts = document.getElementById('stat-alerts');
const statusBadge = document.getElementById('system-status-dot') || document.getElementById('status-badge');

// State
let alertCount = 0;
let tpsHistory = [];
let connected = false;
let isPaused = false;
let pendingLogs = [];

// ============================================================================
// UI HELPERS
// ============================================================================

function updateStatus(status) {
    const dots = document.querySelectorAll('.status-dot');
    const systemDot = document.getElementById('system-status-dot');

    if (status === 'online') {
        dots.forEach(d => d.classList.add('online'));
        if (systemDot) systemDot.style.backgroundColor = 'var(--accent)';
    } else {
        dots.forEach(d => d.classList.remove('online'));
        if (systemDot) systemDot.style.backgroundColor = 'var(--danger)';
    }
}

function flashBadge(color) {
    if (!statusBadge) return;
    const originalColor = statusBadge.style.backgroundColor;
    statusBadge.style.backgroundColor = color === 'red' ? 'var(--danger)' : 'var(--accent)';
    setTimeout(() => {
        statusBadge.style.backgroundColor = originalColor || 'var(--accent)';
    }, 500);
}

// ============================================================================
// SOCKET.IO EVENT HANDLERS
// ============================================================================

socket.on('connect', () => {
    console.log("⚡ Connected to Intel Stream");
    connected = true;
    updateStatus('online');
    addLog('system', 'Connected to real-time feed');
});

socket.on('disconnect', () => {
    console.log("❌ Disconnected");
    connected = false;
    updateStatus('connecting');
    addLog('warn', 'Connection lost - retrying...');
});

socket.on('connect_error', (error) => {
    console.error("Connection error:", error);
    updateStatus('error');
    addLog('error', `Connection error: ${error.message}`);
});

socket.on('message', (payload) => {
    console.log("🔌 Socket message received:", payload);
    if (!payload || !payload.channel) return;
    const { channel, data } = payload;

    switch (channel) {
        case 'solana:alerts':
            processAlert(data);
            break;
        case 'solana:transactions':
            processTx(data);
            break;
        case 'solana:fresh_wallets':
            processFreshWallet(data);
            break;
        case 'solana:pnl':
            updatePnlChart(data);
            break;
        default:
            console.log(`Unknown channel: ${channel}`, data);
    }
});

// ============================================================================
// MESSAGE PROCESSORS
// ============================================================================

function processAlert(data) {
    alertCount++;
    statAlerts.innerText = alertCount.toLocaleString();

    const alertType = data.type || 'unknown';
    let message = '';

    switch (alertType) {
        case 'cabal':
            message = `🔥 CABAL DETECTED: ${data.group_name || 'Unknown Group'} | ${data.wallet_count} wallets | Conf: ${(data.confidence * 100).toFixed(1)}%`;
            addLog('warn', message);
            flashBadge('red');
            showAlertBanner('cabal', '🔥', message);
            break;

        case 'influencer':
            message = `👁️ INFLUENCER MOVE: ${shortenAddress(data.address)} bought ${data.token_symbol || shortenAddress(data.token_mint)} | ${data.amount_sol?.toFixed(2) || '?'} SOL`;
            addLogWithCopyTrade('action', message, data.token_mint, data.token_symbol, data.amount_sol || 0.1);
            flashBadge('purple');
            showAlertBanner('influencer', '👁️', message);
            break;

        case 'fresh_wallet':
            message = `🆕 FRESH WALLET: ${shortenAddress(data.recipient)} funded from ${data.cex_name} | ${data.amount?.toFixed(2) || '?'} SOL`;
            addLog('info', message);
            addFreshWalletCard(data);
            break;

        case 'execution':
            if (data.action === 'SWAP_DETECTED') {
                message = `⚡ TRADE EXECUTED: ${data.action} ${shortenAddress(data.token_mint)} | PnL: ${data.pnl || 'N/A'}`;
                addLog('success', message);
            }
            break;

        case 'system':
            addLog('system', data.message);
            break;

        default:
            message = data.message || JSON.stringify(data);
            addLog('info', message);
    }

    // Track feature stats
    if (typeof processAlertStats === 'function') {
        processAlertStats(data);
    }
}

// ============================================================================
// COPY TRADE FUNCTIONALITY
// ============================================================================

function addLogWithCopyTrade(type, msg, tokenMint, tokenSymbol, suggestedAmount) {
    const div = document.createElement('div');
    div.className = 'log-line log-with-action';

    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    div.innerHTML = `
        <span class="log-time">[${time}]</span>
        <span class="log-type action">ALERT</span>
        <span class="log-msg">${msg}</span>
        <button class="copy-trade-btn" onclick="executeCopyTrade('${tokenMint}', '${tokenSymbol || ''}', ${suggestedAmount})">
            📋 Copy Trade
        </button>
    `;

    termFeed.appendChild(div);
    if (!isPaused) termFeed.scrollTop = termFeed.scrollHeight;
}

window.executeCopyTrade = async function (tokenMint, tokenSymbol, amount) {
    const confirmAmount = prompt(`Copy Trade: Buy ${tokenSymbol || shortenAddress(tokenMint)}\n\nEnter SOL amount:`, amount.toFixed(3));

    if (!confirmAmount) return;

    const amountSol = parseFloat(confirmAmount);
    if (isNaN(amountSol) || amountSol <= 0) {
        addLog('error', 'Invalid amount');
        return;
    }

    addLog('info', `⏳ Executing copy trade: ${amountSol} SOL → ${tokenSymbol || shortenAddress(tokenMint)}...`);

    try {
        const response = await fetch('/api/trade/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                token_mint: tokenMint,
                amount_sol: amountSol,
                token_symbol: tokenSymbol,
                source: 'copy_trade'
            })
        });

        const result = await response.json();

        if (result.success) {
            addLog('success', `✅ Trade executed! Received ${result.tokens_received?.toFixed(2) || '?'} tokens`);
            refreshPositions();
        } else {
            addLog('error', `❌ Trade failed: ${result.error || 'Unknown error'}`);
        }
    } catch (err) {
        addLog('error', `❌ Trade error: ${err.message}`);
    }
};

// Listen for trade events via Socket.io
socket.on('trade:executed', (data) => {
    addLog('success', `🚀 TRADE LIVE: Bought ${data.token} | ${data.amount_sol} SOL`);
    refreshPositions();
});

socket.on('trade:exited', (data) => {
    const pnlClass = data.pnl_sol >= 0 ? 'success' : 'error';
    addLog(pnlClass, `💰 POSITION CLOSED: PnL ${data.pnl_sol >= 0 ? '+' : ''}${data.pnl_sol?.toFixed(4)} SOL (${data.pnl_pct?.toFixed(1)}%)`);
    refreshPositions();
});

socket.on('trade:pnl_update', (data) => {
    updatePnLDisplay(data);
});

function processTx(data) {
    console.log("📡 processTx received:", data);

    if (data.latency_ms) {
        statLatency.innerText = `${data.latency_ms}ms`;
    }

    if (data.tps) {
        statTps.innerText = data.tps.toLocaleString();
    }
}

function processFreshWallet(data) {
    addLog('info', `🆕 CEX → ${shortenAddress(data.recipient_wallet)} | ${data.amount} SOL from ${data.cex_name}`);
}

// ============================================================================
// WALLET ANALYSIS
// ============================================================================

// Expose to window for button onclick
window.searchWallet = async function () {
    const input = document.getElementById('wallet-search');
    const address = input.value.trim();

    if (!address) {
        addLog('warn', 'Please enter a wallet address');
        return;
    }

    if (address.length < 32 || address.length > 44) {
        addLog('error', 'Invalid Solana address length');
        return;
    }

    addLog('info', `🔍 Running forensic analysis on: ${shortenAddress(address)}`);

    try {
        const response = await fetch(`/api/analyze/${address}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`Analysis failed: ${response.statusText}`);
        }

        const data = await response.json();

        // Show detailed results in terminal
        addLog('success', `✅ Analysis complete for ${shortenAddress(address)}`);

        // Display influencer or cabal status prominently
        if (data.is_influencer) {
            addLog('success', `🌟 INFLUENCER WALLET DETECTED - High Signal Source!`);
            flashBadge('purple');
        } else if (data.is_cabal) {
            addLog('warn', `⚠️ CABAL AFFILIATION DETECTED: Cluster ${data.cluster_id}`);
            flashBadge('red');
        } else {
            addLog('info', `📊 No known affiliations detected`);
        }

        addLog('info', `Risk Score: ${data.risk_score}/100 | Win Rate: ${data.win_rate}%`);
        addLog('info', `Tags: [${data.tags.join(', ')}]`);

        // Only switch to graph for cabal detections (where cluster visualization is useful)
        if (data.is_cabal && window.renderGraph) {
            addLog('info', `📈 Switching to Cabal Graph view...`);
            window.switchTab('graph');
            window.renderGraph(address);
        }

    } catch (err) {
        addLog('error', `Analysis error: ${err.message}`);
    }
};

// ============================================================================
// UI CONTROLS
// ============================================================================

// ============================================================================
// TAB SWITCHING (Split Panel Layout)
// ============================================================================

window.switchTab = function (tabName) {
    // 1. Update Button States
    // We scan all panel tabs to find the one matching the requested tabName
    document.querySelectorAll('.panel-tab').forEach(btn => {
        const text = btn.textContent.toLowerCase();
        // Check if this button corresponds to the tabName
        let match = false;

        if (tabName === 'terminal' && text.includes('terminal')) match = true;
        if (tabName === 'graph' && text.includes('graph')) match = true;
        if (tabName === 'performance' && text.includes('leaderboard')) match = true;
        if (tabName === 'fresh' && text.includes('fresh')) match = true;

        if (match) {
            // Activate this button, deactivate its siblings
            btn.classList.add('active');
            // Deactivate siblings in the same container
            Array.from(btn.parentElement.children).forEach(sibling => {
                if (sibling !== btn) sibling.classList.remove('active');
            });
        }
    });

    // 2. Handle Panel Visibility
    const termView = document.getElementById('terminal-view');
    const graphView = document.getElementById('graph-view');
    const perfView = document.getElementById('performance-view');
    const freshView = document.getElementById('fresh-view');

    // Left Panel Logic (Terminal vs Graph)
    if (tabName === 'terminal') {
        if (termView) termView.style.display = 'flex'; // Flex for layout
        if (graphView) graphView.style.display = 'none';
        // Auto scroll
        if (termFeed) termFeed.scrollTop = termFeed.scrollHeight;
    }
    else if (tabName === 'graph') {
        if (termView) termView.style.display = 'none';
        if (graphView) {
            graphView.style.display = 'block';
            // Render demo if empty
            if (!document.getElementById('graph-container').hasChildNodes()) {
                if (window.renderGraph) window.renderGraph('demo');
            }
        }
    }

    // Right Panel Logic (Leaderboard vs Fresh Wallets)
    else if (tabName === 'performance') {
        if (perfView) {
            perfView.style.display = 'block';
            loadAnalytics();
        }
        if (freshView) freshView.style.display = 'none';
    }
    else if (tabName === 'fresh') {
        if (perfView) perfView.style.display = 'none';
        if (freshView) freshView.style.display = 'block';
    }
};

// ============================================================================
// APP NAVIGATION (Sidebar)
// ============================================================================

window.switchView = function (viewName) {
    // 1. Update Sidebar State
    document.querySelectorAll('.nav-item').forEach(btn => {
        // Simple heuristic: check if button title matches viewName
        // If viewName is 'intelligence', match 'Signals' title
        const map = {
            'intelligence': 'Signals',
            'execution': 'Trades',
            'settings': 'Settings',
            'overview': 'Overview'
        };
        const title = btn.getAttribute('title');

        if (title === map[viewName] || (viewName === 'intelligence' && title === 'Overview')) { // Default Overview to Signals for now
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // 2. Toggle View Visibility
    document.querySelectorAll('.main-view').forEach(view => {
        view.style.display = 'none';
    });

    // Determine target view ID
    let targetId = 'view-intelligence'; // Default
    if (viewName === 'execution') targetId = 'view-execution';
    if (viewName === 'settings') targetId = 'view-settings';
    if (viewName === 'overview') targetId = 'view-intelligence'; // Map overview to intelligence logic for now

    console.log(`Switching view to: ${viewName} (${targetId})`);

    const targetView = document.getElementById(targetId);
    if (targetView) targetView.style.display = 'flex';
}


// ============================================================================
// SEARCH HANDLER
// ============================================================================

const searchInput = document.getElementById('wallet-search');
if (searchInput) {
    searchInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            const query = e.target.value.trim();
            if (query) {
                console.log(`Searching for: ${query}`);
                addLog('system', `🔍 Searching: ${query}`);

                // If it looks like a wallet, switch to graph
                if (query.length > 30) {
                    window.switchTab('graph');
                    if (window.renderGraph) window.renderGraph(query);
                } else {
                    // Command handling (e.g. /help) could go here
                }
            }
        }
    });
}

// ============================================================================
// ANALYTICS FUNCTIONS
// ============================================================================

window.loadAnalytics = async function () {
    try {
        // Fetch leaderboard
        const response = await fetch('/api/analytics/leaderboard');
        const data = await response.json();

        // Update leaderboard table
        const tbody = document.getElementById('leaderboard-body');
        if (tbody && data.leaderboard && data.leaderboard.length > 0) {
            tbody.innerHTML = data.leaderboard.map(row => `
                <tr>
                    <td title="${row.source_id}">${row.source_name || shortenAddress(row.source_id)}</td>
                    <td><span class="type-badge ${row.source_type}">${row.source_type}</span></td>
                    <td>${row.total_trades}</td>
                    <td class="${parseFloat(row.win_rate) >= 50 ? 'positive' : 'negative'}">${row.win_rate}%</td>
                    <td class="${parseFloat(row.total_pnl) >= 0 ? 'positive' : 'negative'}">${parseFloat(row.total_pnl).toFixed(4)}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="5" class="no-data">No trade data yet</td></tr>';
        }

        // Fetch summary
        const summaryResponse = await fetch('/api/analytics/summary');
        const summaryData = await summaryResponse.json();

        if (summaryData.summary && summaryData.summary.length > 0) {
            let totalTrades = 0, totalWins = 0, totalPnl = 0;
            summaryData.summary.forEach(s => {
                totalTrades += parseInt(s.total_trades) || 0;
                totalWins += parseInt(s.total_wins) || 0;
                totalPnl += parseFloat(s.total_pnl) || 0;
            });

            const winRate = totalTrades > 0 ? ((totalWins / totalTrades) * 100).toFixed(1) : 0;

            document.getElementById('analytics-total-trades').textContent = totalTrades;
            document.getElementById('analytics-win-rate').textContent = `${winRate}%`;
            document.getElementById('analytics-total-pnl').textContent = `${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(4)} SOL`;

            // Color the PnL
            const pnlEl = document.getElementById('analytics-total-pnl');
            pnlEl.classList.toggle('positive', totalPnl >= 0);
            pnlEl.classList.toggle('negative', totalPnl < 0);
        }

    } catch (error) {
        console.error('Failed to load analytics:', error);
        const tbody = document.getElementById('leaderboard-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="5" class="error">Failed to load data</td></tr>';
    }
};

window.togglePause = function () {
    isPaused = !isPaused;
    const btn = document.getElementById('btn-pause');
    btn.innerHTML = isPaused ? '▶️' : '⏸️';
    btn.classList.toggle('active', isPaused);
    btn.title = isPaused ? 'Resume Stream' : 'Pause Stream';

    if (!isPaused) {
        addLog('system', 'Stream resumed');
        // Flush pending
        pendingLogs.forEach(entry => addLogToDom(entry.type, entry.msg));
        pendingLogs = [];
    } else {
        addLog('system', 'Stream paused');
    }
};

window.clearTerminal = function () {
    termFeed.innerHTML = '';
    addLog('system', 'Terminal cleared');
};

// ============================================================================
// HELPERS
// ============================================================================

function addLog(type, msg) {
    if (isPaused && type !== 'system') {
        pendingLogs.push({ type, msg });
        return;
    }

    addLogToDom(type, msg);
}

function addLogToDom(type, msg) {
    const div = document.createElement('div');
    div.className = 'log-line';

    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

    let typeClass = 'info';
    let label = 'SYS';

    if (type === 'warn' || type === 'cabal') { typeClass = 'warn'; label = 'DETECT'; }
    if (type === 'error') { typeClass = 'error'; label = 'ERROR'; }
    if (type === 'success' || type === 'fresh') { typeClass = 'success'; label = 'OK ⚡'; }
    if (type === 'action' || type === 'execution' || type === 'system') { typeClass = 'action'; label = "TRADE"; }
    if (type === 'system') { typeClass = 'info'; label = 'SYS'; }

    div.innerHTML = `<span class="timestamp">[${time}]</span> <span class="${typeClass}">${label}</span> ${msg}`;

    termFeed.appendChild(div);

    // Auto scroll if near bottom
    if (termFeed.scrollTop + termFeed.clientHeight >= termFeed.scrollHeight - 50) {
        termFeed.scrollTop = termFeed.scrollHeight;
    }

    // Limit history
    if (termFeed.children.length > 200) {
        termFeed.removeChild(termFeed.firstChild);
    }
}

function shortenAddress(addr) {
    if (!addr) return 'Unknown';
    return addr.slice(0, 4) + '...' + addr.slice(-4);
}

function updateStatus(status) {
    statusBadge.className = 'status-badge'; // reset
    if (status === 'online') {
        statusBadge.innerText = '● SYSTEM ONLINE';
        statusBadge.classList.add('status-online');
    } else if (status === 'connecting') {
        statusBadge.innerText = '○ CONNECTING...';
        statusBadge.classList.add('status-pending');
    } else {
        statusBadge.innerText = '● SYSTEM OFFLINE';
        statusBadge.classList.add('status-offline');
    }
}

function flashBadge(color) {
    statusBadge.style.backgroundColor = color === 'red' ? '#ff3333' : '#a855f7';
    setTimeout(() => {
        statusBadge.style.backgroundColor = '';
    }, 200);
}

// Initial Status check
async function checkBackendStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.status === 'ok') {
            updateStatus('online');
        }
    } catch (e) {
        console.log("Backend check failed", e);
        // Don't set offline immediately, let socket.io handle it
    }
}

checkBackendStatus();

// Fake stats simulation (TPS jitter)
setInterval(() => {
    if (connected) {
        const baseTps = 2500 + Math.floor(Math.random() * 1500);
        statTps.innerText = baseTps.toLocaleString();

        if (statLatency.innerText === '--ms' || statLatency.innerText.includes('N/A')) {
            statLatency.innerText = `${Math.floor(Math.random() * 30) + 40}ms`;
        }
    }
}, 2000);

// ============================================================================
// FEATURE SECTION STATS
// ============================================================================

// Track feature section counters
const featureStats = {
    influencerSignals: 0,
    cabalClusters: 0,
    freshWallets: 0,
    blockedTrades: 0,
    exitsExecuted: 0
};

// Update feature section DOM elements
function updateFeatureStats() {
    const elements = {
        'last-influencer-signal': featureStats.influencerSignals > 0 ? 'Just now' : '--',
        'cabal-cluster-count': featureStats.cabalClusters.toString(),
        'fresh-wallet-count': featureStats.freshWallets.toString(),
        'blocked-trades': featureStats.blockedTrades.toString(),
        'exits-executed': featureStats.exitsExecuted.toString()
    };

    for (const [id, value] of Object.entries(elements)) {
        const el = document.getElementById(id);
        if (el) el.innerText = value;
    }
}

// Track stats from alerts (called from socket message handler)
function processAlertStats(data) {
    const alertType = data.type || 'unknown';

    switch (alertType) {
        case 'influencer':
            featureStats.influencerSignals++;
            break;
        case 'cabal':
            featureStats.cabalClusters++;
            break;
        case 'fresh_wallet':
            featureStats.freshWallets++;
            break;
        case 'blocked':
            featureStats.blockedTrades++;
            break;
        case 'exit':
            featureStats.exitsExecuted++;
            break;
    }

    updateFeatureStats();
}

// Initial update
updateFeatureStats();

// Fetch extended stats from backend periodically
async function fetchExtendedStats() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update websocket clients if available
        if (data.websocket_clients !== undefined) {
            const subwalletEl = document.getElementById('subwallet-count');
            if (subwalletEl) subwalletEl.innerText = data.websocket_clients;
        }
    } catch (e) {
        console.log("Extended stats fetch failed", e);
    }
}

// Fetch stats every 30s
setInterval(fetchExtendedStats, 30000);
fetchExtendedStats();

console.log('📊 Dashboard initialized with feature sections');

// ============================================================================
// POSITIONS PANEL & PNL DISPLAY
// ============================================================================

let positions = [];

async function refreshPositions() {
    try {
        const response = await fetch('/api/trade/positions');
        const data = await response.json();

        positions = data.positions || [];
        renderPositionsPanel(positions);
        updatePnLDisplay(data.summary);
    } catch (err) {
        console.error('Failed to refresh positions:', err);
    }
}

function renderPositionsPanel(positions) {
    const container = document.getElementById('positions-panel');
    if (!container) return;

    if (positions.length === 0) {
        container.innerHTML = `
            <div class="positions-empty">
                <span>📭 No open positions</span>
            </div>
        `;
        return;
    }

    container.innerHTML = positions.map(pos => {
        const pnlClass = pos.pnl_pct >= 0 ? 'pnl-positive' : 'pnl-negative';
        const pnlSign = pos.pnl_pct >= 0 ? '+' : '';

        return `
            <div class="position-card">
                <div class="position-header">
                    <span class="position-token">${pos.token}</span>
                    <span class="${pnlClass}">${pnlSign}${pos.pnl_pct?.toFixed(1)}%</span>
                </div>
                <div class="position-details">
                    <span>Entry: ${pos.entry_price?.toFixed(8)}</span>
                    <span>Current: ${pos.current_price?.toFixed(8)}</span>
                </div>
                <div class="position-footer">
                    <span>${pos.amount_sol?.toFixed(3)} SOL</span>
                    <button class="close-position-btn" onclick="closePosition('${pos.trade_id}')">
                        Close
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function updatePnLDisplay(summary) {
    const pnlEl = document.getElementById('stat-pnl');
    if (!pnlEl || !summary) return;

    const totalPnl = summary.total_pnl_sol || 0;
    const sign = totalPnl >= 0 ? '+' : '';

    pnlEl.innerText = `${sign}${totalPnl.toFixed(4)} SOL`;
    pnlEl.className = totalPnl >= 0 ? 'stat-value pnl-positive' : 'stat-value pnl-negative';
}

window.closePosition = async function (tradeId) {
    if (!confirm('Close this position?')) return;

    try {
        const response = await fetch(`/api/trade/close/${tradeId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });

        const result = await response.json();
    } catch (e) {
        console.error("Close position error:", e);
        addLog('error', `Close failed: ${e.message}`);
    }
};

// Refresh positions on load and periodically
refreshPositions();
setInterval(refreshPositions, 15000);

console.log('💹 Trading features initialized');

// ============================================================================
// ALERT BANNER
// ============================================================================

let alertBannerTimeout = null;

function showAlertBanner(type, icon, text) {
    const banner = document.getElementById('alert-banner');
    const iconEl = document.getElementById('alert-banner-icon') || banner.querySelector('.alert-banner-icon');
    const textEl = document.getElementById('alert-banner-text');

    if (!banner) return;

    // Clear previous timeout
    if (alertBannerTimeout) {
        clearTimeout(alertBannerTimeout);
    }

    // Set content
    if (iconEl) iconEl.textContent = icon;
    if (textEl) textEl.textContent = text;

    // Set type class
    banner.className = 'alert-banner ' + type;

    // Show with animation
    banner.classList.remove('hidden');
    requestAnimationFrame(() => {
        banner.classList.add('visible');
    });

    // Auto-hide after 8 seconds
    alertBannerTimeout = setTimeout(() => {
        hideAlertBanner();
    }, 8000);

    // Play notification sound (optional)
    playNotificationSound();
}

window.hideAlertBanner = function () {
    const banner = document.getElementById('alert-banner');
    if (!banner) return;

    banner.classList.remove('visible');
    setTimeout(() => {
        banner.classList.add('hidden');
    }, 400);
};

function playNotificationSound() {
    // Create a subtle notification beep
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);

        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.value = 0.1;

        oscillator.start();
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.2);
        oscillator.stop(audioCtx.currentTime + 0.2);
    } catch (e) {
        // Audio not supported or blocked
    }
}

// ============================================================================
// FRESH WALLET ACTIVITY FEED
// ============================================================================

const freshWalletCards = [];
const MAX_FRESH_CARDS = 10;

function addFreshWalletCard(data) {
    const feed = document.getElementById('fresh-wallet-feed');
    if (!feed) return;

    // Remove empty placeholder
    const emptyEl = feed.querySelector('.activity-empty');
    if (emptyEl) emptyEl.remove();

    // Create card data
    const cardData = {
        recipient: data.recipient || 'Unknown',
        cexName: data.cex_name || 'CEX',
        amount: data.amount || data.amount_sol || 0,
        confidence: data.confidence || 0.5,
        timestamp: new Date()
    };

    freshWalletCards.unshift(cardData);
    if (freshWalletCards.length > MAX_FRESH_CARDS) {
        freshWalletCards.pop();
    }

    // Create card element
    const card = document.createElement('div');
    card.className = 'activity-card';

    const confidencePct = (cardData.confidence * 100).toFixed(0);
    const badgeClass = cardData.confidence >= 0.8 ? 'high' : '';

    card.innerHTML = `
        <span class="activity-card-icon">💸</span>
        <div class="activity-card-info">
            <span class="activity-card-title">${shortenAddress(cardData.recipient)}</span>
            <span class="activity-card-subtitle">${cardData.cexName} → ${cardData.amount.toFixed(2)} SOL</span>
        </div>
        <span class="activity-card-badge ${badgeClass}">${confidencePct}% conf</span>
    `;

    // Insert at top
    feed.insertBefore(card, feed.firstChild);

    // Remove excess cards from DOM
    while (feed.children.length > MAX_FRESH_CARDS) {
        feed.removeChild(feed.lastChild);
    }
}

// ============================================================================
// SERVICE STATUS INDICATORS
// ============================================================================

async function updateServiceStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        const services = data.services || {};

        // Update Redis status
        updateStatusDot('status-redis', services.redis?.status);

        // Update Postgres status
        updateStatusDot('status-postgres', services.postgres?.status);

        // Update Neo4j status
        updateStatusDot('status-neo4j', services.neo4j?.status);

    } catch (e) {
        // Set all to pending on error
        updateStatusDot('status-redis', 'pending');
        updateStatusDot('status-postgres', 'pending');
        updateStatusDot('status-neo4j', 'pending');
    }
}

function updateStatusDot(elementId, status) {
    const el = document.getElementById(elementId);
    if (!el) return;

    // Remove previous classes
    el.classList.remove('connected', 'error', 'pending');

    // Add new class
    if (status === 'connected') {
        el.classList.add('connected');
    } else if (status === 'error' || status === 'disconnected') {
        el.classList.add('error');
    } else {
        el.classList.add('pending');
    }
}

// Fetch service status on load and periodically
updateServiceStatus();
setInterval(updateServiceStatus, 10000);

console.log('🎛️ Dashboard upgrades loaded');
