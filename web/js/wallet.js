/* Wallet Integration - Handles Phantom/Solana Adapter connection */

const btnConnect = document.getElementById('btn-connect');
let walletAddress = null;

// Check for Phantom on load
window.addEventListener('load', async () => {
    if (window.solana && window.solana.isPhantom) {
        console.log('👻 Phantom wallet found');

        // Eager connect if previously trusted
        try {
            const resp = await window.solana.connect({ onlyIfTrusted: true });
            handleConnect(resp.publicKey.toString());
        } catch (err) {
            // Not connected yet
        }
    } else {
        console.log('Solana wallet not found');
    }
});

btnConnect.addEventListener('click', async () => {
    if (!window.solana) {
        alert("Please install Phantom Wallet to access Intel features!");
        window.open('https://phantom.app/', '_blank');
        return;
    }

    try {
        if (!walletAddress) {
            // Connect
            const resp = await window.solana.connect();
            handleConnect(resp.publicKey.toString());
        } else {
            // Disconnect
            await window.solana.disconnect();
            handleDisconnect();
        }
    } catch (err) {
        console.error("Connection failed", err);
    }
});

function handleConnect(publicKey) {
    walletAddress = publicKey;
    const shortKey = publicKey.slice(0, 4) + '...' + publicKey.slice(-4);

    btnConnect.innerText = shortKey;
    btnConnect.classList.add('connected');

    // Announce to system
    console.log(`Wallet connected: ${publicKey}`);

    // Optional: Sign message to authenticate for private feed
    // signAuthMessage();
}

function handleDisconnect() {
    walletAddress = null;
    btnConnect.innerText = "Connect Wallet";
    btnConnect.classList.remove('connected');
}
