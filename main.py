import sys
import threading
import time
import datetime
import json
import uuid
import hashlib
import random
from functools import partial
import os
import glob
import importlib.util
import shutil
import platform
import subprocess
import socket
import getpass
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

from PyQt5.QtWidgets import (QApplication, QMainWindow, QTableWidget, QTableWidgetItem, 
                             QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QHeaderView, 
                             QLabel, QLineEdit, QGroupBox, QTextEdit, QDialog, QFormLayout, 
                             QDoubleSpinBox, QMessageBox, QComboBox, QCheckBox, QAbstractSpinBox,
                             QFileDialog, QSpinBox, QTabWidget)
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject

try:
    import pyttsx3
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    
try:
    from PIL import ImageGrab
    import pyautogui
    SCREENSHOT_AVAILABLE = True
except ImportError:
    SCREENSHOT_AVAILABLE = False

try:
    from flask import Flask, request, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    print("⚠️ Pandas not available - some features disabled")
    PANDAS_AVAILABLE = False
    pd = None

# --- CHART CAPTURE MODULE ---
try:
    from chart_capture import detect_market_direction, capture_chart_with_analysis
    CHART_CAPTURE_AVAILABLE = True
except ImportError:
    CHART_CAPTURE_AVAILABLE = False

# --- MT5 IMPORT CHECK ---
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

# ==============================================================================
# --- ⚙️ PATH & SETTINGS SETUP (AUTO-FIX) ---
# ==============================================================================
# 1. Force Working Directory to Script Location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# Import protection system
try:
    from protection import HardwareProtection, AntiDebugProtection
    PROTECTION_AVAILABLE = True
except ImportError:
    PROTECTION_AVAILABLE = False
    print("⚠️ Protection module not found - running in limited mode")

# Import strategy protection
try:
    from strategy_protection import StrategyProtection, StrategyEncoder
    STRATEGY_PROTECTION_AVAILABLE = True
except ImportError:
    STRATEGY_PROTECTION_AVAILABLE = False
    print("⚠️ Strategy protection not available")

# Import market sentiment
try:
    from market_sentiment import MarketSentiment
    MARKET_SENTIMENT_AVAILABLE = True
except ImportError:
    MARKET_SENTIMENT_AVAILABLE = False
    print("⚠️ Market sentiment not available")

STRATEGIES_DIR = os.path.join(BASE_DIR, "Strategies")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")
LICENSE_FILE = os.path.join(BASE_DIR, "license.dat")
MACHINE_LICENSE_FILE = os.path.join(BASE_DIR, "machine.lic")
WEBHOOK_CONFIG_FILE = os.path.join(BASE_DIR, "webhook_config.json")
SECRET_SALT = "RUDRA24_QUANTUM"

# Webhook Server Settings
WEBHOOK_PORT = 5000
WEBHOOK_SECRET = "RUDRA24_WEBHOOK_KEY"

# AmiBroker Signal File Settings
AMIBROKER_SIGNAL_DIR = os.path.join(BASE_DIR, "AmiBroker_Signals")
AMIBROKER_SIGNAL_FILE = os.path.join(AMIBROKER_SIGNAL_DIR, "signals.txt")

# 2. Folder Check & Auto-Create
if not os.path.exists(STRATEGIES_DIR):
    try:
        os.makedirs(STRATEGIES_DIR)
        print(f"[DEBUG] Created missing folder: {STRATEGIES_DIR}")
    except Exception as e:
        print(f"[ERROR] Could not create folder: {e}")

if not os.path.exists(AMIBROKER_SIGNAL_DIR):
    try:
        os.makedirs(AMIBROKER_SIGNAL_DIR)
        print(f"[DEBUG] Created AmiBroker signals folder: {AMIBROKER_SIGNAL_DIR}")
    except Exception as e:
        print(f"[ERROR] Could not create AmiBroker folder: {e}")

# 3. Default Strategy Check
if os.path.exists(STRATEGIES_DIR) and not glob.glob(os.path.join(STRATEGIES_DIR, "*.py")):
    print("[DEBUG] No strategies found. Creating default TrendRider.py...")
    default_strat = os.path.join(STRATEGIES_DIR, "TrendRider.py")
    with open(default_strat, "w") as f:
        f.write('''
try:
    import pandas as pd
except ImportError:
    pd = None

def calculate(df, tick, positions):
    """
    Default Strategy: Trend Rider
    """
    if df.empty or len(df) < 5:
        return "WAIT"

    # Simple Logic: Current Close > Previous Close = BUY
    current = df.iloc[-1]
    prev = df.iloc[-2]
    
    if current['close'] > prev['close']:
        return "BUY SIGNAL"
    elif current['close'] < prev['close']:
        return "SELL SIGNAL"
        
    return "WAIT"
''')

# ==============================================================================
# --- 🔐 LICENSE SYSTEM ---
# ==============================================================================
def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: return json.load(f)
    except: pass
    return {}

def save_settings(l, p, s):
    try:
        with open(SETTINGS_FILE, 'w') as f: json.dump({"login":l, "password":p, "server":s}, f)
    except: pass

def get_serial():
    mac = uuid.getnode(); h = hashlib.md5(str(mac).encode()).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}-{h[12:16]}"

SERIAL_NO = get_serial()
IS_ACTIVATED = False

def validate_key(k):
    e = hashlib.md5((SERIAL_NO + SECRET_SALT).encode()).hexdigest().upper()[:16]
    return k.strip() == f"{e[:4]}-{e[4:8]}-{e[8:12]}-{e[12:]}"

def load_license():
    """Load and validate license from both license.dat and machine.lic"""
    global IS_ACTIVATED
    
    # Try machine.lic first (hardware-based license)
    try:
        if os.path.exists(MACHINE_LICENSE_FILE):
            with open(MACHINE_LICENSE_FILE, 'r') as f:
                lic_data = json.load(f)
                stored_hwid = lic_data.get('hwid', '')
                
                # Verify hardware ID matches
                if stored_hwid == SERIAL_NO:
                    # Check expiry if present
                    expiry_str = lic_data.get('expiry', 'Lifetime')
                    if expiry_str == 'Lifetime':
                        IS_ACTIVATED = True
                        print("✅ License activated (Lifetime)")
                        return
                    else:
                        # Check expiry date
                        try:
                            from datetime import datetime
                            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
                            if datetime.now() < expiry_date:
                                IS_ACTIVATED = True
                                print(f"✅ License activated (Valid until {expiry_str})")
                                return
                            else:
                                print(f"⚠️ License expired on {expiry_str}")
                        except:
                            pass
    except Exception as e:
        print(f"⚠️ Error loading machine.lic: {e}")
    
    # Fallback to license.dat (old method)
    try:
        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE, 'r') as f: 
                data = json.load(f)
                if validate_key(data.get('key', '')):
                    IS_ACTIVATED = True
                    print("✅ License activated (license.dat)")
                    return
    except Exception as e:
        print(f"⚠️ Error loading license.dat: {e}")
    
    # No valid license found
    IS_ACTIVATED = False
    print("❌ No valid license found")

load_license()

# ==============================================================================
# --- 🧠 DYNAMIC STRATEGY LOADER ---
# ==============================================================================
class StrategyLoader:
    def __init__(self):
        self.strategies = {}
        self.unlocked_strategies = {}  # Strategies user has unlocked with password
        self.strategy_protection = StrategyProtection() if STRATEGY_PROTECTION_AVAILABLE else None
        self.user_mode = "CLIENT"  # Default mode: CLIENT or ADMIN

    def load_all(self):
        self.strategies = {}
        files = glob.glob(os.path.join(STRATEGIES_DIR, "*.py"))
        print(f"[LOADER] Found {len(files)} files in {STRATEGIES_DIR}")
        
        for filepath in files:
            filename = os.path.basename(filepath)
            if filename.startswith("__"): continue
            
            strat_name = os.path.splitext(filename)[0]
            try:
                spec = importlib.util.spec_from_file_location(strat_name, filepath)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Support both old (calculate function) and new (class with execute method)
                if hasattr(module, 'get_strategy'):
                    self.strategies[strat_name] = module.get_strategy()
                    print(f"[LOADER] Loaded (class): {strat_name}")
                elif hasattr(module, 'calculate'):
                    self.strategies[strat_name] = module
                    print(f"[LOADER] Loaded (function): {strat_name}")
            except Exception as e:
                print(f"[ERROR] Failed to load {strat_name}: {e}")
                
        return list(self.strategies.keys())
    
    def is_strategy_unlocked(self, strategy_name):
        """Check if strategy is unlocked for use"""
        # If protection not available, allow all
        if not STRATEGY_PROTECTION_AVAILABLE or not self.strategy_protection:
            return True
        
        # Check if user already unlocked this strategy
        if strategy_name in self.unlocked_strategies:
            return True
        
        return False
    
    def unlock_strategy(self, strategy_name, password):
        """Unlock a strategy with password"""
        if not STRATEGY_PROTECTION_AVAILABLE or not self.strategy_protection:
            return True, "Protection not enabled"
        
        # Verify password
        is_valid, message = self.strategy_protection.verify_strategy_password(strategy_name, password)
        
        if is_valid:
            self.unlocked_strategies[strategy_name] = True
            return True, "Strategy unlocked successfully"
        else:
            return False, message

    def execute_strategy(self, name, df, tick, positions, symbol=None):
        # Check if strategy is unlocked
        if not self.is_strategy_unlocked(name):
            return "🔒 LOCKED (Enter password to unlock)"
        
        if name in self.strategies:
            try:
                strat = self.strategies[name]
                # New class-based strategy with execute method
                if hasattr(strat, 'execute'):
                    # Pass symbol context for ChartAI strategy
                    if hasattr(strat, '_set_symbol') and symbol:
                        strat._set_symbol(symbol)
                    return strat.execute(df, tick, positions)
                # Old function-based strategy
                elif hasattr(strat, 'calculate'):
                    return strat.calculate(df, tick, positions)
            except Exception as e:
                print(f"Error in strategy {name}: {e}")
        return "WAIT"
    
    def reload_strategies(self):
        """Reload all strategies from disk"""
        return self.load_all()

# ==============================================================================
# --- 💹 TRADING ENGINE ---
# ==============================================================================
# ==============================================================================
# --- 📡 TRADINGVIEW WEBHOOK SERVER ---
# ==============================================================================
webhook_signal_queue = []

# ==============================================================================
# --- 📊 AMIBROKER FILE WATCHER ---
# ==============================================================================
amibroker_signal_queue = []
amibroker_processed_signals = set()  # Track processed signals to avoid duplicates

if FLASK_AVAILABLE:
    flask_app = Flask(__name__)
    
    @flask_app.route('/webhook', methods=['POST'])
    def webhook():
        try:
            data = request.json
            secret = data.get('secret', '')
            
            if secret != WEBHOOK_SECRET:
                return jsonify({'status': 'error', 'message': 'Invalid secret'}), 403
            
            signal = {
                'symbol': data.get('symbol', ''),
                'action': data.get('action', ''),  # BUY, SELL, CLOSE
                'price': data.get('price', 0.0),
                'lot': data.get('lot', 0.01),  # Lot size from TradingView
                'timestamp': datetime.datetime.now().isoformat(),
                # TradingView Indicator Data
                'rsi': data.get('rsi', 0),
                'macd': data.get('macd', 0),
                'ema_fast': data.get('ema_fast', 0),
                'ema_slow': data.get('ema_slow', 0),
                'volume': data.get('volume', 0),
                'indicator_text': data.get('indicator', 'N/A')
            }
            
            webhook_signal_queue.append(signal)
            print(f"[WEBHOOK] Received: {signal}")
            
            return jsonify({'status': 'success', 'message': 'Signal received', 'queued': True}), 200
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 400
    
    def run_flask_server():
        flask_app.run(host='0.0.0.0', port=WEBHOOK_PORT, debug=False, use_reloader=False)
else:
    def run_flask_server():
        print("[ERROR] Flask not installed. Install: pip install flask")

class BotSignals(QObject):
    log = pyqtSignal(str, str)
    stats = pyqtSignal(float, float)
    data_updated = pyqtSignal()
    sl_updated = pyqtSignal(float)
    webhook_status = pyqtSignal(str)

