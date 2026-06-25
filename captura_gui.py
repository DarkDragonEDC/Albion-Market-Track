"""
Albion Market Scanner - Aplicativo Desktop
Janela única: controles de captura + tabela de mercado.
Requer execução como Administrador (WinDivert).
"""
import tkinter as tk
from tkinter import ttk
import threading
import pydivert
import struct
import subprocess
import time
import os
import re
import json
import sys
import ctypes
import base64
import socket as _socket
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ── Caminhos ──────────────────────────────────────────────────────────────────
# Quando empacotado com PyInstaller (frozen), __file__ aponta para o diretório
# temporário de extração. sys.executable aponta para o .exe real.
WORK_DIR    = (os.path.dirname(sys.executable)
               if getattr(sys, 'frozen', False)
               else os.path.dirname(os.path.abspath(__file__)))
PCAP_ZONE   = r'C:\temp\albion_zone_detect.pcap'
PCAP_MAIN   = r'C:\temp\albion_capture.pcap'
PCAP_COMBINED = r'C:\temp\albion_combined.pcap'
DC_PATH     = r'C:\Program Files\Albion Data Client\albiondata-client.exe'
SCANNER_DIR = os.path.join(WORK_DIR, 'albion-scanner')
PCAP_HEADER  = struct.pack('<IHHiIII', 0xA1B2C3D4, 2, 4, 0, 0, 65535, 101)
API_BASE     = 'http://localhost:3001'
DATA_STORE    = r'C:\temp\albion_market_store.json'
HISTORY_CACHE = r'C:\temp\albion_history_cache.json'
HISTORY_TTL   = 7200  # segundos (2 horas)
REFRESH_MS  = 5000
ITEMS_CACHE  = r'C:\temp\albion_item_names.json'
GAMEINFO_URL = 'https://gameinfo.albiononline.com/api/gameinfo/items/{}/data'

_item_names: dict = {}           # {unique_name: display_name}  — persistido em cache
_fetch_queue: set  = set()       # IDs aguardando busca de nome
_fetch_lock        = threading.Lock()
_avg_cache:  dict = {}           # "itemId@ench|city|quality" → int (preço médio 24h)

FILTER_UDP = ('udp and ('
              '(ip.SrcAddr >= 5.188.125.0 and ip.SrcAddr <= 5.188.125.255) or '
              '(ip.DstAddr >= 5.188.125.0 and ip.DstAddr <= 5.188.125.255)'
              ')')

LOCATION_NAMES = {
    '4002': 'Fort Sterling', '4000': 'Fort Sterling',
    '3005': 'Martlock',      '3000': 'Martlock',
    '2004': 'Bridgewatch',   '2000': 'Bridgewatch',
    '1002': 'Lymhurst',      '1000': 'Lymhurst',
    '0301': 'Thetford',      '301':  'Thetford',
    '0006': 'Caerleon',      '6':    'Caerleon',
    '0007': 'Black Market',  '7':    'Black Market',
    '3003': 'Black Market',
    '3008': 'Black Market',
    '4500': 'Brecilien',
}

CITIES = ['Todas', 'Bridgewatch', 'Lymhurst', 'Fort Sterling',
          'Martlock', 'Thetford', 'Caerleon', 'Black Market', 'Brecilien']

CAPTURE_CITIES = ['Bridgewatch', 'Caerleon', 'Fort Sterling',
                  'Lymhurst', 'Martlock', 'Thetford', 'Black Market', 'Brecilien']

# PCAP de zona por cidade — Black Market usa o mesmo PCAP de Caerleon (mesma zona)
CITY_ZONE_PCAP = {
    'Bridgewatch':   r'C:\temp\albion_zone_bridgewatch.pcap',
    'Caerleon':      r'C:\temp\albion_zone_caerleon.pcap',
    'Black Market':  r'C:\temp\albion_zone_caerleon.pcap',
    'Fort Sterling': r'C:\temp\albion_zone_fort_sterling.pcap',
    'Lymhurst':      r'C:\temp\albion_zone_lymhurst.pcap',
    'Martlock':      r'C:\temp\albion_zone_martlock.pcap',
    'Thetford':      r'C:\temp\albion_zone_thetford.pcap',
    'Brecilien':     r'C:\temp\albion_zone_brecilien.pcap',
}

TIME_OPTS = [('15 min', 15), ('30 min', 30), ('1 hora', 60), ('Sessão', 10080)]

QUALITY_NAMES = {1: 'Normal', 2: 'Good', 3: 'Outstanding', 4: 'Excellent', 5: 'Masterpiece'}

# (id, rótulo, largura, âncora)
COLS = [
    ('item',       'Item',          310, 'w'),
    ('cidade',     'Cidade',        110, 'center'),
    ('qual',       'Qual.',          80, 'center'),
    ('venda_min',  'Venda mín.',    110, 'e'),
    ('qtd_venda',  'Qtd venda',      75, 'center'),
    ('media_24h',  'Média 24h',     110, 'e'),
    ('capturado',  'Capturado',      80, 'center'),
]

ALBION_DATA_API = 'https://west.albion-online-data.com/api/v2/stats/charts'

ARB_COLS = [
    ('item',       'Item',          310, 'w'),
    ('qual',       'Qual.',          80, 'center'),
    ('cidade',     'Cidade',        110, 'center'),
    ('preco_cid',  'Preço cidade',  120, 'e'),
    ('preco_bm',   'Preço BM',      120, 'e'),
    ('lucro',      'Lucro',         120, 'e'),
    ('lucro_pct',  '% Lucro',        80, 'center'),
    ('qty_bm',     'BM quer (un.)',   100, 'center'),
    ('qty_venda',  'Em venda BM',    100, 'center'),
    ('vol24h',     'Vend. 24h',       80, 'center'),
    ('med24h',     'Média BM',       110, 'e'),
]


# ── Nomes dos itens ───────────────────────────────────────────────────────────
def load_item_names():
    """Carrega cache local de nomes (sem download — nomes chegam via enrich_names)."""
    global _item_names
    try:
        if os.path.exists(ITEMS_CACHE):
            with open(ITEMS_CACHE, encoding='utf-8') as f:
                _item_names = json.load(f)
    except Exception:
        pass


def save_store(items: list):
    try:
        with open(DATA_STORE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)
    except Exception:
        pass


def load_store() -> list:
    try:
        if os.path.exists(DATA_STORE):
            with open(DATA_STORE, encoding='utf-8') as f:
                items = json.load(f)
            # Migra IDs numéricos antigos para nomes legíveis
            changed = False
            for it in items:
                loc = it.get('location', '')
                mapped = LOCATION_NAMES.get(loc)
                if mapped and mapped != loc:
                    it['location'] = mapped
                    changed = True
            if changed:
                save_store(items)
            return items
    except Exception:
        pass
    return []


