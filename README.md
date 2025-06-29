# Octra Public Testnet

## Join Discord
https://discord.gg/octra

---

## Requirements
Linux Ubuntu OS
* **VPS**: You can use a linux VPS to follow the guide
* **Windows**: Install Linux Ubuntu using WSL by following this [guide](https://github.com/0xmoei/Install-Linux-on-Windows)

---

## Install dependecies
Install & Update Packages:
```
sudo apt update && sudo apt upgrade -y
sudo apt install screen curl iptables build-essential git wget lz4 jq make gcc nano automake autoconf tmux htop nvme-cli libgbm1 pkg-config libssl-dev libleveldb-dev tar clang bsdmainutils ncdu unzip libleveldb-dev  -y
```
Install Nodejs (Only VPS users)
```
sudo apt update
sudo curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v
npm install -g yarn
yarn -v
```

---

## Create wallet
### 1. Clone the repository
   ```bash
   git clone https://github.com/0xmoei/wallet-gen.git
   cd wallet-gen
   ```

### 2. Run the wallet generator webserver
   **Linux/macOS:**
   ```bash
   chmod +x ./start.sh
   ./start.sh
   ```


### 3. Open your browser
* **WSL/Linux/MAC users:**
  * Navigate to `http://localhost:8888` on browser

  
* **VPS users:**
  * 1- Open a new terminal
  * 2- Install **localtunnel**:
    ```
    npm install -g localtunnel
    ```
  * 3- Get a password:
    ```
    curl https://loca.lt/mytunnelpassword
    ```
  * The password is actually your VPS IP
  * 4- Get URL
    ```
    lt --port 8888
    ```
  * Visit the prompted url, and enter your password to access wallet generator page

### 4. Generate wallet
* Click "GENERATE NEW WALLET" and watch the real-time progress
* Save all the details of your Wallet

---

## Get Faucet
* Visit [Faucet page](https://faucet.octra.network/)
* Enter your address starting with `oct...` to get faucet

![image](https://github.com/user-attachments/assets/18597b40-eaad-434f-a026-cc4a56a6d1a8)

---
## Task 1: Send transactions

**1. Install Python**
```
sudo apt install python3 python3-pip python3-venv python3-dev -y
```

**2. Install CLI**
```console
git clone https://github.com/octra-labs/octra_pre_client.git
cd octra_pre_client

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp wallet.json.example wallet.json
```

**2. Add wallet to CLI**
```
nano wallet.json
```
* Replace following values:
  * `private-key-here`: Privatekey with `B64` format
  * `octxxxxxxxx...`: Octra address starting with `oct...`


**3. Start CLI**
```
python3 -m venv venv
source venv/bin/activate
python3 cli.py
```

**4. Send transactions**
* Send transactions to my address: `octBvPDeFCaAZtfr3SBr7Jn6nnWnUuCfAZfgCmaqswV8YR5`
* Use [Octra Explorer](https://octrascan.io/) to find more octra addresses


---

## Wait for next steps
Stay tuned.