class TradingEngine:
    def __init__(self, signals):
        self.signals = signals
        self.running = False
        self.connected = False
        self.auto_trading = False
        self.auto_signal_scan = False  # Auto-detect signals from all symbols
        
        # Chart Capture Settings
        self.chart_capture_enabled = False
        self.chart_capture_interval = 300  # 5 minutes (in seconds)
        self.last_chart_capture = {}
        self.charts_folder = os.path.join(os.getcwd(), "Chart_Captures")
        os.makedirs(self.charts_folder, exist_ok=True)
        
        # Trading Mode: 'MT5' or 'TRADINGVIEW' or 'AMIBROKER' or 'DUAL'
        self.trading_mode = 'DUAL'  # Default: All systems active (MT5 + TV + AB → MT5)
        self.webhook_server_running = False
        self.ngrok_url = None
        self.ngrok_process = None
        self.amibroker_watcher_running = False
        self.amibroker_watcher_thread = None
        self.amibroker_watcher_running = False
        self.amibroker_watcher_thread = None
        
        self.loader = StrategyLoader()
        self.available_strats = self.loader.load_all()
        self.active_strategy = self.available_strats[0] if self.available_strats else "None"
        
        # Voice Engine Setup
        self.voice_enabled = False
        self.voice_engine = None
        if VOICE_AVAILABLE:
            try:
                self.voice_engine = pyttsx3.init()
                voices = self.voice_engine.getProperty('voices')
                # Set female voice (usually index 1)
                for voice in voices:
                    if 'female' in voice.name.lower() or 'zira' in voice.name.lower():
                        self.voice_engine.setProperty('voice', voice.id)
                        break
                self.voice_engine.setProperty('rate', 160)
                self.voice_engine.setProperty('volume', 0.9)
                self.voice_enabled = True
            except:
                pass
        
        self.symbols = {} 
        self.tv_live_data = {}  # TradingView live indicator data
        self.ab_live_data = {}  # AmiBroker live indicator data
        self.global_tp = 100.0
        self.global_sl = -50.0
        self.use_trailing = False
        self.trail_start = 50.0 
        self.trail_step = 20.0 

    def connect_mt5(self, login, pw, server):
        if not MT5_AVAILABLE: 
            self.signals.log.emit("MT5 Module Missing - Using Simulator", "red")
            self.connected = True; return True
        if not mt5.initialize(): self.signals.log.emit("MT5 Init Failed", "red"); return False
        try:
            if mt5.login(login=int(login), password=pw, server=server):
                self.connected = True
                self.signals.log.emit(f"Connected to {server}", "lime")
                return True
        except: pass
        self.signals.log.emit("Login Failed - Check Details", "red"); return False

    def logout(self):
        self.connected = False; self.running = False; 
        if MT5_AVAILABLE: mt5.shutdown()
        self.signals.log.emit("Logged Out", "orange")

    def start(self):
        if not IS_ACTIVATED: self.signals.log.emit("LICENSE INVALID", "red"); return
        
        # Refresh strategies on start
        self.available_strats = self.loader.load_all()
        if not self.available_strats:
            self.signals.log.emit("No Strategies Found!", "red")
            return

        self.running = True
        threading.Thread(target=self._market_loop, daemon=True).start()
        self.signals.log.emit(f"Started: {self.active_strategy}", "lime")

    def stop(self):
        self.running = False
        self.signals.log.emit("Engine Stopped", "red")

    def _process_webhook_signals(self):
        """Process signals from TradingView webhooks"""
        global webhook_signal_queue
        while webhook_signal_queue:
            signal = webhook_signal_queue.pop(0)
            try:
                symbol = signal['symbol']
                action = signal['action'].upper()
                price = signal.get('price', 0)
                lot = signal.get('lot', 0.01)
                rsi = signal.get('rsi', 0)
                macd = signal.get('macd', 0)
                ema_fast = signal.get('ema_fast', 0)
                ema_slow = signal.get('ema_slow', 0)
                indicator = signal.get('indicator_text', 'N/A')
                
                if symbol not in self.symbols:
                    self.symbols[symbol] = {'lot': lot, 'strategy': 'TradingView'}
                    self.signals.log.emit(f"[TV] Auto-added symbol: {symbol}", "blue")
                
                # Log signal details
                signal_details = f"📊 Indicators: RSI={rsi:.1f}, MACD={macd:.4f}, EMA(9)={ema_fast:.4f}, EMA(21)={ema_slow:.4f}"
                self.signals.log.emit(signal_details, "cyan")
                
                if action == 'BUY':
                    self.signals.log.emit(f"📺 [TV] 🟢 BUY SIGNAL: {symbol} @ {price} | Lot: {lot}", "lime")
                    if self.voice_enabled:
                        self._voice_alert(f"TradingView buy signal on {symbol}")
                    if self.auto_trading:
                        self.execute_trade(symbol, "BUY")
                        self.signals.log.emit(f"✅ Order placed from TradingView signal", "gold")
                        
                elif action == 'SELL':
                    self.signals.log.emit(f"📺 [TV] 🔴 SELL SIGNAL: {symbol} @ {price} | Lot: {lot}", "red")
                    if self.voice_enabled:
                        self._voice_alert(f"TradingView sell signal on {symbol}")
                    if self.auto_trading:
                        self.execute_trade(symbol, "SELL")
                        self.signals.log.emit(f"✅ Order placed from TradingView signal", "gold")
                        
                elif action == 'CLOSE':
                    self.signals.log.emit(f"📺 [TV] 🟡 CLOSE SIGNAL: {symbol}", "orange")
                    self.close_positions_for_symbol(symbol)
                    self.signals.log.emit(f"✅ Position closed from TradingView signal", "gold")
                
                elif action == 'REV':
                    self.signals.log.emit(f"📺 [TV] 🔄 REVERSE SIGNAL: {symbol}", "aqua")
                    if self.auto_trading:
                        self.execute_trade(symbol, "REV")
                        self.signals.log.emit(f"✅ Position reversed from TradingView signal", "gold")
                    
            except Exception as e:
                self.signals.log.emit(f"[TV ERROR] {str(e)}", "red")
                import traceback
                traceback.print_exc()
    
    # ==============================================================================
    # --- 📊 AMIBROKER INTEGRATION ---
    # ==============================================================================
    
    def start_amibroker_watcher(self):
        """Start file watcher for AmiBroker signals"""
        if self.amibroker_watcher_running:
            self.signals.log.emit("AmiBroker watcher already running", "orange")
            return True
        
        try:
            self.amibroker_watcher_running = True
            self.amibroker_watcher_thread = threading.Thread(target=self._watch_amibroker_signals, daemon=True)
            self.amibroker_watcher_thread.start()
            self.signals.log.emit(f"AmiBroker watcher started: {AMIBROKER_SIGNAL_FILE}", "lime")
            return True
        except Exception as e:
            self.signals.log.emit(f"Failed to start AmiBroker watcher: {e}", "red")
            return False
    
    def stop_amibroker_watcher(self):
        """Stop AmiBroker file watcher"""
        self.amibroker_watcher_running = False
        self.signals.log.emit("AmiBroker watcher stopped", "orange")
    
    def _watch_amibroker_signals(self):
        """Monitor AmiBroker signal file for new signals"""
        last_modified = 0
        
        while self.amibroker_watcher_running:
            try:
                if os.path.exists(AMIBROKER_SIGNAL_FILE):
                    current_modified = os.path.getmtime(AMIBROKER_SIGNAL_FILE)
                    
                    if current_modified > last_modified:
                        last_modified = current_modified
                        
                        with open(AMIBROKER_SIGNAL_FILE, 'r') as f:
                            lines = f.readlines()
                        
                        for line in lines:
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            
                            # Signal format: SYMBOL,ACTION,LOT,RSI,MACD,EMA_FAST,EMA_SLOW
                            # Example: EURUSD,BUY,0.01,45.2,0.032,1.0523,1.0520
                            try:
                                parts = line.split(',')
                                if len(parts) < 3:
                                    continue
                                
                                signal_id = hashlib.md5(line.encode()).hexdigest()
                                if signal_id in amibroker_processed_signals:
                                    continue
                                
                                amibroker_processed_signals.add(signal_id)
                                
                                signal = {
                                    'symbol': parts[0].strip().upper(),
                                    'action': parts[1].strip().upper(),
                                    'lot': float(parts[2]) if len(parts) > 2 else 0.01,
                                    'rsi': float(parts[3]) if len(parts) > 3 else 0,
                                    'macd': float(parts[4]) if len(parts) > 4 else 0,
                                    'ema_fast': float(parts[5]) if len(parts) > 5 else 0,
                                    'ema_slow': float(parts[6]) if len(parts) > 6 else 0,
                                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                }
                                
                                amibroker_signal_queue.append(signal)
                                self.signals.log.emit(f"[AB] Signal received: {signal['action']} {signal['symbol']}", "cyan")
                                
                            except Exception as e:
                                self.signals.log.emit(f"[AB] Parse error: {e}", "red")
                
                time.sleep(0.5)  # Check every 500ms
                
            except Exception as e:
                self.signals.log.emit(f"[AB] Watcher error: {e}", "red")
                time.sleep(1)
    
    def _process_amibroker_signals(self):
        """Process signals from AmiBroker and place MT5 orders"""
        global amibroker_signal_queue
        while amibroker_signal_queue:
            signal = amibroker_signal_queue.pop(0)
            try:
                symbol = signal['symbol']
                action = signal['action'].upper()
                lot_size = signal.get('lot', 0.01)
                
                # Auto-add symbol if not exists
                if symbol not in self.symbols:
                    self.symbols[symbol] = {
                        'lot': lot_size,
                        'bid': 0,
                        'ask': 0,
                        'status': '-',
                        'pnl': 0.0,
                        'd_pct': 0.0,
                        'spread': 0,
                        'mode': '',
                        'orders': 0
                    }
                    self.signals.log.emit(f"[AB] Auto-added symbol: {symbol}", "cyan")
                else:
                    # Update lot size from signal
                    self.symbols[symbol]['lot'] = lot_size
                
                # Store AmiBroker indicator data
                self.ab_live_data[symbol] = {
                    'rsi': signal.get('rsi', 0),
                    'macd': signal.get('macd', 0),
                    'ema_fast': signal.get('ema_fast', 0),
                    'ema_slow': signal.get('ema_slow', 0),
                    'last_update': signal.get('timestamp', '')
                }
                
                if action == 'BUY':
                    ind_info = f"RSI:{signal.get('rsi',0):.1f} MACD:{signal.get('macd',0):.2f}"
                    self.signals.log.emit(f"[AB] BUY {symbol} | Lot:{lot_size} | {ind_info}", "lime")
                    if self.voice_enabled and self.voice_engine:
                        threading.Thread(target=lambda: self.voice_engine.say(f"AmiBroker buy signal on {symbol}") or self.voice_engine.runAndWait(), daemon=True).start()
                    
                    # Execute order
                    self._execute_amibroker_order(symbol, 'BUY', lot_size)
                    
                elif action == 'SELL':
                    ind_info = f"RSI:{signal.get('rsi',0):.1f} MACD:{signal.get('macd',0):.2f}"
                    self.signals.log.emit(f"[AB] SELL {symbol} | Lot:{lot_size} | {ind_info}", "yellow")
                    if self.voice_enabled and self.voice_engine:
                        threading.Thread(target=lambda: self.voice_engine.say(f"AmiBroker sell signal on {symbol}") or self.voice_engine.runAndWait(), daemon=True).start()
                    
                    # Execute order
                    self._execute_amibroker_order(symbol, 'SELL', lot_size)
                        
                elif action == 'CLOSE':
                    self.signals.log.emit(f"[AB] CLOSE {symbol}", "orange")
                    self.close_positions_for_symbol(symbol)
                    
            except Exception as e:
                self.signals.log.emit(f"[AB ERROR] {e}", "red")
    
    def _execute_amibroker_order(self, symbol, action, lot_size):
        """Execute AmiBroker order directly on MT5"""
        if not MT5_AVAILABLE or not self.connected:
            self.signals.log.emit(f"[AB] MT5 not connected", "red")
            return
        
        try:
            # Get tick data
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                self.signals.log.emit(f"[AB] No tick data for {symbol}", "red")
                return
            
            # Determine order type and price
            order_type = mt5.ORDER_TYPE_BUY if action == 'BUY' else mt5.ORDER_TYPE_SELL
            price = tick.ask if action == 'BUY' else tick.bid
            
            # Create order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot_size),
                "type": order_type,
                "price": price,
                "magic": 999,  # AmiBroker orders use magic number 999
                "comment": "AmiBroker",
                "type_filling": self.get_filling_mode(symbol),
            }
            
            # Send order
            result = mt5.order_send(request)
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                self.signals.log.emit(
                    f"✅ [AB] {action} {symbol} | Lot: {lot_size} | Price: {price} | Ticket: {result.order}",
                    "lime"
                )
            else:
                error_msg = result.comment if result else "Unknown error"
                self.signals.log.emit(f"[AB] Order failed: {error_msg}", "red")
                
        except Exception as e:
            self.signals.log.emit(f"[AB] Execute error: {e}", "red")
    
    def start_webhook_server(self):
        """Start Flask webhook server in background"""
        if not FLASK_AVAILABLE:
            self.signals.log.emit("Flask not installed!", "red")
            return False
        
        if self.webhook_server_running:
            self.signals.log.emit("Webhook server already running", "orange")
            return True
        
        try:
            threading.Thread(target=run_flask_server, daemon=True).start()
            self.webhook_server_running = True
            self.signals.log.emit(f"Webhook server started on port {WEBHOOK_PORT}", "lime")
            self.signals.webhook_status.emit("ACTIVE")
            return True
        except Exception as e:
            self.signals.log.emit(f"Failed to start webhook: {e}", "red")
            return False
    
    def setup_ngrok(self):
        """Setup Ngrok tunnel for remote webhook access"""
        try:
            import subprocess
            import json
            
            # Check if ngrok is installed
            try:
                result = subprocess.run(["ngrok", "--version"], capture_output=True, text=True, timeout=5)
                self.signals.log.emit("✅ Ngrok already installed", "lime")
            except:
                self.signals.log.emit("📥 Installing Ngrok... (one-time setup)", "blue")
                os.system("pip install pyngrok")
            
            from pyngrok import ngrok
            
            # Start ngrok tunnel
            self.signals.log.emit("🌐 Starting Ngrok tunnel...", "cyan")
            tunnel = ngrok.connect(WEBHOOK_PORT, "http")
            self.ngrok_tunnel = tunnel
            self.ngrok_url = tunnel.public_url
            
            self.signals.log.emit(f"✅ Ngrok tunnel started!", "lime")
            self.signals.log.emit(f"🌐 Public URL: {self.ngrok_url}", "gold")
            
            return True
        except Exception as e:
            self.signals.log.emit(f"❌ Ngrok setup failed: {str(e)}", "red")
            return False
    
    def stop_ngrok(self):
        """Stop Ngrok tunnel"""
        try:
            from pyngrok import ngrok
            ngrok.kill()
            self.ngrok_url = None
            self.signals.log.emit("🛑 Ngrok tunnel stopped", "orange")
            return True
        except Exception as e:
            self.signals.log.emit(f"❌ Failed to stop Ngrok: {str(e)}", "red")
            return False
    
    def get_ngrok_url(self):
        """Get current Ngrok public URL"""
        if hasattr(self, 'ngrok_url') and self.ngrok_url:
            return self.ngrok_url
        
        try:
            from pyngrok import ngrok
            tunnels = ngrok.get_tunnels()
            if tunnels:
                return tunnels[0].public_url
        except:
            pass
        
        return None

    def get_filling_mode(self, symbol):
        if not MT5_AVAILABLE: return mt5.ORDER_FILLING_RETURN if 'mt5' in globals() else 0
        info = mt5.symbol_info(symbol)
        if info is None: return mt5.ORDER_FILLING_RETURN
        modes = info.filling_mode
        if modes & 1: return mt5.ORDER_FILLING_FOK
        if modes & 2: return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def get_filling_str(self, symbol):
        mode = self.get_filling_mode(symbol)
        if mode == mt5.ORDER_FILLING_FOK: return "FOK"
        if mode == mt5.ORDER_FILLING_IOC: return "IOC"
        return "RET"

    def execute_trade(self, symbol, action):
        if MT5_AVAILABLE and self.connected:
            info = mt5.symbol_info(symbol)
            if info is None:
                if not mt5.symbol_select(symbol, True): return
                info = mt5.symbol_info(symbol)
            point = info.point
        else:
            point = 0.00001

        if action == "X": 
            self.signals.log.emit(f"CLOSE: {symbol}", "orange")
            if MT5_AVAILABLE and self.connected:
                positions = mt5.positions_get(symbol=symbol)
                if positions:
                    for pos in positions:
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL, 
                            "symbol": symbol, 
                            "volume": pos.volume, 
                            "type": mt5.ORDER_TYPE_SELL if pos.type==mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY, 
                            "position": pos.ticket, 
                            "magic": 101,
                            "type_filling": self.get_filling_mode(symbol) 
                        }
                        mt5.order_send(req)
        
        elif action == "REV":
            self.signals.log.emit(f"REVERSE: {symbol}", "cyan")
            if MT5_AVAILABLE and self.connected:
                positions = mt5.positions_get(symbol=symbol)
                if positions:
                    for pos in positions:
                        curr_type = pos.type 
                        self.execute_trade(symbol, "X"); time.sleep(1) 
                        new_act = "SELL" if curr_type == mt5.ORDER_TYPE_BUY else "BUY"
                        self.execute_trade(symbol, new_act)

        else: 
            if symbol not in self.symbols: return
            lot = float(self.symbols[symbol]['lot'])
            strategy_name = self.symbols[symbol].get('strategy', self.active_strategy)
            if MT5_AVAILABLE and self.connected:
                tick = mt5.symbol_info_tick(symbol)
                if tick is None: return
                order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
                price = tick.ask if action == "BUY" else tick.bid
                req = { 
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lot, "type": order_type, 
                    "price": price, "magic": 101, "comment": strategy_name,  # Strategy name in comment
                    "type_filling": self.get_filling_mode(symbol),
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE: 
                    self.signals.log.emit(f"✅ {action} {symbol} | Strategy: {strategy_name} | Lot: {lot} | Ticket: {res.order}", "lime")
                    # Voice alert for manual orders
                    if action in ["BUY", "SELL", "REV", "X"]:
                        self._voice_alert(f"Manual {action} order executed on {symbol}")
                else: 
                    self.signals.log.emit(f"Order Failed: {res.comment if res else 'Err'}", "red")
    
    def execute_partial_close(self, symbol, percentage=50):
        """Close partial position (for profit booking)"""
        if not MT5_AVAILABLE or not self.connected:
            return
        
        try:
            positions = mt5.positions_get(symbol=symbol)
            if not positions:
                return
            
            for pos in positions:
                if pos.magic != 101:  # Only bot's positions
                    continue
                
                # Calculate partial volume
                original_volume = pos.volume
                close_volume = round(original_volume * (percentage / 100), 2)
                
                if close_volume < 0.01:  # Minimum lot size
                    close_volume = 0.01
                
                # Close partial position
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue
                
                price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": close_volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": price,
                    "magic": 101,
                    "comment": f"Partial Close {percentage}%",
                    "type_filling": self.get_filling_mode(symbol),
                }
                
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.signals.log.emit(
                        f"💰 PARTIAL CLOSE: {symbol} | {percentage}% | Vol: {close_volume} | Profit: ${pos.profit:.2f}",
                        "yellow"
                    )
                else:
                    error = result.comment if result else "Unknown error"
                    self.signals.log.emit(f"Partial close failed: {error}", "red")
                    
        except Exception as e:
            self.signals.log.emit(f"Partial close error: {e}", "red")

    def close_all(self):
        """Enhanced close all positions - compatible with all MT5 brokers"""
        self.signals.log.emit("🚨 CLOSING ALL POSITIONS (ALL BROKERS)...", "red")
        if MT5_AVAILABLE and self.connected:
            positions = mt5.positions_get()
            if positions:
                closed_count = 0
                for pos in positions:
                    try:
                        # Try multiple filling modes for broker compatibility
                        tick = mt5.symbol_info_tick(pos.symbol)
                        if not tick:
                            continue
                        
                        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                        
                        # Try FOK first (most brokers)
                        request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": pos.symbol,
                            "volume": pos.volume,
                            "type": close_type,
                            "position": pos.ticket,
                            "price": price,
                            "magic": pos.magic,
                            "comment": "Close All",
                            "type_filling": mt5.ORDER_FILLING_FOK,
                        }
                        
                        result = mt5.order_send(request)
                        
                        # If FOK fails, try IOC
                        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                            request["type_filling"] = mt5.ORDER_FILLING_IOC
                            result = mt5.order_send(request)
                        
                        # If IOC fails, try RETURN
                        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                            request["type_filling"] = mt5.ORDER_FILLING_RETURN
                            result = mt5.order_send(request)
                        
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            closed_count += 1
                            self.signals.log.emit(f"✅ Closed: {pos.symbol} | Ticket: {pos.ticket}", "lime")
                        else:
                            error = result.comment if result else "Unknown"
                            self.signals.log.emit(f"⚠️ Failed to close {pos.symbol}: {error}", "orange")
                    
                    except Exception as e:
                        self.signals.log.emit(f"❌ Error closing {pos.symbol}: {e}", "red")
                
                self.signals.log.emit(f"📊 Total Closed: {closed_count}/{len(positions)} positions", "cyan")
            else:
                self.signals.log.emit("ℹ️ No open positions to close", "gray")
    
    def scan_all_symbols_for_signals(self):
        """Auto-scan all loaded symbols for strategy signals (per-symbol strategy)"""
        if not self.auto_signal_scan or not self.connected:
            return
        
        if not MT5_AVAILABLE:
            return
        
        for symbol in list(self.symbols.keys()):
            try:
                # Check if strategy is active for this symbol
                if not self.symbols[symbol].get('strategy_active', True):
                    continue  # Skip if strategy disabled for this symbol
                
                # Get symbol-specific strategy (or use global active strategy)
                symbol_strategy = self.symbols[symbol].get('strategy', self.active_strategy)
                
                # Get OHLC data
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 100)
                if rates is None or len(rates) < 50:
                    continue
                
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                
                # Get current tick
                tick = mt5.symbol_info_tick(symbol)
                if tick is None:
                    continue
                
                # Get current positions
                positions = mt5.positions_get(symbol=symbol)
                pos_list = []
                if positions:
                    for p in positions:
                        pos_list.append({
                            'type': 'BUY' if p.type == mt5.ORDER_TYPE_BUY else 'SELL',
                            'volume': p.volume,
                            'profit': p.profit
                        })
                
                # Execute symbol-specific strategy
                status = self.loader.execute_strategy(symbol_strategy, df, tick, pos_list)
                
                if status and status != "WAIT":
                    # Signal detected!
                    is_buy = "BUY" in status.upper()
                    is_sell = "SELL" in status.upper()
                    
                    # Check if already have position
                    has_buy = any(p['type'] == 'BUY' for p in pos_list)
                    has_sell = any(p['type'] == 'SELL' for p in pos_list)
                    
                    if is_buy and not has_buy:
                        self.signals.log.emit(f"🔍 AUTO: {symbol} | {symbol_strategy} | {status}", "lime")
                        if has_sell:
                            self.execute_trade(symbol, "X")
                            time.sleep(0.5)
                        self.execute_trade(symbol, "BUY")
                        self._voice_alert(f"Auto buy signal: {symbol}")
                    
                    elif is_sell and not has_sell:
                        self.signals.log.emit(f"🔍 AUTO: {symbol} | {symbol_strategy} | {status}", "yellow")
                        if has_buy:
                            self.execute_trade(symbol, "X")
                            time.sleep(0.5)
                        self.execute_trade(symbol, "SELL")
                        self._voice_alert(f"Auto sell signal: {symbol}")
                        
            except Exception as e:
                # Silent fail - don't spam logs
                pass
    
    def analyze_market_conditions(self, symbol):
        """Analyze market conditions for a symbol"""
        if not MT5_AVAILABLE or not self.connected:
            return None
        
        try:
            # Get hourly data for trend analysis
            rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 50)
            if rates_h1 is None or len(rates_h1) < 20:
                return None
            
            df_h1 = pd.DataFrame(rates_h1)
            
            # Calculate volatility (ATR)
            high_low = df_h1['high'] - df_h1['low']
            volatility = high_low.rolling(14).mean().iloc[-1]
            avg_volatility = high_low.mean()
            volatility_ratio = volatility / avg_volatility if avg_volatility > 0 else 1
            
            # Calculate trend strength (ADX-like)
            close_changes = df_h1['close'].diff()
            up_moves = close_changes.where(close_changes > 0, 0).rolling(14).sum()
            down_moves = abs(close_changes.where(close_changes < 0, 0)).rolling(14).sum()
            trend_strength = abs(up_moves.iloc[-1] - down_moves.iloc[-1]) / (up_moves.iloc[-1] + down_moves.iloc[-1] + 0.0001)
            
            # Calculate momentum
            momentum = (df_h1['close'].iloc[-1] - df_h1['close'].iloc[-10]) / df_h1['close'].iloc[-10] * 100
            
            # Volume analysis
            volume_ratio = df_h1['tick_volume'].iloc[-5:].mean() / df_h1['tick_volume'].mean()
            
            # Get current time (UTC)
            current_hour = datetime.datetime.utcnow().hour
            
            # Market session
            if 0 <= current_hour < 8:
                session = 'ASIA'
            elif 8 <= current_hour < 16:
                session = 'EUROPE'
            else:
                session = 'US'
            
            return {
                'volatility_ratio': volatility_ratio,
                'trend_strength': trend_strength,
                'momentum': momentum,
                'volume_ratio': volume_ratio,
                'session': session,
                'current_hour': current_hour
            }
            
        except Exception as e:
            return None
    
    def match_best_strategy(self, symbol):
        """AI-powered strategy matching based on market conditions"""
        conditions = self.analyze_market_conditions(symbol)
        if not conditions:
            return self.active_strategy
        
        # Strategy scoring system
        scores = {strategy: 0 for strategy in self.available_strats}
        
        vol_ratio = conditions['volatility_ratio']
        trend = conditions['trend_strength']
        momentum = conditions['momentum']
        volume = conditions['volume_ratio']
        session = conditions['session']
        
        # Scoring logic for each strategy
        for strategy in self.available_strats:
            strategy_lower = strategy.lower()
            
            # TrendRider: Best for strong trends
            if 'trend' in strategy_lower or 'rider' in strategy_lower:
                if trend > 0.6:
                    scores[strategy] += 30
                if abs(momentum) > 0.5:
                    scores[strategy] += 20
                if vol_ratio < 1.5:  # Moderate volatility
                    scores[strategy] += 15
            
            # SpikeHunter: Best for high volatility
            if 'spike' in strategy_lower or 'hunt' in strategy_lower:
                if vol_ratio > 1.5:
                    scores[strategy] += 30
                if volume > 1.2:
                    scores[strategy] += 20
                if session == 'US':  # US session more volatile
                    scores[strategy] += 15
            
            # Leopard (Breakout): Best for ranging to breakout
            if 'leopard' in strategy_lower or 'break' in strategy_lower:
                if vol_ratio > 1.3:
                    scores[strategy] += 25
                if trend < 0.4:  # Weak trend (ranging)
                    scores[strategy] += 25
                if volume > 1.3:
                    scores[strategy] += 15
            
            # RSI strategies: Best for ranging markets
            if 'rsi' in strategy_lower:
                if trend < 0.5:
                    scores[strategy] += 30
                if vol_ratio < 1.2:
                    scores[strategy] += 20
                if session == 'ASIA':  # Asia often ranges
                    scores[strategy] += 10
            
            # Moving Average Cross: Best for clear trends
            if 'moving' in strategy_lower or 'ma' in strategy_lower or 'ema' in strategy_lower:
                if trend > 0.5:
                    scores[strategy] += 25
                if abs(momentum) > 0.3:
                    scores[strategy] += 20
                if vol_ratio > 0.8 and vol_ratio < 1.5:
                    scores[strategy] += 15
            
            # Bollinger Bands: Best for mean reversion in ranging markets
            if 'bollinger' in strategy_lower or 'band' in strategy_lower:
                if trend < 0.4:
                    scores[strategy] += 30
                if vol_ratio > 1.2:
                    scores[strategy] += 20
                if session in ['EUROPE', 'US']:
                    scores[strategy] += 10
        
        # Find best strategy
        best_strategy = max(scores, key=scores.get)
        best_score = scores[best_strategy]
        
        # Log the match
        match_info = f"Vol:{vol_ratio:.2f} Trend:{trend:.2f} Mom:{momentum:.2f}% Ses:{session}"
        self.signals.log.emit(f"🧠 AI: {symbol} → {best_strategy} (Score:{best_score}) | {match_info}", "cyan")
        
        return best_strategy
    
    def auto_match_all_strategies(self):
        """Auto-match best strategy for all loaded symbols"""
        if not MT5_AVAILABLE or not self.connected:
            self.signals.log.emit("⚠️ MT5 not connected!", "red")
            return
        
        self.signals.log.emit("🧠 AI STRATEGY MATCHER: Analyzing all symbols...", "yellow")
        matched_count = 0
        
        for symbol in list(self.symbols.keys()):
            try:
                best_strategy = self.match_best_strategy(symbol)
                self.symbols[symbol]['strategy'] = best_strategy
                matched_count += 1
                time.sleep(0.1)  # Small delay between analyses
            except Exception as e:
                self.signals.log.emit(f"⚠️ {symbol}: Analysis failed", "orange")
        
        self.signals.log.emit(f"✅ AI MATCHER: {matched_count} symbols matched to optimal strategies!", "lime")
        self.signals.data_updated.emit()  # Refresh table
    
    def capture_symbol_chart(self, symbol):
        """Capture chart for a single symbol with market direction"""
        if not CHART_CAPTURE_AVAILABLE:
            self.signals.log.emit("📸 Chart capture module not available", "red")
            return None
        
        try:
            filepath = capture_chart_with_analysis(symbol, self.charts_folder, mt5.TIMEFRAME_M15)
            if filepath:
                analysis = detect_market_direction(symbol, mt5.TIMEFRAME_M15)
                direction_emoji = "🟢" if "BULLISH" in analysis['direction'] else ("🔴" if "BEARISH" in analysis['direction'] else "⚪")
                self.signals.log.emit(
                    f"📸 {direction_emoji} {symbol}: {analysis['direction']} | Chart saved!",
                    "lime" if "BULLISH" in analysis['direction'] else ("red" if "BEARISH" in analysis['direction'] else "yellow")
                )
                return filepath
        except Exception as e:
            self.signals.log.emit(f"📸 {symbol} capture failed: {e}", "red")
        return None
    
    def auto_capture_all_charts(self):
        """Auto capture charts for all loaded symbols"""
        if not self.chart_capture_enabled or not CHART_CAPTURE_AVAILABLE:
            return
        
        current_time = time.time()
        
        for symbol in list(self.symbols.keys()):
            # Check if enough time has passed since last capture
            last_time = self.last_chart_capture.get(symbol, 0)
            if current_time - last_time >= self.chart_capture_interval:
                self.capture_symbol_chart(symbol)
                self.last_chart_capture[symbol] = current_time
                time.sleep(0.5)  # Small delay between captures
    
    def _process_webhook_signals(self):
        """Process signals from TradingView webhooks and place MT5 orders"""
        global webhook_signal_queue
        while webhook_signal_queue:
            signal = webhook_signal_queue.pop(0)
            try:
                symbol = signal['symbol']
                action = signal['action'].upper()
                lot_size = signal.get('lot', 0.01)
                
                # Auto-add symbol if not exists
                if symbol not in self.symbols:
                    self.symbols[symbol] = {
                        'lot': lot_size,
                        'bid': 0,
                        'ask': 0,
                        'status': '-',
                        'pnl': 0.0,
                        'd_pct': 0.0,
                        'spread': 0,
                        'mode': '',
                        'orders': 0
                    }
                    self.signals.log.emit(f"[TV] Auto-added symbol: {symbol}", "cyan")
                else:
                    # Update lot size from signal
                    self.symbols[symbol]['lot'] = lot_size
                
                # Store TradingView indicator data
                self.tv_live_data[symbol] = {
                    'price': signal.get('price', 0),
                    'rsi': signal.get('rsi', 0),
                    'macd': signal.get('macd', 0),
                    'ema_fast': signal.get('ema_fast', 0),
                    'ema_slow': signal.get('ema_slow', 0),
                    'volume': signal.get('volume', 0),
                    'indicator': signal.get('indicator_text', 'N/A'),
                    'last_update': signal.get('timestamp', '')
                }
                
                if action == 'BUY':
                    ind_info = f"RSI:{signal.get('rsi',0):.1f} MACD:{signal.get('macd',0):.2f}"
                    self.signals.log.emit(f"[TV] BUY {symbol} | Lot:{lot_size} | {ind_info}", "lime")
                    if self.voice_enabled and self.voice_engine:
                        threading.Thread(target=lambda: self.voice_engine.say(f"TradingView buy signal on {symbol}") or self.voice_engine.runAndWait(), daemon=True).start()
                    
                    # Always execute trade from TradingView (ignore auto_trading flag for TV signals)
                    self._execute_tv_order(symbol, "BUY", lot_size)
                        
                elif action == 'SELL':
                    ind_info = f"RSI:{signal.get('rsi',0):.1f} MACD:{signal.get('macd',0):.2f}"
                    self.signals.log.emit(f"[TV] SELL {symbol} | Lot:{lot_size} | {ind_info}", "red")
                    if self.voice_enabled and self.voice_engine:
                        threading.Thread(target=lambda: self.voice_engine.say(f"TradingView sell signal on {symbol}") or self.voice_engine.runAndWait(), daemon=True).start()
                    
                    self._execute_tv_order(symbol, "SELL", lot_size)
                        
                elif action == 'CLOSE':
                    self.signals.log.emit(f"[TV] CLOSE {symbol}", "orange")
                    if MT5_AVAILABLE and self.connected:
                        positions = mt5.positions_get(symbol=symbol)
                        if positions:
                            for pos in positions:
                                self.execute_trade(symbol, "X")
                            self.signals.log.emit(f"[TV] Closed {len(positions)} position(s) for {symbol}", "orange")
                        else:
                            self.signals.log.emit(f"[TV] No open positions for {symbol}", "cyan")
                    
            except Exception as e:
                self.signals.log.emit(f"[TV ERROR] {e}", "red")
                print(f"[WEBHOOK ERROR] {e}")
    
    def _execute_tv_order(self, symbol, action, lot_size):
        """Execute TradingView order directly on MT5"""
        if not MT5_AVAILABLE or not self.connected:
            self.signals.log.emit(f"[TV] MT5 not connected! Order skipped: {action} {symbol}", "red")
            return
        
        try:
            # Select symbol
            if not mt5.symbol_select(symbol, True):
                self.signals.log.emit(f"[TV] Symbol {symbol} not available in MT5", "red")
                return
            
            # Get tick data
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                self.signals.log.emit(f"[TV] No tick data for {symbol}", "red")
                return
            
            # Determine order type and price
            if action == "BUY":
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:  # SELL
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            
            # Create order request
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot_size),
                "type": order_type,
                "price": price,
                "magic": 888,  # Magic number for TradingView orders
                "comment": "TradingView",
                "type_filling": self.get_filling_mode(symbol),
            }
            
            # Send order
            result = mt5.order_send(request)
            
            if result is None:
                self.signals.log.emit(f"[TV] Order send failed: No result", "red")
                return
            
            # Check result
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.signals.log.emit(
                    f"✅ [TV] {action} {symbol} | Lot: {lot_size} | Price: {price:.5f} | Ticket: {result.order}",
                    "lime"
                )
                if self.voice_enabled and self.voice_engine:
                    threading.Thread(
                        target=lambda: self.voice_engine.say(f"Order executed: {action} {symbol}") or self.voice_engine.runAndWait(),
                        daemon=True
                    ).start()
            else:
                error_msg = f"[TV] Order failed: {result.comment} (Code: {result.retcode})"
                self.signals.log.emit(error_msg, "red")
                print(f"[MT5 ERROR] {error_msg}")
                print(f"[MT5 RESULT] {result}")
                
        except Exception as e:
            self.signals.log.emit(f"[TV] Order execution error: {e}", "red")
            print(f"[TV ORDER ERROR] {e}")
    
    def start_webhook_server(self):
        """Start Flask webhook server in background"""
        if not FLASK_AVAILABLE:
            self.signals.log.emit("Flask not installed!", "red")
            return False
        
        if self.webhook_server_running:
            self.signals.log.emit("Webhook server already running", "orange")
            return True
        
        try:
            threading.Thread(target=run_flask_server, daemon=True).start()
            self.webhook_server_running = True
            self.signals.log.emit(f"Webhook server started on port {WEBHOOK_PORT}", "lime")
            self.signals.webhook_status.emit("ACTIVE")
            return True
        except Exception as e:
            self.signals.log.emit(f"Failed to start webhook: {e}", "red")
            return False

    def _market_loop(self):
        while self.running:
            # Process TradingView webhook signals (TV mode or DUAL mode)
            if hasattr(self, 'trading_mode') and self.trading_mode in ['TRADINGVIEW', 'DUAL']:
                self._process_webhook_signals()
            
            # Process AmiBroker file signals (AB mode or DUAL mode)
            if hasattr(self, 'trading_mode') and self.trading_mode in ['AMIBROKER', 'DUAL']:
                self._process_amibroker_signals()
            
            # Auto-scan all symbols for signals (if enabled)
            if self.auto_signal_scan and self.trading_mode in ['MT5', 'DUAL']:
                self.scan_all_symbols_for_signals()
            
            pnl, eq = 0.0, 10000.0
            if MT5_AVAILABLE and self.connected:
                a = mt5.account_info()
                if a: pnl, eq = a.profit, a.equity
            else: 
                pnl = random.uniform(-40, 120)
            self.signals.stats.emit(pnl, eq)

            if self.use_trailing and pnl > self.trail_start:
                new_sl = pnl - self.trail_step
                if new_sl > self.global_sl:
                    self.global_sl = new_sl; self.signals.sl_updated.emit(new_sl)
                    self.signals.log.emit(f"Trail SL: ${new_sl:.2f}", "cyan")

            if pnl >= self.global_tp: 
                self.signals.log.emit("Global TP Hit!", "lime"); self.close_all(); self.running = False
            elif pnl <= self.global_sl: 
                self.signals.log.emit("Global SL Hit!", "red"); self.close_all(); self.running = False

            for s in list(self.symbols.keys()):
                bid, ask, status, ind_pnl = 0, 0, "WAIT", 0.0
                day_change, spread, orders_count = 0.0, 0, 0
                
                if MT5_AVAILABLE and self.connected:
                    if not mt5.symbol_select(s, True): pass 
                    positions = mt5.positions_get(symbol=s)
                    pos_list = []
                    if positions:
                        orders_count = len(positions)
                        for pos in positions: 
                            ind_pnl += pos.profit
                            pos_list.append({'type': pos.type, 'volume': pos.volume})
                    
                    t = mt5.symbol_info_tick(s); info = mt5.symbol_info(s)
                    if t and info:
                        bid, ask = t.bid, t.ask; spread = info.spread
                        rates_d1 = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 1)
                        if rates_d1 is not None and len(rates_d1) > 0:
                            if rates_d1[0]['open'] > 0: day_change = ((bid - rates_d1[0]['open']) / rates_d1[0]['open']) * 100
                    
                    # FETCH DATA & RUN STRATEGY
                    rates = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M5, 0, 50)
                    df = pd.DataFrame(rates) if rates is not None and len(rates) > 0 else pd.DataFrame()
                    if not df.empty: df['time'] = pd.to_datetime(df['time'], unit='s')
                    
                    # Check if strategy is active for this symbol
                    if not self.symbols[s].get('strategy_active', True):
                        status = "WAIT (Strategy Disabled)"
                    else:
                        # Use symbol-specific strategy
                        symbol_strategy = self.symbols[s].get('strategy', self.active_strategy)
                        status = self.loader.execute_strategy(symbol_strategy, df, t, pos_list, symbol=s)
                    
                    if self.auto_trading and status != "WAIT":
                        is_buy = any(p['type'] == mt5.ORDER_TYPE_BUY for p in pos_list)
                        is_sell = any(p['type'] == mt5.ORDER_TYPE_SELL for p in pos_list)
                        
                        # Handle hedge signal
                        if "HEDGE" in status:
                            # Open opposite position for hedging
                            if is_buy:
                                self.execute_trade(s, "SELL")  # Hedge with opposite
                            elif is_sell:
                                self.execute_trade(s, "BUY")   # Hedge with opposite
                        # Handle partial close signal
                        elif "PARTIAL CLOSE" in status:
                            self.execute_partial_close(s, percentage=50)
                        # Handle full close signal
                        elif "CLOSE ALL" in status:
                            self.execute_trade(s, "X")
                        # Handle new entries
                        elif "BUY" in status and not is_buy:
                            if is_sell: self.execute_trade(s, "X"); time.sleep(1)
                            self.execute_trade(s, "BUY")
                            self._voice_alert(f"Buy signal for {s}")
                        elif "SELL" in status and not is_sell:
                            if is_buy: self.execute_trade(s, "X"); time.sleep(1)
                            self.execute_trade(s, "SELL")
                            self._voice_alert(f"Sell signal for {s}")
                else:
                    bid = 1.0500 + random.uniform(-0.0005, 0.0005); ask = bid + 0.0002
                    status = random.choice(["BUY SIGNAL", "SELL SIGNAL", "WAIT"])
                
                # Add strategy name to status display
                if MT5_AVAILABLE and self.connected and status != "WAIT":
                    display_status = f"[{symbol_strategy}] {status}"
                else:
                    display_status = status
                
                self.symbols[s].update({'bid':bid, 'ask':ask, 'status':display_status, 'pnl':ind_pnl, 
                                      'd_pct':day_change, 'spread':spread, 'orders':orders_count, 
                                      'mode':self.get_filling_str(s)})
            
            # Auto chart capture
            if self.chart_capture_enabled:
                self.auto_capture_all_charts()
            
            self.signals.data_updated.emit()
            time.sleep(1)
    
    def _voice_alert(self, message):
        """Internal voice alert caller - fixed threading issue"""
        if self.voice_enabled and self.voice_engine:
            try:
                # Use queue to prevent multiple runAndWait calls
                def speak():
                    try:
                        self.voice_engine.say(message)
                        self.voice_engine.runAndWait()
                    except RuntimeError:
                        # If already running, skip
                        pass
                    except Exception as e:
                        print(f"Voice error: {e}")
                
                # Start in separate thread with error handling
                threading.Thread(target=speak, daemon=True).start()
            except Exception as e:
                print(f"Voice thread error: {e}")

