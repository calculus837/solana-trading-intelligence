# ⚡ Vultr VPS Setup Guide (Step-by-Step)

## 1. Create Account & Add Payment
1.  Go to [Vultr.com](https://www.vultr.com/).
2.  Login or Sign Up.
3.  Ensure you have added a credit card (required to spin up servers).

## 2. Deploy New Instance
Click the blue **[+]** or **"Deploy New Instance"** button (top right).

### Step 2.1: Choose Server Type
*   **Select:** `Cloud Compute` (Cheapest/Standard) OR `High Frequency` (Faster NVMe, recommended for $6+).

### Step 2.2: Choose Location
*   **Select:** `New York (NJ)` or `Tokyo` (Select the one closest to where you think most Solana activity/RPCs are, usually US East or Tokyo). 
    *   *Tip:* `New York (NJ)` is a safe bet for liquidity.

### Step 2.3: Server Image (OS)
*   **Select:** `Ubuntu`
*   **Version:** `22.04 LTS x64` (Do NOT choose 24.04 yet, 22.04 is most stable for Docker).

### Step 2.4: Server Size
*   **Filter:** "Regular Performance" (if available).
*   **Select:** **55 GB SSD / 2 vCPU / 4 GB RAM** (~$24/month)
    *   *Minimum:* You CAN try the $12/mo (2GB RAM) plan but it might struggle.
    *   *Recommended for 10h deadline:* **4 GB RAM** or **8 GB RAM** plan to avoid headaches.

### Step 2.5: Additional Features (Optional)
*   Uncheck backups (save money).
*   Uncheck IPv6 (not needed).

### Step 2.6: Hostname
*   **Enter Server Hostname:** `solana-intel-prod` (or anything you like).
*   **Click:** `Deploy Now`

## 3. Get Your IP & Password
1.  Wait ~60 seconds for the status to change from "Installing" to "Running".
2.  Click on the **Server Name** (`solana-intel-prod`) to open details.
3.  **IP Address:** Copy the numbers (e.g., `149.28.xxx.xxx`).
4.  **Username:** It will say `root`.
5.  **Password:** Click the "Copy" icon next to the hidden password field.

## 4. Run Deployment (From Your Local PC)
Now go back to your VS Code terminal and run:

```bash
# syntax: ./deploy/deploy.sh root@<YOUR_COPIED_IP>

./deploy/deploy.sh root@149.28.123.456
```

*   It will ask for a password. Paste the one you copied from Vultr.
*   (If asked "Are you sure you want to continue connecting?", type `yes`).

---
**Status Check:**
Once the script finishes, copy the IP into your browser: `http://<YOUR_IP>:8000`.