def load_history_cache() -> dict:
    try:
        if os.path.exists(HISTORY_CACHE):
            with open(HISTORY_CACHE, encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_history_cache(cache: dict):
    try:
        with open(HISTORY_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    except Exception:
        pass


def enqueue_fetch(base_id: str):
    with _fetch_lock:
        if base_id not in _item_names and base_id not in _fetch_queue:
            _fetch_queue.add(base_id)


def enrich_names(app):
    """Thread permanente: busca nomes ausentes na API gameinfo e atualiza a tabela."""
    from concurrent.futures import ThreadPoolExecutor

    def fetch_one(uid):
        try:
            url = GAMEINFO_URL.format(uid)
            req = urllib.request.Request(url, headers={'User-Agent': 'AlbionScanner/1.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            loc  = data.get('localizedNames') or {}
            name = loc.get('PT-BR') or loc.get('EN-US') or ''
            return uid, name
        except Exception:
            return uid, ''

    while True:
        time.sleep(1)
        with _fetch_lock:
            batch = list(_fetch_queue)[:20]
        if not batch:
            continue

        results = {}
        with ThreadPoolExecutor(max_workers=5) as pool:
            for uid, name in pool.map(fetch_one, batch):
                if name:
                    results[uid] = name

        if results:
            with _fetch_lock:
                _item_names.update(results)
                for uid in batch:
                    _fetch_queue.discard(uid)
            try:
                with open(ITEMS_CACHE, 'w', encoding='utf-8') as f:
                    json.dump(_item_names, f, ensure_ascii=False)
            except Exception:
                pass
            app.after(0, app._render_table)
        else:
            with _fetch_lock:
                for uid in batch:
                    _fetch_queue.discard(uid)


# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_name(item_id: str, enchantment: int = 0) -> str:
    base   = re.sub(r'@\d+', '', item_id)
    tier_m = re.match(r'^T(\d+)', base)
    tier_n = int(tier_m.group(1)) if tier_m else 0
    prefix = f'T{tier_n}.{enchantment}' if enchantment else (f'T{tier_n}' if tier_n else '')

    real = _item_names.get(base)
    if real:
        return f'{prefix} {real}' if prefix else real

    # nome ainda não carregado — enfileira busca em background
    enqueue_fetch(base)
    name = re.sub(r'^T\d+_', '', base).replace('_', ' ').title()
    return f'{prefix} {name}'.strip()


def fmt(n) -> str:
    """Formata preço em silver com separador de milhar, sem arredondamento."""
    if n is None: return '-'
    return f'{int(n):,}'.replace(',', '.')


def time_ago(iso: str) -> str:
    try:
        dt   = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        diff = int((datetime.now(timezone.utc) - dt).total_seconds())
        if diff < 60:   return f'{diff}s'
        if diff < 3600: return f'{diff // 60}min'
        return f'{diff // 3600}h'
    except Exception:
        return '-'


# ── Captura de pacotes ────────────────────────────────────────────────────────
stop_capture = threading.Event()


def capturar_para(pcap_path: str, seconds=None, stop_ev=None, append=False) -> int:
    count = 0
    start = time.time()
    mode = 'ab' if append else 'wb'
    with open(pcap_path, mode) as f:
        if not append:
            f.write(PCAP_HEADER)
        with pydivert.WinDivert(FILTER_UDP) as w:
            for pkt in w:
                w.send(pkt)
                raw = bytes(pkt.raw)
                if len(raw) < 20:
                    continue
                t       = time.time()
                ts_sec  = int(t)
                ts_usec = int((t - ts_sec) * 1_000_000)
                f.write(struct.pack('<IIII', ts_sec, ts_usec, len(raw), len(raw)))
                f.write(raw)
                count += 1
                if seconds and (time.time() - start) >= seconds:
                    break
                if stop_ev and stop_ev.is_set():
                    break
    return count


_WS_DEBUG_LOG = r'C:\temp\albion_ws_debug.txt'


def _ws_log(msg: str):
    try:
        ts = time.strftime('%H:%M:%S')
        with open(_WS_DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass


def _ws_read_exact(sock, n: int) -> bytes | None:
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _ws_recv_frame(sock) -> tuple[int, bytes] | None:
    """Lê um frame WebSocket. Retorna (opcode, payload) ou None no fechamento."""
    header = _ws_read_exact(sock, 2)
    if header is None:
        return None
    opcode = header[0] & 0x0f
    if opcode == 8:
        return None
    payload_len = header[1] & 0x7f
    if payload_len == 126:
        ext = _ws_read_exact(sock, 2)
        if ext is None: return None
        payload_len = struct.unpack('>H', ext)[0]
    elif payload_len == 127:
        ext = _ws_read_exact(sock, 8)
        if ext is None: return None
        payload_len = struct.unpack('>Q', ext)[0]
    payload = _ws_read_exact(sock, payload_len) if payload_len else b''
    if payload is None:
        return None
    return opcode, payload


def _coletar_via_ws(orders_out: list, done: threading.Event):
    """Thread: conecta ao Data Client (porta 8099) e coleta market orders."""
    _ws_log('--- nova sessão ---')
    sock = None
    for attempt in range(40):       # tenta por até 4 segundos
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(('127.0.0.1', 8099))
            sock = s
            _ws_log(f'conectou na tentativa {attempt + 1}')
            break
        except Exception as e:
            if attempt == 0:
                _ws_log(f'tentativa 0 falhou: {e}')
            time.sleep(0.1)
    if sock is None:
        _ws_log('FALHA: porta 8099 nunca abriu (Data Client nao abre WS em modo offline?)')
        done.set()
        return
    try:
        key = base64.b64encode(b'albionscanner00000').decode()
        handshake = (
            'GET /ws HTTP/1.1\r\n'
            'Host: 127.0.0.1:8099\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            'Origin: http://localhost\r\n'
            '\r\n'
        )
        sock.sendall(handshake.encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                _ws_log('conexão fechou durante handshake')
                return
            resp += chunk
        if b'101' not in resp:
            _ws_log(f'handshake recusado: {resp[:200]}')
            return
        _ws_log('handshake OK — aguardando frames')
        sock.settimeout(60)
        frames_total = 0
        while True:
            result = _ws_recv_frame(sock)
            if result is None:
                break
            opcode, payload = result
            frames_total += 1
            # opcode 1 = texto, opcode 2 = binário, opcode 0 = continuação
            if opcode in (0, 1, 2) and payload:
                try:
                    msg = json.loads(payload.decode('utf-8'))
                    topic = msg.get('topic', '')
                    _ws_log(f'frame opcode={opcode} topic={topic!r} len={len(payload)}')
                    if topic == 'marketorders.ingest':
                        batch = msg.get('data', {}).get('Orders', [])
                        orders_out.extend(batch)
                        _ws_log(f'  → {len(batch)} ordens adicionadas (total={len(orders_out)})')
                except Exception as e:
                    _ws_log(f'frame opcode={opcode} parse erro: {e} raw={payload[:80]}')
        _ws_log(f'conexão encerrada — {frames_total} frames, {len(orders_out)} ordens')
    except Exception as e:
        _ws_log(f'exceção: {e}')
    finally:
        try: sock.close()
        except Exception: pass
        done.set()


def _combinar_pcaps(zone_path: str, main_path: str, out_path: str) -> str:
    """Concatena pacotes do PCAP de zona com os do PCAP principal.
    Retorna out_path se ok, main_path como fallback."""
    try:
        with open(out_path, 'wb') as out:
            out.write(PCAP_HEADER)
            for src in (zone_path, main_path):
                if not os.path.exists(src):
                    continue
                with open(src, 'rb') as f:
                    header = f.read(24)
                    if len(header) < 24:
                        continue
                    out.write(f.read())   # copia apenas os pacotes, sem o header global
        return out_path
    except Exception:
        return main_path


def processar_pcap(pcap_path: str):
    """Roda Data Client e recebe ordens diretamente via WebSocket porta 8099."""
    orders: list = []
    ws_done = threading.Event()

    # Inicia receptor WebSocket ANTES do Data Client abrir a porta
    threading.Thread(target=_coletar_via_ws, args=(orders, ws_done),
                     daemon=True).start()

    try:
        args = [DC_PATH, '-o', pcap_path, '-p', 'http://localhost:3001', '-debug']
        proc = subprocess.run(args, cwd=WORK_DIR, capture_output=True, timeout=60)
        out  = proc.stdout.decode('utf-8', errors='replace')
        resps  = out.count('Got response to AuctionGet')
        errors = out.count('location has not yet been set')
        m      = re.search(r'opChangeCluster.*?0:"(\d+)"', out)
        cidade = LOCATION_NAMES.get(m.group(1), f'Zona {m.group(1)}') if m else ''
    except Exception:
        resps, cidade, errors = 0, '', -1

    ws_done.wait(timeout=5)   # aguarda o WebSocket fechar e drenar mensagens
    _ws_log(f'processar_pcap: resps={resps} ordens_ws={len(orders)}')

    # Fallback: se WebSocket não entregou nada, busca do Node.js HTTP
    if not orders:
        _ws_log('fallback: consultando Node.js HTTP /api/items')
        try:
            with urllib.request.urlopen('http://localhost:3001/api/items?minutes=60',
                                        timeout=4) as r:
                raw_items = json.loads(r.read())
            if raw_items:
                _ws_log(f'fallback OK: {len(raw_items)} itens do Node.js')
                # Converte formato Node.js para formato de ordens brutas compatível
                # com _aplicar_ordens (mas em formato já processado)
                orders.append({'_fallback_items': raw_items})
        except Exception as e:
            _ws_log(f'fallback HTTP falhou: {e}')

    return resps, cidade, errors, orders


# ── Aplicativo ────────────────────────────────────────────────────────────────
class App(tk.Tk):
    BG      = '#0d0f14'
    BG2     = '#18181b'
    BG_ROW  = '#1a1d24'
    BORDER  = '#2a2a2f'
    FG      = '#e4e4e7'
    FG_DIM  = '#71717a'
    GREEN   = '#4ade80'
    YELLOW  = '#f59e0b'
    RED     = '#f87171'
    BTN_BG  = '#27272a'
    BTN_ACT = '#3f3f46'

    def __init__(self):
        super().__init__()
        self.title('Albion Market Scanner')
        self.geometry('1070x720')
        self.minsize(800, 520)
        self.configure(bg=self.BG)

        self._items         = []
        self._sort_col      = None
        self._sort_rev      = False
        self._node_proc     = None
        self._city_var      = tk.StringVar(value='Todas')
        self._time_var      = tk.StringVar(value='15 min')
        self._tax_var       = tk.DoubleVar(value=10.0)
        self._arb_sort       = 'lucro'
        self._arb_sort_rev   = True
        self._arb_history    = load_history_cache()
        self._arb_overrides  = {}   # (itemId, ench, qual) → {'precoCidade': N, 'precoBM': N}
        self._arb_row_map    = {}   # iid → row dict
        self._arb_fname      = tk.StringVar(value='')
        self._arb_min_pct    = tk.StringVar(value='')
        self._arb_tiers      = {i: tk.BooleanVar(value=True) for i in range(1, 9)}
        self._arb_enchs      = {i: tk.BooleanVar(value=True) for i in range(4)}
        self._status_var    = tk.StringVar(value='Iniciando servidor...')
        self._count_var     = tk.StringVar(value='')
        self._selected_city = tk.StringVar(value='')
        self._arb_mode      = tk.StringVar(value='bm_cidade')

        self._setup_styles()
        self._build()
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        threading.Thread(target=self._boot, daemon=True).start()

    # ── Estilos ───────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use('clam')

        s.configure('Treeview',
            background=self.BG2, foreground=self.FG,
            fieldbackground=self.BG2, borderwidth=0,
            rowheight=28, font=('Segoe UI', 9))

        s.configure('Treeview.Heading',
            background=self.BG, foreground=self.FG_DIM,
            borderwidth=0, relief='flat',
            font=('Segoe UI', 8, 'bold'))

        s.map('Treeview',
            background=[('selected', '#2d3748')],
            foreground=[('selected', self.FG)])

        s.map('Treeview.Heading',
            background=[('active', self.BORDER)],
            relief=[('active', 'flat')])

        s.configure('Vertical.TScrollbar',
            background=self.BORDER, troughcolor=self.BG,
            borderwidth=0, arrowsize=12)

        # dropdown list colors
        self.option_add('*TCombobox*Listbox.background',       self.BTN_BG)
        self.option_add('*TCombobox*Listbox.foreground',       self.FG)
        self.option_add('*TCombobox*Listbox.selectBackground', '#3f3f46')
        self.option_add('*TCombobox*Listbox.selectForeground', self.FG)

        s.configure('TCombobox',
            background=self.BTN_BG, foreground=self.FG,
            fieldbackground=self.BTN_BG, arrowcolor=self.FG_DIM,
            selectbackground=self.BTN_BG, selectforeground=self.FG,
            borderwidth=1, relief='flat')

        s.map('TCombobox',
            background=[('readonly', self.BTN_BG)],
            fieldbackground=[('readonly', self.BTN_BG)],
            foreground=[('readonly', self.FG)],
            selectbackground=[('readonly', self.BTN_BG)],
            selectforeground=[('readonly', self.FG)])

        s.configure('TNotebook', background=self.BG, borderwidth=0, tabmargins=[0, 0, 0, 0])
        s.configure('TNotebook.Tab',
            background=self.BTN_BG, foreground=self.FG_DIM,
            padding=[14, 5], borderwidth=0, font=('Segoe UI', 9))
        s.map('TNotebook.Tab',
            background=[('selected', self.BG)],
            foreground=[('selected', self.FG)])

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Barra superior ────────────────────────────────────────────────────
        top = tk.Frame(self, bg=self.BG2, height=58)
        top.pack(fill='x')
        top.pack_propagate(False)

        lft = tk.Frame(top, bg=self.BG2)
        lft.pack(side='left', fill='y', padx=(16, 0))

        tk.Label(lft, text='Albion Market', bg=self.BG2, fg=self.FG,
                 font=('Segoe UI', 12, 'bold')).pack(side='left', pady=16, padx=(0, 18))

        tk.Label(lft, text='Cidade:', bg=self.BG2, fg=self.FG_DIM,
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
        self._cmb_cidade = ttk.Combobox(lft, textvariable=self._selected_city,
                                         values=CAPTURE_CITIES, state='readonly',
                                         width=14, font=('Segoe UI', 9))
        self._cmb_cidade.pack(side='left', pady=12, padx=(0, 8))
        self._cmb_cidade.bind('<<ComboboxSelected>>', self._on_cidade_select)

        self.lbl_zona = tk.Label(lft, text='Selecione a cidade', bg=self.BG2,
                                  fg=self.FG_DIM, font=('Segoe UI', 8))
        self.lbl_zona.pack(side='left', padx=(0, 8))

        self.btn_capturar_zona = self._btn(lft, '⬡  Cap. zona',
                                            self._capturar_zona_1x,
                                            state='disabled', small=True)
        self.btn_capturar_zona.pack(side='left', pady=12)

        rgt = tk.Frame(top, bg=self.BG2)
        rgt.pack(side='right', fill='y', padx=(0, 16))

        self.lbl_timer = tk.Label(rgt, text='', bg=self.BG2,
                                   fg=self.RED, font=('Segoe UI', 10, 'bold'))
        self.lbl_timer.pack(side='left', padx=(0, 12))

        self.btn_start = self._btn(rgt, '▶  Iniciar Captura', self._iniciar_captura,
                                    state='disabled', fg=self.GREEN)
        self.btn_start.pack(side='left', pady=12, padx=(0, 6))

        self.btn_fin = self._btn(rgt, '■  Finalizar', self._finalizar,
                                  state='disabled', fg=self.RED)
        self.btn_fin.pack(side='left', pady=12)

        # ── Notebook (abas) ───────────────────────────────────────────────────
        tk.Frame(self, bg=self.BORDER, height=1).pack(fill='x')

        nb = ttk.Notebook(self)
        nb.pack(fill='both', expand=True, padx=0, pady=0)

        # ── Aba 1: Mercado ────────────────────────────────────────────────────
        tab1 = tk.Frame(nb, bg=self.BG)
        nb.add(tab1, text='  Mercado  ')

        def lbl(parent, text):
            return tk.Label(parent, text=text, bg=self.BG, fg=self.FG_DIM,
                            font=('Segoe UI', 8))

        fbar = tk.Frame(tab1, bg=self.BG, height=40)
        fbar.pack(fill='x')
        fbar.pack_propagate(False)

        lbl(fbar, 'Cidade:').pack(side='left', padx=(14, 4))
        cb_c = ttk.Combobox(fbar, textvariable=self._city_var, values=CITIES,
                              state='readonly', width=13, font=('Segoe UI', 8))
        cb_c.pack(side='left', pady=8)
        cb_c.bind('<<ComboboxSelected>>', lambda _: self._render_table())

        lbl(fbar, 'Período:').pack(side='left', padx=(14, 4))
        cb_t = ttk.Combobox(fbar, textvariable=self._time_var,
                              values=[l for l, _ in TIME_OPTS],
                              state='readonly', width=8, font=('Segoe UI', 8))
        cb_t.pack(side='left', pady=8)
        cb_t.bind('<<ComboboxSelected>>', lambda _: self._force_fetch())

        self._btn(fbar, 'Limpar dados', self._clear, small=True).pack(
            side='left', padx=(12, 0), pady=8)
        self._btn(fbar, 'Limpar cidade', self._clear_city, small=True).pack(
            side='left', padx=(6, 0), pady=8)

        self.lbl_upd = tk.Label(fbar, text='', bg=self.BG,
                                  fg=self.FG_DIM, font=('Segoe UI', 8))
        self.lbl_upd.pack(side='right', padx=14)

        self.lbl_cnt = tk.Label(fbar, textvariable=self._count_var,
                                  bg=self.BG, fg=self.FG_DIM, font=('Segoe UI', 8, 'bold'))
        self.lbl_cnt.pack(side='right', padx=(0, 4))

        tk.Frame(tab1, bg=self.BORDER, height=1).pack(fill='x')

        wrap1 = tk.Frame(tab1, bg=self.BG2)
        wrap1.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(wrap1, columns=[c[0] for c in COLS],
                                   show='headings', selectmode='browse')
        vsb1 = ttk.Scrollbar(wrap1, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb1.set)
        vsb1.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)

        for col_id, label, width, anchor in COLS:
            self.tree.heading(col_id, text=label,
                              command=lambda c=col_id: self._sort_by(c))
            self.tree.column(col_id, width=width, anchor=anchor, minwidth=40,
                             stretch=(col_id == 'item'))

        self.tree.tag_configure('odd',  background=self.BG2)
        self.tree.tag_configure('even', background=self.BG_ROW)

        # ── Aba 2: Arbitragem BM ──────────────────────────────────────────────
        tab2 = tk.Frame(nb, bg=self.BG)
        nb.add(tab2, text='  Arbitragem BM  ')

        abar = tk.Frame(tab2, bg=self.BG, height=40)
        abar.pack(fill='x')
        abar.pack_propagate(False)

        lbl(abar, 'Modo:').pack(side='left', padx=(14, 4))
        for val, txt in (('bm_cidade', 'Pedido de venda'),):
            tk.Radiobutton(abar, text=txt, variable=self._arb_mode, value=val,
                           bg=self.BG, fg=self.FG, selectcolor=self.BG2,
                           activebackground=self.BG, activeforeground=self.FG,
                           font=('Segoe UI', 8), cursor='hand2',
                           command=self._render_arb_table).pack(side='left', padx=(0, 8))

        tk.Frame(abar, bg=self.BORDER, width=1).pack(side='left', fill='y', padx=(4, 8), pady=6)

        lbl(abar, 'Taxa %:').pack(side='left', padx=(0, 4))
        tax_sb = tk.Spinbox(abar, textvariable=self._tax_var,
                            from_=0, to=25, increment=0.5, width=6, format='%.1f',
                            bg=self.BTN_BG, fg=self.FG, insertbackground=self.FG,
                            buttonbackground=self.BTN_BG, relief='flat',
                            font=('Segoe UI', 8), command=self._render_arb_table)
        tax_sb.pack(side='left', pady=8)
        tax_sb.bind('<Return>', lambda _: self._render_arb_table())

        self.lbl_arb_cnt = tk.Label(abar, text='', bg=self.BG,
                                     fg=self.FG_DIM, font=('Segoe UI', 8, 'bold'))
        self.lbl_arb_cnt.pack(side='right', padx=14)

        tk.Frame(tab2, bg=self.BORDER, height=1).pack(fill='x')

        # ── Barra de filtros da aba de Arbitragem ────────────────────────────
        fbar2 = tk.Frame(tab2, bg=self.BG, height=32)
        fbar2.pack(fill='x')
        fbar2.pack_propagate(False)

        lbl(fbar2, 'Nome:').pack(side='left', padx=(10, 4))
        nome_e = tk.Entry(fbar2, textvariable=self._arb_fname, width=18,
                          bg=self.BTN_BG, fg=self.FG, insertbackground=self.FG,
                          relief='flat', font=('Segoe UI', 8))
        nome_e.pack(side='left', pady=6)
        nome_e.bind('<KeyRelease>', lambda _: self._render_arb_table())

        tk.Frame(fbar2, bg=self.BORDER, width=1).pack(side='left', fill='y', padx=(8, 6), pady=5)

        lbl(fbar2, 'Tier:').pack(side='left', padx=(0, 4))
        for t in range(1, 9):
            tk.Checkbutton(fbar2, text=f'T{t}', variable=self._arb_tiers[t],
                           bg=self.BG, fg=self.FG, selectcolor=self.BG2,
                           activebackground=self.BG, activeforeground=self.FG,
                           font=('Segoe UI', 8), cursor='hand2',
                           command=self._render_arb_table).pack(side='left', padx=1)

        tk.Frame(fbar2, bg=self.BORDER, width=1).pack(side='left', fill='y', padx=(6, 6), pady=5)

        lbl(fbar2, 'Enc.:').pack(side='left', padx=(0, 4))
        for e, lbl_txt in enumerate(['.0', '.1', '.2', '.3']):
            tk.Checkbutton(fbar2, text=lbl_txt, variable=self._arb_enchs[e],
                           bg=self.BG, fg=self.FG, selectcolor=self.BG2,
                           activebackground=self.BG, activeforeground=self.FG,
                           font=('Segoe UI', 8), cursor='hand2',
                           command=self._render_arb_table).pack(side='left', padx=1)

        tk.Frame(fbar2, bg=self.BORDER, width=1).pack(side='left', fill='y', padx=(6, 6), pady=5)

        lbl(fbar2, 'Lucro % ≥:').pack(side='left', padx=(0, 4))
        pct_e = tk.Entry(fbar2, textvariable=self._arb_min_pct, width=6,
                         bg=self.BTN_BG, fg=self.FG, insertbackground=self.FG,
                         relief='flat', font=('Segoe UI', 8), justify='right')
        pct_e.pack(side='left', pady=6)
        pct_e.bind('<KeyRelease>', lambda _: self._render_arb_table())

        tk.Frame(tab2, bg=self.BORDER, height=1).pack(fill='x')

        wrap2 = tk.Frame(tab2, bg=self.BG2)
        wrap2.pack(fill='both', expand=True)

        self.arb_tree = ttk.Treeview(wrap2, columns=[c[0] for c in ARB_COLS],
                                      show='headings', selectmode='browse')
        vsb2 = ttk.Scrollbar(wrap2, orient='vertical', command=self.arb_tree.yview)
        self.arb_tree.configure(yscrollcommand=vsb2.set)
        vsb2.pack(side='right', fill='y')
        self.arb_tree.pack(fill='both', expand=True)

        _arb_heading_labels = {
            'preco_bm':  'BM ordem venda',
            'preco_cid': 'Preço cidade',
        }
        for col_id, label, width, anchor in ARB_COLS:
            self.arb_tree.heading(col_id,
                                   text=_arb_heading_labels.get(col_id, label),
                                   command=lambda c=col_id: self._sort_arb_by(c))
            self.arb_tree.column(col_id, width=width, anchor=anchor, minwidth=40,
                                  stretch=(col_id == 'item'))

        self.arb_tree.tag_configure('odd',      background=self.BG2)
        self.arb_tree.tag_configure('even',     background=self.BG_ROW)
        self.arb_tree.tag_configure('green',    foreground='#4ade80')
        self.arb_tree.tag_configure('red',      foreground='#f87171')
        self.arb_tree.tag_configure('edited',   foreground='#f59e0b')
        self.arb_tree.bind('<Double-1>', self._arb_double_click)

        # ── Status bar ────────────────────────────────────────────────────────
        tk.Frame(self, bg=self.BORDER, height=1).pack(fill='x')
        sbar = tk.Frame(self, bg=self.BG, height=24)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)
        tk.Label(sbar, textvariable=self._status_var, bg=self.BG,
                 fg=self.FG_DIM, font=('Segoe UI', 8)).pack(side='left', padx=12, pady=3)

    def _btn(self, parent, text, cmd, state='normal', fg=None, small=False):
        return tk.Button(
            parent, text=text, command=cmd, state=state,
            bg=self.BTN_BG, fg=fg or self.FG,
            activebackground=self.BTN_ACT, activeforeground=self.FG,
            relief='flat', bd=0, highlightthickness=0,
            font=('Segoe UI', 8 if small else 9),
            cursor='hand2',
            padx=8 if small else 12,
            pady=3 if small else 6,
        )

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status_var.set(msg))

    # ── Inicialização ─────────────────────────────────────────────────────────
    def _boot(self):
        load_item_names()
        self._items = load_store()
        n_cache = len(_item_names)
        n_items = len(self._items)
        self._set_status(f'{n_cache} nomes em cache. Iniciando servidor...')
        threading.Thread(target=enrich_names, args=(self,), daemon=True).start()
        self._start_node()

        time.sleep(3)
        if n_items:
            self.after(0, self._render_table)
            msg = f'{n_items} itens carregados do histórico. Selecione a cidade e inicie a captura.'
        else:
            msg = 'Pronto. Selecione a cidade e inicie a captura.'
        self._set_status(msg)
        self.after(3100, self._schedule_refresh)

    def _start_node(self):
        try:
            subprocess.run('taskkill /F /IM node.exe', shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.3)
            self._node_proc = subprocess.Popen(
                'npm start', shell=True, cwd=SCANNER_DIR,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)  # CREATE_NO_WINDOW
        except Exception as e:
            self._set_status(f'Erro ao iniciar servidor: {e}')

    # ── Refresh periódico ─────────────────────────────────────────────────────
    def _schedule_refresh(self):
        self._render_table()
        self.after(REFRESH_MS, self._schedule_refresh)

    def _force_fetch(self):
        self._render_table()

    # ── Tabela ────────────────────────────────────────────────────────────────
    def _render_table(self):
        items = list(self._items)

        # filtro local de cidade
        city = self._city_var.get()
        if city != 'Todas':
            items = [i for i in items if i.get('location') == city]

        if self._sort_col:
            def key(it):
                c = self._sort_col
                if c == 'item':      return parse_name(it.get('itemId', ''), it.get('enchantment', 0))
                if c == 'cidade':    return it.get('location', '')
                if c == 'qual':      return it.get('quality', 0)
                if c == 'venda_min': return it.get('minSell') or 0
                if c == 'qtd_venda': return it.get('totalSellQty') or 0
                if c == 'media_24h': return it.get('avgPrice24h') or 0
                if c == 'capturado': return it.get('capturedAt', '')
                return ''
            items.sort(key=key, reverse=self._sort_rev)

        # preserva larguras definidas pelo usuário
        saved_widths = {c[0]: self.tree.column(c[0], 'width') for c in COLS}

        for row in self.tree.get_children():
            self.tree.delete(row)

        for i, it in enumerate(items):
            qual_n = it.get('quality', 1)
            avg    = it.get('avgPrice24h')
            self.tree.insert('', 'end', tags=('odd' if i % 2 else 'even',), values=(
                parse_name(it.get('itemId', ''), it.get('enchantment', 0)),
                it.get('location', '-'),
                QUALITY_NAMES.get(qual_n, str(qual_n)),
                fmt(it.get('minSell')),
                it.get('totalSellQty') or '-',
                fmt(avg) if avg else ('...' if avg is None else '-'),
                time_ago(it.get('capturedAt', '')),
            ))

        # restaura larguras após o re-render
        for col_id, w in saved_widths.items():
            self.tree.column(col_id, width=w)

        n = len(items)
        self._count_var.set(f'{n} {"item" if n == 1 else "itens"}')
        self.lbl_upd.config(text=f'atualizado {time.strftime("%H:%M:%S")}')
        if n > 0:
            self._status_var.set(f'✓  {n} itens na tabela — atualizado {time.strftime("%H:%M:%S")}')

        self._render_arb_table()

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        for c, label, _, _ in COLS:
            arrow = (' ↑' if self._sort_rev else ' ↓') if c == col else ''
            self.tree.heading(c, text=label + arrow)
        self._render_table()

    def _sort_arb_by(self, col: str):
        if self._arb_sort == col:
            self._arb_sort_rev = not self._arb_sort_rev
        else:
            self._arb_sort = col
            self._arb_sort_rev = col in ('lucro', 'lucro_pct', 'preco_bm', 'preco_cid',
                                          'vol24h', 'med24h', 'qty_bm', 'qty_venda')
        _arb_heading_labels = {
            'preco_bm':  'BM ordem venda',
            'preco_cid': 'Preço cidade',
        }
        for c, label, _, _ in ARB_COLS:
            base = _arb_heading_labels.get(c, label)
            arrow = (' ↑' if self._arb_sort_rev else ' ↓') if c == col else ''
            self.arb_tree.heading(c, text=base + arrow)
        self._render_arb_table()

    def _compute_arbitragem(self) -> list:
        tax  = self._tax_var.get() / 100

        bm_data:   dict = {}  # (itemId, ench, qual) → {maxBuy, minSell, maxSell, qtyBuy, qtySell}
        city_best: dict = {}  # (itemId, ench, qual) → {minSell, location}

        for it in self._items:
            key = (it['itemId'], it.get('enchantment', 0), it.get('quality', 1))
            loc = it.get('location', '')
            if loc == 'Black Market':
                if key not in bm_data:
                    bm_data[key] = {'maxBuy': None, 'minSell': None, 'maxSell': None, 'qtyBuy': 0, 'qtySell': 0}
                buy  = it.get('maxBuy')
                sell = it.get('minSell')
                max_sell = it.get('maxSell')
                # maxBuy: pedido de compra real (AuctionType='request', raro no BM)
                if buy and (bm_data[key]['maxBuy'] is None or buy > bm_data[key]['maxBuy']):
                    bm_data[key]['maxBuy'] = buy
                    bm_data[key]['qtyBuy'] = it.get('totalBuyQty') or 0
                # Para cada entrada BM, guarda {minSell, maxSell} da entrada com MENOR minSell
                # (essa é a entrada dos pedidos de compra do BM — preços menores)
                # e da entrada com MAIOR minSell (pedidos de venda dos jogadores — preços maiores)
                if sell:
                    cur_min = bm_data[key]['minSell']
                    if cur_min is None or sell < cur_min:
                        # nova entrada com preço menor = pedidos de compra
                        bm_data[key]['minSell']             = sell
                        bm_data[key]['_maxSell_of_min_entry'] = max_sell  # maior pedido de compra
                        bm_data[key]['qtySell']             = it.get('totalSellQty') or 0
                    if bm_data[key]['maxSell'] is None or sell > bm_data[key]['maxSell']:
                        # entrada com preço maior = pedidos de venda dos jogadores
                        bm_data[key]['maxSell'] = sell
            else:
                sell = it.get('minSell')
                if sell:
                    if key not in city_best or sell < city_best[key]['minSell']:
                        city_best[key] = {'minSell': sell, 'location': loc}

        results = []
        # Compra na cidade (minSell) → posta ordem de venda no BM
        # maxSell do BM = preço mais alto = pedidos de venda dos jogadores (referência para postar)
        for key, bm in bm_data.items():
            bm_price = bm['maxSell']
            if not bm_price or key not in city_best:
                continue
            city      = city_best[key]
            city_sell = city['minSell']
            net       = round(bm_price * (1 - tax))
            lucro     = net - city_sell
            pct       = lucro / city_sell * 100 if city_sell > 0 else 0
            item_id, ench, qual = key
            results.append({
                'itemId': item_id, 'enchantment': ench, 'quality': qual,
                'location': city['location'],
                'precoCidade': city_sell, 'precoBM': bm_price,
                'lucro': lucro, 'lucroPct': pct,
                'qtyBm': bm['qtyBuy'], 'qtyVenda': bm['qtySell'],
            })
        return results

    def _fetch_arb_history_bg(self, keys):
        import concurrent.futures, urllib.request
        from datetime import datetime, timezone, timedelta
        BASE   = 'https://west.albion-online-data.com/api/v2/stats/charts'
        now_ts = time.time()
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=24)

        # Filtra só os que não estão em cache válido
        to_fetch = []
        for key in keys:
            cache_key = f'{key[0]}|{key[1]}|{key[2]}'
            entry = self._arb_history.get(cache_key)
            if not entry or (now_ts - entry.get('_ts', 0)) > HISTORY_TTL:
                to_fetch.append(key)

        if not to_fetch:
            self.after(0, self._render_arb_table)
            return

        def fetch_one(key):
            item_id, ench, qual = key
            full_id = f'{item_id}@{ench}' if ench else item_id
            url = f'{BASE}/{full_id}?locations=Black+Market&time-scale=1&qualities={qual}'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'AlbionScanner/1.0'})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.loads(r.read())
                if not data:
                    return key, None
                entry = next((d for d in data if d.get('quality') == qual), data[0])
                d      = entry.get('data', {})
                tss    = d.get('timestamps', [])
                counts = d.get('item_count', [])
                prices = d.get('prices_avg', [])
                vol24h = 0; p_sum = 0; p_cnt = 0
                for ts, cnt, price in zip(tss, counts, prices):
                    try:
                        t = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        if t >= cutoff_dt:
                            vol24h += cnt or 0
                            if price > 0:
                                p_sum += price * (cnt or 1)
                                p_cnt += cnt or 1
                    except Exception:
                        pass
                avg = round(p_sum / p_cnt) if p_cnt > 0 else 0
                return key, {'vol24h': vol24h, 'avg24h': avg, '_ts': now_ts}
            except Exception:
                return key, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for key, result in pool.map(fetch_one, to_fetch):
                if result is not None:
                    cache_key = f'{key[0]}|{key[1]}|{key[2]}'
                    self._arb_history[cache_key] = result

        save_history_cache(self._arb_history)
        self.after(0, self._render_arb_table)

    def _arb_double_click(self, event):
        item = self.arb_tree.identify_row(event.y)
        col  = self.arb_tree.identify_column(event.x)
        if not item or not col:
            return
        col_idx = int(col.replace('#', '')) - 1
        col_ids = [c[0] for c in ARB_COLS]
        if col_idx >= len(col_ids) or col_ids[col_idx] not in ('preco_cid', 'preco_bm'):
            return
        field   = 'precoCidade' if col_ids[col_idx] == 'preco_cid' else 'precoBM'
        bbox    = self.arb_tree.bbox(item, col)
        if not bbox:
            return
        x, y, w, h = bbox

        row = self._arb_row_map.get(item)
        if not row:
            return
        key     = (row['itemId'], row['enchantment'], row['quality'])
        current = self._arb_overrides.get(key, {}).get(field, row[field])

        entry = tk.Entry(self.arb_tree, font=('Segoe UI', 9),
                         bg='#2a2d36', fg='#f59e0b', insertbackground='#f59e0b',
                         relief='flat', bd=1, justify='right')
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, str(current))
        entry.select_range(0, 'end')
        entry.focus_set()

        def commit(ev=None):
            val_str = entry.get().strip().replace('.', '').replace(',', '').replace(' ', '')
            entry.destroy()
            try:
                val = int(val_str)
            except ValueError:
                return
            ov = self._arb_overrides.setdefault(key, {})
            ov[field] = val
            self._render_arb_table()

        def cancel(ev=None):
            entry.destroy()

        def clear_and_commit(ev=None):
            entry.destroy()
            ov = self._arb_overrides.get(key, {})
            ov.pop(field, None)
            if not ov:
                self._arb_overrides.pop(key, None)
            self._render_arb_table()

        entry.bind('<Return>',  commit)
        entry.bind('<Escape>',  cancel)
        entry.bind('<Delete>',  clear_and_commit)
        entry.bind('<FocusOut>', commit)

    def _render_arb_table(self):
        rows = self._compute_arbitragem()
        tax  = self._tax_var.get() / 100

        # Aplica overrides ANTES de ordenar para que a posição reflita os valores editados
        for idx, r in enumerate(rows):
            key = (r['itemId'], r['enchantment'], r['quality'])
            ov  = self._arb_overrides.get(key, {})
            if ov:
                r = dict(r)
                r['precoCidade'] = ov.get('precoCidade', r['precoCidade'])
                r['precoBM']     = ov.get('precoBM',     r['precoBM'])
                net              = round(r['precoBM'] * (1 - tax))
                r['lucro']       = net - r['precoCidade']
                r['lucroPct']    = r['lucro'] / r['precoCidade'] * 100 if r['precoCidade'] > 0 else 0
                rows[idx]        = r

        # Filtros
        fname = self._arb_fname.get().strip().lower()
        active_tiers = {t for t, v in self._arb_tiers.items() if v.get()}
        active_enchs = {e for e, v in self._arb_enchs.items() if v.get()}
        try:
            min_pct = float(self._arb_min_pct.get().replace(',', '.').replace('%', '').strip())
        except ValueError:
            min_pct = None

        def _tier(item_id):
            try: return int(item_id[1])
            except: return 0

        rows = [r for r in rows
                if _tier(r['itemId']) in active_tiers
                and r['enchantment'] in active_enchs
                and (not fname or fname in parse_name(r['itemId'], r['enchantment']).lower())
                and (min_pct is None or r['lucroPct'] >= min_pct)]

        _ARB_SORT_KEY = {
            'item':      lambda r: parse_name(r['itemId'], r['enchantment']).lower(),
            'qual':      lambda r: r.get('quality', 0),
            'cidade':    lambda r: r.get('location', ''),
            'preco_cid': lambda r: r.get('precoCidade') or 0,
            'preco_bm':  lambda r: r.get('precoBM') or 0,
            'lucro':     lambda r: r.get('lucro') or 0,
            'lucro_pct': lambda r: r.get('lucroPct') or 0,
            'qty_bm':    lambda r: r.get('qtyBm') or 0,
            'qty_venda': lambda r: r.get('qtyVenda') or 0,
            'vol24h':    lambda r: (self._arb_history.get(
                             f"{r['itemId']}|{r['enchantment']}|{r['quality']}") or {}).get('vol24h') or 0,
            'med24h':    lambda r: (self._arb_history.get(
                             f"{r['itemId']}|{r['enchantment']}|{r['quality']}") or {}).get('avg24h') or 0,
        }
        col = self._arb_sort
        sort_fn = _ARB_SORT_KEY.get(col, lambda r: r.get('lucro') or 0)
        rows.sort(key=sort_fn, reverse=self._arb_sort_rev)

        saved = {c[0]: self.arb_tree.column(c[0], 'width') for c in ARB_COLS}
        for row in self.arb_tree.get_children():
            self.arb_tree.delete(row)

        now_ts    = time.time()
        missing   = []
        self._arb_row_map.clear()
        for i, r in enumerate(rows):
            key = (r['itemId'], r['enchantment'], r['quality'])
            ov  = self._arb_overrides.get(key, {})

            lucro     = r['lucro']
            base_tag  = 'odd' if i % 2 else 'even'
            color_tag = 'green' if lucro > 0 else 'red'
            edit_tag  = ('edited',) if ov else ()
            pct_str   = f"{r['lucroPct']:+.1f}%"
            qty_bm    = r.get('qtyBm') or 0
            qty_venda = r.get('qtyVenda') or 0
            cache_key = f"{r['itemId']}|{r['enchantment']}|{r['quality']}"
            hist      = self._arb_history.get(cache_key)
            if not hist or (now_ts - hist.get('_ts', 0)) > HISTORY_TTL:
                missing.append((r['itemId'], r['enchantment'], r['quality']))
                vol_str = '…'
                med_str = '…'
            else:
                vol_str = str(hist['vol24h']) if hist['vol24h'] else '—'
                med_str = fmt(hist['avg24h']) if hist['avg24h'] else '—'
            iid = f"{r['itemId']}|{r['enchantment']}|{r['quality']}"
            try:
                self.arb_tree.insert('', 'end', iid=iid,
                                     tags=(base_tag, color_tag) + edit_tag, values=(
                    parse_name(r['itemId'], r['enchantment']),
                    QUALITY_NAMES.get(r['quality'], str(r['quality'])),
                    r['location'],
                    fmt(r['precoCidade']),
                    fmt(r['precoBM']),
                    fmt(lucro),
                    pct_str,
                    str(qty_bm)    if qty_bm    else '—',
                    str(qty_venda) if qty_venda else '—',
                    vol_str,
                    med_str,
                ))
            except tk.TclError:
                # iid duplicado (mesma combinação item+ench+qual de cidade diferente)
                iid = f"{r['itemId']}|{r['enchantment']}|{r['quality']}|{i}"
                self.arb_tree.insert('', 'end', iid=iid,
                                     tags=(base_tag, color_tag) + edit_tag, values=(
                    parse_name(r['itemId'], r['enchantment']),
                    QUALITY_NAMES.get(r['quality'], str(r['quality'])),
                    r['location'],
                    fmt(r['precoCidade']),
                    fmt(r['precoBM']),
                    fmt(lucro),
                    pct_str,
                    str(qty_bm)    if qty_bm    else '—',
                    str(qty_venda) if qty_venda else '—',
                    vol_str,
                    med_str,
                ))
            self._arb_row_map[iid] = r
        if missing:
            threading.Thread(target=self._fetch_arb_history_bg,
                             args=(missing,), daemon=True).start()

        for col_id, w in saved.items():
            self.arb_tree.column(col_id, width=w)

        n = len(rows)
        self.lbl_arb_cnt.config(text=f'{n} {"oportunidade" if n == 1 else "oportunidades"}')

    def _clear(self):
        try:
            req = urllib.request.Request(API_BASE + '/api/clear', method='POST')
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass
        self._items = []
        save_store([])
        self._render_table()
        self._set_status('Dados limpos.')

    def _clear_city(self):
        city = self._city_var.get()
        if not city or city == 'Todas':
            self._set_status('Selecione uma cidade no filtro antes de limpar.')
            return
        before = len(self._items)
        self._items = [it for it in self._items if it.get('location') != city]
        removed = before - len(self._items)
        save_store(self._items)
        self._render_table()
        self._set_status(f'{removed} itens de {city} removidos.')

    # ── Zona: seleção manual + captura única ──────────────────────────────────
    def _atualizar_ui_zona(self, zona_ok: bool):
        """Atualiza status da zona e habilita/desabilita botões conforme estado."""
        city = self._selected_city.get()
        if zona_ok:
            self.btn_capturar_zona.config(state='disabled')
            if city:
                self.lbl_zona.config(text='✓  Zona pronta', fg=self.GREEN)
                self.btn_start.config(state='normal')
            else:
                self.lbl_zona.config(text='Selecione a cidade', fg=self.FG_DIM)
                self.btn_start.config(state='disabled')
        else:
            self.lbl_zona.config(text='⚠  Capture zona 1x', fg=self.YELLOW)
            self.btn_capturar_zona.config(state='normal')
            self.btn_start.config(state='disabled')

    def _on_cidade_select(self, _=None):
        """Chamado quando o usuário seleciona uma cidade no combobox."""
        city = self._selected_city.get()
        z_pcap = CITY_ZONE_PCAP.get(city, PCAP_ZONE)
        zona_ok = os.path.exists(z_pcap)
        self._atualizar_ui_zona(zona_ok)
        if zona_ok and city:
            self._set_status(f'Cidade: {city}. Inicie a captura quando estiver no mercado.')

    def _capturar_zona_1x(self):
        """Captura o PCAP de zona da cidade selecionada (necessário 1x por cidade)."""
        city = self._selected_city.get()
        if not city:
            return
        self._zona_pcap_destino = CITY_ZONE_PCAP.get(city, PCAP_ZONE)
        self.btn_capturar_zona.config(state='disabled')
        self.btn_start.config(state='disabled')
        self._zone_stop = threading.Event()
        hint = 'Caerleon' if city == 'Black Market' else city
        self._set_status(f'Troque de mapa para {hint} agora (tela de loading)...')
        self._zone_countdown(25)
        threading.Thread(target=self._detect_zone_bg, daemon=True).start()

    def _zone_countdown(self, n: int):
        if self._zone_stop.is_set():
            return
        self.lbl_zona.config(text=f'⏳ Troque de mapa ({n}s)...', fg=self.YELLOW)
        if n > 0:
            self.after(1000, self._zone_countdown, n - 1)

    def _detect_zone_bg(self):
        pcap = getattr(self, '_zona_pcap_destino', PCAP_ZONE)
        CHUNK, TOTAL = 5, 25
        try:
            for i in range(TOTAL // CHUNK):
                if self._zone_stop.is_set():
                    return
                capturar_para(pcap, seconds=CHUNK, append=(i > 0))
                _, detected, _, _ = processar_pcap(pcap)
                if detected:
                    self._zone_stop.set()
                    self.after(0, self._zona_capturada_ok)
                    return
        except Exception as e:
            self._zone_stop.set()
            self.after(0, self._zona_capturada_fail, str(e))
            return
        self._zone_stop.set()
        self.after(0, self._zona_capturada_fail)

    def _zona_capturada_ok(self):
        city = self._selected_city.get()
        self.lbl_zona.config(text='✓  Zona pronta', fg=self.GREEN)
        self.btn_capturar_zona.config(state='disabled')
        if city:
            self.btn_start.config(state='normal')
            self._set_status(f'Zona pronta. Inicie a captura em {city}.')
        else:
            self._set_status('Zona pronta. Selecione a cidade e inicie a captura.')

    def _zona_capturada_fail(self, _=''):
        self.lbl_zona.config(text='⚠  Capture zona 1x', fg=self.YELLOW)
        self.btn_capturar_zona.config(state='normal')
        self._set_status('Zona não detectada. Troque de mapa e tente novamente.')

    # ── Captura de mercado ────────────────────────────────────────────────────
    def _iniciar_captura(self):
        stop_capture.clear()
        self._cmb_cidade.config(state='disabled')
        self.btn_capturar_zona.config(state='disabled')
        self.btn_start.config(state='disabled')
        self.btn_fin.config(state='normal')
        self._tick_start = time.time()
        self._tick()
        self._set_status('Capturando — navegue no mercado por quanto tempo quiser.')
        threading.Thread(
            target=lambda: capturar_para(PCAP_MAIN, stop_ev=stop_capture),
            daemon=True).start()

    def _tick(self):
        if not stop_capture.is_set():
            s = int(time.time() - self._tick_start)
            m, sec = divmod(s, 60)
            self.lbl_timer.config(text=f'⏺  {m:02d}:{sec:02d}')
            self.after(1000, self._tick)
        else:
            self.lbl_timer.config(text='')

    def _finalizar(self):
        stop_capture.set()
        self.btn_fin.config(state='disabled')
        self._set_status('Processando dados capturados...')
        threading.Thread(target=self._processar_final, daemon=True).start()

    def _processar_final(self):
        city = self._selected_city.get()
        z_pcap = CITY_ZONE_PCAP.get(city, PCAP_ZONE)
        pcap = _combinar_pcaps(z_pcap, PCAP_MAIN, PCAP_COMBINED)
        resps, _, errors, orders = processar_pcap(pcap)
        self.after(0, self._pos_processar, resps, city, errors, orders)

    def _pos_processar(self, resps: int, cidade: str, errors: int, orders: list):
        self._cmb_cidade.config(state='readonly')
        self.btn_start.config(state='normal')
        if resps > 0:
            loc = cidade or 'mercado'
            novos = self._aplicar_ordens(orders)
            self._render_table()
            self._set_status(f'✓  {resps} respostas de {loc} — {novos} grupos na tabela.')
            self._buscar_medias_24h()
        elif errors > 0:
            self._set_status('✗  Dados sem localização — clique "Cap. zona" e troque de mapa uma vez.')
        else:
            self._set_status('Nenhuma ordem de mercado encontrada nesta captura.')

    def _aplicar_ordens(self, orders: list) -> int:
        """Processa lista de ordens brutas e atualiza self._items diretamente."""
        # Caso fallback: Node.js já retornou itens processados
        if len(orders) == 1 and '_fallback_items' in orders[0]:
            fb = orders[0]['_fallback_items']
            store: dict = {f"{it['itemId']}|{it.get('location_raw', it['location'])}|{it['quality']}|{it['enchantment']}": it
                           for it in self._items if 'itemId' in it}
            for it in fb:
                raw = it.get('location_raw') or it['location']
                key = f"{it['itemId']}|{raw}|{it['quality']}|{it['enchantment']}"
                store[key] = {**it, 'location_raw': raw}
            self._items = list(store.values())
            snapshot = list(self._items)
            threading.Thread(target=save_store, args=(snapshot,), daemon=True).start()
            return len(fb)

        now = datetime.now(timezone.utc).isoformat()
        grouped: dict = {}
        for o in orders:
            key = (f"{o.get('ItemTypeId','')}"
                   f"|{o.get('LocationId','')}"
                   f"|{o.get('QualityLevel',0)}"
                   f"|{o.get('EnchantmentLevel',0)}")
            if key not in grouped:
                grouped[key] = {'sells': [], 'buys': []}
            price = round(o.get('UnitPriceSilver', 0) / 10000)
            if o.get('AuctionType') == 'offer':
                grouped[key]['sells'].append({'price': price, 'amount': o.get('Amount', 0)})
            else:
                grouped[key]['buys'].append({'price': price, 'amount': o.get('Amount', 0)})

        # Reconstrói self._items mantendo dados anteriores
        store = {f"{it['itemId']}|{it.get('location_raw', it['location'])}|{it['quality']}|{it['enchantment']}": it
                 for it in self._items if 'itemId' in it}

        for key, data in grouped.items():
            item_id, loc_id, qual, ench = key.split('|')
            loc_name = LOCATION_NAMES.get(loc_id, loc_id)
            sells_sorted = sorted(data['sells'], key=lambda x: x['price'])
            store[key] = {
                'itemId':       item_id,
                'location':     loc_name,
                'location_raw': loc_id,
                'quality':      int(qual),
                'enchantment':  int(ench),
                'minSell':      sells_sorted[0]['price'] if sells_sorted else None,
                'maxSell':      sells_sorted[-1]['price'] if sells_sorted else None,
                'totalSellQty': sum(s['amount'] for s in data['sells']),
                'maxBuy':       (sorted(data['buys'], key=lambda x: x['price'], reverse=True)[0]['price']
                                 if data['buys'] else None),
                'totalBuyQty':  sum(b['amount'] for b in data['buys']),
                'capturedAt':   now,
            }

        self._items = list(store.values())
        snapshot = list(self._items)
        threading.Thread(target=save_store, args=(snapshot,), daemon=True).start()
        return len(grouped)

    # ── Média 24h ─────────────────────────────────────────────────────────────
    def _buscar_medias_24h(self):
        threading.Thread(target=self._fetch_avgs_bg, daemon=True).start()

    def _fetch_avgs_bg(self):
        items_snap = list(self._items)
        if not items_snap:
            return

        # Agrupa por cidade para minimizar chamadas à API
        by_city: dict = {}
        for it in items_snap:
            city = it.get('location', '')
            if not city or city == 'Black Market':
                continue
            cache_key = (f"{it['itemId']}@{it['enchantment']}"
                         if it.get('enchantment') else it['itemId'],
                         city, it.get('quality', 1))
            if cache_key in _avg_cache:
                continue
            by_city.setdefault(city, []).append((it, cache_key))

        for city, entries in by_city.items():
            BATCH = 15
            for start in range(0, len(entries), BATCH):
                batch = entries[start:start + BATCH]
                item_ids = ','.join(ck[0] for _, ck in batch)
                quals    = ','.join(str(ck[2]) for _, ck in batch)
                url = (f'{ALBION_DATA_API}/{item_ids}'
                       f'?locations={urllib.parse.quote(city)}'
                       f'&qualities={quals}&time-scale=24')
                try:
                    req = urllib.request.Request(
                        url, headers={'User-Agent': 'AlbionMarketScanner/1.0'})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = json.loads(r.read())
                    for entry in data:
                        raw_id = entry.get('item_id', '')
                        base_id = re.sub(r'@\d+', '', raw_id)
                        ench_m = re.search(r'@(\d+)', raw_id)
                        ench = int(ench_m.group(1)) if ench_m else 0
                        api_id = f'{base_id}@{ench}' if ench else base_id
                        ck = (api_id, entry.get('city', ''), entry.get('quality', 1))
                        avgs = entry.get('data', {}).get('prices_avg', [])
                        _avg_cache[ck] = int(avgs[-1]) if avgs and avgs[-1] else 0
                except Exception as e:
                    _ws_log(f'avg API error [{city}]: {e}')

        # Aplica cache nos items e re-renderiza
        changed = False
        for it in self._items:
            ench = it.get('enchantment', 0)
            api_id = f"{it['itemId']}@{ench}" if ench else it['itemId']
            ck = (api_id, it.get('location', ''), it.get('quality', 1))
            if ck in _avg_cache and 'avgPrice24h' not in it:
                it['avgPrice24h'] = _avg_cache[ck] or None
                changed = True

        if changed:
            self.after(0, self._render_table)

    # ── Fechar ────────────────────────────────────────────────────────────────
    def _on_close(self):
        stop_capture.set()
        if self._node_proc:
            self._node_proc.terminate()
        self.destroy()


# ── Entrada ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    os.makedirs(r'C:\temp', exist_ok=True)

    # Oculta a janela de console do Windows
    if sys.platform == 'win32':
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    try:
        App().mainloop()
    except Exception:
        import traceback
        try:
            from tkinter import messagebox
            messagebox.showerror('Erro fatal', traceback.format_exc())
        except Exception:
            print(traceback.format_exc())
            input('Enter para fechar...')