# ==============================================================================
# --- 🖥️ DIALOGS ---
# ==============================================================================
class BulkLoadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BULK SYMBOL LOADER")
        self.resize(300, 300)
        self.setStyleSheet(STYLESHEET)
        l = QVBoxLayout(self)
        l.addWidget(QLabel("Paste List (e.g., EURUSD, BTCUSD):"))
        self.txt = QTextEdit(); self.txt.setPlaceholderText("EURUSD\nGBPUSD")
        l.addWidget(self.txt)
        btn = QPushButton("LOAD NOW"); btn.setStyleSheet("background:#00c853; color:black;")
        btn.clicked.connect(self.accept); l.addWidget(btn)
    def get_list(self): return [x.strip().upper() for x in self.txt.toPlainText().replace(',', '\n').split('\n') if x.strip()]

class ActivationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LICENSE ACTIVATION")
        self.resize(400, 350)
        self.setStyleSheet(STYLESHEET)
        l = QVBoxLayout(self)
        lbl = QLabel("e2eNISHAANKAN BOT QT")
        lbl.setStyleSheet("color:#00bcd4;font-size:18px;border-bottom:2px solid #333; padding-bottom: 10px;")
        lbl.setAlignment(Qt.AlignCenter); l.addWidget(lbl)
        self.status_box = QLabel(); self.status_box.setAlignment(Qt.AlignCenter); self.update_status_display(); l.addWidget(self.status_box)
        g1 = QGroupBox("Step 1: Copy Hardware ID"); v1 = QVBoxLayout(g1)
        t = QLineEdit(SERIAL_NO); t.setReadOnly(True); t.setStyleSheet("border:1px solid #00bcd4;background:#000;color:#00e676;font-size:13px;")
        v1.addWidget(t); l.addWidget(g1)
        g2 = QGroupBox("Step 2: Enter License Key"); v2 = QVBoxLayout(g2)
        self.k = QLineEdit(); self.k.setPlaceholderText("XXXX-XXXX-XXXX-XXXX"); v2.addWidget(self.k); l.addWidget(g2)
        b = QPushButton("ACTIVATE NOW"); b.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:8px;")
        b.clicked.connect(self.ok); l.addWidget(b)

    def update_status_display(self):
        """Update license status display - checks both machine.lic and license.dat"""
        global IS_ACTIVATED
        
        # Check machine.lic first (hardware-based)
        try:
            if os.path.exists(MACHINE_LICENSE_FILE):
                with open(MACHINE_LICENSE_FILE, 'r') as f:
                    lic_data = json.load(f)
                    stored_hwid = lic_data.get('hwid', '')
                    
                    if stored_hwid == SERIAL_NO:
                        expiry_str = lic_data.get('expiry', 'Lifetime')
                        lic_type = lic_data.get('type', 'Commercial')
                        
                        if expiry_str == 'Lifetime':
                            IS_ACTIVATED = True
                            self.status_box.setText(f"✅ STATUS: ACTIVE\n📅 License Type: {lic_type}\n🔒 Valid: Lifetime")
                            self.status_box.setStyleSheet("color: #00e676; font-size: 14px; font-weight: bold; border: 1px dashed #00e676; padding: 10px; margin: 5px;")
                            return
                        else:
                            from datetime import datetime
                            try:
                                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
                                if datetime.now() < expiry_date:
                                    IS_ACTIVATED = True
                                    days_left = (expiry_date - datetime.now()).days
                                    self.status_box.setText(f"✅ STATUS: ACTIVE\n📅 Valid Until: {expiry_str}\n⏰ Days Remaining: {days_left}")
                                    self.status_box.setStyleSheet("color: #00e676; font-size: 14px; font-weight: bold; border: 1px dashed #00e676; padding: 10px; margin: 5px;")
                                    return
                                else:
                                    IS_ACTIVATED = False
                                    self.status_box.setText(f"⚠️ LICENSE EXPIRED\n📅 Expired On: {expiry_str}\n📧 Contact Admin for Renewal")
                                    self.status_box.setStyleSheet("color: #ff9800; font-size: 14px; font-weight: bold; border: 1px dashed #ff9800; padding: 10px; margin: 5px;")
                                    return
                            except:
                                pass
        except:
            pass
        
        # Fallback to license.dat (old method)
        try:
            with open(LICENSE_FILE, 'r') as f: 
                data = json.load(f); key = data.get('key', ''); expiry = data.get('expiry', 'Lifetime') 
                if validate_key(key):
                    IS_ACTIVATED = True; self.status_box.setText(f"✅ STATUS: ACTIVE\n📅 Valid Up To: {expiry}")
                    self.status_box.setStyleSheet("color: #00e676; font-size: 14px; font-weight: bold; border: 1px dashed #00e676; padding: 10px; margin: 5px;")
                    return
        except:
            pass
        
        # No valid license
        IS_ACTIVATED = False; self.status_box.setText("❌ STATUS: NOT ACTIVATED")
        self.status_box.setStyleSheet("color: #ff5252; font-size: 14px; font-weight: bold; border: 1px dashed #ff5252; padding: 10px; margin: 5px;")

    def ok(self):
        input_key = self.k.text().strip()
        if validate_key(input_key):
            expiry_date = (datetime.datetime.now() + datetime.timedelta(days=365)).strftime("%d-%b-%Y")
            with open(LICENSE_FILE, 'w') as f: json.dump({'key': input_key, 'expiry': expiry_date}, f)
            QMessageBox.information(self, "Success", "License Activated!")
            global IS_ACTIVATED; IS_ACTIVATED = True; self.accept()
        else: QMessageBox.warning(self, "Error", "Invalid Key")

