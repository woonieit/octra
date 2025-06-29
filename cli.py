#!/usr/bin/env python3
import json
import base64
import hashlib
import time
import sys
import re
import random
import string
import os
import shutil
import asyncio
import aiohttp
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, List, Dict, Any
import nacl.signing

# Color codes
class Colors:
    RESET = '\033[0m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    BG_BLUE = '\033[44m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    WHITE = '\033[97m'

# Constants
MICRO_UNIT = 1_000_000
ADDRESS_REGEX = re.compile(r"^oct[1-9A-HJ-NP-Za-km-z]{44}$")
AMOUNT_REGEX = re.compile(r"^\d+(\.\d+)?$")
SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

class WalletClient:
    def __init__(self):
        self.priv_key: Optional[str] = None
        self.address: Optional[str] = None
        self.rpc_url: Optional[str] = None
        self.signing_key: Optional[nacl.signing.SigningKey] = None
        self.public_key: Optional[str] = None
        
        self.current_balance: Optional[float] = None
        self.current_nonce: Optional[int] = None
        self.last_update: float = 0
        self.last_history_update: float = 0
        
        self.transaction_history: List[Dict[str, Any]] = []
        self.session: Optional[aiohttp.ClientSession] = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.stop_flag = threading.Event()
        self.spinner_idx = 0
        
    def __del__(self):
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())
        self.executor.shutdown(wait=False)

    # Terminal utilities
    @staticmethod
    def clear_screen():
        os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def get_terminal_size() -> Tuple[int, int]:
        return shutil.get_terminal_size((80, 25))

    @staticmethod
    def move_cursor(x: int, y: int, text: str, color: str = ''):
        print(f"\033[{y};{x}H{Colors.BG_BLUE}{color}{text}{Colors.BG_BLUE}", end='')

    @staticmethod
    def input_at(x: int, y: int) -> str:
        print(f"\033[{y};{x}H{Colors.BG_BLUE}{Colors.BOLD}{Colors.WHITE}", end='', flush=True)
        return input()

    async def async_input(self, x: int, y: int) -> str:
        print(f"\033[{y};{x}H{Colors.BG_BLUE}{Colors.BOLD}{Colors.WHITE}", end='', flush=True)
        try:
            return await asyncio.get_event_loop().run_in_executor(self.executor, input)
        except:
            self.stop_flag.set()
            return ''

    def load_wallet(self) -> bool:
        """Load wallet configuration from JSON file"""
        try:
            with open('wallet.json', 'r') as f:
                data = json.load(f)
            
            self.priv_key = data.get('priv')
            self.address = data.get('addr')
            self.rpc_url = data.get('rpc', 'https://octra.network')
            
            if not self.priv_key or not self.address:
                return False
                
            self.signing_key = nacl.signing.SigningKey(base64.b64decode(self.priv_key))
            self.public_key = base64.b64encode(self.signing_key.verify_key.encode()).decode()
            return True
        except Exception as e:
            print(f"Error loading wallet: {e}")
            return False

    def fill_background(self):
        """Fill terminal with background color"""
        cols, rows = self.get_terminal_size()
        print(f"{Colors.BG_BLUE}", end='')
        for _ in range(rows):
            print(" " * cols)
        print("\033[H", end='')

    def draw_box(self, x: int, y: int, width: int, height: int, title: str = ""):
        """Draw a box with optional title"""
        print(f"\033[{y};{x}H{Colors.BG_BLUE}{Colors.WHITE}┌{'─' * (width - 2)}┐{Colors.BG_BLUE}")
        if title:
            print(f"\033[{y};{x}H{Colors.BG_BLUE}{Colors.WHITE}┤ {Colors.BOLD}{title} {Colors.WHITE}├{Colors.BG_BLUE}")
        
        for i in range(1, height - 1):
            print(f"\033[{y + i};{x}H{Colors.BG_BLUE}{Colors.WHITE}│{' ' * (width - 2)}│{Colors.BG_BLUE}")
        
        print(f"\033[{y + height - 1};{x}H{Colors.BG_BLUE}{Colors.WHITE}└{'─' * (width - 2)}┘{Colors.BG_BLUE}")

    async def spinner_animation(self, x: int, y: int, message: str):
        """Display spinning animation"""
        try:
            while True:
                self.move_cursor(x, y, f"{Colors.CYAN}{SPINNER_FRAMES[self.spinner_idx]} {message}", Colors.CYAN)
                self.spinner_idx = (self.spinner_idx + 1) % len(SPINNER_FRAMES)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            self.move_cursor(x, y, " " * (len(message) + 3), "")

    async def http_request(self, method: str, path: str, data: Optional[Dict] = None, timeout: int = 10) -> Tuple[int, str, Optional[Dict]]:
        """Make HTTP request to RPC endpoint"""
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
        
        try:
            url = f"{self.rpc_url}{path}"
            async with getattr(self.session, method.lower())(url, json=data if method == 'POST' else None) as resp:
                text = await resp.text()
                try:
                    json_data = json.loads(text) if text else None
                except:
                    json_data = None
                return resp.status, text, json_data
        except asyncio.TimeoutError:
            return 0, "timeout", None
        except Exception as e:
            return 0, str(e), None

    async def get_status(self) -> Tuple[Optional[int], Optional[float]]:
        """Get current nonce and balance"""
        now = time.time()
        if self.current_balance is not None and (now - self.last_update) < 30:
            return self.current_nonce, self.current_balance
        
        # Parallel requests for efficiency
        results = await asyncio.gather(
            self.http_request('GET', f'/balance/{self.address}'),
            self.http_request('GET', '/staging', 5),
            return_exceptions=True
        )
        
        status, text, json_data = results[0] if not isinstance(results[0], Exception) else (0, str(results[0]), None)
        staging_status, _, staging_data = results[1] if not isinstance(results[1], Exception) else (0, None, None)
        
        if status == 200 and json_data:
            self.current_nonce = int(json_data.get('nonce', 0))
            self.current_balance = float(json_data.get('balance', 0))
            self.last_update = now
            
            # Check staging for pending transactions
            if staging_status == 200 and staging_data:
                our_txs = [tx for tx in staging_data.get('staged_transactions', []) if tx.get('from') == self.address]
                if our_txs:
                    self.current_nonce = max(self.current_nonce, max(int(tx.get('nonce', 0)) for tx in our_txs))
        elif status == 404:
            self.current_nonce, self.current_balance, self.last_update = 0, 0.0, now
        elif status == 200 and text and not json_data:
            # Parse text response
            try:
                parts = text.strip().split()
                if len(parts) >= 2:
                    self.current_balance = float(parts[0]) if parts[0].replace('.', '').isdigit() else 0.0
                    self.current_nonce = int(parts[1]) if parts[1].isdigit() else 0
                    self.last_update = now
            except:
                pass
                
        return self.current_nonce, self.current_balance

    async def get_history(self):
        """Fetch transaction history"""
        now = time.time()
        if now - self.last_history_update < 60 and self.transaction_history:
            return
        
        status, text, json_data = await self.http_request('GET', f'/address/{self.address}?limit=20')
        if status != 200 or (not json_data and not text):
            return
        
        if json_data and 'recent_transactions' in json_data:
            tx_hashes = [ref["hash"] for ref in json_data.get('recent_transactions', [])]
            tx_results = await asyncio.gather(
                *[self.http_request('GET', f'/tx/{hash}', 5) for hash in tx_hashes],
                return_exceptions=True
            )
            
            existing_hashes = {tx['hash'] for tx in self.transaction_history}
            new_history = []
            
            for ref, result in zip(json_data.get('recent_transactions', []), tx_results):
                if isinstance(result, Exception):
                    continue
                    
                tx_status, _, tx_data = result
                if tx_status == 200 and tx_data and 'parsed_tx' in tx_data:
                    parsed = tx_data['parsed_tx']
                    tx_hash = ref['hash']
                    
                    if tx_hash in existing_hashes:
                        continue
                    
                    is_incoming = parsed.get('to') == self.address
                    amount_raw = parsed.get('amount_raw', parsed.get('amount', '0'))
                    amount = float(amount_raw) if '.' in str(amount_raw) else int(amount_raw) / MICRO_UNIT
                    
                    new_history.append({
                        'time': datetime.fromtimestamp(parsed.get('timestamp', 0)),
                        'hash': tx_hash,
                        'amt': amount,
                        'to': parsed.get('to') if not is_incoming else parsed.get('from'),
                        'type': 'in' if is_incoming else 'out',
                        'ok': True,
                        'nonce': parsed.get('nonce', 0),
                        'epoch': ref.get('epoch', 0)
                    })
            
            # Keep only recent transactions
            one_hour_ago = datetime.now() - timedelta(hours=1)
            self.transaction_history[:] = sorted(
                new_history + [tx for tx in self.transaction_history if tx.get('time', datetime.now()) > one_hour_ago],
                key=lambda x: x['time'],
                reverse=True
            )[:50]
            self.last_history_update = now
        elif status == 404 or (status == 200 and text and 'no transactions' in text.lower()):
            self.transaction_history.clear()
            self.last_history_update = now

    def create_transaction(self, to_address: str, amount: float, nonce: int) -> Tuple[Dict, str]:
        """Create and sign a transaction"""
        tx = {
            "from": self.address,
            "to_": to_address,
            "amount": str(int(amount * MICRO_UNIT)),
            "nonce": int(nonce),
            "ou": "1" if amount < 1000 else "3",
            "timestamp": time.time() + random.random() * 0.01
        }
        
        # Sign transaction
        tx_bytes = json.dumps(tx, separators=(",", ":")).encode()
        signature = base64.b64encode(self.signing_key.sign(tx_bytes).signature).decode()
        tx.update(signature=signature, public_key=self.public_key)
        
        # Calculate hash
        tx_hash = hashlib.sha256(tx_bytes).hexdigest()
        
        return tx, tx_hash

    async def send_transaction(self, tx: Dict) -> Tuple[bool, str, float, Optional[Dict]]:
        """Send transaction to network"""
        start_time = time.time()
        status, text, json_data = await self.http_request('POST', '/send-tx', tx)
        elapsed = time.time() - start_time
        
        if status == 200:
            if json_data and json_data.get('status') == 'accepted':
                return True, json_data.get('tx_hash', ''), elapsed, json_data
            elif text.lower().startswith('ok'):
                return True, text.split()[-1], elapsed, None
                
        return False, json.dumps(json_data) if json_data else text, elapsed, json_data

    async def display_explorer(self, x: int, y: int, width: int, height: int):
        """Display wallet explorer panel"""
        self.draw_box(x, y, width, height, "wallet explorer")
        
        nonce, balance = await self.get_status()
        await self.get_history()
        
        # Display wallet info
        self.move_cursor(x + 2, y + 2, "address:", Colors.CYAN)
        self.move_cursor(x + 11, y + 2, self.address, Colors.WHITE)
        
        self.move_cursor(x + 2, y + 3, "balance:", Colors.CYAN)
        balance_color = Colors.BOLD + Colors.GREEN if balance else Colors.WHITE
        self.move_cursor(x + 11, y + 3, f"{balance:.6f} oct" if balance is not None else "---", balance_color)
        
        self.move_cursor(x + 2, y + 4, "nonce:  ", Colors.CYAN)
        self.move_cursor(x + 11, y + 4, str(nonce) if nonce is not None else "---", Colors.WHITE)
        
        self.move_cursor(x + 2, y + 5, "public: ", Colors.CYAN)
        self.move_cursor(x + 11, y + 5, self.public_key, Colors.WHITE)
        
        # Check staging
        _, _, staging_data = await self.http_request('GET', '/staging', 2)
        staging_count = len([tx for tx in staging_data.get('staged_transactions', []) 
                           if tx.get('from') == self.address]) if staging_data else 0
        
        self.move_cursor(x + 2, y + 6, "staging:", Colors.CYAN)
        self.move_cursor(x + 11, y + 6, f"{staging_count} pending" if staging_count else "none", 
                        Colors.YELLOW if staging_count else Colors.WHITE)
        
        self.move_cursor(x + 1, y + 7, "─" * (width - 2), Colors.WHITE)
        
        # Display transaction history
        self.move_cursor(x + 2, y + 8, "recent transactions:", Colors.BOLD + Colors.CYAN)
        
        if not self.transaction_history:
            self.move_cursor(x + 2, y + 10, "no transactions yet", Colors.YELLOW)
        else:
            self.move_cursor(x + 2, y + 10, "time     type  amount      address", Colors.CYAN)
            self.move_cursor(x + 2, y + 11, "─" * (width - 4), Colors.WHITE)
            
            seen_hashes = set()
            display_count = 0
            
            for tx in sorted(self.transaction_history, key=lambda x: x['time'], reverse=True):
                if tx['hash'] in seen_hashes:
                    continue
                    
                seen_hashes.add(tx['hash'])
                if display_count >= min(len(self.transaction_history), height - 15):
                    break
                
                is_pending = not tx.get('epoch')
                time_color = Colors.YELLOW if is_pending else Colors.WHITE
                
                self.move_cursor(x + 2, y + 12 + display_count, tx['time'].strftime('%H:%M:%S'), time_color)
                self.move_cursor(x + 11, y + 12 + display_count, " in" if tx['type'] == 'in' else "out", 
                               Colors.GREEN if tx['type'] == 'in' else Colors.RED)
                self.move_cursor(x + 16, y + 12 + display_count, f"{float(tx['amt']):>10.6f}", Colors.WHITE)
                self.move_cursor(x + 28, y + 12 + display_count, str(tx.get('to', '---')), Colors.YELLOW)
                
                status_text = "pen" if is_pending else f"e{tx.get('epoch', 0)}"
                status_color = Colors.YELLOW + Colors.BOLD if is_pending else Colors.CYAN
                self.move_cursor(x + width - 6, y + 12 + display_count, status_text, status_color)
                
                display_count += 1

    def display_menu(self, x: int, y: int, width: int, height: int):
        """Display command menu"""
        self.draw_box(x, y, width, height, "commands")
        
        menu_items = [
            (3, "[1] send tx"),
            (5, "[2] refresh balance"),
            (7, "[3] multi send"),
            (9, "[4] export keys"),
            (11, "[5] clear hist"),
            (13, "[0] exit")
        ]
        
        for y_offset, text in menu_items:
            self.move_cursor(x + 2, y + y_offset, text, Colors.WHITE)
        
        self.move_cursor(x + 2, y + height - 2, "command: ", Colors.BOLD + Colors.YELLOW)

    async def display_main_screen(self) -> str:
        """Display main screen and get user command"""
        cols, rows = self.get_terminal_size()
        self.clear_screen()
        self.fill_background()
        
        # Header
        title = f" octra pre-client v0.0.12 (optimized) │ {datetime.now().strftime('%H:%M:%S')} "
        self.move_cursor((cols - len(title)) // 2, 1, title, Colors.BOLD + Colors.WHITE)
        
        # Layout
        sidebar_width = 28
        self.display_menu(2, 3, sidebar_width, 17)
        
        # Info box
        info_y = 21
        self.draw_box(2, info_y, sidebar_width, 9)
        self.move_cursor(4, info_y + 2, "testnet environment.", Colors.YELLOW)
        self.move_cursor(4, info_y + 3, "actively updated.", Colors.YELLOW)
        self.move_cursor(4, info_y + 4, "monitor changes!", Colors.YELLOW)
        self.move_cursor(4, info_y + 6, "testnet tokens have", Colors.YELLOW)
        self.move_cursor(4, info_y + 7, "no commercial value.", Colors.YELLOW)
        
        # Explorer
        explorer_x = sidebar_width + 4
        explorer_width = cols - explorer_x - 2
        await self.display_explorer(explorer_x, 3, explorer_width, rows - 6)
        
        # Status bar
        self.move_cursor(2, rows - 1, " " * (cols - 4), Colors.BG_BLUE)
        self.move_cursor(2, rows - 1, "ready", Colors.BG_GREEN + Colors.WHITE)
        
        return await self.async_input(13, 18)

    async def send_single_transaction(self):
        """Handle single transaction sending"""
        cols, rows = self.get_terminal_size()
        self.clear_screen()
        self.fill_background()
        
        width, height = 85, 22
        x = (cols - width) // 2
        y = (rows - height) // 2
        
        self.draw_box(x, y, width, height, "send transaction")
        
        # Get recipient address
        self.move_cursor(x + 2, y + 2, "to address: (or [esc] to cancel)", Colors.YELLOW)
        self.move_cursor(x + 2, y + 3, "─" * (width - 4), Colors.WHITE)
        to_address = await self.async_input(x + 2, y + 4)
        
        if not to_address or to_address.lower() == 'esc':
            return
        
        # Validate address
        if not ADDRESS_REGEX.match(to_address):
            self.move_cursor(x + 2, y + 14, "invalid address format! Expected: oct[44 characters]", Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + 15, "Example: oct1234567890abcdefghijklmnopqrstuvwxyz12345678", Colors.YELLOW)
            self.move_cursor(x + 2, y + 16, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + 17)
            return
        
        self.move_cursor(x + 2, y + 5, f"to: {to_address}", Colors.GREEN)
        
        # Get amount
        self.move_cursor(x + 2, y + 7, "amount: (or [esc] to cancel)", Colors.YELLOW)
        self.move_cursor(x + 2, y + 8, "─" * (width - 4), Colors.WHITE)
        amount_str = await self.async_input(x + 2, y + 9)
        
        if not amount_str or amount_str.lower() == 'esc':
            return
        
        # Validate amount
        if not AMOUNT_REGEX.match(amount_str) or float(amount_str) <= 0:
            self.move_cursor(x + 2, y + 14, "invalid amount! Must be a positive number.", Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + 15, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + 16)
            return
        
        amount = float(amount_str)
        
        # Get current status
        self.last_update = 0  # Force refresh
        nonce, balance = await self.get_status()
        
        if nonce is None:
            self.move_cursor(x + 2, y + 14, "failed to get nonce!", Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + 15, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + 16)
            return
        
        if not balance or balance < amount:
            self.move_cursor(x + 2, y + 14, f"insufficient balance ({balance:.6f} < {amount})", Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + 15, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + 16)
            return
        
        # Confirm transaction
        self.move_cursor(x + 2, y + 11, "─" * (width - 4), Colors.WHITE)
        self.move_cursor(x + 2, y + 12, f"send {amount:.6f} oct", Colors.BOLD + Colors.GREEN)
        self.move_cursor(x + 2, y + 13, f"to:  {to_address}", Colors.GREEN)
        self.move_cursor(x + 2, y + 14, f"fee: {'0.001' if amount < 1000 else '0.003'} oct (nonce: {nonce + 1})", Colors.YELLOW)
        self.move_cursor(x + 2, y + 15, "[y]es / [n]o: ", Colors.BOLD + Colors.YELLOW)
        
        if (await self.async_input(x + 16, y + 15)).strip().lower() != 'y':
            return
        
        # Send transaction
        spin_task = asyncio.create_task(self.spinner_animation(x + 2, y + 16, "sending transaction"))
        
        tx, _ = self.create_transaction(to_address, amount, nonce + 1)
        success, tx_hash, elapsed, response = await self.send_transaction(tx)
        
        spin_task.cancel()
        try:
            await spin_task
        except asyncio.CancelledError:
            pass
        
        # Display result
        if success:
            for i in range(16, 21):
                self.move_cursor(x + 2, y + i, " " * (width - 4), Colors.BG_BLUE)
            
            self.move_cursor(x + 2, y + 16, f"✓ transaction accepted!", Colors.BG_GREEN + Colors.WHITE)
            self.move_cursor(x + 2, y + 17, f"hash: {tx_hash[:64]}...", Colors.GREEN)
            self.move_cursor(x + 2, y + 18, f"      {tx_hash[64:]}", Colors.GREEN)
            self.move_cursor(x + 2, y + 19, f"time: {elapsed:.2f}s", Colors.WHITE)
            
            if response and 'pool_info' in response:
                pool_size = response['pool_info'].get('total_pool_size', 0)
                self.move_cursor(x + 2, y + 20, f"pool: {pool_size} txs pending", Colors.YELLOW)
            
            # Add to history
            self.transaction_history.append({
                'time': datetime.now(),
                'hash': tx_hash,
                'amt': amount,
                'to': to_address,
                'type': 'out',
                'ok': True
            })
            self.last_update = 0  # Force balance refresh
        else:
            self.move_cursor(x + 2, y + 16, f"✗ transaction failed!", Colors.BG_RED + Colors.WHITE)
            error_msg = str(tx_hash)[:width - 10]
            self.move_cursor(x + 2, y + 17, f"error: {error_msg}", Colors.RED)
        
        await self.wait_for_key()

    async def send_multi_transaction(self):
        """Handle multiple transaction sending with improved validation"""
        cols, rows = self.get_terminal_size()
        self.clear_screen()
        self.fill_background()
        
        width, height = 70, rows - 4
        x = (cols - width) // 2
        y = 2
        
        self.draw_box(x, y, width, height, "multi send")
        
        # Instructions
        self.move_cursor(x + 2, y + 2, "enter recipients (address amount), empty line to finish:", Colors.YELLOW)
        self.move_cursor(x + 2, y + 3, "format: oct[44-char-address] amount", Colors.CYAN)
        self.move_cursor(x + 2, y + 4, "example: oct1234...xyz 10.5", Colors.CYAN)
        self.move_cursor(x + 2, y + 5, "type [esc] to cancel", Colors.CYAN)
        self.move_cursor(x + 2, y + 6, "─" * (width - 4), Colors.WHITE)
        
        recipients = []
        total_amount = 0
        line_y = y + 7
        max_lines = height - 15
        
        while line_y < y + 7 + max_lines:
            self.move_cursor(x + 2, line_y, f"[{len(recipients) + 1}] ", Colors.CYAN)
            line_input = await self.async_input(x + 7, line_y)
            
            if line_input.lower() == 'esc':
                return
            
            if not line_input:
                break
            
            # Improved parsing with better error messages
            parts = line_input.strip().split()
            
            if len(parts) != 2:
                self.move_cursor(x + 40, line_y, "need address & amount", Colors.RED)
                continue
            
            address, amount_str = parts
            
            # Validate address
            if not ADDRESS_REGEX.match(address):
                self.move_cursor(x + 40, line_y, "invalid address!", Colors.RED)
                self.move_cursor(x + 2, line_y + 1, f"  └─ Expected: oct[44 chars]", Colors.YELLOW)
                line_y += 1
                continue
            
            # Validate amount
            if not AMOUNT_REGEX.match(amount_str) or float(amount_str) <= 0:
                self.move_cursor(x + 40, line_y, "invalid amount!", Colors.RED)
                continue
            
            amount = float(amount_str)
            recipients.append((address, amount))
            total_amount += amount
            
            self.move_cursor(x + 50, line_y, f"+{amount:.6f}", Colors.GREEN)
            line_y += 1
        
        if not recipients:
            return
        
        # Display summary
        self.move_cursor(x + 2, y + height - 7, "─" * (width - 4), Colors.WHITE)
        self.move_cursor(x + 2, y + height - 6, f"total: {total_amount:.6f} oct to {len(recipients)} addresses", 
                        Colors.BOLD + Colors.YELLOW)
        
        # Check balance
        self.last_update = 0  # Force refresh
        nonce, balance = await self.get_status()
        
        if nonce is None:
            self.move_cursor(x + 2, y + height - 5, "failed to get nonce!", Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + height - 4, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + height - 3)
            return
        
        if not balance or balance < total_amount:
            self.move_cursor(x + 2, y + height - 5, f"insufficient balance! ({balance:.6f} < {total_amount})", 
                           Colors.BG_RED + Colors.WHITE)
            self.move_cursor(x + 2, y + height - 4, "press enter to go back...", Colors.YELLOW)
            await self.async_input(x + 2, y + height - 3)
            return
        
        # Confirm
        self.move_cursor(x + 2, y + height - 5, f"send all? [y/n] (starting nonce: {nonce + 1}): ", Colors.YELLOW)
        if (await self.async_input(x + 48, y + height - 5)).strip().lower() != 'y':
            return
        
        # Send transactions
        spin_task = asyncio.create_task(self.spinner_animation(x + 2, y + height - 3, "sending transactions"))
        
        batch_size = 5
        batches = [recipients[i:i+batch_size] for i in range(0, len(recipients), batch_size)]
        success_count, fail_count = 0, 0
        
        for batch_idx, batch in enumerate(batches):
            tasks = []
            
            for i, (to_address, amount) in enumerate(batch):
                idx = batch_idx * batch_size + i
                self.move_cursor(x + 2, y + height - 2, f"[{idx + 1}/{len(recipients)}] preparing batch...", Colors.CYAN)
                
                tx, _ = self.create_transaction(to_address, amount, nonce + 1 + idx)
                tasks.append(self.send_transaction(tx))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for i, (result, (to_address, amount)) in enumerate(zip(results, batch)):
                idx = batch_idx * batch_size + i
                
                if isinstance(result, Exception):
                    fail_count += 1
                    self.move_cursor(x + 55, y + height - 2, "✗ fail ", Colors.RED)
                else:
                    success, tx_hash, _, _ = result
                    if success:
                        success_count += 1
                        self.move_cursor(x + 55, y + height - 2, "✓ ok   ", Colors.GREEN)
                        
                        # Add to history
                        self.transaction_history.append({
                            'time': datetime.now(),
                            'hash': tx_hash,
                            'amt': amount,
                            'to': to_address,
                            'type': 'out',
                            'ok': True
                        })
                    else:
                        fail_count += 1
                        self.move_cursor(x + 55, y + height - 2, "✗ fail ", Colors.RED)
                
                self.move_cursor(x + 2, y + height - 2, f"[{idx + 1}/{len(recipients)}] {amount:.6f} to {to_address[:20]}...", 
                               Colors.CYAN)
                await asyncio.sleep(0.05)
        
        spin_task.cancel()
        try:
            await spin_task
        except asyncio.CancelledError:
            pass
        
        # Display final result
        self.last_update = 0  # Force refresh
        self.move_cursor(x + 2, y + height - 2, " " * 65, Colors.BG_BLUE)
        
        bg_color = Colors.BG_GREEN if fail_count == 0 else Colors.BG_RED
        self.move_cursor(x + 2, y + height - 2, f"completed: {success_count} success, {fail_count} failed", 
                        bg_color + Colors.WHITE)
        
        await self.wait_for_key()

    async def export_keys(self):
        """Export wallet keys and information"""
        cols, rows = self.get_terminal_size()
        self.clear_screen()
        self.fill_background()
        
        width, height = 70, 15
        x = (cols - width) // 2
        y = (rows - height) // 2
        
        self.draw_box(x, y, width, height, "export keys")
        
        # Display current wallet info
        self.move_cursor(x + 2, y + 2, "current wallet info:", Colors.CYAN)
        self.move_cursor(x + 2, y + 4, "address:", Colors.CYAN)
        self.move_cursor(x + 11, y + 4, self.address[:32] + "...", Colors.WHITE)
        
        self.move_cursor(x + 2, y + 5, "balance:", Colors.CYAN)
        nonce, balance = await self.get_status()
        self.move_cursor(x + 11, y + 5, f"{balance:.6f} oct" if balance is not None else "---", Colors.GREEN)
        
        # Export options
        self.move_cursor(x + 2, y + 7, "export options:", Colors.YELLOW)
        self.move_cursor(x + 2, y + 8, "[1] show private key", Colors.WHITE)
        self.move_cursor(x + 2, y + 9, "[2] save full wallet to file", Colors.WHITE)
        self.move_cursor(x + 2, y + 10, "[3] copy address to clipboard", Colors.WHITE)
        self.move_cursor(x + 2, y + 11, "[0] cancel", Colors.WHITE)
        self.move_cursor(x + 2, y + 13, "choice: ", Colors.BOLD + Colors.YELLOW)
        
        choice = await self.async_input(x + 10, y + 13)
        choice = choice.strip()
        
        # Clear options area
        for i in range(7, 14):
            self.move_cursor(x + 2, y + i, " " * (width - 4), Colors.BG_BLUE)
        
        if choice == '1':
            # Show private key
            self.move_cursor(x + 2, y + 7, "private key (keep secret!):", Colors.RED)
            self.move_cursor(x + 2, y + 8, self.priv_key[:32], Colors.RED)
            self.move_cursor(x + 2, y + 9, self.priv_key[32:], Colors.RED)
            self.move_cursor(x + 2, y + 11, "public key:", Colors.GREEN)
            self.move_cursor(x + 2, y + 12, self.public_key[:44] + "...", Colors.GREEN)
            
        elif choice == '2':
            # Save to file
            filename = f"octra_wallet_{int(time.time())}.json"
            wallet_data = {
                'priv': self.priv_key,
                'addr': self.address,
                'rpc': self.rpc_url
            }
            
            try:
                with open(filename, 'w') as f:
                    json.dump(wallet_data, f, indent=2)
                
                self.move_cursor(x + 2, y + 9, f"saved to {filename}", Colors.GREEN)
                self.move_cursor(x + 2, y + 11, "file contains private key - keep safe!", Colors.RED)
            except Exception as e:
                self.move_cursor(x + 2, y + 9, f"error saving file: {str(e)}", Colors.RED)
                
        elif choice == '3':
            # Copy to clipboard
            try:
                import pyperclip
                pyperclip.copy(self.address)
                self.move_cursor(x + 2, y + 9, "address copied to clipboard!", Colors.GREEN)
            except:
                self.move_cursor(x + 2, y + 9, "clipboard not available", Colors.RED)
                self.move_cursor(x + 2, y + 10, f"address: {self.address}", Colors.YELLOW)
        else:
            return
        
        await self.wait_for_key()

    async def wait_for_key(self):
        """Wait for user to press enter"""
        cols, rows = self.get_terminal_size()
        message = "press enter to continue..."
        message_len = len(message)
        y_pos = rows - 2
        x_pos = max(2, (cols - message_len) // 2)
        
        self.move_cursor(x_pos, y_pos, message, Colors.YELLOW)
        print(f"\033[{y_pos};{x_pos + message_len}H{Colors.BG_BLUE}", end='', flush=True)
        
        try:
            await asyncio.get_event_loop().run_in_executor(self.executor, input)
        except:
            self.stop_flag.set()

    async def run(self):
        """Main application loop"""
        if not self.load_wallet():
            sys.exit("[!] wallet.json error")
        
        if not self.address:
            sys.exit("[!] wallet.json not configured")
        
        try:
            # Initial data load
            await self.get_status()
            await self.get_history()
            
            while not self.stop_flag.is_set():
                command = await self.display_main_screen()
                
                if command == '1':
                    await self.send_single_transaction()
                elif command == '2':
                    # Force refresh
                    self.last_update = 0
                    self.last_history_update = 0
                    await self.get_status()
                    await self.get_history()
                elif command == '3':
                    await self.send_multi_transaction()
                elif command == '4':
                    await self.export_keys()
                elif command == '5':
                    # Clear history
                    self.transaction_history.clear()
                    self.last_history_update = 0
                elif command in ['0', 'q', '']:
                    break
                    
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if self.session and not self.session.closed:
                await self.session.close()
            self.executor.shutdown(wait=False)


async def main():
    """Entry point"""
    client = WalletClient()
    await client.run()


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=ResourceWarning)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        # Clean exit
        os.system('cls' if os.name == 'nt' else 'clear')
        print(Colors.RESET)
        os._exit(0)
