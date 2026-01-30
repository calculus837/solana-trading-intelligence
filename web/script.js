const termFeed = document.getElementById('terminal-feed');
const logs = [
    { type: 'info', text: 'Scanning CEX wallets [Binance, Coinbase, OKX]...' },
    { type: 'info', text: 'Geyser stream active: 24,000 tps' },
    { type: 'success', text: 'Latencystats: 45ms ping to eu-central-1' },
    { type: 'warn', text: 'Whale Alert: 5,000 SOL -> Fresh Wallet 8x...3k' },
    { type: 'info', text: 'Graph Update: 12 new nodes correlated' },
    { type: 'action', text: 'SIMULATION passed: Profit est. +2.4 SOL' },
    { type: 'success', text: 'Jito Bundle #892 accepted (Tip: 0.01 SOL)' },
    { type: 'info', text: 'Position closed. PnL: +12.5%' }
];

function addLog() {
    const log = logs[Math.floor(Math.random() * logs.length)];
    const now = new Date();
    const time = now.toLocaleTimeString('en-US', { hour12: false });

    const div = document.createElement('div');
    div.className = 'log-line';

    // Type formatting
    let typeClass = 'info';
    let typeLabel = 'INFO';

    if (log.type === 'success') { typeClass = 'success'; typeLabel = 'OK'; }
    if (log.type === 'warn') { typeClass = 'warn'; typeLabel = 'DETECT'; }
    if (log.type === 'action') { typeClass = 'action'; typeLabel = 'EXE'; }

    div.innerHTML = `<span class="timestamp">[${time}]</span> <span class="${typeClass}">${typeLabel}</span> ${log.text}`;

    termFeed.appendChild(div);

    // Auto scroll
    termFeed.scrollTop = termFeed.scrollHeight;

    // Cleanup old logs
    if (termFeed.children.length > 8) {
        termFeed.removeChild(termFeed.children[0]);
    }
}

// Start simulation
setInterval(addLog, 1500);
addLog(); // Initial log