class MarketSentimentDialog(QDialog):
    """Market Sentiment Popup - Shows worldwide market conditions"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌍 WORLDWIDE MARKET SENTIMENT")
        
        # Set as MODAL dialog to prevent parent interaction
        self.setModal(True)
        
        # Get screen size and set to 70% x 75% (not too big)
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().screenGeometry()
        width = int(screen.width() * 0.70)  # 70% of screen width
        height = int(screen.height() * 0.75)  # 75% of screen height
        self.setFixedSize(width, height)  # FIXED SIZE - prevents resizing
        
        # Center on screen
        self.move(
            (screen.width() - width) // 2,
            (screen.height() - height) // 2
        )
        
        self.setStyleSheet(STYLESHEET)
        
        # Simple window with close button only
        self.setWindowFlags(
            Qt.Dialog | 
            Qt.WindowCloseButtonHint
        )
        
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header (no window controls needed - dialog has fixed size)
        header_layout = QHBoxLayout()
        
        header = QLabel("🌍 WORLDWIDE MARKET DASHBOARD")
        header.setStyleSheet("color:#00e676;font-size:18px;font-weight:bold;padding:8px;")
        header_layout.addWidget(header)
        header_layout.addStretch()
        
        header_container = QWidget()
        header_container.setLayout(header_layout)
        header_container.setStyleSheet("border-bottom:2px solid #333;")
        layout.addWidget(header_container)
        
        # NEWS SECTION (HIGHLIGHTED AT TOP)
        news_header = QLabel("📰 BREAKING NEWS (LIVE)")
        news_header.setStyleSheet("color:#ff5722;font-size:14px;font-weight:bold;background:#1a1a1a;padding:6px;border:2px solid #ff5722;")
        news_header.setAlignment(Qt.AlignCenter)
        layout.addWidget(news_header)
        
        self.news_display = QTextEdit()
        self.news_display.setReadOnly(True)
        news_height = int(height * 0.30)  # 30% of window height for better visibility
        self.news_display.setFixedHeight(news_height)
        self.news_display.setWordWrapMode(1)  # Word wrap
        self.news_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.news_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.news_display.setStyleSheet("""
            QTextEdit {
                background: #1a1a1a;
                color: #ffffff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 11px;
                border: 2px solid #ff5722;
                padding: 10px;
                line-height: 1.5;
            }
        """)
        layout.addWidget(self.news_display)
        
        # Loading label
        self.loading_label = QLabel("⏳ Fetching live market data and news...")
        self.loading_label.setStyleSheet("color:#ffa726;font-size:12px;padding:8px;")
        self.loading_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.loading_label)
        
        # Data display area
        self.data_display = QTextEdit()
        self.data_display.setReadOnly(True)
        self.data_display.setWordWrapMode(1)  # Word wrap
        self.data_display.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.data_display.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.data_display.setStyleSheet("""
            QTextEdit {
                background: #0a0a0a;
                color: #e0e0e0;
                font-family: 'Segoe UI', Consolas, monospace;
                font-size: 10px;
                border: 1px solid #333;
                padding: 8px;
                line-height: 1.3;
            }
        """)
        layout.addWidget(self.data_display)
        
        # Status bar
        self.status_label = QLabel("📡 Connecting to market data sources...")
        self.status_label.setStyleSheet("color:#00bcd4;font-size:11px;padding:5px;")
        layout.addWidget(self.status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 REFRESH")
        refresh_btn.setStyleSheet("background:#00bcd4;color:black;font-weight:bold;padding:8px;")
        refresh_btn.clicked.connect(self.load_market_data)
        btn_layout.addWidget(refresh_btn)
        
        close_btn = QPushButton("✅ START TRADING")
        close_btn.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:8px;")
        close_btn.clicked.connect(lambda: self.start_trading_safely())
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
        
        # Auto-load data
        QTimer.singleShot(100, self.load_market_data)
    
    def _format_news_html(self, news_text: str) -> str:
        """Convert plain news text to HTML with better formatting"""
        html = "<div style='font-family: Segoe UI, Arial; font-size: 11px; line-height: 1.6;'>"
        
        for line in news_text.split('\n'):
            line = line.strip()
            
            if not line:
                html += "<br>"
            elif line.startswith('═'):
                html += "<hr style='border: 1px solid #ff5722; margin: 8px 0;'>"
            elif '📰 BREAKING' in line:
                html += f"<h2 style='color: #ff5722; margin: 10px 0; font-size: 14px;'>{line}</h2>"
            elif line.startswith('⏰'):
                html += f"<p style='color: #00bcd4; margin: 5px 0; font-size: 10px;'>{line}</p>"
            elif line.startswith('⚠️'):
                html += f"<p style='color: #ffa726; margin: 10px 0; font-size: 10px;'>{line}</p>"
            elif '🔴' in line or '🟡' in line or '🟢' in line:
                # News headline with impact marker
                if '[HIGH IMPACT]' in line:
                    html += f"<p style='color: #ff5252; font-weight: bold; margin: 8px 0;'>{line}</p>"
                elif '[MEDIUM]' in line:
                    html += f"<p style='color: #ffa726; font-weight: bold; margin: 8px 0;'>{line}</p>"
                else:
                    html += f"<p style='color: #00e676; margin: 8px 0;'>{line}</p>"
            elif line.startswith('   '):
                # News title (indented)
                html += f"<p style='color: #e0e0e0; margin: 2px 0 10px 20px; font-size: 11px;'>{line.strip()}</p>"
            else:
                html += f"<p style='margin: 5px 0;'>{line}</p>"
        
        html += "</div>"
        return html
    
    def load_market_data(self):
        """Load market sentiment data in background"""
        if not MARKET_SENTIMENT_AVAILABLE:
            self.data_display.setText("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ⚠️ MARKET SENTIMENT MODULE NOT AVAILABLE                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Install required package:
    pip install requests

Module provides:
  • Live worldwide market data (indices, forex, commodities, crypto)
  • Yesterday's close analysis
  • Today's sentiment
  • Tomorrow's prediction

Continue with trading...
            """)
            self.loading_label.hide()
            self.status_label.setText("⚠️ Module not available - install 'requests' package")
            return
        
        self.loading_label.show()
        self.loading_label.setText("⏳ Fetching live market data and news...")
        self.status_label.setText("📡 Connecting to data sources...")
        
        # Show placeholder immediately
        self.news_display.setHtml("<div style='color: #ffa726; padding: 20px; text-align: center;'><h3>📡 Loading News...</h3><p>Connecting to Reuters, Yahoo Finance, MarketWatch, CNBC...</p></div>")
        
        # Run in background thread
        def fetch_data():
            try:
                print("📊 Starting market data fetch...")
                print(f"📊 Thread started at {datetime.datetime.now().strftime('%H:%M:%S')}")
                
                # Fetch market sentiment
                sentiment = MarketSentiment()
                success = sentiment.fetch_market_data()
                summary = sentiment.get_summary_text()
                print(f"📊 Market data fetched: {success}, Length: {len(summary) if summary else 0}")
                
                # Fetch news with timeout
                news_text = ""
                try:
                    from news_fetcher import NewsFetcher
                    print("📰 Creating NewsFetcher instance...")
                    news = NewsFetcher()
                    print("📰 Fetching articles...")
                    articles = news.fetch_news()
                    print(f"📰 Articles fetched: {len(articles)}")
                    news_text = news.get_formatted_news()
                    print(f"📰 Formatted news length: {len(news_text)}")
                except Exception as e:
                    import traceback
                    print(f"❌ News fetch error: {e}")
                    print(f"❌ Traceback: {traceback.format_exc()}")
                    news_text = "📰 News temporarily unavailable\n\n"
                    news_text += f"Error: {str(e)}\n\n"
                    news_text += "• Install feedparser: py -m pip install feedparser\n"
                    news_text += "• Check internet connection\n"
                    news_text += "• Click REFRESH to retry"
                
                print(f"✅ Calling display_data with news length: {len(news_text)}")
                # Update UI on main thread
                QTimer.singleShot(0, lambda: self.display_data(summary, news_text, success))
            except Exception as e:
                import traceback
                print(f"❌ Data fetch error: {e}")
                print(f"❌ Traceback: {traceback.format_exc()}")
                QTimer.singleShot(0, lambda: self.display_error(str(e)))
        
        threading.Thread(target=fetch_data, daemon=True).start()
        print("🚀 Background thread launched")
    
    def display_data(self, summary: str, news: str, success: bool):
        """Display fetched market data and news"""
        print(f"🖥️ display_data called: summary={len(summary) if summary else 0} chars, news={len(news) if news else 0} chars")
        self.loading_label.hide()
        
        # Display news - ALWAYS show something
        if news and len(news.strip()) > 20:
            try:
                html_content = self._format_news_html(news)
                self.news_display.setHtml(html_content)
                print(f"✅ News displayed as HTML: {len(html_content)} characters")
            except Exception as e:
                print(f"❌ HTML formatting error: {e}")
                self.news_display.setPlainText(news)
                print(f"✅ News displayed as plain text: {len(news)} characters")
        else:
            fallback = "<div style='color: #ff5722; padding: 20px;'><h3>📰 No News Available</h3><p>Click 🔄 REFRESH to try again</p><p style='color: #888; font-size: 10px;'>Make sure feedparser is installed and internet is connected</p></div>"
            self.news_display.setHtml(fallback)
            print("⚠️ No news content - showing fallback message")
        
        # Display market data - ALWAYS show something
        if summary and len(summary.strip()) > 20:
            self.data_display.setText(summary)
            print(f"✅ Market data displayed: {len(summary)} characters")
        else:
            self.data_display.setText("📊 No market data available. Click REFRESH to retry.")
            print("⚠️ No market data - showing fallback message")
        
        if success:
            self.status_label.setText("✅ Live data loaded | Last updated: " + datetime.datetime.now().strftime("%H:%M:%S"))
            self.status_label.setStyleSheet("color:#00e676;font-size:11px;padding:5px;")
        else:
            self.status_label.setText("⚠️ Using demo data (API connection failed) | Updated: " + datetime.datetime.now().strftime("%H:%M:%S"))
            self.status_label.setStyleSheet("color:#ffa726;font-size:11px;padding:5px;")
    
    def display_error(self, error: str):
        """Display error message"""
        self.loading_label.hide()
        self.data_display.setText(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                           ❌ ERROR LOADING DATA                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

Error: {error}

Possible causes:
  • No internet connection
  • API rate limit reached
  • Network firewall blocking requests

You can:
  1. Click REFRESH to try again
  2. Check your internet connection
  3. Continue trading without market sentiment
        """)
        self.status_label.setText("❌ Failed to load market data")
        self.status_label.setStyleSheet("color:#ff5252;font-size:11px;padding:5px;")
    
    def start_trading_safely(self):
        """Safely start trading - close dialog and return to main window"""
        print("✅ User clicked START TRADING - returning to main window")
        # Simply close the dialog, parent window remains unchanged
        self.close()


# ==============================================================================
# --- 🖥️ MAIN WINDOW ---
# ==============================================================================
class BotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("e2eNISHAANKAN BOT power by RUDRA24 (QUANTUM TRADER)")
        
        # Set fixed reasonable size - prevent auto-resize
        self.setMinimumSize(1200, 700)
        self.resize(1200, 750)
        
        self.setStyleSheet(STYLESHEET)
        
        self.sig = BotSignals(); self.bot = TradingEngine(self.sig)
        self.logs = []
        self.log_color_index = 0  # Color rotation index for live messages
        self.log_colors = ["#00e676", "#ffd700", "#00bcd4", "#e91e63"]  # Green, Gold, Aqua, Pink
        self.sig.log.connect(self.log_msg); self.sig.stats.connect(self.upd_stats)
        self.sig.data_updated.connect(self.refresh_table); self.sig.sl_updated.connect(self.update_sl_visual)
        self.init_ui()
        
        # Check license status - but DON'T auto-show market sentiment
        if IS_ACTIVATED:
            print("✅ Bot started with valid license - ready to trade")
            # User can manually click MARKET button when needed
        else:
            # License invalid - show activation dialog
            print("❌ License not activated - showing activation dialog")
            QTimer.singleShot(100, self.open_activation)

    def init_ui(self):
        main = QWidget(); self.setCentralWidget(main); layout = QVBoxLayout(main)
        
        # --- HEADER ---
        top = QHBoxLayout()
        logo_lbl = QLabel("RUDRA24 QUANTUM")
        logo_lbl.setFixedSize(200, 50); logo_lbl.setStyleSheet("color: white; font-size: 14px; font-weight:bold; background: #222; border-radius: 5px; padding: 5px;")
        logo_lbl.setAlignment(Qt.AlignCenter)
        if os.path.exists(os.path.join(BASE_DIR, "logo.png")):
            pixmap = QPixmap(os.path.join(BASE_DIR, "logo.png")).scaled(200, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_lbl.setPixmap(pixmap)
        top.addWidget(logo_lbl); top.addSpacing(15)

        t_box = QVBoxLayout()
        t1 = QLabel("e2eNISHAANKAN BOT QT"); t1.setStyleSheet("color:#00e676;font-size:24px;font-weight:900;")
        self.lbl_strat = QLabel(f"Strategy: {self.bot.active_strategy}"); self.lbl_strat.setStyleSheet("color:#aaa;font-size:12px;")
        t_box.addWidget(t1); t_box.addWidget(self.lbl_strat); top.addLayout(t_box); top.addStretch()
        
        self.lbl_pnl = QLabel("P/L: $ 0.00"); self.lbl_pnl.setObjectName("PnL")
        top.addWidget(self.lbl_pnl); top.addSpacing(20)
        
        b_key = QPushButton("🔑 LICENSE"); b_key.setToolTip("🔑 LICENSE MANAGER\n═══════════════\nView license status & activate software\nColor: Default Gray"); b_key.clicked.connect(self.open_activation)
        b_mt5 = QPushButton("⚡ MT5"); b_mt5.setToolTip("⚡ MT5 LOGIN\n═══════════════\nConfigure MetaTrader 5 connection\nLogin/Server/Password settings\nColor: Default Gray"); b_mt5.clicked.connect(self.open_login)
        b_admin = QPushButton("🔒 ADMIN"); b_admin.setStyleSheet("background:#e91e63;color:white;"); b_admin.setToolTip("🔒 ADMIN PANEL (LOCKED)\n════════════════════\nRequires admin password\nSet custom strategy password\nLock/Unlock strategies\nColor: Pink (#e91e63)"); b_admin.clicked.connect(self.verify_admin_access)
        b_mkt = QPushButton("🌍 MARKET"); b_mkt.setStyleSheet("background:#1976d2;color:white;"); b_mkt.setToolTip("🌍 MARKET SENTIMENT\n══════════════════\nView worldwide market conditions\n• Indices, Forex, Commodities, Crypto\n• Live news feed\n• Market analysis\nColor: Blue (#1976d2)"); b_mkt.clicked.connect(self.show_market_sentiment)
        b_tv = QPushButton("📺 TRADINGVIEW"); b_tv.setStyleSheet("background:#2962ff;color:white;"); b_tv.setToolTip("📺 TRADINGVIEW SETUP\n═══════════════════\nConfigure TradingView webhook\nReceive alerts from TradingView\nAuto-trade based on alerts\nColor: Dark Blue (#2962ff)"); b_tv.clicked.connect(self.open_tv_config)
        b_ab = QPushButton("📊 AMIBROKER"); b_ab.setStyleSheet("background:#ff6f00;color:white;"); b_ab.setToolTip("📊 AMIBROKER INTEGRATION\n════════════════════════\nConnect AmiBroker signals\nAuto-sync with AFL files\nReal-time signal monitoring\nColor: Orange (#ff6f00)"); b_ab.clicked.connect(self.open_amibroker_config)
        b_ai_chart = QPushButton("📸 AI CHART"); b_ai_chart.setStyleSheet("background:#9c27b0;color:white;"); b_ai_chart.setToolTip("📸 AI CHART CAPTURE\n══════════════════\nCapture MT5 chart screenshot\nAI analyzes market direction\nBUY/SELL/NEUTRAL prediction\nColor: Purple (#9c27b0)"); b_ai_chart.clicked.connect(self.capture_chart)
        b_out = QPushButton("🚪 LOGOUT"); b_out.setStyleSheet("background:#b71c1c;color:white;"); b_out.setToolTip("🚪 LOGOUT FROM MT5\n═════════════════\nDisconnect from MetaTrader 5\nStop all running processes\nColor: Red (#b71c1c)"); b_out.clicked.connect(self.logout)
        top.addWidget(b_key); top.addWidget(b_mt5); top.addWidget(b_admin); top.addWidget(b_mkt); top.addWidget(b_tv); top.addWidget(b_ab); top.addWidget(b_ai_chart); top.addWidget(b_out); layout.addLayout(top)
        
        # --- CONTROLS ---
        ctrl = QHBoxLayout()
        g_strat = QGroupBox("EXTERNAL STRATEGY"); l_strat = QVBoxLayout(g_strat)
        strat_row = QHBoxLayout()
        self.c_strat = QComboBox(); self.c_strat.addItems(self.bot.available_strats)
        self.c_strat.currentTextChanged.connect(self.change_strategy); strat_row.addWidget(self.c_strat)
        b_add_strat = QPushButton("➕"); b_add_strat.setFixedWidth(30); b_add_strat.setStyleSheet("background:#2196f3;color:white;font-weight:bold;")
        b_add_strat.clicked.connect(self.add_strategy); strat_row.addWidget(b_add_strat)
        b_reload_strat = QPushButton("🔄"); b_reload_strat.setFixedWidth(30); b_reload_strat.setStyleSheet("background:#00bcd4;color:black;font-weight:bold;")
        b_reload_strat.clicked.connect(self.reload_strategies); strat_row.addWidget(b_reload_strat)
        b_apply_all = QPushButton("👉 ALL"); b_apply_all.setFixedWidth(40); b_apply_all.setStyleSheet("background:#ff9800;color:black;font-weight:bold;")
        b_apply_all.setToolTip("Apply selected strategy to all symbols"); b_apply_all.clicked.connect(self.apply_strategy_to_all); strat_row.addWidget(b_apply_all)
        b_unlock_help = QPushButton("🔓"); b_unlock_help.setFixedWidth(30); b_unlock_help.setStyleSheet("background:#9c27b0;color:white;font-weight:bold;")
        b_unlock_help.setToolTip("Strategy Password Help"); b_unlock_help.clicked.connect(self.show_password_help); strat_row.addWidget(b_unlock_help)
        b_unlock_strat = QPushButton("🔐"); b_unlock_strat.setFixedWidth(30); b_unlock_strat.setStyleSheet("background:#00e676;color:black;font-weight:bold;")
        b_unlock_strat.setToolTip("Unlock Strategy (Admin/Client)"); b_unlock_strat.clicked.connect(self.open_unlock_interface); strat_row.addWidget(b_unlock_strat)
        l_strat.addLayout(strat_row)
        
        # User mode selector and All Strategy checkbox
        strat_row2 = QHBoxLayout()
        mode_label = QLabel("Mode:"); mode_label.setStyleSheet("color:white;font-weight:bold;")
        strat_row2.addWidget(mode_label)
        self.c_user_mode = QComboBox(); self.c_user_mode.addItems(["👥 CLIENT", "👤 ADMIN"])
        self.c_user_mode.setStyleSheet("background:#1a1a1a;color:white;font-weight:bold;padding:3px;")
        self.c_user_mode.setToolTip("Select user mode:\n• CLIENT: Unlock with password only\n• ADMIN: Full control (lock/unlock/password)")
        self.c_user_mode.currentTextChanged.connect(self.change_user_mode)
        strat_row2.addWidget(self.c_user_mode)
        self.chk_all_strategy = QCheckBox("✅ ALL STRATEGY"); self.chk_all_strategy.setStyleSheet("color:#ffeb3b;font-weight:bold;")
        self.chk_all_strategy.setToolTip("Enable all strategies simultaneously (each symbol uses its assigned strategy)")
        self.chk_all_strategy.setChecked(False); strat_row2.addWidget(self.chk_all_strategy)
        l_strat.addLayout(strat_row2)
        ctrl.addWidget(g_strat)
        
        g_lot = QGroupBox("GLOBAL LOT"); l_lot = QHBoxLayout(g_lot)
        self.s_glot = QDoubleSpinBox(); self.s_glot.setValue(0.01); self.s_glot.setSingleStep(0.01); l_lot.addWidget(self.s_glot)
        b_glot = QPushButton("UPDATE"); b_glot.clicked.connect(self.update_all_lots); l_lot.addWidget(b_glot); ctrl.addWidget(g_lot)
        
        g_trail = QGroupBox("AUTO TRAIL"); l_trail = QHBoxLayout(g_trail)
        self.chk_trail = QCheckBox("On"); self.chk_trail.setStyleSheet("color:#00e676"); self.chk_trail.toggled.connect(self.toggle_trailing); l_trail.addWidget(self.chk_trail)
        l_trail.addWidget(QLabel("Start:")); self.s_tr_start = QDoubleSpinBox(); self.s_tr_start.setRange(0,9999); self.s_tr_start.setValue(50); self.s_tr_start.valueChanged.connect(self.update_trail_params); l_trail.addWidget(self.s_tr_start)
        l_trail.addWidget(QLabel("Step:")); self.s_tr_step = QDoubleSpinBox(); self.s_tr_step.setRange(0,9999); self.s_tr_step.setValue(20); self.s_tr_step.valueChanged.connect(self.update_trail_params); l_trail.addWidget(self.s_tr_step); ctrl.addWidget(g_trail)
        
        g_risk = QGroupBox("GLOBAL RISK"); l_risk = QHBoxLayout(g_risk)
        l_risk.addWidget(QLabel("TP $")); self.s_tp = QDoubleSpinBox(); self.s_tp.setRange(0,9999); self.s_tp.setValue(100.0); l_risk.addWidget(self.s_tp)
        l_risk.addWidget(QLabel("SL $")); self.s_sl = QDoubleSpinBox(); self.s_sl.setRange(-9999,9999); self.s_sl.setValue(-50.0); l_risk.addWidget(self.s_sl)
        b_risk = QPushButton("SET"); b_risk.setStyleSheet("background:#ff9800;color:black;"); b_risk.clicked.connect(self.update_risk); l_risk.addWidget(b_risk); ctrl.addWidget(g_risk)
        
        g_mode = QGroupBox("TRADING MODE"); l_mode = QHBoxLayout(g_mode)
        self.c_mode = QComboBox(); self.c_mode.addItems(["DUAL", "MT5", "TRADINGVIEW", "AMIBROKER"])
        self.c_mode.currentTextChanged.connect(self.change_trading_mode); l_mode.addWidget(self.c_mode)
        self.lbl_webhook = QLabel("⚫"); self.lbl_webhook.setStyleSheet("color:gray;font-size:20px;"); l_mode.addWidget(self.lbl_webhook)
        self.lbl_amibroker = QLabel("⚫"); self.lbl_amibroker.setStyleSheet("color:gray;font-size:20px;"); l_mode.addWidget(self.lbl_amibroker)
        ctrl.addWidget(g_mode)
        
        g_autoscan = QGroupBox("AUTO SIGNAL SCAN"); l_autoscan = QHBoxLayout(g_autoscan)
        self.chk_autoscan = QCheckBox("🔍 AUTO DETECT"); self.chk_autoscan.setStyleSheet("color:#ffeb3b;font-weight:bold;")
        self.chk_autoscan.toggled.connect(self.toggle_autoscan); l_autoscan.addWidget(self.chk_autoscan)
        b_ai_match = QPushButton("🧠 AI MATCH"); b_ai_match.setStyleSheet("background:#9c27b0;color:white;font-weight:bold;")
        b_ai_match.setToolTip("AI analyzes market and assigns best strategy to each symbol")
        b_ai_match.clicked.connect(self.ai_match_strategies); l_autoscan.addWidget(b_ai_match); ctrl.addWidget(g_autoscan)
        
        # Chart Capture Section
        g_chart = QGroupBox("📸 CHART CAPTURE"); l_chart = QHBoxLayout(g_chart)
        self.chk_chart = QCheckBox("📸 AUTO"); self.chk_chart.setStyleSheet("color:cyan;font-weight:bold;")
        self.chk_chart.toggled.connect(self.toggle_chart_capture); l_chart.addWidget(self.chk_chart)
        l_chart.addWidget(QLabel("Interval (min):"))
        self.spin_chart_interval = QSpinBox(); self.spin_chart_interval.setRange(1, 60); self.spin_chart_interval.setValue(5)
        self.spin_chart_interval.valueChanged.connect(self.update_chart_interval); l_chart.addWidget(self.spin_chart_interval)
        b_capture = QPushButton("📷 NOW"); b_capture.setStyleSheet("background:#00aa00;color:white;padding:5px;")
        b_capture.clicked.connect(self.manual_capture_all); l_chart.addWidget(b_capture)
        b_folder = QPushButton("📁 FOLDER"); b_folder.setStyleSheet("background:#0066cc;color:white;padding:5px;")
        b_folder.clicked.connect(self.open_charts_folder); l_chart.addWidget(b_folder); ctrl.addWidget(g_chart)
        
        g_act = QGroupBox("ACTIONS"); l_act = QHBoxLayout(g_act)
        chk = QCheckBox("AUTO"); chk.setStyleSheet("color:#00e676;"); chk.toggled.connect(lambda x: setattr(self.bot, 'auto_trading', x))
        chk_voice = QCheckBox("🔊 VOICE"); chk_voice.setStyleSheet("color:#ff69b4;"); chk_voice.setChecked(self.bot.voice_enabled); chk_voice.toggled.connect(lambda x: setattr(self.bot, 'voice_enabled', x))
        b_load = QPushButton("📂 LOAD"); b_load.clicked.connect(self.bulk_load)
        self.b_run = QPushButton("START"); self.b_run.setCheckable(True); self.b_run.setStyleSheet("QPushButton{background:#00ff00;color:black;font-weight:bold;padding:10px;} QPushButton:checked{background:#d50000;color:white;}")
        self.b_run.setToolTip("▶️ START/STOP BOT\n═══════════════\nLime Green = START (with blinking)\nRed = STOP\nToggle button"); self.b_run.clicked.connect(self.toggle_bot)
        
        # Blinking timer for START button when running
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.blink_start_button)
        self.blink_state = False
        b_close_all = QPushButton("💀 CLOSE ALL"); b_close_all.setStyleSheet("background:#b71c1c; color:white; font-weight:bold;"); b_close_all.setToolTip("💀 CLOSE ALL POSITIONS\n═════════════════════\nClose all open positions immediately\nSupports FOK/IOC/RETURN fallback\nColor: Red (#b71c1c)"); b_close_all.clicked.connect(self.bot.close_all)
        l_act.addWidget(chk); l_act.addWidget(chk_voice); l_act.addWidget(b_load); l_act.addWidget(self.b_run); l_act.addWidget(b_close_all)
        ctrl.addWidget(g_act)
        
        layout.addLayout(ctrl)
        
        # --- TABLE ---
        self.table = QTableWidget(); self.table.setColumnCount(14) 
        self.table.setHorizontalHeaderLabels(["No.", "SYMBOL", "LOT", "STRATEGY", "ACTIVE", "D%", "Spread", "Mode", "Orders", "STATUS", "PnL", "BID", "ASK", "ACTIONS"])
        
        # Set reasonable column widths instead of stretch
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)  # Allow manual resize
        
        # Set fixed widths for specific columns
        self.table.setColumnWidth(0, 50)    # No.
        self.table.setColumnWidth(1, 100)   # SYMBOL
        self.table.setColumnWidth(2, 70)    # LOT
        self.table.setColumnWidth(3, 150)   # STRATEGY
        self.table.setColumnWidth(4, 80)    # ACTIVE
        self.table.setColumnWidth(5, 70)    # D%
        self.table.setColumnWidth(6, 70)    # Spread
        self.table.setColumnWidth(7, 80)    # Mode
        self.table.setColumnWidth(8, 70)    # Orders
        self.table.setColumnWidth(9, 120)   # STATUS
        self.table.setColumnWidth(10, 80)   # PnL
        self.table.setColumnWidth(11, 90)   # BID
        self.table.setColumnWidth(12, 90)   # ASK
        self.table.setColumnWidth(13, 180)  # ACTIONS (increased for bigger buttons)
        
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True); layout.addWidget(self.table)
        
        # --- TRADINGVIEW LIVE DATA PANEL (REMOVED) ---
        # Indicators display removed for cleaner dashboard
        
        # --- NEWS TICKER PANEL ---
        news_panel = QGroupBox("📰 LIVE FINANCIAL NEWS")
        news_panel.setMaximumHeight(100)
        news_layout = QVBoxLayout(news_panel)
        
        self.news_ticker = QLabel("🔴 Loading news...")
        self.news_ticker.setStyleSheet("color:#ffeb3b;font-size:11px;background:#000;padding:8px;border:1px solid #ff5722;")
        self.news_ticker.setWordWrap(True)
        news_layout.addWidget(self.news_ticker)
        
        layout.addWidget(news_panel)
        
        # Update timer for news ticker
        self.news_update_timer = QTimer()
        self.news_update_timer.timeout.connect(self.update_news_ticker)
        self.news_update_timer.start(15000)  # Update every 15 seconds
        QTimer.singleShot(2000, self.update_news_ticker)  # First update after 2 seconds
        
        self.logs = QTextEdit(); self.logs.setMaximumHeight(100); self.logs.setReadOnly(True)
        self.logs.setStyleSheet("background:#000;border-top:1px solid #333;")
        layout.addWidget(self.logs)
        
        # Timer to update logs display with colors
        self.logs_update_timer = QTimer()
        self.logs_update_timer.timeout.connect(self.update_logs_display)
        self.logs_update_timer.start(100)  # Update every 100ms for smooth display

    # --- ADDED MISSING METHOD HERE ---
    def open_activation(self):
        ActivationDialog(self).exec_()
    
    def show_market_sentiment(self):
        """Market sentiment display removed - dashboard simplified"""
        pass  # Function disabled - no popup
    
    def open_tv_config(self):
        """TradingView Webhook Configuration"""
        d = QDialog(self)
        d.setWindowTitle("📺 TradingView Webhook Setup - Complete")
        d.setStyleSheet(STYLESHEET)
        d.setAttribute(Qt.WA_DeleteOnClose)
        
        # Get screen size and use maximum available
        screen = QApplication.primaryScreen().geometry()
        width = int(screen.width() * 0.9)
        height = int(screen.height() * 0.9)
        
        d.setMinimumSize(1100, 800)
        d.resize(width, height)
        
        # Center on screen
        center = screen.center()
        d.move(center.x() - d.width()//2, center.y() - d.height()//2)
        
        layout = QVBoxLayout(d)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # Info
        info = QLabel("📺 TradingView Webhook Integration - Remote Ready!")
        info.setStyleSheet("color:#2962ff;font-size:16px;font-weight:bold;")
        layout.addWidget(info)
        
        # URL Options Tabs with scroll area
        url_tabs = QTabWidget()
        url_tabs.setStyleSheet("""
            QTabWidget { background:#222; border:1px solid #444; border-radius:4px; }
            QTabBar::tab { padding:12px 25px; font-weight:bold; background:#1a1a1a; color:#aaa; border:1px solid #333; margin-right:2px; border-radius:4px 4px 0px 0px; }
            QTabBar::tab:selected { background:#2962ff; color:white; border:1px solid #2962ff; }
            QTabBar::tab:hover { background:#444; }
        """)
        
        # Tab 1: Local URL (with scroll)
        tab_local_scroll = QScrollArea()
        tab_local_scroll.setWidgetResizable(True)
        tab_local_scroll.setStyleSheet("""
            QScrollArea { background:#222; border:1px solid #444; border-radius:4px; }
            QScrollBar:vertical { width:12px; background:#1a1a1a; border:1px solid #333; border-radius:6px; }
            QScrollBar::handle:vertical { background:#00e676; border-radius:6px; min-height:20px; }
            QScrollBar::handle:vertical:hover { background:#00ff99; }
        """)
        tab_local = QWidget()
        l_local = QVBoxLayout(tab_local)
        l_local.setContentsMargins(15, 15, 15, 15)
        l_local.setSpacing(10)
        
        lbl_local = QLabel("🏠 For Local TradingView (Same Computer)")
        lbl_local.setStyleSheet("color:#00e676;font-weight:bold;font-size:14px;")
        l_local.addWidget(lbl_local)
        
        desc_local = QLabel("Use this if TradingView and MT5 are on the SAME computer")
        desc_local.setStyleSheet("color:#aaa;font-size:11px;padding:5px;background:#1a1a1a;border-radius:4px;")
        l_local.addWidget(desc_local)
        
        local_url = f"http://localhost:{WEBHOOK_PORT}/webhook"
        local_edit = QLineEdit(local_url)
        local_edit.setReadOnly(True)
        local_edit.setStyleSheet("background:#111;color:#00e676;font-size:13px;padding:10px;border:1px solid #00e676;border-radius:4px;")

        local_edit.setMinimumHeight(40)
        l_local.addWidget(local_edit)
        
        btn_copy_local = QPushButton("📋 COPY LOCAL URL")
        btn_copy_local.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:10px;border-radius:4px;")
        btn_copy_local.setMinimumHeight(35)
        btn_copy_local.clicked.connect(lambda: (QApplication.clipboard().setText(local_url), 
                                                 self.log_msg("✅ Local URL copied!", "lime")))
        l_local.addWidget(btn_copy_local)
        l_local.addStretch()
        
        tab_local.setLayout(l_local)
        tab_local_scroll.setWidget(tab_local)
        url_tabs.addTab(tab_local_scroll, "🏠 LOCAL")
        
        # Tab 2: Network URL (with scroll)
        tab_network_scroll = QScrollArea()
        tab_network_scroll.setWidgetResizable(True)
        tab_network_scroll.setStyleSheet("""
            QScrollArea { background:#222; border:1px solid #444; border-radius:4px; }
            QScrollBar:vertical { width:12px; background:#1a1a1a; border:1px solid #333; border-radius:6px; }
            QScrollBar::handle:vertical { background:#2962ff; border-radius:6px; min-height:20px; }
            QScrollBar::handle:vertical:hover { background:#5c7cff; }
        """)
        tab_network = QWidget()
        l_network = QVBoxLayout(tab_network)
        l_network.setContentsMargins(15, 15, 15, 15)
        l_network.setSpacing(10)
        
        lbl_network = QLabel("🌐 For Same Network (Other PC/Laptop on WiFi)")
        lbl_network.setStyleSheet("color:#2962ff;font-weight:bold;font-size:14px;")
        l_network.addWidget(lbl_network)
        
        desc_network = QLabel("Use this if TradingView is on another computer but same WiFi network")
        desc_network.setStyleSheet("color:#aaa;font-size:11px;padding:5px;background:#1a1a1a;border-radius:4px;")
        l_network.addWidget(desc_network)
        
        import socket
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except:
            local_ip = "192.168.1.XXX"
        network_url = f"http://{local_ip}:{WEBHOOK_PORT}/webhook"
        network_edit = QLineEdit(network_url)
        network_edit.setReadOnly(True)
        network_edit.setStyleSheet("background:#111;color:#2962ff;font-size:13px;padding:10px;border:1px solid #2962ff;border-radius:4px;")
        network_edit.setMinimumHeight(40)
        l_network.addWidget(network_edit)
        
        btn_copy_network = QPushButton("📋 COPY NETWORK URL")
        btn_copy_network.setStyleSheet("background:#2962ff;color:white;font-weight:bold;padding:10px;border-radius:4px;")
        btn_copy_network.setMinimumHeight(35)
        btn_copy_network.clicked.connect(lambda: (QApplication.clipboard().setText(network_url), 
                                                   self.log_msg(f"✅ Network URL copied: {local_ip}", "aqua")))
        l_network.addWidget(btn_copy_network)
        
        note_network = QLabel("⚠️ IMPORTANT:\n• Both devices on same WiFi\n• Windows Firewall: Allow port 5000\n• Your IP: " + local_ip)
        note_network.setStyleSheet("color:#ff9800;font-size:11px;padding:10px;background:#1a1a1a;border-left:3px solid #ff9800;border-radius:4px;")
        l_network.addWidget(note_network)
        l_network.addStretch()
        
        tab_network.setLayout(l_network)
        tab_network_scroll.setWidget(tab_network)
        url_tabs.addTab(tab_network_scroll, "🌐 NETWORK")
        
        # Tab 3: Remote URL (Ngrok - with scroll)
        tab_remote_scroll = QScrollArea()
        tab_remote_scroll.setWidgetResizable(True)
        tab_remote_scroll.setStyleSheet("""
            QScrollArea { background:#222; border:1px solid #444; border-radius:4px; }
            QScrollBar:vertical { width:14px; background:#1a1a1a; border:1px solid #333; border-radius:7px; }
            QScrollBar::handle:vertical { background:#ff5722; border-radius:7px; min-height:20px; margin:2px; }
            QScrollBar::handle:vertical:hover { background:#ff8a50; }
        """)
        tab_remote = QWidget()
        l_remote = QVBoxLayout(tab_remote)
        l_remote.setContentsMargins(15, 15, 15, 15)
        l_remote.setSpacing(10)
        
        lbl_remote = QLabel("🌍 For Remote Access (Anywhere in World)")
        lbl_remote.setStyleSheet("color:#ff5722;font-weight:bold;font-size:14px;")
        l_remote.addWidget(lbl_remote)
        
        desc_remote = QLabel("Use this if TradingView is on ANY computer/phone ANYWHERE in the world (Ngrok)")
        desc_remote.setStyleSheet("color:#aaa;font-size:11px;padding:5px;background:#1a1a1a;border-radius:4px;")
        desc_remote.setWordWrap(True)
        l_remote.addWidget(desc_remote)
        
        remote_info = QTextEdit()
        remote_info.setReadOnly(True)
        remote_info.setStyleSheet("background:#111;color:#ccc;font-size:12px;padding:10px;border:1px solid #444;border-radius:4px;")
        remote_info.setMaximumHeight(220)
        remote_info.setHtml("""
        <div style='color:#00e676;line-height:1.6;'>
        <b>🚀 Setup Remote Access with Ngrok:</b><br><br>
        
        <b style='color:#2962ff;'>Step 1:</b> Download Ngrok<br>
        <span style='color:#aaa;margin-left:20px;'>• Visit: https://ngrok.com/download<br>
        • Sign up (Free account)<br>
        • Download for Windows</span><br><br>
        
        <b style='color:#2962ff;'>Step 2:</b> Install & Setup<br>
        <span style='color:#aaa;margin-left:20px;'>• Extract ngrok.exe<br>
        • Open CMD/PowerShell<br>
        • Run: ngrok authtoken YOUR_TOKEN</span><br><br>
        
        <b style='color:#2962ff;'>Step 3:</b> Start Tunnel<br>
        <span style='color:#aaa;margin-left:20px;'>• Run: ngrok http 5000<br>
        • Copy the "Forwarding" URL<br>
        • Webhook URL: https://abc123.ngrok.io/webhook</span><br><br>
        
        <b style='color:#ffd700;'>✅ Works from anywhere!</b>
        </div>
        """)
        l_remote.addWidget(remote_info)
        
        # Ngrok URL display
        lbl_ngrok_url = QLabel("Your Remote Webhook URL:")
        lbl_ngrok_url.setStyleSheet("color:#ff5722;font-weight:bold;margin-top:10px;")
        l_remote.addWidget(lbl_ngrok_url)
        
        self.ngrok_url_edit = QLineEdit("Not started yet - Click 'START NGROK' button below")
        self.ngrok_url_edit.setReadOnly(True)
        self.ngrok_url_edit.setStyleSheet("background:#111;color:#ff9800;font-size:12px;padding:10px;font-weight:bold;border:1px solid #ff9800;border-radius:4px;")
        self.ngrok_url_edit.setMinimumHeight(35)
        l_remote.addWidget(self.ngrok_url_edit)
        
        btn_copy_ngrok_url = QPushButton("📋 COPY NGROK URL")
        btn_copy_ngrok_url.setStyleSheet("background:#4caf50;color:white;font-weight:bold;padding:10px;border-radius:4px;")
        btn_copy_ngrok_url.setMinimumHeight(35)
        btn_copy_ngrok_url.clicked.connect(lambda: self.copy_ngrok_url())
        l_remote.addWidget(btn_copy_ngrok_url)
        
        btn_start_ngrok = QPushButton("🚀 START NGROK TUNNEL")
        btn_start_ngrok.setStyleSheet("background:#ff5722;color:white;font-weight:bold;padding:12px;font-size:14px;border-radius:4px;")
        btn_start_ngrok.setMinimumHeight(40)
        btn_start_ngrok.clicked.connect(lambda: self.start_ngrok_tunnel())
        l_remote.addWidget(btn_start_ngrok)
        
        btn_open_ngrok = QPushButton("🌍 DOWNLOAD NGROK (If Not Installed)")
        btn_open_ngrok.setStyleSheet("background:#666;color:white;padding:10px;border-radius:4px;")
        btn_open_ngrok.setMinimumHeight(35)
        btn_open_ngrok.clicked.connect(lambda: os.system("start https://ngrok.com/download"))
        l_remote.addWidget(btn_open_ngrok)
        
        btn_ngrok_cmd = QPushButton("📋 COPY MANUAL COMMAND")
        btn_ngrok_cmd.setStyleSheet("background:#9c27b0;color:white;padding:10px;border-radius:4px;")
        btn_ngrok_cmd.setMinimumHeight(35)
        btn_ngrok_cmd.clicked.connect(lambda: (QApplication.clipboard().setText("ngrok http 5000"), 
                                                self.log_msg("✅ Manual command copied: ngrok http 5000", "pink")))
        l_remote.addWidget(btn_ngrok_cmd)
        l_remote.addStretch()
        
        tab_remote.setLayout(l_remote)
        tab_remote_scroll.setWidget(tab_remote)
        url_tabs.addTab(tab_remote_scroll, "🌍 REMOTE")
        
        layout.addWidget(url_tabs, 1)  # Give tabs priority space
        
        # Secret Key (scrollable)
        g_secret = QGroupBox("🔐 Webhook Secret Key")
        l_secret = QVBoxLayout(g_secret)
        secret_edit = QLineEdit(WEBHOOK_SECRET)
        secret_edit.setReadOnly(True)
        secret_edit.setStyleSheet("background:#111;color:#ff9800;font-size:13px;padding:10px;border:1px solid #ff9800;border-radius:4px;")
        secret_edit.setMinimumHeight(40)
        l_secret.addWidget(secret_edit)
        
        btn_copy_secret = QPushButton("📋 COPY SECRET")
        btn_copy_secret.setStyleSheet("background:#ff9800;color:black;font-weight:bold;padding:8px;border-radius:4px;")
        btn_copy_secret.setMinimumHeight(32)
        btn_copy_secret.clicked.connect(lambda: (QApplication.clipboard().setText(WEBHOOK_SECRET), 
                                                  self.log_msg("✅ Secret copied!", "gold")))
        l_secret.addWidget(btn_copy_secret)
        layout.addWidget(g_secret)
        
        # JSON Template (scrollable)
        g_json = QGroupBox("📄 TradingView Alert Message (JSON)")
        l_json = QVBoxLayout(g_json)
        json_template = '''{\n  "secret": "RUDRA24_WEBHOOK_KEY",\n  "symbol": "{{ticker}}",\n  "action": "{{strategy.order.action}}",\n  "price": {{close}},\n  "lot": 0.01,\n  "rsi": {{rsi}},\n  "macd": {{macd}},\n  "ema_fast": {{ema(9)}},\n  "ema_slow": {{ema(21)}},\n  "volume": {{volume}},\n  "indicator": "{{strategy.market_position}}"\n}'''
        json_edit = QTextEdit(json_template)
        json_edit.setStyleSheet("background:#111;color:#00bcd4;font-family:monospace;font-size:12px;padding:10px;border:1px solid #00bcd4;border-radius:4px;")
        json_edit.setMinimumHeight(200)
        l_json.addWidget(json_edit)
        
        note = QLabel("📊 Indicators will display live | ✅ Orders execute directly on MT5!")
        note.setStyleSheet("color:#00e676;font-size:11px;font-weight:bold;padding:5px;background:#1a1a1a;border-radius:4px;")
        l_json.addWidget(note)
        
        btn_copy_json = QPushButton("📋 COPY JSON")
        btn_copy_json.setStyleSheet("background:#00bcd4;color:black;font-weight:bold;padding:8px;border-radius:4px;")
        btn_copy_json.setMinimumHeight(32)
        btn_copy_json.clicked.connect(lambda: (QApplication.clipboard().setText(json_template), 
                                               self.log_msg("✅ JSON copied!", "aqua")))
        l_json.addWidget(btn_copy_json)
        layout.addWidget(g_json)
        
        # Controls - Bottom buttons
        btn_start = QPushButton("🚀 START WEBHOOK SERVER")
        btn_start.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:12px;border-radius:4px;font-size:13px;")
        btn_start.setMinimumHeight(40)
        btn_start.clicked.connect(lambda: self.bot.start_webhook_server())
        layout.addWidget(btn_start)
        
        btn_guide = QPushButton("📖 HOW TO CONNECT TRADINGVIEW CHART")
        btn_guide.setStyleSheet("background:#2962ff;color:white;font-weight:bold;padding:12px;border-radius:4px;font-size:13px;")
        btn_guide.setMinimumHeight(40)
        btn_guide.clicked.connect(self.show_tv_chart_guide)
        layout.addWidget(btn_guide)
        
        btn_test = QPushButton("🧪 TEST WEBHOOK CONNECTION")
        btn_test.setStyleSheet("background:#9c27b0;color:white;font-weight:bold;padding:12px;border-radius:4px;font-size:13px;")
        btn_test.setMinimumHeight(40)
        btn_test.clicked.connect(self.test_webhook_connection)
        layout.addWidget(btn_test)
        
        btn_close = QPushButton("✖️ CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;font-weight:bold;padding:10px;border-radius:4px;")
        btn_close.setMinimumHeight(35)
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()
    
    def show_tv_chart_guide(self):
        """Show step-by-step TradingView chart connection guide"""
        d = QDialog(self)
        d.setWindowTitle("📺 TradingView Chart Connection Guide")
        d.setStyleSheet(STYLESHEET)
        d.resize(700, 600)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel("📺 HOW TO CONNECT TRADINGVIEW CHART")
        header.setStyleSheet("color:#2962ff;font-size:18px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Scrollable content
        scroll = QTextEdit()
        scroll.setReadOnly(True)
        scroll.setHtml(f"""
<div style='color:#e0e0e0;font-size:13px;line-height:1.8;'>

<h1 style='color:#2962ff;text-align:center;'>📺 TRADINGVIEW CHART CONNECTION</h1>
<h2 style='color:#00e676;text-align:center;'>Complete Step-by-Step Guide</h2>

<hr style='border:2px solid #00e676;'>

<h2 style='color:#ffd700;'>🎯 STEP 1: START WEBHOOK SERVER (In This Bot)</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #00e676;margin:10px 0;'>
<p><b style='color:#00e676;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>📍 In this dialog, click <b style='color:#00e676;'>🚀 START WEBHOOK SERVER</b> button</li>
<li>📍 Wait for message in logs: <span style='color:#00e676;background:#111;padding:2px 8px;'>"✅ Webhook server running on port 5000"</span></li>
<li>📍 Keep this bot window <b>OPEN</b> - don't close!</li>
<li>📍 Make sure MT5 is <b>logged in</b></li>
</ol>

<p><b style='color:#ffeb3b;'>✅ What you'll see:</b></p>
<pre style='background:#000;padding:10px;color:#00e676;'>
[10:30:45] 🚀 Webhook server starting...
[10:30:46] ✅ Webhook server running on port 5000
[10:30:46] 📡 Listening for TradingView signals...
</pre>

<p><b style='color:#ff9800;'>⚠️ Common Issues:</b></p>
<ul style='color:#aaa;'>
<li>❌ Port already in use → Close other bots or restart PC</li>
<li>❌ Firewall blocking → Allow Python in Windows Firewall</li>
</ul>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 2: OPEN TRADINGVIEW WEBSITE</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #2962ff;margin:10px 0;'>
<p><b style='color:#2962ff;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>🌐 Open browser (Chrome/Firefox/Edge)</li>
<li>🌐 Go to: <a href='https://www.tradingview.com' style='color:#2962ff;font-weight:bold;'>www.tradingview.com</a></li>
<li>🌐 Login to your account (Free or Premium)</li>
<li>🌐 Click <b>"Chart"</b> at top</li>
</ol>

<p><b style='color:#ffeb3b;'>✅ You should see:</b></p>
<ul style='color:#aaa;'>
<li>📊 Big chart in center</li>
<li>🔧 Toolbar on left side</li>
<li>📝 Pine Editor button at bottom</li>
</ul>

<p><b style='color:#00e676;'>💡 Tip:</b> Use <b>Premium account</b> for webhook alerts!</p>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 3: SELECT TRADING SYMBOL</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #00bcd4;margin:10px 0;'>
<p><b style='color:#00bcd4;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>🔍 Click on symbol name (top-left of chart)</li>
<li>🔍 Search for: <b>EURUSD</b>, <b>GBPUSD</b>, <b>BTCUSD</b>, etc.</li>
<li>🔍 Select your preferred symbol</li>
<li>🔍 Set timeframe: <b>5 min</b>, <b>15 min</b>, or <b>1 hour</b></li>
</ol>

<p><b style='color:#ffeb3b;'>✅ Example Symbols:</b></p>
<ul style='color:#00bcd4;'>
<li>💱 Forex: EURUSD, GBPUSD, USDJPY</li>
<li>₿ Crypto: BTCUSD, ETHUSD, BNBUSD</li>
<li>📈 Stocks: AAPL, TSLA, GOOGL</li>
<li>🥇 Commodities: XAUUSD (Gold), USOIL</li>
</ul>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 4: ADD INDICATORS TO CHART</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #9c27b0;margin:10px 0;'>
<p><b style='color:#9c27b0;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>📊 Click <b>"Indicators"</b> button (top toolbar)</li>
<li>📊 Search and add:
   <ul style='color:#aaa;margin-top:5px;'>
   <li>✅ RSI (Relative Strength Index)</li>
   <li>✅ MACD (Moving Average Convergence Divergence)</li>
   <li>✅ EMA 9 (Exponential Moving Average)</li>
   <li>✅ EMA 21</li>
   </ul>
</li>
<li>📊 Indicators will appear on chart</li>
</ol>

<p><b style='color:#ffeb3b;'>✅ How to add:</b></p>
<pre style='background:#000;padding:10px;color:#9c27b0;'>
1. Click "Indicators" → Search "RSI" → Click
2. Repeat for MACD, EMA
3. You'll see them on chart with different colors
</pre>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 5: OPEN PINE EDITOR</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #ff6f00;margin:10px 0;'>
<p><b style='color:#ff6f00;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>🖊️ Look at <b>bottom</b> of TradingView page</li>
<li>🖊️ Click <b>"Pine Editor"</b> tab</li>
<li>🖊️ Editor window will open</li>
<li>🖊️ Delete any default code</li>
</ol>

<p><b style='color:#ffeb3b;'>✅ You should see:</b></p>
<ul style='color:#aaa;'>
<li>📝 Empty code editor</li>
<li>💾 "Save" button at top</li>
<li>▶️ "Add to Chart" button</li>
</ul>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 6: WRITE PINE SCRIPT STRATEGY</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #f44336;margin:10px 0;'>
<p><b style='color:#f44336;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>📝 Copy this code → Paste in Pine Editor:</li>
</ol>

<pre style='background:#000;padding:15px;color:#00bcd4;border:2px solid #00e676;font-family:monospace;font-size:12px;overflow-x:auto;'>
//@version=5
strategy("RUDRA Bot Auto Trader", overlay=true)

// ========== INDICATORS ==========
rsi = ta.rsi(close, 14)
[macd_line, signal_line, _] = ta.macd(close, 12, 26, 9)
ema_fast = ta.ema(close, 9)
ema_slow = ta.ema(close, 21)

// ========== BUY SIGNAL ==========
buy_condition = ta.crossover(ema_fast, ema_slow) and rsi < 50
if buy_condition
    strategy.entry("BUY", strategy.long)
    alert("BUY Signal Generated", alert.freq_once_per_bar)

// ========== SELL SIGNAL ==========
sell_condition = ta.crossunder(ema_fast, ema_slow) and rsi > 50
if sell_condition
    strategy.entry("SELL", strategy.short)
    alert("SELL Signal Generated", alert.freq_once_per_bar)

// ========== PLOT ON CHART ==========
plot(ema_fast, color=color.green, title="EMA 9")
plot(ema_slow, color=color.red, title="EMA 21")
</pre>

<ol start='2' style='font-size:14px;margin-top:10px;'>
<li>💾 Click <b>"Save"</b> → Name it: <span style='color:#00e676;'>"RUDRA Bot"</span></li>
<li>▶️ Click <b>"Add to Chart"</b></li>
<li>📊 Strategy will start showing BUY/SELL signals on chart!</li>
</ol>

<p><b style='color:#00e676;'>✅ What happens:</b></p>
<ul style='color:#aaa;'>
<li>🟢 Green arrows = BUY signals</li>
<li>🔴 Red arrows = SELL signals</li>
<li>📊 Lines show on chart (Green EMA 9, Red EMA 21)</li>
</ul>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 7: CREATE WEBHOOK ALERT</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #00e676;margin:10px 0;'>
<p><b style='color:#00e676;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>⏰ Click <b>"Alert"</b> button (⏰ icon, right side of chart)</li>
<li>⏰ Alert dialog will open</li>
<li>⏰ Fill these fields:</li>
</ol>

<table style='width:100%;border-collapse:collapse;margin:10px 0;'>
<tr style='background:#111;'>
<td style='padding:8px;border:1px solid #333;color:#00e676;font-weight:bold;'>Field</td>
<td style='padding:8px;border:1px solid #333;color:#00e676;font-weight:bold;'>Value</td>
</tr>
<tr>
<td style='padding:8px;border:1px solid #333;color:#ffeb3b;'>Condition</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>RUDRA Bot → Order fills</td>
</tr>
<tr style='background:#0a0a0a;'>
<td style='padding:8px;border:1px solid #333;color:#ffeb3b;'>Alert name</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>RUDRA Trading Signal</td>
</tr>
<tr>
<td style='padding:8px;border:1px solid #333;color:#ffeb3b;'>Message</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>See JSON below ⬇️</td>
</tr>
<tr style='background:#0a0a0a;'>
<td style='padding:8px;border:1px solid #333;color:#ffeb3b;'>Webhook URL</td>
<td style='padding:8px;border:1px solid #333;color:#00e676;font-weight:bold;'>http://localhost:5000/webhook</td>
</tr>
</table>

<p><b style='color:#ffeb3b;'>📋 Message (JSON) - Copy this exactly:</b></p>
<pre style='background:#000;padding:15px;color:#00bcd4;border:2px solid #ffd700;font-family:monospace;font-size:11px;overflow-x:auto;'>
{{
  "secret": "RUDRA24_WEBHOOK_KEY",
  "symbol": "{{{{ticker}}}}",
  "action": "{{{{strategy.order.action}}}}",
  "price": {{{{close}}}},
  "lot": 0.01,
  "rsi": {{{{ta.rsi(close, 14)}}}},
  "macd": {{{{ta.macd(close, 12, 26, 9)[0]}}}},
  "ema_fast": {{{{ta.ema(close, 9)}}}},
  "ema_slow": {{{{ta.ema(close, 21)}}}},
  "timeframe": "{{{{interval}}}}",
  "indicator": "{{{{strategy.market_position}}}}"
}}
</pre>

<ol start='4' style='font-size:14px;margin-top:10px;'>
<li>✅ Check: <b>"Webhook URL"</b> checkbox</li>
<li>✅ Click <b>"Create"</b> button</li>
</ol>

<p><b style='color:#00e676;'>✅ Alert created!</b> You'll see it in alert list.</p>

<p><b style='color:#ff9800;'>⚠️ Important:</b></p>
<ul style='color:#aaa;'>
<li>🔑 Secret must match: <b style='color:#ffeb3b;'>RUDRA24_WEBHOOK_KEY</b></li>
<li>🌐 URL for same PC: <b>http://localhost:5000/webhook</b></li>
<li>🌐 URL for different PC: <b>http://YOUR_IP:5000/webhook</b></li>
<li>💎 Premium TradingView required for webhooks!</li>
</ul>
</div>

<hr style='border:1px solid #333;margin:20px 0;'>

<h2 style='color:#ffd700;'>🎯 STEP 8: TEST THE CONNECTION</h2>

<div style='background:#1a1a1a;padding:15px;border-left:4px solid #2962ff;margin:10px 0;'>
<p><b style='color:#2962ff;font-size:15px;'>What to do:</b></p>
<ol style='font-size:14px;'>
<li>🧪 In this dialog, click <b style='color:#00e676;'>🧪 Test Webhook</b> button</li>
<li>🧪 Check logs in bot for test signal</li>
<li>🧪 Wait for strategy signal on TradingView chart</li>
<li>🧪 When signal appears, check bot logs</li>
</ol>

<p><b style='color:#ffeb3b;'>✅ What you should see in bot logs:</b></p>
<pre style='background:#000;padding:10px;color:#00e676;'>
[10:45:23] 📡 TradingView signal received
[10:45:23] Symbol: EURUSD | Action: BUY
[10:45:23] RSI: 45.2 | MACD: 0.0012
[10:45:24] ✅ Order placed: BUY EURUSD 0.01 lots
</pre>

<p><b style='color:#ff9800;'>⚠️ Troubleshooting:</b></p>
<table style='width:100%;border-collapse:collapse;margin:10px 0;'>
<tr style='background:#111;'>
<td style='padding:8px;border:1px solid #333;color:#ff9800;font-weight:bold;'>Problem</td>
<td style='padding:8px;border:1px solid #333;color:#ff9800;font-weight:bold;'>Solution</td>
</tr>
<tr>
<td style='padding:8px;border:1px solid #333;color:#f44336;'>No signal received</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>Check webhook URL, verify server running</td>
</tr>
<tr style='background:#0a0a0a;'>
<td style='padding:8px;border:1px solid #333;color:#f44336;'>Wrong symbol</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>Symbol must match MT5 (EURUSD not EUR/USD)</td>
</tr>
<tr>
<td style='padding:8px;border:1px solid #333;color:#f44336;'>Order not placed</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>Check MT5 login, account balance, symbol tradable</td>
</tr>
<tr style='background:#0a0a0a;'>
<td style='padding:8px;border:1px solid #333;color:#f44336;'>Invalid secret</td>
<td style='padding:8px;border:1px solid #333;color:#aaa;'>Secret must be: RUDRA24_WEBHOOK_KEY</td>
</tr>
</table>
</div>

<hr style='border:2px solid #00e676;margin:20px 0;'>

<h2 style='color:#00e676;text-align:center;'>🎉 CONGRATULATIONS!</h2>
<p style='text-align:center;font-size:16px;color:#ffeb3b;'>
Your TradingView chart is now connected to the bot!<br>
Every signal will automatically execute trades on MT5!
</p>

<hr style='border:1px solid #333;margin:20px 0;'>

<h3 style='color:#00bcd4;'>📚 ADDITIONAL RESOURCES</h3>

<div style='background:#0a0a0a;padding:15px;border-radius:5px;'>
<p><b style='color:#ffd700;'>🌐 For Remote Access (Different PC/Phone):</b></p>
<ol style='color:#aaa;'>
<li>Download <b>ngrok</b>: <a href='https://ngrok.com/download' style='color:#2962ff;'>ngrok.com/download</a></li>
<li>Run: <code style='background:#111;padding:2px 8px;color:#00bcd4;'>ngrok http 5000</code></li>
<li>Copy ngrok URL (e.g., https://abc123.ngrok.io)</li>
<li>Use in TradingView webhook: <code style='background:#111;padding:2px 8px;color:#00e676;'>https://abc123.ngrok.io/webhook</code></li>
<li>Now works from anywhere in world! 🌍</li>
</ol>

<p><b style='color:#ffd700;'>💡 Pro Tips:</b></p>
<ul style='color:#aaa;'>
<li>🎯 Test with <b>paper trading</b> first (TradingView feature)</li>
<li>📊 Start with small lot sizes (0.01)</li>
<li>⏰ Check signals during active market hours</li>
<li>🔒 Keep bot running 24/7 for live signals</li>
<li>📱 Use VPS for uninterrupted trading</li>
</ul>

<p><b style='color:#ffd700;'>📞 Need Help?</b></p>
<p style='color:#aaa;'>
Check logs carefully - they show exactly what's happening!<br>
Most issues are: Wrong URL, Firewall, or MT5 not logged in.
</p>
</div>

</div>
        """)
        scroll.setStyleSheet("background:#0a0a0a;border:1px solid #333;padding:10px;")
        layout.addWidget(scroll)
        
        # Quick links
        links_layout = QHBoxLayout()
        
        btn_ngrok = QPushButton("🌐 Download ngrok")
        btn_ngrok.setStyleSheet("background:#9c27b0;color:white;padding:8px;")
        btn_ngrok.clicked.connect(lambda: os.system("start https://ngrok.com/download"))
        links_layout.addWidget(btn_ngrok)
        
        btn_tv = QPushButton("📺 Open TradingView")
        btn_tv.setStyleSheet("background:#2962ff;color:white;padding:8px;")
        btn_tv.clicked.connect(lambda: os.system("start https://www.tradingview.com"))
        links_layout.addWidget(btn_tv)
        
        btn_test = QPushButton("🧪 Test Webhook")
        btn_test.setStyleSheet("background:#00e676;color:black;padding:8px;font-weight:bold;")
        btn_test.clicked.connect(self.test_webhook_connection)
        links_layout.addWidget(btn_test)
        
        btn_remote = QPushButton("🌍 Remote Setup (Ngrok)")
        btn_remote.setStyleSheet("background:#2962ff;color:white;padding:8px;font-weight:bold;")
        btn_remote.clicked.connect(self.setup_remote_webhook)
        links_layout.addWidget(btn_remote)
        
        layout.addLayout(links_layout)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()
    
    def start_ngrok_tunnel(self):
        """Start ngrok tunnel and get public URL"""
        try:
            # Check if ngrok is installed
            result = subprocess.run(['where', 'ngrok'], capture_output=True, text=True, shell=True)
            if result.returncode != 0:
                QMessageBox.warning(self, "❌ Ngrok Not Found", 
                    "Ngrok is not installed or not in PATH!\n\n"
                    "Download from: https://ngrok.com/download\n\n"
                    "After installing:\n"
                    "1. Extract ngrok.exe\n"
                    "2. Copy to C:\\Windows\\System32\\ (or add to PATH)\n"
                    "3. Run: ngrok authtoken YOUR_TOKEN\n"
                    "4. Restart this bot")
                os.system("start https://ngrok.com/download")
                return
            
            # Start ngrok in background
            self.log_msg("🚀 Starting Ngrok tunnel...", "aqua")
            
            # Kill existing ngrok processes
            subprocess.run(['taskkill', '/F', '/IM', 'ngrok.exe'], capture_output=True, shell=True)
            time.sleep(1)
            
            # Start ngrok tunnel
            ngrok_process = subprocess.Popen(['ngrok', 'http', '5000'], 
                                            stdout=subprocess.PIPE, 
                                            stderr=subprocess.PIPE,
                                            creationflags=subprocess.CREATE_NEW_CONSOLE)
            
            self.log_msg("⏳ Waiting for ngrok to start (5 seconds)...", "orange")
            time.sleep(5)
            
            # Get ngrok URL from API
            try:
                import requests
                response = requests.get("http://localhost:4040/api/tunnels", timeout=5)
                tunnels = response.json()['tunnels']
                
                if tunnels:
                    public_url = tunnels[0]['public_url']
                    webhook_url = f"{public_url}/webhook"
                    
                    self.ngrok_url_edit.setText(webhook_url)
                    self.ngrok_url_edit.setStyleSheet("background:#111;color:#00e676;font-size:14px;padding:8px;font-weight:bold;")
                    
                    QApplication.clipboard().setText(webhook_url)
                    
                    QMessageBox.information(self, "✅ Ngrok Started!", 
                        f"🌍 Remote Webhook URL:\n\n{webhook_url}\n\n"
                        f"✅ URL copied to clipboard!\n\n"
                        f"Use this URL in TradingView alert.\n"
                        f"It works from anywhere in the world! 🌎")
                    
                    self.log_msg(f"✅ Ngrok tunnel active: {public_url}", "lime")
                    self.log_msg(f"📋 Webhook URL: {webhook_url}", "gold")
                else:
                    self.log_msg("❌ Ngrok tunnel not found", "red")
                    QMessageBox.warning(self, "⚠️ Tunnel Error", 
                        "Ngrok started but no tunnel found.\n\n"
                        "Possible issues:\n"
                        "• Ngrok authtoken not set\n"
                        "• Free account tunnel limit reached\n\n"
                        "Run manually: ngrok http 5000")
            except Exception as e:
                self.log_msg(f"❌ Failed to get ngrok URL: {e}", "red")
                QMessageBox.warning(self, "⚠️ URL Fetch Failed", 
                    f"Ngrok started but couldn't get URL.\n\n"
                    f"Error: {e}\n\n"
                    f"Try manually:\n"
                    f"1. Open CMD\n"
                    f"2. Run: ngrok http 5000\n"
                    f"3. Copy the 'Forwarding' URL")
                
        except Exception as e:
            self.log_msg(f"❌ Ngrok error: {e}", "red")
            QMessageBox.critical(self, "❌ Error", f"Failed to start ngrok:\n\n{str(e)}")
    
    def copy_ngrok_url(self):
        """Copy ngrok URL to clipboard"""
        url = self.ngrok_url_edit.text()
        if "Not started" in url:
            QMessageBox.warning(self, "⚠️ No URL", "Start ngrok tunnel first!")
        else:
            QApplication.clipboard().setText(url)
            self.log_msg(f"📋 Copied: {url}", "lime")
            QMessageBox.information(self, "✅ Copied", f"URL copied to clipboard:\n\n{url}")
    
    def test_webhook_connection(self):
        """Test webhook server with sample data and diagnostics"""
        # Create diagnostic dialog
        diag_dlg = QDialog(self)
        diag_dlg.setWindowTitle("🧪 Webhook Connection Test")
        diag_dlg.setStyleSheet(STYLESHEET)
        diag_dlg.resize(600, 500)
        
        layout = QVBoxLayout(diag_dlg)
        
        # Header
        header = QLabel("🧪 WEBHOOK CONNECTION DIAGNOSTICS")
        header.setStyleSheet("color:#00e676;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Status display
        status_text = QTextEdit()
        status_text.setReadOnly(True)
        status_text.setStyleSheet("background:#000;color:#00e676;font-family:monospace;padding:10px;")
        layout.addWidget(status_text)
        
        def log_status(msg, color="#00e676"):
            status_text.append(f"<span style='color:{color};'>{msg}</span>")
            QApplication.processEvents()
        
        # Run diagnostics
        log_status("🔍 Starting diagnostics...", "#00bcd4")
        log_status("")
        
        # Check 1: Import requests
        try:
            import requests
            log_status("✅ Step 1: requests library available", "#00e676")
        except ImportError:
            log_status("❌ Step 1: requests library missing!", "#f44336")
            log_status("   Fix: pip install requests", "#ff9800")
            layout.addWidget(QPushButton("CLOSE").clicked.connect(diag_dlg.accept) or QPushButton("CLOSE"))
            diag_dlg.exec_()
            return
        
        log_status("")
        
        # Check 2: Server running
        log_status("🔍 Step 2: Checking if webhook server is running...", "#00bcd4")
        try:
            response = requests.get("http://localhost:5000/", timeout=2)
            log_status("✅ Step 2: Webhook server is running!", "#00e676")
            log_status(f"   Server response: {response.status_code}", "#aaa")
        except requests.exceptions.ConnectionError:
            log_status("❌ Step 2: Webhook server NOT running!", "#f44336")
            log_status("   Fix: Click '🚀 START WEBHOOK SERVER' button", "#ff9800")
            
            # Auto-start option
            btn_start = QPushButton("🚀 START WEBHOOK NOW")
            btn_start.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:10px;")
            btn_start.clicked.connect(lambda: (self.bot.start_webhook_server(), log_status("✅ Server started!", "#00e676")))
            layout.addWidget(btn_start)
            
            btn_close = QPushButton("CLOSE")
            btn_close.clicked.connect(diag_dlg.accept)
            layout.addWidget(btn_close)
            diag_dlg.exec_()
            return
        except Exception as e:
            log_status(f"❌ Step 2: Error - {str(e)}", "#f44336")
            layout.addWidget(QPushButton("CLOSE").clicked.connect(diag_dlg.accept) or QPushButton("CLOSE"))
            diag_dlg.exec_()
            return
        
        log_status("")
        
        # Check 3: Send test webhook
        log_status("🔍 Step 3: Sending test webhook data...", "#00bcd4")
        test_data = {
            "secret": WEBHOOK_SECRET,
            "symbol": "EURUSD",
            "action": "BUY",
            "price": 1.0850,
            "lot": 0.01,
            "rsi": 45.5,
            "macd": 0.0012,
            "indicator": "long"
        }
        
        log_status(f"   Data: {test_data}", "#aaa")
        
        try:
            response = requests.post("http://localhost:5000/webhook", json=test_data, timeout=5)
            log_status("")
            
            if response.status_code == 200:
                log_status("✅ Step 3: Webhook accepted data!", "#00e676")
                log_status(f"   Response: {response.json()}", "#00bcd4")
                log_status("")
                log_status("="*50, "#333")
                log_status("🎉 ALL TESTS PASSED!", "#00e676")
                log_status("="*50, "#333")
                log_status("")
                log_status("✅ Your TradingView can now connect!", "#ffd700")
                log_status("📋 Use this webhook URL in TradingView:", "#00bcd4")
                log_status("   http://localhost:5000/webhook", "#ffeb3b")
                self.log_msg("🧪 Webhook test PASSED - Ready for TradingView!", "lime")
            else:
                log_status(f"⚠️ Step 3: Unexpected response: {response.status_code}", "#ff9800")
                log_status(f"   Response text: {response.text}", "#aaa")
        except Exception as e:
            log_status(f"❌ Step 3: Error - {str(e)}", "#f44336")
        
        log_status("")
        
        # Check 4: MT5 connection
        log_status("🔍 Step 4: Checking MT5 connection...", "#00bcd4")
        try:
            import MetaTrader5 as mt5
            if mt5.initialize():
                account_info = mt5.account_info()
                if account_info:
                    log_status(f"✅ Step 4: MT5 connected!", "#00e676")
                    log_status(f"   Account: {account_info.login}", "#aaa")
                    log_status(f"   Balance: ${account_info.balance:.2f}", "#aaa")
                else:
                    log_status("⚠️ Step 4: MT5 initialized but not logged in", "#ff9800")
                    log_status("   Fix: Click '⚡ MT5' button and login", "#ff9800")
            else:
                log_status("❌ Step 4: MT5 not initialized", "#f44336")
                log_status("   Fix: Install and open MT5 terminal", "#ff9800")
        except ImportError:
            log_status("❌ Step 4: MetaTrader5 library missing", "#f44336")
            log_status("   Fix: pip install MetaTrader5", "#ff9800")
        except Exception as e:
            log_status(f"⚠️ Step 4: {str(e)}", "#ff9800")
        
        log_status("")
        log_status("="*50, "#333")
        log_status("📊 DIAGNOSTICS COMPLETE", "#00bcd4")
        log_status("="*50, "#333")
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        btn_copy_url = QPushButton("📋 COPY WEBHOOK URL")
        btn_copy_url.setStyleSheet("background:#2962ff;color:white;padding:8px;font-weight:bold;")
        btn_copy_url.clicked.connect(lambda: (QApplication.clipboard().setText("http://localhost:5000/webhook"), 
                                              log_status("✅ URL copied to clipboard!", "#00e676")))
        btn_layout.addWidget(btn_copy_url)
        
        btn_open_tv = QPushButton("📺 OPEN TRADINGVIEW")
        btn_open_tv.setStyleSheet("background:#2962ff;color:white;padding:8px;")
        btn_open_tv.clicked.connect(lambda: os.system("start https://www.tradingview.com"))
        btn_layout.addWidget(btn_open_tv)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:8px;")
        btn_close.clicked.connect(diag_dlg.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        diag_dlg.exec_()
    
    def setup_remote_webhook(self):
        """Setup remote webhook using Ngrok for external access"""
        dialog = QDialog(self)
        dialog.setWindowTitle("🌍 Remote Webhook Setup - Ngrok")
        dialog.setStyleSheet(STYLESHEET)
        dialog.resize(700, 500)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header = QLabel("🌍 REMOTE WEBHOOK CONFIGURATION")
        header.setStyleSheet("color:#00e676;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Info text
        info = QLabel("Access your webhook from anywhere! Uses Ngrok for secure tunneling.")
        info.setStyleSheet("color:#aaa;padding:10px;")
        layout.addWidget(info)
        
        # Status display
        status_text = QTextEdit()
        status_text.setReadOnly(True)
        status_text.setStyleSheet("background:#000;color:#00e676;font-family:monospace;padding:10px;height:300px;")
        layout.addWidget(status_text)
        
        def log_status(msg, color="#00e676"):
            status_text.append(f"<span style='color:{color};'>{msg}</span>")
            QApplication.processEvents()
        
        # Step 1: Check Ngrok
        log_status("🔍 Step 1: Checking Ngrok...", "#00bcd4")
        try:
            import subprocess
            result = subprocess.run(["ngrok", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                log_status(f"✅ {result.stdout.strip()}", "#00e676")
            else:
                raise Exception("Ngrok not found")
        except Exception as e:
            log_status(f"❌ Ngrok not installed: {str(e)}", "#f44336")
            log_status("   Install from: https://ngrok.com/download", "#ff9800")
            
            # Auto download option
            btn_download = QPushButton("⬇️ DOWNLOAD NGROK NOW")
            btn_download.setStyleSheet("background:#ff9800;color:black;font-weight:bold;padding:10px;")
            btn_download.clicked.connect(lambda: os.system("start https://ngrok.com/download"))
            layout.insertWidget(layout.count()-1, btn_download)
            dialog.exec_()
            return
        
        log_status("")
        
        # Step 2: Start Ngrok tunnel
        log_status("🔍 Step 2: Starting Ngrok tunnel...", "#00bcd4")
        try:
            import subprocess
            import time
            
            # Kill existing ngrok process
            subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"], capture_output=True)
            time.sleep(1)
            
            # Start new ngrok process
            self.ngrok_process = subprocess.Popen(
                ["ngrok", "http", "5000", "--log=stdout"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            log_status("✅ Ngrok tunnel started", "#00e676")
            log_status("   Waiting for URL...", "#aaa")
            
            # Wait for URL to appear in logs
            ngrok_url = None
            timeout = time.time() + 15
            
            while time.time() < timeout:
                line = self.ngrok_process.stdout.readline()
                if line and "url=" in line.lower():
                    import re
                    urls = re.findall(r'(https?://[^\s]+)', line)
                    if urls and "ngrok" in urls[0]:
                        ngrok_url = urls[0].rstrip('/')
                        break
                QApplication.processEvents()
            
            if not ngrok_url:
                log_status("⚠️ Could not get Ngrok URL, trying API...", "#ff9800")
                time.sleep(2)
                try:
                    import requests
                    response = requests.get("http://localhost:4040/api/tunnels", timeout=5)
                    if response.status_code == 200:
                        tunnels = response.json().get('tunnels', [])
                        for tunnel in tunnels:
                            if tunnel.get('proto') == 'https':
                                ngrok_url = tunnel.get('public_url')
                                break
                except:
                    pass
            
            if ngrok_url:
                log_status("")
                log_status("="*50, "#333")
                log_status("🎉 REMOTE WEBHOOK READY!", "#00e676")
                log_status("="*50, "#333")
                log_status("")
                log_status("✅ Remote URL (for TradingView):", "#ffd700")
                log_status(f"   {ngrok_url}/webhook", "#ffeb3b")
                log_status("")
                log_status("🔐 Secret Key:", "#00bcd4")
                log_status(f"   {WEBHOOK_SECRET}", "#ffeb3b")
                log_status("")
                log_status("📋 Complete webhook URL:", "#00bcd4")
                log_status(f"   {ngrok_url}/webhook", "#aaa")
                log_status("")
                log_status("⚠️ Your local IP (for same network):", "#ff9800")
                try:
                    import socket
                    hostname = socket.gethostname()
                    local_ip = socket.gethostbyname(hostname)
                    log_status(f"   http://{local_ip}:5000/webhook", "#aaa")
                except:
                    pass
                
                self.log_msg(f"🌍 Remote webhook: {ngrok_url}/webhook", "lime")
                
                # Copy button
                btn_copy_remote = QPushButton("📋 COPY REMOTE URL")
                btn_copy_remote.setStyleSheet("background:#2962ff;color:white;padding:10px;font-weight:bold;")
                btn_copy_remote.clicked.connect(lambda: (
                    QApplication.clipboard().setText(f"{ngrok_url}/webhook"),
                    log_status("✅ Remote URL copied!", "#00e676")
                ))
                layout.insertWidget(layout.count()-1, btn_copy_remote)
                
            else:
                log_status("❌ Failed to get Ngrok URL", "#f44336")
                log_status("   Make sure webhook server is running", "#ff9800")
        
        except Exception as e:
            log_status(f"❌ Error: {str(e)}", "#f44336")
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        btn_test = QPushButton("🧪 TEST REMOTE")
        btn_test.setStyleSheet("background:#2962ff;color:white;padding:8px;")
        btn_test.clicked.connect(dialog.accept)
        btn_layout.addWidget(btn_test)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:8px;")
        btn_close.clicked.connect(dialog.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        dialog.exec_()
    
    def get_local_network_url(self):
        """Get local network URL for same-network access"""
        try:
            import socket
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            return f"http://{ip}:5000/webhook"
        except:
            return "http://localhost:5000/webhook"
    
    def open_amibroker_config(self):
        """AmiBroker File Signal Configuration"""
        d = QDialog(self)
        d.setWindowTitle("AmiBroker Integration Setup")
        d.setStyleSheet(STYLESHEET)
        d.resize(650, 550)
        
        layout = QVBoxLayout(d)
        
        # Info
        info = QLabel("📊 AmiBroker to MT5 Integration")
        info.setStyleSheet("color:#ff6f00;font-size:16px;font-weight:bold;")
        layout.addWidget(info)
        
        # Signal File Path
        g_path = QGroupBox("Signal File Path")
        l_path = QVBoxLayout(g_path)
        path_edit = QLineEdit(AMIBROKER_SIGNAL_FILE)
        path_edit.setReadOnly(True)
        path_edit.setStyleSheet("background:#111;color:#00e676;font-size:12px;")
        l_path.addWidget(path_edit)
        
        btn_copy_path = QPushButton("📋 COPY PATH")
        btn_copy_path.clicked.connect(lambda: QApplication.clipboard().setText(AMIBROKER_SIGNAL_FILE))
        l_path.addWidget(btn_copy_path)
        
        btn_open_folder = QPushButton("📂 OPEN FOLDER")
        btn_open_folder.clicked.connect(lambda: os.startfile(AMIBROKER_SIGNAL_DIR) if os.path.exists(AMIBROKER_SIGNAL_DIR) else None)
        l_path.addWidget(btn_open_folder)
        layout.addWidget(g_path)
        
        # Signal Format
        g_format = QGroupBox("Signal File Format (CSV)")
        l_format = QVBoxLayout(g_format)
        format_template = '''# AmiBroker Signal Format (One signal per line)
# SYMBOL,ACTION,LOT,RSI,MACD,EMA_FAST,EMA_SLOW

EURUSD,BUY,0.01,45.2,0.032,1.0523,1.0520
GBPUSD,SELL,0.02,65.8,-0.021,1.2645,1.2650
BTCUSD,CLOSE,0.01,50.0,0.0,0.0,0.0

# Actions: BUY, SELL, CLOSE
# Lot: Minimum 0.01 (broker dependent)'''
        
        format_edit = QTextEdit(format_template)
        format_edit.setStyleSheet("background:#111;color:#00bcd4;font-family:monospace;font-size:12px;")
        format_edit.setMaximumHeight(150)
        l_format.addWidget(format_edit)
        
        note = QLabel("📊 Bot watches this file | ✅ Orders execute directly on MT5!")
        note.setStyleSheet("color:#00e676;font-size:11px;font-weight:bold;")
        l_format.addWidget(note)
        
        btn_copy_format = QPushButton("📋 COPY FORMAT")
        btn_copy_format.clicked.connect(lambda: QApplication.clipboard().setText(format_template))
        l_format.addWidget(btn_copy_format)
        layout.addWidget(g_format)
        
        # AFL Script Info
        g_afl = QGroupBox("AmiBroker AFL Script")
        l_afl = QVBoxLayout(g_afl)
        afl_info = QLabel('''Use this AFL code to write signals to file:

fh = fopen("''' + AMIBROKER_SIGNAL_FILE.replace('\\', '\\\\') + '''", "w");
if (Buy) fputs(Name() + ",BUY,0.01," + RSI(14) + ",0,0,0\\n", fh);
if (Sell) fputs(Name() + ",SELL,0.01," + RSI(14) + ",0,0,0\\n", fh);
fclose(fh);''')
        afl_info.setStyleSheet("background:#111;color:#ffeb3b;font-family:monospace;font-size:11px;padding:10px;")
        afl_info.setWordWrap(True)
        l_afl.addWidget(afl_info)
        layout.addWidget(g_afl)
        
        # Controls
        btn_start = QPushButton("🚀 START AMIBROKER WATCHER")
        btn_start.setStyleSheet("background:#ff6f00;color:white;font-weight:bold;padding:10px;")
        btn_start.clicked.connect(lambda: self.bot.start_amibroker_watcher())
        layout.addWidget(btn_start)
        
        btn_stop = QPushButton("⏸️ STOP WATCHER")
        btn_stop.setStyleSheet("background:#b71c1c;color:white;font-weight:bold;padding:10px;")
        btn_stop.clicked.connect(lambda: self.bot.stop_amibroker_watcher())
        layout.addWidget(btn_stop)
        
        btn_guide = QPushButton("📖 VIEW FULL GUIDE")
        btn_guide.clicked.connect(lambda: os.startfile(os.path.join(BASE_DIR, "AMIBROKER_TO_MT5.md")) if os.path.exists(os.path.join(BASE_DIR, "AMIBROKER_TO_MT5.md")) else None)
        layout.addWidget(btn_guide)
        
        btn_close = QPushButton("CLOSE")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()

    def open_login(self):
        d = QDialog(self); d.setWindowTitle("MT5 Login"); d.setStyleSheet(STYLESHEET); f = QFormLayout(d)
        u = QLineEdit(); p = QLineEdit(); p.setEchoMode(QLineEdit.Password); s = QLineEdit()
        sv = load_settings(); u.setText(sv.get("login","")); p.setText(sv.get("password","")); s.setText(sv.get("server",""))
        f.addRow("Login:", u); f.addRow("Password:", p); f.addRow("Server:", s)
        def conn(): save_settings(u.text(), p.text(), s.text()); self.bot.connect_mt5(u.text(), p.text(), s.text()); d.accept()
        btn = QPushButton("CONNECT"); btn.clicked.connect(conn); f.addRow(btn); d.exec_()
    
    def logout(self): self.bot.logout(); self.b_run.setChecked(False); self.b_run.setText("START")
    
    def change_user_mode(self, mode):
        """Change user mode between CLIENT and ADMIN"""
        if "ADMIN" in mode:
            self.bot.loader.user_mode = "ADMIN"
            self.log_msg("🔐 Mode: ADMIN - Full control enabled", "lime")
        else:
            self.bot.loader.user_mode = "CLIENT"
            self.log_msg("👥 Mode: CLIENT - Password unlock only", "cyan")
    
    def open_unlock_interface(self):
        """Unified unlock interface for Admin/Client"""
        selected_strategy = self.c_strat.currentText()
        if not selected_strategy:
            QMessageBox.warning(self, "No Strategy", "Please select a strategy from dropdown first!")
            return
        
        mode = self.bot.loader.user_mode
        
        if mode == "ADMIN":
            self.open_admin_unlock_dialog(selected_strategy)
        else:
            self.open_client_unlock_dialog(selected_strategy)
    
    def open_client_unlock_dialog(self, strategy_name):
        """Client unlock dialog - Password only"""
        d = QDialog(self)
        d.setWindowTitle(f"🔓 Unlock Strategy - {strategy_name}")
        d.setStyleSheet(STYLESHEET)
        d.resize(500, 300)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel(f"🔓 CLIENT UNLOCK: {strategy_name}")
        header.setStyleSheet("color:#00e676;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Check if already unlocked
        if self.bot.loader.is_strategy_unlocked(strategy_name):
            status = QLabel(f"✅ Strategy already unlocked!")
            status.setStyleSheet("color:#00e676;font-size:14px;padding:10px;background:#1a1a1a;border-radius:5px;")
            layout.addWidget(status)
        else:
            # Check if locked by admin
            if hasattr(self.bot.loader, 'strategy_protection'):
                is_locked = self.bot.loader.strategy_protection.is_strategy_locked(strategy_name)
                if is_locked:
                    locked_msg = QLabel("🔒 This strategy is LOCKED by Admin\n\nContact administrator to unlock.")
                    locked_msg.setStyleSheet("color:#f44336;font-size:13px;padding:15px;background:#1a1a1a;border-radius:5px;font-weight:bold;")
                    layout.addWidget(locked_msg)
                    btn_close = QPushButton("CLOSE")
                    btn_close.setStyleSheet("background:#666;color:white;padding:10px;")
                    btn_close.clicked.connect(d.reject)
                    layout.addWidget(btn_close)
                    d.exec_()
                    return
            
            # Password input
            pass_label = QLabel("Enter Strategy Password:")
            pass_label.setStyleSheet("color:white;font-size:12px;")
            layout.addWidget(pass_label)
            
            pass_input = QLineEdit()
            pass_input.setEchoMode(QLineEdit.Password)
            pass_input.setPlaceholderText("Default: RUDRA24")
            pass_input.setStyleSheet("background:#111;color:white;padding:10px;font-size:13px;")
            layout.addWidget(pass_input)
            
            status_label = QLabel("")
            status_label.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
            layout.addWidget(status_label)
            
            def unlock_strategy():
                password = pass_input.text().strip()
                if not password:
                    status_label.setText("⚠️ Please enter password")
                    status_label.setStyleSheet("color:#ff9800;")
                    return
                
                success, msg = self.bot.loader.unlock_strategy(strategy_name, password)
                if success:
                    status_label.setText(f"✅ {msg}")
                    status_label.setStyleSheet("color:#00e676;font-weight:bold;")
                    self.log_msg(f"🔓 Client unlocked: {strategy_name}", "lime")
                    QTimer.singleShot(1500, d.accept)
                else:
                    status_label.setText(f"❌ {msg}")
                    status_label.setStyleSheet("color:#f44336;font-weight:bold;")
            
            btn_unlock = QPushButton("🔓 UNLOCK STRATEGY")
            btn_unlock.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:12px;")
            btn_unlock.clicked.connect(unlock_strategy)
            layout.addWidget(btn_unlock)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_close.clicked.connect(d.reject)
        layout.addWidget(btn_close)
        
        d.exec_()
    
    def open_admin_unlock_dialog(self, strategy_name):
        """Admin unlock dialog - Full control"""
        d = QDialog(self)
        d.setWindowTitle(f"🔐 Admin Control - {strategy_name}")
        d.setStyleSheet(STYLESHEET)
        d.resize(550, 450)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel(f"🔐 ADMIN CONTROL: {strategy_name}")
        header.setStyleSheet("color:#e91e63;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Admin password
        admin_group = QGroupBox("Admin Authentication")
        admin_layout = QFormLayout(admin_group)
        
        admin_pass_input = QLineEdit()
        admin_pass_input.setEchoMode(QLineEdit.Password)
        admin_pass_input.setPlaceholderText("RUDRA@2025#MASTER")
        admin_pass_input.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        admin_layout.addRow("Admin Password:", admin_pass_input)
        layout.addWidget(admin_group)
        
        # Status display
        status_box = QLabel("")
        status_box.setStyleSheet("color:#00bcd4;font-size:13px;padding:10px;background:#1a1a1a;border-radius:3px;")
        layout.addWidget(status_box)
        
        def update_status():
            if hasattr(self.bot.loader, 'strategy_protection'):
                is_locked = self.bot.loader.strategy_protection.is_strategy_locked(strategy_name)
                is_unlocked = self.bot.loader.is_strategy_unlocked(strategy_name)
                
                status_text = f"Strategy: {strategy_name}\n"
                status_text += f"Lock Status: {'🔒 LOCKED' if is_locked else '🔓 UNLOCKED'}\n"
                status_text += f"User Access: {'❌ Blocked' if is_locked else '✅ Allowed'}\n"
                status_text += f"Current State: {'✅ Active' if is_unlocked else '⚠️ Inactive'}"
                
                status_box.setText(status_text)
                if is_locked:
                    status_box.setStyleSheet("color:#f44336;font-size:12px;padding:10px;background:#1a1a1a;border-radius:3px;font-weight:bold;")
                else:
                    status_box.setStyleSheet("color:#00e676;font-size:12px;padding:10px;background:#1a1a1a;border-radius:3px;font-weight:bold;")
        
        update_status()
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        btn_lock = QPushButton("🔒 LOCK")
        btn_lock.setStyleSheet("background:#f44336;color:white;font-weight:bold;padding:12px;")
        btn_lock.setToolTip("Lock strategy - Block all client access")
        btn_layout.addWidget(btn_lock)
        
        btn_unlock = QPushButton("🔓 UNLOCK")
        btn_unlock.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:12px;")
        btn_unlock.setToolTip("Unlock strategy - Allow client password access")
        btn_layout.addWidget(btn_unlock)
        
        layout.addLayout(btn_layout)
        
        action_status = QLabel("")
        action_status.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
        layout.addWidget(action_status)
        
        # Lock function
        def lock_strategy():
            admin_pass = admin_pass_input.text().strip()
            if admin_pass != "RUDRA@2025#MASTER":
                action_status.setText("❌ Invalid admin password!")
                action_status.setStyleSheet("color:#f44336;font-weight:bold;")
                return
            
            if hasattr(self.bot.loader, 'strategy_protection'):
                success, msg = self.bot.loader.strategy_protection.lock_strategy(strategy_name, admin_pass)
                if success:
                    action_status.setText(msg)
                    action_status.setStyleSheet("color:#00e676;font-weight:bold;")
                    self.log_msg(f"🔒 Admin locked: {strategy_name}", "orange")
                    update_status()
                else:
                    action_status.setText(msg)
                    action_status.setStyleSheet("color:#f44336;font-weight:bold;")
        
        # Unlock function
        def unlock_strategy():
            admin_pass = admin_pass_input.text().strip()
            if admin_pass != "RUDRA@2025#MASTER":
                action_status.setText("❌ Invalid admin password!")
                action_status.setStyleSheet("color:#f44336;font-weight:bold;")
                return
            
            if hasattr(self.bot.loader, 'strategy_protection'):
                success, msg = self.bot.loader.strategy_protection.unlock_strategy_admin(strategy_name, admin_pass)
                if success:
                    action_status.setText(msg)
                    action_status.setStyleSheet("color:#00e676;font-weight:bold;")
                    self.log_msg(f"🔓 Admin unlocked: {strategy_name}", "lime")
                    update_status()
                else:
                    action_status.setText(msg)
                    action_status.setStyleSheet("color:#f44336;font-weight:bold;")
        
        btn_lock.clicked.connect(lock_strategy)
        btn_unlock.clicked.connect(unlock_strategy)
        
        # Info
        info = QLabel("<b>Admin Actions:</b><br>• LOCK: Prevent all client access<br>• UNLOCK: Allow clients to unlock with password")
        info.setStyleSheet("color:#aaa;font-size:11px;padding:10px;background:#0a0a0a;border-radius:5px;")
        layout.addWidget(info)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()
    
    def verify_admin_access(self):
        """Verify admin password before opening admin panel"""
        d = QDialog(self)
        d.setWindowTitle("🔒 Admin Access")
        d.setStyleSheet(STYLESHEET)
        d.resize(450, 250)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel("🔒 ADMIN ACCESS REQUIRED")
        header.setStyleSheet("color:#e91e63;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Info
        info = QLabel("⚠️ This area is restricted to administrators only.\nPlease enter the admin password to continue.")
        info.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;background:#1a1a1a;border-radius:5px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Password input
        pass_label = QLabel("Admin Password:")
        pass_label.setStyleSheet("color:white;font-size:12px;margin-top:10px;")
        layout.addWidget(pass_label)
        
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.Password)
        pass_input.setPlaceholderText("Enter admin password")
        pass_input.setStyleSheet("background:#111;color:white;padding:10px;font-size:13px;border:1px solid #444;")
        layout.addWidget(pass_input)
        
        status_label = QLabel("")
        status_label.setStyleSheet("color:#ff9800;font-size:11px;padding:5px;")
        layout.addWidget(status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        def verify_and_open():
            password = pass_input.text().strip()
            if not password:
                status_label.setText("⚠️ Please enter password")
                status_label.setStyleSheet("color:#ff9800;")
                return
            
            if password == "RUDRA@2025#MASTER":
                status_label.setText("✅ Access granted!")
                status_label.setStyleSheet("color:#00e676;font-weight:bold;")
                self.log_msg("🔓 Admin panel accessed", "lime")
                d.accept()
                QTimer.singleShot(100, self.open_admin_panel)
            else:
                status_label.setText("❌ Invalid password! Access denied.")
                status_label.setStyleSheet("color:#f44336;font-weight:bold;")
                self.log_msg("❌ Admin access denied - Invalid password", "red")
        
        btn_verify = QPushButton("🔓 VERIFY & ENTER")
        btn_verify.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:10px;")
        btn_verify.clicked.connect(verify_and_open)
        btn_layout.addWidget(btn_verify)
        
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_cancel.clicked.connect(d.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Forgot password link
        forgot_link = QLabel("<a href='#' style='color:#00bcd4;'>🔑 Forgot Password? Click here to recover</a>")
        forgot_link.setStyleSheet("padding:10px;")
        forgot_link.linkActivated.connect(lambda: self.recover_admin_password(d))
        layout.addWidget(forgot_link)
        
        # Enter key shortcut
        pass_input.returnPressed.connect(verify_and_open)
        
        d.exec_()
    
    def recover_admin_password(self, parent_dialog=None):
        """Admin password recovery system"""
        d = QDialog(self)
        d.setWindowTitle("🔑 Password Recovery")
        d.setStyleSheet(STYLESHEET)
        d.resize(600, 500)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel("🔑 ADMIN PASSWORD RECOVERY")
        header.setStyleSheet("color:#00bcd4;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Recovery options tabs
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; background: #0a0a0a; }
            QTabBar::tab { background: #1a1a1a; color: white; padding: 8px 15px; border: 1px solid #444; }
            QTabBar::tab:selected { background: #00bcd4; color: white; font-weight: bold; }
        """)
        
        # TAB 1: Security Question
        tab_security = QWidget()
        sec_layout = QVBoxLayout(tab_security)
        
        sec_info = QLabel("Answer the security question to recover password:")
        sec_info.setStyleSheet("color:#00e676;font-size:12px;padding:10px;")
        sec_layout.addWidget(sec_info)
        
        sec_question = QLabel("🔐 Security Question:\nWhat is your bot's license HWID?")
        sec_question.setStyleSheet("color:white;font-size:13px;padding:10px;background:#1a1a1a;border-radius:5px;font-weight:bold;")
        sec_layout.addWidget(sec_question)
        
        sec_answer = QLineEdit()
        sec_answer.setPlaceholderText("Enter HWID (e.g.,73EF-5407-DF8C-AAA3)")
        sec_answer.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        sec_layout.addWidget(sec_answer)
    
        sec_hint = QLabel("💡 Hint: Check machine.lic file or License button")
        sec_hint.setStyleSheet("color:#ffeb3b;font-size:11px;padding:5px;")
        sec_layout.addWidget(sec_hint)
        
        sec_status = QLabel("")
        sec_status.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
        sec_layout.addWidget(sec_status)
        
        def verify_hwid():
            answer = sec_answer.text().strip()
            if not answer:
                sec_status.setText("⚠️ Please enter HWID")
                sec_status.setStyleSheet("color:#ff9800;")
                return
            
            # Get actual HWID
            import subprocess
            try:
                result = subprocess.run(['wmic', 'csproduct', 'get', 'uuid'], 
                                      capture_output=True, text=True, timeout=5)
                actual_hwid = result.stdout.strip().split('\n')[1].strip()
                actual_hwid_formatted = '-'.join([actual_hwid[i:i+4] for i in range(0, min(16, len(actual_hwid)), 4)]).upper()
            except:
                actual_hwid_formatted = "0151-3B9F-667C-2446"  # Fallback
            
            if answer.upper() == actual_hwid_formatted or answer.upper().replace('-','') == actual_hwid_formatted.replace('-',''):
                sec_status.setText(f"✅ Verified! Admin Password: RUDRA@2025#MASTER")
                sec_status.setStyleSheet("color:#00e676;font-weight:bold;font-size:14px;")
                self.log_msg("🔑 Password recovered via HWID", "lime")
            else:
                sec_status.setText(f"❌ Incorrect HWID! Try again.")
                sec_status.setStyleSheet("color:#f44336;font-weight:bold;")
        
        btn_verify_hwid = QPushButton("🔍 VERIFY & SHOW PASSWORD")
        btn_verify_hwid.setStyleSheet("background:#00e676;color:black;font-weight:bold;padding:10px;")
        btn_verify_hwid.clicked.connect(verify_hwid)
        sec_layout.addWidget(btn_verify_hwid)
        sec_layout.addStretch()
        
        tabs.addTab(tab_security, "🔐 Security Question")
        
        # TAB 2: Emergency Recovery
        tab_emergency = QWidget()
        emer_layout = QVBoxLayout(tab_emergency)
        
        emer_info = QLabel("⚠️ Emergency Recovery Method")
        emer_info.setStyleSheet("color:#ff9800;font-size:13px;padding:10px;font-weight:bold;")
        emer_layout.addWidget(emer_info)
        
        emer_steps = QLabel("""
<b style='color:#00bcd4;'>📋 Manual Recovery Steps:</b><br><br>
<b>Method 1: File Recovery</b><br>
1. Open folder: <span style='color:#ffeb3b;'>TradingBot</span><br>
2. Find file: <span style='color:#00e676;'>admin_permissions.py</span><br>
3. Open with notepad<br>
4. Line 16: See password = <span style='color:#f44336;'>"RUDRA@2025#MASTER"</span><br><br>

<b>Method 2: Reset Password</b><br>
1. Close this application<br>
2. Delete file: <span style='color:#f44336;'>admin_permissions.json</span><br>
3. Restart bot - Password resets to default<br><br>

<b>Method 3: Contact Developer</b><br>
• Email: support@rudrabot.com<br>
• Provide license HWID for verification
        """)
        emer_steps.setWordWrap(True)
        emer_steps.setStyleSheet("color:#aaa;font-size:11px;padding:10px;background:#0a0a0a;border-radius:5px;line-height:1.5;")
        emer_layout.addWidget(emer_steps)
        
        def open_admin_file():
            try:
                file_path = "admin_permissions.py"
                if os.path.exists(file_path):
                    os.startfile(file_path)
                    self.log_msg("📂 Opened admin_permissions.py", "cyan")
                else:
                    QMessageBox.warning(d, "File Not Found", "admin_permissions.py not found!")
            except Exception as e:
                QMessageBox.warning(d, "Error", f"Could not open file: {e}")
        
        btn_open_file = QPushButton("📂 OPEN admin_permissions.py")
        btn_open_file.setStyleSheet("background:#2196f3;color:white;font-weight:bold;padding:10px;")
        btn_open_file.clicked.connect(open_admin_file)
        emer_layout.addWidget(btn_open_file)
        emer_layout.addStretch()
        
        tabs.addTab(tab_emergency, "🆘 Emergency Recovery")
        
        # TAB 3: Show Default Password
        tab_default = QWidget()
        def_layout = QVBoxLayout(tab_default)
        
        def_info = QLabel("🔑 Default Admin Password")
        def_info.setStyleSheet("color:#00e676;font-size:13px;padding:10px;font-weight:bold;")
        def_layout.addWidget(def_info)
        
        def_pass_box = QLabel("RUDRA@2025#MASTER")
        def_pass_box.setStyleSheet("color:#ffeb3b;font-size:18px;padding:20px;background:#1a1a1a;border:2px solid #00e676;border-radius:5px;font-weight:bold;text-align:center;")
        def_pass_box.setAlignment(Qt.AlignCenter)
        def_layout.addWidget(def_pass_box)
        
        def copy_password():
            QApplication.clipboard().setText("RUDRA@2025#MASTER")
            copy_status.setText("✅ Password copied to clipboard!")
            copy_status.setStyleSheet("color:#00e676;font-weight:bold;")
            self.log_msg("📋 Admin password copied", "cyan")
        
        btn_copy = QPushButton("📋 COPY PASSWORD")
        btn_copy.setStyleSheet("background:#9c27b0;color:white;font-weight:bold;padding:12px;")
        btn_copy.clicked.connect(copy_password)
        def_layout.addWidget(btn_copy)
        
        copy_status = QLabel("")
        copy_status.setStyleSheet("color:#00e676;font-size:12px;padding:10px;")
        def_layout.addWidget(copy_status)
        
        def_note = QLabel("""
<b style='color:#ff9800;'>⚠️ Security Note:</b><br>
• This is the default master password<br>
• Anyone with file access can see this<br>
• Keep your bot files secure<br>
• Consider changing password after recovery
        """)
        def_note.setWordWrap(True)
        def_note.setStyleSheet("color:#aaa;font-size:11px;padding:10px;background:#0a0a0a;border-radius:5px;")
        def_layout.addWidget(def_note)
        def_layout.addStretch()
        
        tabs.addTab(tab_default, "🔑 Default Password")
        
        layout.addWidget(tabs)
        
        # Close button
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;font-weight:bold;")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()
        
        # Close parent dialog if password recovered
        if parent_dialog and "✅ Verified" in sec_status.text():
            QTimer.singleShot(100, parent_dialog.reject)
    
    def open_admin_panel(self):
        """Admin panel for password management and strategy lock/unlock"""
        d = QDialog(self)
        d.setWindowTitle("🔐 Admin Control Panel")
        d.setStyleSheet(STYLESHEET)
        d.resize(700, 600)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel("🔐 ADMIN CONTROL PANEL")
        header.setStyleSheet("color:#e91e63;font-size:18px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Admin password verification
        admin_group = QGroupBox("Admin Authentication")
        admin_layout = QFormLayout(admin_group)
        
        admin_pass_input = QLineEdit()
        admin_pass_input.setEchoMode(QLineEdit.Password)
        admin_pass_input.setPlaceholderText("Enter admin password (RUDRA@2025#MASTER)")
        admin_pass_input.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        admin_layout.addRow("Admin Password:", admin_pass_input)
        layout.addWidget(admin_group)
        
        # Tab widget for different admin functions
        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; background: #0a0a0a; }
            QTabBar::tab { background: #1a1a1a; color: white; padding: 10px 20px; border: 1px solid #444; }
            QTabBar::tab:selected { background: #e91e63; color: white; font-weight: bold; }
        """)
        
        # TAB 1: Set Custom Password
        tab_password = QWidget()
        pass_layout = QVBoxLayout(tab_password)
        
        current_info = QLabel("📌 Current Default Password: RUDRA24")
        current_info.setStyleSheet("color:#00e676;font-size:12px;padding:5px;background:#1a1a1a;border-radius:3px;")
        pass_layout.addWidget(current_info)
        
        new_pass_input = QLineEdit()
        new_pass_input.setPlaceholderText("Enter new password (min 6 characters)")
        new_pass_input.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        pass_layout.addWidget(QLabel("New Password:"))
        pass_layout.addWidget(new_pass_input)
        
        confirm_pass_input = QLineEdit()
        confirm_pass_input.setPlaceholderText("Confirm new password")
        confirm_pass_input.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        pass_layout.addWidget(QLabel("Confirm Password:"))
        pass_layout.addWidget(confirm_pass_input)
        
        pass_status = QLabel("")
        pass_status.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
        pass_layout.addWidget(pass_status)
        
        btn_save_pass = QPushButton("💾 SET NEW PASSWORD")
        btn_save_pass.setStyleSheet("background:#00c853;color:white;font-weight:bold;padding:10px;")
        pass_layout.addWidget(btn_save_pass)
        pass_layout.addStretch()
        
        tabs.addTab(tab_password, "🔑 Set Password")
        
        # TAB 2: Lock/Unlock Strategies
        tab_lockmanage = QWidget()
        lock_layout = QVBoxLayout(tab_lockmanage)
        
        strategy_label = QLabel("Select Strategy:")
        lock_layout.addWidget(strategy_label)
        
        strategy_combo = QComboBox()
        strategy_combo.addItems(self.bot.available_strats)
        strategy_combo.setStyleSheet("background:#111;color:white;padding:8px;font-size:13px;")
        lock_layout.addWidget(strategy_combo)
        
        lock_status = QLabel("")
        lock_status.setStyleSheet("color:#00bcd4;font-size:13px;padding:10px;background:#1a1a1a;border-radius:3px;")
        lock_layout.addWidget(lock_status)
        
        def update_lock_status():
            strat = strategy_combo.currentText()
            if strat and hasattr(self.bot.loader, 'strategy_protection'):
                is_locked = self.bot.loader.strategy_protection.is_strategy_locked(strat)
                if is_locked:
                    lock_status.setText(f"🔒 Status: LOCKED - Clients cannot unlock")
                    lock_status.setStyleSheet("color:#f44336;font-size:13px;padding:10px;background:#1a1a1a;border-radius:3px;font-weight:bold;")
                else:
                    lock_status.setText(f"🔓 Status: UNLOCKED - Clients can unlock with password")
                    lock_status.setStyleSheet("color:#00e676;font-size:13px;padding:10px;background:#1a1a1a;border-radius:3px;font-weight:bold;")
        
        strategy_combo.currentTextChanged.connect(update_lock_status)
        update_lock_status()
        
        btn_layout = QHBoxLayout()
        btn_lock = QPushButton("🔒 LOCK STRATEGY")
        btn_lock.setStyleSheet("background:#f44336;color:white;font-weight:bold;padding:12px;")
        btn_layout.addWidget(btn_lock)
        
        btn_unlock = QPushButton("🔓 UNLOCK STRATEGY")
        btn_unlock.setStyleSheet("background:#00e676;color:#000;font-weight:bold;padding:12px;")
        btn_layout.addWidget(btn_unlock)
        
        lock_layout.addLayout(btn_layout)
        
        lock_msg = QLabel("")
        lock_msg.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
        lock_layout.addWidget(lock_msg)
        
        info_text = QLabel("""
<b style='color:#00bcd4;'>📋 Lock/Unlock Info:</b><br>
• <b>LOCK:</b> Prevents clients from unlocking strategy (even with password)<br>
• <b>UNLOCK:</b> Allows clients to unlock using strategy password<br>
• Locked strategies show 🔒 in status and cannot be used by clients<br>
        """)
        info_text.setWordWrap(True)
        info_text.setStyleSheet("color:#aaa;font-size:11px;padding:10px;background:#0a0a0a;border-radius:5px;")
        lock_layout.addWidget(info_text)
        lock_layout.addStretch()
        
        tabs.addTab(tab_lockmanage, "🔐 Lock/Unlock")
        
        layout.addWidget(tabs)
        
        # Main status
        main_status = QLabel("")
        main_status.setStyleSheet("color:#ff9800;font-size:12px;padding:10px;")
        layout.addWidget(main_status)
        
        # Save Password Function
        def save_password():
            admin_pass = admin_pass_input.text().strip()
            if admin_pass != "RUDRA@2025#MASTER":
                main_status.setText("❌ Invalid admin password!")
                main_status.setStyleSheet("color:#f44336;font-weight:bold;")
                return
            
            new_pass = new_pass_input.text().strip()
            confirm_pass = confirm_pass_input.text().strip()
            
            if not new_pass or not confirm_pass:
                pass_status.setText("⚠️ Please fill both password fields")
                pass_status.setStyleSheet("color:#ff9800;")
                return
            
            if len(new_pass) < 6:
                pass_status.setText("⚠️ Password must be at least 6 characters")
                pass_status.setStyleSheet("color:#ff9800;")
                return
            
            if new_pass != confirm_pass:
                pass_status.setText("❌ Passwords do not match!")
                pass_status.setStyleSheet("color:#f44336;")
                return
            
            try:
                import json
                password_file = "strategy_password.json"
                password_data = {
                    "password": new_pass,
                    "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "created_by": "ADMIN"
                }
                
                with open(password_file, 'w') as f:
                    json.dump(password_data, f, indent=4)
                
                if hasattr(self.bot.loader, 'strategy_protection'):
                    for strategy in self.bot.available_strats:
                        self.bot.loader.strategy_protection.set_strategy_password(strategy, new_pass)
                
                pass_status.setText(f"✅ Password set successfully: {new_pass}")
                pass_status.setStyleSheet("color:#00e676;font-weight:bold;")
                main_status.setText("✅ Strategy password updated for all strategies!")
                main_status.setStyleSheet("color:#00e676;font-weight:bold;")
                self.log_msg(f"🔐 Admin: Custom strategy password set", "lime")
                
            except Exception as e:
                pass_status.setText(f"❌ Error: {str(e)}")
                pass_status.setStyleSheet("color:#f44336;")
        
        btn_save_pass.clicked.connect(save_password)
        
        # Lock Strategy Function
        def lock_strategy():
            admin_pass = admin_pass_input.text().strip()
            if admin_pass != "RUDRA@2025#MASTER":
                lock_msg.setText("❌ Invalid admin password!")
                lock_msg.setStyleSheet("color:#f44336;font-weight:bold;")
                return
            
            strat = strategy_combo.currentText()
            if not strat:
                lock_msg.setText("⚠️ Select a strategy first")
                lock_msg.setStyleSheet("color:#ff9800;")
                return
            
            if hasattr(self.bot.loader, 'strategy_protection'):
                success, msg = self.bot.loader.strategy_protection.lock_strategy(strat, admin_pass)
                if success:
                    lock_msg.setText(msg)
                    lock_msg.setStyleSheet("color:#00e676;font-weight:bold;")
                    main_status.setText(f"🔒 Strategy '{strat}' locked successfully")
                    main_status.setStyleSheet("color:#00e676;font-weight:bold;")
                    self.log_msg(f"🔒 Admin locked strategy: {strat}", "orange")
                    update_lock_status()
                else:
                    lock_msg.setText(msg)
                    lock_msg.setStyleSheet("color:#f44336;font-weight:bold;")
        
        btn_lock.clicked.connect(lock_strategy)
        
        # Unlock Strategy Function
        def unlock_strategy():
            admin_pass = admin_pass_input.text().strip()
            if admin_pass != "RUDRA@2025#MASTER":
                lock_msg.setText("❌ Invalid admin password!")
                lock_msg.setStyleSheet("color:#f44336;font-weight:bold;")
                return
            
            strat = strategy_combo.currentText()
            if not strat:
                lock_msg.setText("⚠️ Select a strategy first")
                lock_msg.setStyleSheet("color:#ff9800;")
                return
            
            if hasattr(self.bot.loader, 'strategy_protection'):
                success, msg = self.bot.loader.strategy_protection.unlock_strategy_admin(strat, admin_pass)
                if success:
                    lock_msg.setText(msg)
                    lock_msg.setStyleSheet("color:#00e676;font-weight:bold;")
                    main_status.setText(f"🔓 Strategy '{strat}' unlocked successfully")
                    main_status.setStyleSheet("color:#00e676;font-weight:bold;")
                    self.log_msg(f"🔓 Admin unlocked strategy: {strat}", "lime")
                    update_lock_status()
                else:
                    lock_msg.setText(msg)
                    lock_msg.setStyleSheet("color:#f44336;font-weight:bold;")
        
        btn_unlock.clicked.connect(unlock_strategy)
        
        # Close button
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;font-weight:bold;")
        btn_close.clicked.connect(d.accept)
        layout.addWidget(btn_close)
        
        d.exec_()
    
    def show_password_help(self):
        """Show strategy password help dialog"""
        d = QDialog(self)
        d.setWindowTitle("🔓 Strategy Password Help")
        d.setStyleSheet(STYLESHEET)
        d.resize(500, 350)
        
        layout = QVBoxLayout(d)
        
        # Header
        header = QLabel("🔒 STRATEGY PASSWORD INFORMATION")
        header.setStyleSheet("color:#9c27b0;font-size:16px;font-weight:bold;padding:10px;")
        layout.addWidget(header)
        
        # Password info
        info_text = """
<div style='color:#e0e0e0;font-size:13px;line-height:1.8;'>
<p><b style='color:#00e676;'>✅ Default Strategy Password:</b></p>
<p style='background:#1a1a1a;padding:15px;border-left:4px solid #9c27b0;'>
<span style='color:#ffeb3b;font-size:18px;font-weight:bold;'>RUDRA24</span>
</p>

<p><b style='color:#ff9800;'>📌 How to Use:</b></p>
<ul style='color:#aaa;'>
<li>Select a locked strategy from dropdown</li>
<li>A password dialog will appear</li>
<li>Enter: <b style='color:#ffeb3b;'>RUDRA24</b></li>
<li>Strategy will unlock permanently</li>
</ul>

<p><b style='color:#2196f3;'>ℹ️ Protected Strategies:</b></p>
<p style='color:#888;'>Strategies with 🔒 icon require password</p>
</div>
        """
        
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("background:#0a0a0a;padding:15px;border-radius:5px;")
        layout.addWidget(info_label)
        
        # Copy button
        btn_layout = QHBoxLayout()
        
        btn_copy = QPushButton("📋 COPY PASSWORD")
        btn_copy.setStyleSheet("background:#9c27b0;color:white;font-weight:bold;padding:10px;")
        btn_copy.clicked.connect(lambda: (QApplication.clipboard().setText("RUDRA24"), 
                                          self.log_msg("✅ Password copied to clipboard: RUDRA24", "lime")))
        btn_layout.addWidget(btn_copy)
        
        btn_close = QPushButton("CLOSE")
        btn_close.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_close.clicked.connect(d.accept)
        btn_layout.addWidget(btn_close)
        
        layout.addLayout(btn_layout)
        
        d.exec_()
    
    def change_strategy(self, text): 
        """Change global strategy with password check"""
        # Check if strategy is locked
        if not self.bot.loader.is_strategy_unlocked(text):
            # Show password dialog for global strategy
            self.unlock_global_strategy_dialog(text)
            # Revert dropdown to previous strategy
            self.c_strat.blockSignals(True)
            self.c_strat.setCurrentText(self.bot.active_strategy)
            self.c_strat.blockSignals(False)
            return
        
        # Strategy is unlocked, apply it
        self.bot.active_strategy = text
        self.lbl_strat.setText(f"Strategy: {text}")
        self.log_msg(f"Switched to: {text}", "cyan")
    
    def unlock_global_strategy_dialog(self, strategy):
        """Show dialog to unlock global strategy"""
        d = QDialog(self)
        d.setWindowTitle(f"🔒 Unlock Strategy: {strategy}")
        d.setStyleSheet(STYLESHEET)
        d.resize(450, 250)
        
        layout = QVBoxLayout(d)
        
        info = QLabel(f"🔒 '{strategy}' requires password")
        info.setStyleSheet("color:#ff9800;font-size:14px;font-weight:bold;")
        layout.addWidget(info)
        
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.Password)
        pass_input.setPlaceholderText("Enter password: RUDRA24")
        pass_input.setStyleSheet("background:#111;color:white;font-size:14px;padding:10px;border:2px solid #9c27b0;")
        layout.addWidget(pass_input)
        
        status_label = QLabel("")
        status_label.setStyleSheet("color:#ff9800;font-size:11px;padding:5px;")
        layout.addWidget(status_label)
        
        def try_unlock():
            password = pass_input.text().strip()
            if not password:
                status_label.setText("⚠️ Please enter password")
                return
            
            success, message = self.bot.loader.unlock_strategy(strategy, password)
            
            if success:
                status_label.setText(f"✅ {message}")
                status_label.setStyleSheet("color:#00e676;")
                self.bot.active_strategy = strategy
                self.lbl_strat.setText(f"Strategy: {strategy}")
                self.c_strat.setCurrentText(strategy)
                self.log_msg(f"🔓 Unlocked & Switched to: {strategy}", "lime")
                QTimer.singleShot(800, d.accept)
            else:
                status_label.setText(f"❌ {message}")
                status_label.setStyleSheet("color:#f44336;")
                pass_input.clear()
        
        btn_layout = QHBoxLayout()
        btn_unlock = QPushButton("🔓 UNLOCK")
        btn_unlock.setStyleSheet("background:#00c853;color:white;font-weight:bold;padding:8px;")
        btn_unlock.clicked.connect(try_unlock)
        pass_input.returnPressed.connect(try_unlock)
        btn_layout.addWidget(btn_unlock)
        
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setStyleSheet("background:#666;color:white;padding:8px;")
        btn_cancel.clicked.connect(d.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        pass_input.setFocus()
        d.exec_()
    
    def change_symbol_strategy(self, symbol, strategy):
        """Change strategy for a specific symbol"""
        # Check if strategy is locked
        if not self.bot.loader.is_strategy_unlocked(strategy):
            # Show password dialog
            self.unlock_strategy_dialog(symbol, strategy)
            return
        
        if symbol in self.bot.symbols:
            self.bot.symbols[symbol]['strategy'] = strategy
            self.log_msg(f"📊 {symbol} → Strategy: {strategy}", "cyan")
    
    def unlock_strategy_dialog(self, symbol, strategy):
        """Show dialog to unlock strategy with password"""
        d = QDialog(self)
        d.setWindowTitle(f"🔒 Unlock Strategy: {strategy}")
        d.setStyleSheet(STYLESHEET)
        d.resize(500, 300)
        
        layout = QVBoxLayout(d)
        
        # Info
        info = QLabel(f"🔒 Strategy '{strategy}' is password protected")
        info.setStyleSheet("color:#ff9800;font-size:14px;font-weight:bold;")
        layout.addWidget(info)
        
        desc = QLabel("This strategy requires admin permission.\nEnter the password to unlock:")
        desc.setStyleSheet("color:#aaa;font-size:12px;padding:10px;")
        layout.addWidget(desc)
        
        # Password input
        g_pass = QGroupBox("Password")
        l_pass = QFormLayout(g_pass)
        
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.Password)
        pass_input.setStyleSheet("background:#111;color:white;font-size:14px;padding:8px;")
        l_pass.addRow("Enter Password:", pass_input)
        layout.addWidget(g_pass)
        
        # Status label
        status_label = QLabel("")
        status_label.setStyleSheet("color:#ff9800;font-size:12px;padding:5px;")
        layout.addWidget(status_label)
        
        # Buttons
        btn_layout = QHBoxLayout()
        
        def try_unlock():
            password = pass_input.text().strip()
            if not password:
                status_label.setText("⚠️ Please enter password")
                status_label.setStyleSheet("color:#ff9800;")
                return
            
            # Try to unlock
            success, message = self.bot.loader.unlock_strategy(strategy, password)
            
            if success:
                status_label.setText(f"✅ {message}")
                status_label.setStyleSheet("color:#00e676;")
                
                # Set strategy for symbol
                if symbol in self.bot.symbols:
                    self.bot.symbols[symbol]['strategy'] = strategy
                    self.log_msg(f"🔓 {symbol} → Strategy: {strategy} (Unlocked)", "lime")
                
                # Close dialog after 1 second
                QTimer.singleShot(1000, d.accept)
            else:
                status_label.setText(f"❌ {message}")
                status_label.setStyleSheet("color:#f44336;")
                pass_input.clear()
                pass_input.setFocus()
        
        btn_unlock = QPushButton("🔓 UNLOCK")
        btn_unlock.setStyleSheet("background:#00c853;color:white;font-weight:bold;padding:10px;")
        btn_unlock.clicked.connect(try_unlock)
        pass_input.returnPressed.connect(try_unlock)
        btn_layout.addWidget(btn_unlock)
        
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setStyleSheet("background:#666;color:white;padding:10px;")
        btn_cancel.clicked.connect(d.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        
        # Admin contact info
        admin_info = QLabel("📧 Contact admin for password: support@rudrabot.com")
        admin_info.setStyleSheet("color:#666;font-size:10px;padding:10px;")
        layout.addWidget(admin_info)
        
        pass_input.setFocus()
        d.exec_()
    
    def change_trading_mode(self, mode):
        """
        Switch between trading modes:
        - MT5: Only bot strategies → MT5 orders
        - TRADINGVIEW: Only TradingView signals → MT5 orders
        - AMIBROKER: Only AmiBroker signals → MT5 orders
        - DUAL: All systems active (MT5 strategies + TradingView + AmiBroker → MT5)
        """
        self.bot.trading_mode = mode
        self.log_msg(f"Trading Mode: {mode}", "cyan")
        
        # TradingView webhook server (active in TRADINGVIEW or DUAL mode)
        if mode in ['TRADINGVIEW', 'DUAL']:
            if not hasattr(self.bot, 'webhook_server_running') or not self.bot.webhook_server_running:
                self.bot.start_webhook_server()
                self.lbl_webhook.setText("🟢")
                self.lbl_webhook.setStyleSheet("color:#00e676;font-size:20px;")
        else:
            self.lbl_webhook.setText("⚫")
            self.lbl_webhook.setStyleSheet("color:gray;font-size:20px;")
        
        # AmiBroker file watcher (active in AMIBROKER or DUAL mode)
        if mode in ['AMIBROKER', 'DUAL']:
            if not hasattr(self.bot, 'amibroker_watcher_running') or not self.bot.amibroker_watcher_running:
                self.bot.start_amibroker_watcher()
                self.lbl_amibroker.setText("🟢")
                self.lbl_amibroker.setStyleSheet("color:#ff6f00;font-size:20px;")
        else:
            # Stop AmiBroker watcher if switching out of AB/DUAL mode
            if hasattr(self.bot, 'amibroker_watcher_running') and self.bot.amibroker_watcher_running:
                self.bot.stop_amibroker_watcher()
            self.lbl_amibroker.setText("⚫")
            self.lbl_amibroker.setStyleSheet("color:gray;font-size:20px;")
    
    def add_strategy(self):
        """Import external strategy file"""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Strategy File", "", "Python Files (*.py)")
        if file_path:
            try:
                dest = os.path.join(STRATEGIES_DIR, os.path.basename(file_path))
                shutil.copy(file_path, dest)
                self.reload_strategies()
                self.log_msg(f"Added: {os.path.basename(file_path)}", "lime")
                QMessageBox.information(self, "Success", f"Strategy '{os.path.basename(file_path)}' added!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add strategy: {e}")
    
    def reload_strategies(self):
        """Reload all strategies"""
        self.bot.available_strats = self.bot.loader.reload_strategies()
        self.c_strat.clear()
        self.c_strat.addItems(self.bot.available_strats)
        if self.bot.available_strats:
            self.bot.active_strategy = self.bot.available_strats[0]
        self.log_msg("Strategies reloaded", "cyan")
    
    def capture_chart(self):
        """AI Chart Capture - takes screenshot and saves"""
        if not SCREENSHOT_AVAILABLE:
            QMessageBox.warning(self, "Missing Library", "Install: pip install pillow pyautogui")
            return
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_dir = os.path.join(BASE_DIR, "Screenshots")
            if not os.path.exists(screenshot_dir):
                os.makedirs(screenshot_dir)
            
            filename = os.path.join(screenshot_dir, f"chart_{timestamp}.png")
            screenshot = ImageGrab.grab()
            screenshot.save(filename)
            
            self.log_msg(f"Chart saved: {filename}", "lime")
            self.speak(f"Chart captured at {datetime.datetime.now().strftime('%H:%M')}")
            QMessageBox.information(self, "Captured", f"Screenshot saved:\n{filename}")
        except Exception as e:
            self.log_msg(f"Capture failed: {e}", "red")
    
    def speak(self, text):
        """Female voice alert"""
        if self.bot.voice_enabled and self.bot.voice_engine:
            try:
                threading.Thread(target=lambda: self.bot.voice_engine.say(text) or self.bot.voice_engine.runAndWait(), daemon=True).start()
            except:
                pass
    
    def bulk_load(self):
        d = BulkLoadDialog(self)
        if d.exec_():
            syms = d.get_list()
            self.bot.symbols = {s: {'lot':0.01, 'bid':0, 'ask':0, 'status':'-', 'pnl':0.0, 'd_pct':0.0, 'spread':0, 'mode':'', 'orders':0, 'strategy': self.bot.active_strategy} for s in syms}
            self.refresh_rows(syms)
            self.log_msg(f"Loaded {len(syms)} Symbols", "lime")
    
    def refresh_rows(self, syms):
        self.table.setRowCount(0)
        
        for i, s in enumerate(syms):
            self.table.insertRow(i)
            def item(t, c="white"): it = QTableWidgetItem(str(t)); it.setTextAlignment(Qt.AlignCenter); it.setForeground(QColor(c)); return it
            
            self.table.setItem(i, 0, item(str(i+1), "gray"))
            self.table.setItem(i, 1, item(s, "#00bcd4"))
            
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0)
            sb = QDoubleSpinBox(); sb.setRange(0.01, 100); sb.setValue(0.01); sb.setSingleStep(0.01); sb.setButtonSymbols(QAbstractSpinBox.NoButtons); sb.setAlignment(Qt.AlignCenter); sb.setStyleSheet("background:transparent;border:none;color:yellow;")
            sb.valueChanged.connect(partial(self.upd_sym_data, s, 'lot')); h.addWidget(sb); self.table.setCellWidget(i, 2, w)
            
            # Strategy dropdown
            strategy_combo = QComboBox()
            strategy_combo.addItems(self.bot.available_strats)
            strategy_combo.setCurrentText(self.bot.active_strategy)
            strategy_combo.setStyleSheet("background:#1a1a1a;color:#ffeb3b;border:1px solid #444;")
            strategy_combo.currentTextChanged.connect(partial(self.change_symbol_strategy, s))
            self.table.setCellWidget(i, 3, strategy_combo)
            
            # Strategy ACTIVE checkbox
            w_active = QWidget(); h_active = QHBoxLayout(w_active); h_active.setContentsMargins(0,0,0,0); h_active.setAlignment(Qt.AlignCenter)
            chk_active = QCheckBox("✓"); chk_active.setChecked(True); chk_active.setStyleSheet("color:#00e676;font-weight:bold;")
            chk_active.toggled.connect(partial(self.toggle_strategy_active, s))
            h_active.addWidget(chk_active); self.table.setCellWidget(i, 4, w_active)
            # Initialize active state
            if s in self.bot.symbols:
                self.bot.symbols[s]['strategy_active'] = True
            
            self.table.setItem(i, 5, item("0.0%")) # D%
            self.table.setItem(i, 6, item("0"))    # Spread
            self.table.setItem(i, 7, item("-"))    # Mode
            self.table.setItem(i, 8, item("0"))    # Orders
            self.table.setItem(i, 9, item("WAIT", "gray")) # Status
            self.table.setItem(i, 10, item("0.00")) # PnL
            self.table.setItem(i, 11, item("0.0000")) # Bid
            self.table.setItem(i, 12, item("0.0000")) # Ask
            
            wb = QWidget(); lb = QHBoxLayout(wb); lb.setContentsMargins(2,2,2,2); lb.setSpacing(3)
            for txt, col, act in [("B","#00c853","BUY"), ("S","#d50000","SELL"), ("X","#ff6f00","X"), ("R","#aa00ff","REV")]:
                b = QPushButton(txt); b.setFixedSize(35, 28); b.setStyleSheet(f"background:{col};border:none;color:{'black' if txt=='X' else 'white'};font-weight:bold;font-size:12px;")
                b.clicked.connect(partial(self.bot.execute_trade, s, act)); lb.addWidget(b)
            self.table.setCellWidget(i, 13, wb)
            
    def upd_sym_data(self, s, k, v): 
        if s in self.bot.symbols: self.bot.symbols[s][k] = v
    
    def toggle_strategy_active(self, symbol, state):
        """Toggle strategy execution for a specific symbol"""
        if symbol in self.bot.symbols:
            self.bot.symbols[symbol]['strategy_active'] = state
            status = "ON ✅" if state else "OFF ⚫"
            self.log_msg(f"📊 {symbol} Strategy: {status}", "cyan" if state else "gray")
    
    def manual_buy(self, symbol=None, lot=None):
        """Execute manual BUY order - called from ACTIONS column"""
        if not symbol:
            self.log_msg("⚠️ Symbol not provided for BUY!", "orange")
            return
        if lot is None:
            lot = 0.01
        self.log_msg(f"📲 MANUAL BUY: {symbol} | Lot: {lot}", "lime")
        threading.Thread(target=self.bot.execute_trade, args=(symbol, "BUY", lot), daemon=True).start()
    
    def manual_sell(self, symbol=None, lot=None):
        """Execute manual SELL order - called from ACTIONS column"""
        if not symbol:
            self.log_msg("⚠️ Symbol not provided for SELL!", "orange")
            return
        if lot is None:
            lot = 0.01
        self.log_msg(f"📲 MANUAL SELL: {symbol} | Lot: {lot}", "red")
        threading.Thread(target=self.bot.execute_trade, args=(symbol, "SELL", lot), daemon=True).start()
    
    def manual_reverse(self, symbol=None):
        """Reverse all positions for symbol - called from ACTIONS column"""
        if not symbol:
            self.log_msg("⚠️ Symbol not provided for REVERSE!", "orange")
            return
        self.log_msg(f"🔄 MANUAL REVERSE: {symbol}", "cyan")
        threading.Thread(target=self.bot.execute_trade, args=(symbol, "REV"), daemon=True).start()
    
    def manual_close(self, symbol=None):
        """Close all positions for symbol - called from ACTIONS column"""
        if not symbol:
            self.log_msg("⚠️ Symbol not provided for CLOSE!", "orange")
            return
        self.log_msg(f"📲 MANUAL CLOSE: {symbol}", "orange")
        threading.Thread(target=self.bot.execute_trade, args=(symbol, "X"), daemon=True).start()
        
    def update_all_lots(self):
        val = self.s_glot.value()
        for s in self.bot.symbols: self.bot.symbols[s]['lot'] = val
        for r in range(self.table.rowCount()):
            w = self.table.cellWidget(r, 2); 
            if w: w.findChild(QDoubleSpinBox).setValue(val)
        self.log_msg(f"All Lots Updated to {val}", "cyan")
    
    def apply_strategy_to_all(self):
        """Apply selected strategy to all loaded symbols"""
        selected_strategy = self.c_strat.currentText()
        if not selected_strategy or not self.bot.symbols:
            self.log_msg("⚠️ No strategy selected or no symbols loaded!", "orange")
            return
        
        count = 0
        for symbol in self.bot.symbols:
            self.bot.symbols[symbol]['strategy'] = selected_strategy
            count += 1
        
        # Update all strategy dropdowns in table
        for r in range(self.table.rowCount()):
            strategy_widget = self.table.cellWidget(r, 3)
            if strategy_widget and isinstance(strategy_widget, QComboBox):
                strategy_widget.blockSignals(True)
                strategy_widget.setCurrentText(selected_strategy)
                strategy_widget.blockSignals(False)
        
        self.log_msg(f"✅ Applied '{selected_strategy}' to all {count} symbols", "lime")
        
    def toggle_trailing(self, checked): self.bot.use_trailing = checked; self.log_msg(f"Auto Trail {'On' if checked else 'Off'}", "cyan")
    
    def toggle_autoscan(self, state):
        """Toggle auto signal scanning for all symbols"""
        self.bot.auto_signal_scan = state
        if state:
            self.log_msg(f"🔍 AUTO SCAN: ON | Strategy: {self.bot.active_strategy}", "yellow")
            self.log_msg(f"Will scan all loaded symbols for {self.bot.active_strategy} signals", "cyan")
        else:
            self.log_msg("🔍 AUTO SCAN: OFF", "gray")
    
    def ai_match_strategies(self):
        """AI-powered strategy matching for all symbols"""
        if not self.bot.symbols:
            self.log_msg("⚠️ No symbols loaded! Load symbols first.", "orange")
            return
        
        self.log_msg("🧠 Starting AI Strategy Matcher...", "cyan")
        threading.Thread(target=self.bot.auto_match_all_strategies, daemon=True).start()
    
    def toggle_chart_capture(self, state):
        """Enable/disable auto chart capture"""
        self.bot.chart_capture_enabled = (state == Qt.Checked)
        status = "ON ✅" if self.bot.chart_capture_enabled else "OFF ⚫"
        self.log_msg(f"📸 AUTO CHART CAPTURE: {status}", "cyan")
        if self.bot.chart_capture_enabled:
            interval = self.spin_chart_interval.value()
            self.log_msg(f"Will capture charts every {interval} minutes with market direction", "lime")
    
    def update_chart_interval(self, value):
        """Update chart capture interval"""
        self.bot.chart_capture_interval = value * 60  # Convert to seconds
        self.log_msg(f"📸 Capture Interval: {value} minutes", "cyan")
    
    def manual_capture_all(self):
        """Manually capture charts for all symbols"""
        if not self.bot.symbols:
            self.log_msg("⚠️ No symbols loaded!", "orange")
            return
        
        if not CHART_CAPTURE_AVAILABLE:
            self.log_msg("📸 Chart capture not available. Install matplotlib!", "red")
            return
        
        self.log_msg(f"📸 Capturing charts for {len(self.bot.symbols)} symbols...", "cyan")
        
        def capture_thread():
            for symbol in list(self.bot.symbols.keys()):
                self.bot.capture_symbol_chart(symbol)
                time.sleep(0.5)
            self.log_msg(f"✅ Captured {len(self.bot.symbols)} charts!", "lime")
        
        threading.Thread(target=capture_thread, daemon=True).start()
    
    def open_charts_folder(self):
        """Open charts folder in file explorer"""
        import subprocess
        folder = self.bot.charts_folder
        if os.path.exists(folder):
            subprocess.Popen(f'explorer "{folder}"')
            self.log_msg(f"📁 Opened: {folder}", "cyan")
        else:
            self.log_msg("📁 No charts folder found yet. Capture a chart first!", "orange")
    
    def update_trail_params(self): self.bot.trail_start = self.s_tr_start.value(); self.bot.trail_step = self.s_tr_step.value()
    def update_sl_visual(self, val): self.s_sl.setValue(val)
    def update_risk(self): self.bot.global_tp = self.s_tp.value(); self.bot.global_sl = self.s_sl.value(); self.log_msg(f"Risk: TP ${self.s_tp.value()} | SL ${self.s_sl.value()}", "orange")
    def toggle_bot(self):
        if self.b_run.isChecked(): 
            self.bot.start(); self.b_run.setText("STOP")
            self.blink_timer.start(500)  # Blink every 500ms when running
        else: 
            self.bot.stop(); self.b_run.setText("START")
            self.blink_timer.stop()
            # Reset to lime green
            self.b_run.setStyleSheet("QPushButton{background:#00ff00;color:black;font-weight:bold;padding:10px;} QPushButton:checked{background:#d50000;color:white;}")
    
    def blink_start_button(self):
        """Create blinking effect for START button when bot is running"""
        if self.b_run.isChecked():
            if self.blink_state:
                self.b_run.setStyleSheet("QPushButton{background:#00ff00;color:black;font-weight:bold;padding:10px;} QPushButton:checked{background:#d50000;color:white;}")
            else:
                self.b_run.setStyleSheet("QPushButton{background:#00ff00;color:black;font-weight:bold;padding:10px;} QPushButton:checked{background:#ff0000;color:white;}")
            self.blink_state = not self.blink_state
        
    def refresh_table(self):
        for r in range(self.table.rowCount()):
            sym_item = self.table.item(r, 1)
            if not sym_item: continue
            sym = sym_item.text(); d = self.bot.symbols.get(sym)
            if d:
                # Update strategy dropdown
                strategy_widget = self.table.cellWidget(r, 3)
                if strategy_widget:
                    current_strategy = d.get('strategy', self.bot.active_strategy)
                    if strategy_widget.currentText() != current_strategy:
                        strategy_widget.blockSignals(True)
                        strategy_widget.setCurrentText(current_strategy)
                        strategy_widget.blockSignals(False)
                
                # Safely update d_pct column
                dp = self.table.item(r, 4)
                if dp:
                    dp.setText(f"{d.get('d_pct',0):.2f}%")
                    dp.setForeground(QColor("#00e676" if d.get('d_pct',0)>=0 else "#ff5252"))
                
                # Safely update other columns
                spread_item = self.table.item(r, 5)
                if spread_item: spread_item.setText(str(d.get('spread',0)))
                
                mode_item = self.table.item(r, 6)
                if mode_item: mode_item.setText(str(d.get('mode','-')))
                
                orders_item = self.table.item(r, 7)
                if orders_item: orders_item.setText(str(d.get('orders',0)))
                
                st = self.table.item(r, 8)
                if st:
                    st.setText(d['status'])
                    st.setForeground(QColor("#00e676" if "BUY" in d['status'] else "#ff5252" if "SELL" in d['status'] else "gray"))
                
                pnl = d.get('pnl', 0.0)
                p_item = self.table.item(r, 9)
                if p_item:
                    p_item.setText(f"{pnl:.2f}")
                    p_item.setForeground(QColor("#00e676" if pnl >= 0 else "#ff5252"))
                
                bid_item = self.table.item(r, 10)
                if bid_item: bid_item.setText(f"{d['bid']:.5f}")
                
                ask_item = self.table.item(r, 11)
                if ask_item: ask_item.setText(f"{d['ask']:.5f}")

    def upd_stats(self, pnl, eq):
        c = "#00e676" if pnl >= 0 else "#ff5252"
        self.lbl_pnl.setText(f"P/L: $ {pnl:.2f}"); self.lbl_pnl.setStyleSheet(f"color:{c};font-size:20px;font-weight:900;border:2px solid {c};padding:5px 15px;border-radius:5px;background:#080808;")
    
    def update_news_ticker(self):
        """Update news ticker with live financial news"""
        try:
            if hasattr(self, 'news_ticker'):
                # Simple news update
                import datetime
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                news_items = [
                    "📈 Market Update: Trading systems active",
                    "💹 Forex markets showing volatility", 
                    "📊 Technical analysis in progress",
                    "🔔 Monitor your positions closely",
                    "⚡ Live trading signals being processed"
                ]
                import random
                news = random.choice(news_items)
                self.news_ticker.setText(f"[{current_time}] {news}")
        except Exception as e:
            if hasattr(self, 'news_ticker'):
                self.news_ticker.setText(f"📰 News service updating...")
        # Timer will auto-restart

    def update_tv_display(self):
        """TradingView display update - disabled for cleaner dashboard"""
        pass  # Function disabled
    
    def log_msg(self, msg, col):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Color mapping with 4-color rotation for default/cyan messages
        if col == 'red':
            color = '#ff5252'
        elif col == 'lime':
            color = '#00e676'
        elif col == 'orange':
            color = '#ff9800'
        elif col == 'cyan' or col == 'default':
            # Rotate through 4 colors: Green, Gold, Aqua, Pink
            color = self.log_colors[self.log_color_index]
            self.log_color_index = (self.log_color_index + 1) % 4
        else:
            # Rotate for any other color
            color = self.log_colors[self.log_color_index]
            self.log_color_index = (self.log_color_index + 1) % 4
        
        self.logs.append(f"<span style='color:{color}'>[{t}] {msg}</span>")
    
    def update_logs_display(self):
        """Update logs QTextEdit with HTML colored messages"""
        if hasattr(self, 'logs') and isinstance(self.logs, list):
            # Keep last 50 messages only
            recent_logs = self.logs[-50:] if len(self.logs) > 50 else self.logs
            html_content = "<br>".join(recent_logs)
            
            # Update QTextEdit with HTML
            logs_widget = self.findChild(QTextEdit)
            if logs_widget:
                logs_widget.setHtml(html_content)
                # Auto-scroll to bottom
                scrollbar = logs_widget.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())

STYLESHEET = """
    QMainWindow, QDialog, QWidget { background-color: #050505; color: #e0e0e0; font-family: 'Segoe UI'; font-size: 12px; font-weight: bold; }
    QGroupBox { border: 1px solid #333; margin-top: 20px; font-weight: bold; color: #00bcd4; font-size: 11px; background: #0a0a0a; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
    QLineEdit, QDoubleSpinBox, QTextEdit { background: #151515; border: 1px solid #444; padding: 4px; color: white; font-weight: bold; font-size: 12px; border-radius: 4px; }
    QComboBox { background: #151515; border: 1px solid #444; padding: 4px; color: white; font-weight: bold; font-size: 12px; border-radius: 4px; min-height: 20px; }
    QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border-left: 1px solid #555; background: #222; }
    QComboBox::down-arrow { image: none; border: 2px solid #00bcd4; width: 6px; height: 6px; background: transparent; margin-right: 4px; }
    QComboBox QAbstractItemView { background: #151515; color: white; selection-background-color: #00bcd4; selection-color: black; border: 1px solid #444; outline: none; }
    QTableWidget { background-color: #000000; alternate-background-color: #111; gridline-color: #333; border: 1px solid #333; font-size: 12px; font-weight: bold; }
    QTableWidget::item { padding-left: 5px; padding-right: 5px; }
    QHeaderView::section { background-color: #1a1a1a; color: #00e676; padding: 6px; border: 1px solid #333; font-weight: bold; font-size: 11px; }
    QPushButton { background-color: #333; color: white; padding: 6px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; }
    QPushButton:hover { background-color: #444; }
"""

if __name__ == "__main__":
    # Hardware protection check
    if PROTECTION_AVAILABLE:
        protection = HardwareProtection()
        
        # Check for debugger
        if AntiDebugProtection.check_debugger():
            print("❌ Debugger detected! Exiting...")
            sys.exit(1)
        
        # Validate license
        is_valid, message, license_data = protection.validate_license()
        
        if not is_valid:
            print("="*60)
            print("🔒 LICENSE VALIDATION FAILED")
            print("="*60)
            print(f"❌ {message}")
            print("\n📧 Contact: support@rudrabot.com")
            print("🔑 Hardware ID:", protection.get_hardware_id()[:32])
            print("="*60)
            
            # Show error dialog
            app = QApplication(sys.argv)
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("License Error")
            msg.setText(f"License Validation Failed\n\n{message}")
            msg.setInformativeText(f"Hardware ID: {protection.get_hardware_id()[:32]}...\n\nContact support to activate.")
            msg.exec_()
            sys.exit(1)
        
        print("="*60)
        print("✅ LICENSE VALIDATED")
        print("="*60)
        print(f"👤 Licensed to: {license_data['user']}")
        print(f"📅 Valid until: {license_data['expiry']}")
        print(f"🎯 Product: {license_data['product']}")
        print("="*60)
    
    app = QApplication(sys.argv); app.setStyle("Fusion")
    win = BotWindow(); win.show(); sys.exit(app.exec_())