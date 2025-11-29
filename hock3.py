# -*- coding: utf-8 -*-
# BUG CODE BY CTEVCL ENCODER - ANTI-CRASH VERSION
# MODE: DELAYED INJECTION + RECURSION GUARD (FIX KILLED ERROR)

import sys
import os
import threading
import traceback
import runpy
import json
import gzip
import zlib
import time
from functools import wraps
from datetime import datetime

# --- CẤU HÌNH ---
LOG_FILE = "network_capture.log"
ENABLE_COLOR = True
IGNORE_EXTENSIONS = ('.jpg', '.png', '.css', '.js', '.woff', '.ico')
DELAY_SECONDS = 20  # Giữ nguyên 20s để bypass check key

# --- BIẾN TRẠNG THÁI CHỐNG LẶP ---
# Biến này cực quan trọng để tránh lỗi "Killed"
_thread_local = threading.local()

# --- UTILS MÀU SẮC ---
class Colors:
    RESET = "\033[0m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"

def cprint(msg, color=Colors.RESET):
    if ENABLE_COLOR:
        sys.stderr.write(f"{color}{msg}{Colors.RESET}\n")
    else:
        sys.stderr.write(f"{msg}\n")

# --- LOGGER ---
class DeepLogger:
    def __init__(self):
        self.lock = threading.Lock()
    
    def _decode_body(self, body, encoding='utf-8'):
        if body is None: return ""
        if isinstance(body, str): return body
        try: return gzip.decompress(body).decode(encoding, errors='ignore')
        except: pass
        try: return zlib.decompress(body).decode(encoding, errors='ignore')
        except: pass
        try: return body.decode(encoding, errors='ignore')
        except: return f"<Binary Len={len(body)}>"

    def log(self, source, method, url, req_headers, req_body, status, resp_headers, resp_body, duration):
        try:
            url_str = str(url)
            if any(url_str.endswith(ext) for ext in IGNORE_EXTENSIONS): return
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            decoded_req = self._decode_body(req_body)
            decoded_resp = self._decode_body(resp_body)
            
            # Chỉ hiển thị ngắn gọn trên màn hình để đỡ lag
            with self.lock:
                cprint(f"[{timestamp}] [{source}] {method} {url} | {status}", Colors.CYAN)

            # Ghi file full
            log_entry = (
                f"{'='*40}\nTIME: {timestamp} | SRC: {source}\nREQ: {method} {url}\n"
                f"STATUS: {status} | DUR: {duration:.4f}s\n"
                f"--- REQ BODY ---\n{decoded_req[:2000]}\n" # Giới hạn độ dài để tránh crash ghi file
                f"--- RESP BODY ---\n{decoded_resp[:4000]}\n"
            )
            with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
        except: pass

logger = DeepLogger()

# --- HOOK MANAGER ---
PENDING_HOOKS = []

def register_hook(target_module, target_attr):
    def decorator(hook_func):
        PENDING_HOOKS.append({'mod': target_module, 'attr': target_attr, 'func': hook_func})
        return hook_func
    return decorator

def apply_hooks_now():
    cprint(f"\n[+] KÍCH HOẠT ANTI-CRASH INTERCEPTOR SAU {DELAY_SECONDS}s...", Colors.YELLOW)
    
    # 1. Hook các thư viện chuẩn
    for h in PENDING_HOOKS:
        try:
            parts = h['mod'].split('.')
            mod = __import__(parts[0])
            for part in parts[1:]: mod = getattr(mod, part)
            
            orig = getattr(mod, h['attr'])
            if getattr(orig, '_is_hooked', False): continue

            @wraps(orig)
            def wrapper(*args, **kwargs):
                return h['func'](orig, *args, **kwargs)
            
            wrapper._is_hooked = True
            setattr(mod, h['attr'], wrapper)
            cprint(f"    [OK] Hooked: {h['mod']}", Colors.GREEN)
        except: pass

    # 2. Hook nâng cao (Manual)
    manual_hook_aiohttp()
    cprint(f"[+] GOD MODE ON - SAFE MODE (NO CRASH)\n", Colors.RED)

# --- HOOK LOGIC VỚI RECURSION GUARD ---

# CHỈ HOOK URLLIB3 (BỎ REQUESTS VÌ NÓ GỌI URLLIB3 -> GÂY LẶP)
# Hook tầng thấp nhất sẽ bắt được tất cả, an toàn hơn.
@register_hook("urllib3.connectionpool.HTTPConnectionPool", "urlopen")
def hook_urllib3(original_func, self, method, url, body=None, headers=None, **kwargs):
    # >>> RECURSION GUARD: Nếu đang xử lý log rồi thì bỏ qua để tránh lặp <<<
    if getattr(_thread_local, 'processing', False):
        return original_func(self, method, url, body=body, headers=headers, **kwargs)
    
    _thread_local.processing = True
    start_time = time.time()
    resp_body = b""
    status = "ERR"
    resp_headers = {}
    
    try:
        response = original_func(self, method, url, body=body, headers=headers, **kwargs)
        status = response.status
        resp_headers = dict(response.headers)
        if hasattr(response, 'data'): resp_body = response.data
        return response
    except Exception as e:
        status = f"EXC: {e}"
        raise e
    finally:
        # Ghi log xong mới tắt cờ processing
        try:
            full_url = f"{self.scheme}://{self.host}:{self.port}{url}"
            logger.log("URLLIB3", method, full_url, headers, body, status, resp_headers, resp_body, time.time() - start_time)
        except: pass
        _thread_local.processing = False

# AIOHTTP (Async - Cần xử lý riêng)
def manual_hook_aiohttp():
    try:
        import aiohttp
        if getattr(aiohttp.ClientSession._request, '_is_hooked', False): return

        async def hook_aiohttp_func(self, method, str_or_url, **kwargs):
            # Guard cho Async hơi khác, tạm thời bỏ qua để tránh lỗi phức tạp
            start_time = time.time()
            url = str(str_or_url)
            try:
                response = await self._original_request(method, str_or_url, **kwargs)
                # Đọc body nhẹ nhàng
                resp_body = "" # Không đọc sâu để tránh crash stream
                logger.log("AIOHTTP", method, url, kwargs.get('headers'), None, response.status, dict(response.headers), resp_body, time.time() - start_time)
                return response
            except Exception as e: raise e

        if not hasattr(aiohttp.ClientSession, '_original_request'):
            aiohttp.ClientSession._original_request = aiohttp.ClientSession._request
        
        hook_aiohttp_func._is_hooked = True
        aiohttp.ClientSession._request = hook_aiohttp_func
        cprint("    [OK] Hooked: aiohttp", Colors.GREEN)
    except: pass

# --- LOADER ---
def worker():
    time.sleep(DELAY_SECONDS)
    apply_hooks_now()

def main():
    if len(sys.argv) < 2: return
    target = sys.argv[1]
    sys.argv = sys.argv[1:]
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))

    # Chạy thread đếm ngược
    threading.Thread(target=worker, daemon=True).start()

    try:
        runpy.run_path(target, run_name="__main__")
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    main()
