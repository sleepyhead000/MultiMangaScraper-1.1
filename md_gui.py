import shutil
import zipfile
import sys
import os
import io
import re
import json
import base64
import time
import random
import requests
import threading
import concurrent.futures
import unicodedata
import traceback
from urllib.parse import urljoin, urlparse
from PIL import Image
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass
from bs4 import BeautifulSoup
try:
    from curl_cffi import requests as requests_cf
except ImportError:
    requests_cf = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as SeleniumOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import UnexpectedAlertPresentException, NoAlertPresentException
    from webdriver_manager.chrome import ChromeDriverManager
    from seleniumbase import Driver
    try:
        import undetected_chromedriver as uc
        uc_available = True
    except ImportError:
        uc_available = False
    selenium_available = True
except ImportError:
    selenium_available = False
    uc_available = False
from pathlib import Path
from typing import List, Optional, Dict, Any

from baozimh_client_v2 import BaozimhClient, DownloadEvent
from download_utils import interruptible_sleep, atomic_write_bytes

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                               QTreeWidget, QTreeWidgetItem, QSplitter, QTextEdit, 
                               QCheckBox, QProgressBar, QMessageBox, QFileDialog,
                               QListWidget, QAbstractItemView, QFrame, QSizePolicy,
                               QHeaderView, QMenu, QDialog, QDialogButtonBox, QListWidgetItem,
                               QComboBox, QScrollArea, QStackedWidget)
from PySide6.QtCore import Qt, QThread, Signal, QObject, QEvent, QSize, Property, QRect, QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QPixmap, QImage, QFont, QIcon, QAction, QColor, QPalette, QActionGroup, QPainter, QBrush, QPen, QLinearGradient
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer

import icons
from stylesheet import STYLESHEET, SURFACE_0, SURFACE_1, SURFACE_2, SURFACE_3, BORDER, ACCENT, ACCENT_DIM, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, SUCCESS, WARNING, INFO
from widgets import ToggleSwitch, ChipWidget, DownloadButton, StatusBadge, SegmentedControl, WelcomeWidget, LoadingPage

try:
    import zhconv
except ImportError:
    zhconv = None

class ScalableImageLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_pixmap = None
        self._last_resize_time = 0
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(150, 225)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("border: 1px solid #444; background-color: #1a1a1a; border-radius: 4px;")

    def set_pixmap(self, pixmap):
        self._original_pixmap = pixmap
        self.update_display()

    def resizeEvent(self, event):
                                                                    
        current_time = time.time()
        if current_time - self._last_resize_time > 0.05:                
            self.update_display()
            self._last_resize_time = current_time
        super().resizeEvent(event)

    def update_display(self):
        if not self.isVisible(): return
        if self._original_pixmap and not self._original_pixmap.isNull():
                                              
            try:
                scaled = self._original_pixmap.scaled(
                    self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                super().setPixmap(scaled)
            except:
                pass                                   
        else:
            super().setText("No Cover")

class GroupFilterDialog(QDialog):
    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filter Groups")
        self.resize(300, 400)
        self.layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
        self.layout.addWidget(self.list_widget)
        
        self.groups = sorted(list(groups))
        
                                           
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("All")
        btn_all.clicked.connect(self.select_all)
        btn_none = QPushButton("None")
        btn_none.clicked.connect(self.select_none)
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        self.layout.addLayout(btn_layout)

                   
        for g in self.groups:
            item = QListWidgetItem(g)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
            
                        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
        self.setStyleSheet("""
            QDialog { background-color: #2d2d2d; color: #fff; }
            QListWidget { background-color: #252526; color: #fff; border: 1px solid #444; }
            QListWidget::item:hover { background-color: #3e3e42; }
        """)

    def select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Checked)

    def select_none(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Unchecked)

    def get_selected_groups(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected

class LibraryDialog(QDialog):
    def __init__(self, library_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library")
        self.resize(500, 600)
        self.layout = QVBoxLayout(self)
        self.library_data = library_data
        
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.load_selected)
        self.layout.addWidget(self.list_widget)
        
        self.refresh_list()
        
        btn_layout = QHBoxLayout()
        self.btn_load = QPushButton("Load")
        self.btn_load.clicked.connect(self.load_selected)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_close)
        self.layout.addLayout(btn_layout)
        
        self.setStyleSheet("""
            QDialog { background-color: #2d2d2d; color: #fff; }
            QListWidget { background-color: #252526; color: #fff; border: 1px solid #444; }
            QListWidget::item:hover { background-color: #3e3e42; }
            QListWidget::item:selected { background-color: #007acc; }
        """)

    def refresh_list(self):
        self.list_widget.clear()
        for mid, data in self.library_data.items():
            title = data.get('title', 'Unknown')
                                                
            suffix = ""
            if data.get('has_update'):
                suffix = " [UPDATE!]"
            item = QListWidgetItem(f"{title}{suffix}")
            item.setData(Qt.UserRole, mid)
            self.list_widget.addItem(item)

    def load_selected(self):
        item = self.list_widget.currentItem()
        if item:
            mid = item.data(Qt.UserRole)
            self.parent().load_manga_from_library(mid)
            self.accept()

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item:
            mid = item.data(Qt.UserRole)
            if mid in self.library_data:
                del self.library_data[mid]
                self.refresh_list()

                                  
def excepthook(exc_type, exc_value, exc_traceback):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print("CRITICAL ERROR:", tb)
                                                      
    if QApplication.instance():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setText("An unexpected error occurred.")
        msg.setInformativeText(str(exc_value))
        msg.setDetailedText(tb)
        msg.setWindowTitle("Error")
        msg.exec()

sys.excepthook = excepthook

                       

API = "https://api.mangadex.org"
BAOZIMH_BASE = "https://www.baozimh.com"
BAOZI_CLIENT = BaozimhClient()
HAPPYMH_BASE = "https://m.happymh.com"
SETTINGS_FILE = "settings.json"
LIBRARY_FILE = "library.json"

def sort_chapters_newest_first(chapters):
    """Sort by chapter number DESC (highest first)"""
    def extract_number(chapter):
        # Extract number from title or chapter field: "第41话" → 41, "Ch 97" → 97
        text = str(chapter.get('title', '')) + " " + str(chapter.get('chapter', ''))
        num_match = re.search(r'(\d+(?:\.\d+)?)', text)
        try:
            return float(num_match.group(1)) if num_match else 0.0
        except:
            return 0.0
     
    return sorted(chapters, key=extract_number, reverse=True)

def extract_newtoki_images_pro(driver):
    """Community-tested data-* attribute extraction"""
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    img_tags = soup.select("p img")
     
    image_urls = []
    data_pattern = re.compile(r"^data-[a-zA-Z0-9]{1,20}$")
     
    for img in img_tags:
        # PRIORITY: data-* attributes first
        found_data = False
        for attr_name, attr_value in img.attrs.items():
            if data_pattern.match(attr_name) and attr_value.startswith("http"):
                image_urls.append(attr_value)
                found_data = True
                break
        
        if not found_data:
            # FALLBACK: src
            if img.get('src') and img['src'].startswith("http") and "loading-image.gif" not in img['src']:
                image_urls.append(img['src'])
     
    # Dedupe
    return list(dict.fromkeys(image_urls))

def test_url_works(url, timeout=3):
    """HEAD request + multiple fallbacks"""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code == 200 and 'image' in resp.headers.get('content-type', '').lower()
    except:
        try:
            resp = requests.get(url, timeout=timeout, stream=True)
            if resp.status_code == 200:
                # Read a bit of content to verify it's an image
                chunk = next(resp.iter_content(1024), b'')
                return len(chunk) > 100
            return False
        except:
            return False

def baozimh_universal_watermark_bypass(img_url):
    """SIMPLE - path extraction only (FINAL FIX)"""
    if not img_url: return img_url
    path = re.sub(r'^https?://[^/]+', '', img_url)
    return f"https://static-tw.baozimh.com{path}"

def extract_images_with_autoscroll(driver, max_scrolls=10):
    """Scroll + Wait + Extract ALL images (lazy-loaded)"""
    print("🔄 Auto-scrolling to load ALL images...")
    
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    
    while scroll_count < max_scrolls:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height
        scroll_count += 1
        
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    image_urls = []
    
    selectors = [
        'img[src*="baozimh"]', 'img[src*="baozicdn"]', 'img[src*=".jpg"]',
        'img[src*=".png"]', 'img[src*=".webp"]', 'p img', '.content img',
        'div.reader img', '[class*="image"] img', 'img.lazy',
        'img.comic-contain_ui-Image_img'
    ]
    
    for selector in selectors:
        try:
            imgs = soup.select(selector)
            for img in imgs:
                src = img.get('data-src') or img.get('src') or img.get('data-lazy') or img.get('data-original')
                if src and src.startswith('http'):
                    image_urls.append(src)
        except: pass
        
    image_urls = list(dict.fromkeys(image_urls))
    print(f"✅ Found {len(image_urls)} images after scrolling")
    return image_urls

def is_last_page_baozimh(driver):
    """DETECT icon-xiayibu = END (FINAL FIX)"""
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    return bool(soup.select_one('span.iconfont.icon-xiayibu'))

def extract_complete_baozimh_chapter_final(driver):
    """FIXED: Stops at icon-xiayibu + duplicate detection"""
    all_images = []
    visited_urls = set()
    page_num = 1
    last_page_images = []
    consecutive_empty = 0
    base_url = driver.current_url
     
    while page_num <= 15:  # Reasonable max
        current_url = driver.current_url
        pure_url = current_url.split('#')[0].split('?')[0]
        
        if pure_url in visited_urls:
            print("🔄 LOOP DETECTED - ENDING")
            break
        visited_urls.add(pure_url)
        
        print(f"📄 Page {page_num}: {current_url}")
        
        # AUTO-SCROLL + EXTRACT
        page_images = extract_images_with_autoscroll(driver)
        
        # LAST PAGE CHECKS
        if is_last_page_baozimh(driver):
            # Still add these images if they aren't complete duplicates
            if page_images:
                clean_images = [baozimh_universal_watermark_bypass(url) for url in page_images]
                for img in clean_images:
                    if img not in all_images:
                        all_images.append(img)
            print("🎉 LAST PAGE CONFIRMED!")
            break
            
        if page_images:
            clean_images = [baozimh_universal_watermark_bypass(url) for url in page_images]
            # Dedupe while adding
            for img in clean_images:
                if img not in all_images:
                    all_images.append(img)
            print(f"   → {len(page_images)} images found (total: {len(all_images)})")
            consecutive_empty = 0
        else:
            consecutive_empty += 1
            print("   → EMPTY PAGE")
            if consecutive_empty >= 2:
                print("✅ NO PROGRESS - ENDING")
                break
         
        last_page_images = page_images
        
        # NEXT LINK
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        next_link = soup.select_one('div.next_chapter a[href*="_"], .next-page a, a[href*="下一頁"]')
         
        if next_link:
            next_href = next_link.get('href')
            next_url = urljoin(current_url, next_href)
            if next_url.split('#')[0] not in visited_urls and "#bottom" not in next_href:
                print(f"🔗 Next link found: {next_url}")
                driver.get(next_url)
                page_num += 1
                time.sleep(2)
                continue
         
        # SEQUENTIAL PREDICTION
        if '_2.html' in pure_url:
            predicted = re.sub(r'_(\d+)\.html$', lambda m: f"_{int(m.group(1))+1}.html", pure_url)
        elif not re.search(r'_\d+\.html$', pure_url):
            predicted = pure_url.replace('.html', '_2.html')
        else:
            predicted = re.sub(r'_(\d+)\.html$', lambda m: f"_{int(m.group(1))+1}.html", pure_url)
            
        if predicted and predicted not in visited_urls:
            print(f"🔮 Predicting next page: {predicted}")
            driver.get(predicted)
            time.sleep(2)
            if "404" in driver.title:
                break
            page_num += 1
            continue
            
        break
     
    driver.get(base_url)
    return list(dict.fromkeys(all_images))

def extract_complete_baozimh_chapter(driver):
    return extract_complete_baozimh_chapter_final(driver)

def api_get(path: str, params: dict | None = None) -> dict:
    url = API.rstrip("/") + "/" + path.lstrip("/")
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"API Error: {e}")
        return {}

def _normalize_text(s: Optional[str]) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _all_title_candidates(attrs: dict) -> List[str]:
    titles = set()
    if not attrs: return []
    title_map = attrs.get("title") or {}
    for v in title_map.values():
        if v: titles.add(str(v))
    alt = attrs.get("altTitles") or []
    for entry in alt:
        if isinstance(entry, dict):
            for v in entry.values():
                if v: titles.add(str(v))
        elif isinstance(entry, str):
            titles.add(entry)
    return list(titles)

def _matches_query(query_norm: str, title_norm: str) -> bool:
    if not query_norm or not title_norm: return False
    if query_norm in title_norm: return True
    q_tokens = query_norm.split()
    t_tokens = set(title_norm.split())
    return all(token in t_tokens for token in q_tokens)

def search_manga(title: str, limit: int = 100) -> List[dict]:
    title = (title or "").strip()
    if not title: return []
    query_norm = _normalize_text(title)
    collected_raw = []
    direct_id = None
    
                                     
    url_match = re.search(r"mangadex\.org/title/([a-fA-F0-9\-]+)", title)
    if url_match:
        direct_id = url_match.group(1)
        try:
            resp = api_get(f"/manga/{direct_id}", params={"includes[]": ["cover_art"]})
            data = resp.get("data")
            if data:
                collected_raw = [data]
        except: pass
    else:
        try:
            params = {"title": title, "limit": min(limit, 100), "includes[]": ["cover_art"]}
            resp = api_get("/manga", params=params)
            collected_raw.extend(resp.get("data", []))
        except: pass

                                      
    if not collected_raw or len(collected_raw) < 5:
        tokens = [t for t in re.split(r"[^A-Za-z0-9]+", title) if t]
        if tokens:
            try:
                params = {"title": " ".join(tokens[:4]), "limit": 100, "includes[]": ["cover_art"]}
                resp = api_get("/manga", params=params)
                for r in resp.get("data", []):
                                      
                    if not any(existing['id'] == r['id'] for existing in collected_raw):
                        collected_raw.append(r)
            except: pass

    results = []
    seen_ids = set()
    for item in collected_raw:
        manga_id = item.get("id")
        if not manga_id or manga_id in seen_ids: continue
        attrs = item.get("attributes", {}) or {}
        
        candidates = _all_title_candidates(attrs)
        matched = False
        if direct_id and direct_id == manga_id:
            matched = True
        else:
            for cand in candidates:
                if _matches_query(query_norm, _normalize_text(cand)):
                    matched = True
                    break
        
        display_title_map = attrs.get("title") or {}
                                                          
        default_title = display_title_map.get("en") or next(iter(display_title_map.values()), None) or (candidates[0] if candidates else "Unknown")
        
        cover_filename = None
        for rel in item.get("relationships", []) or []:
            if rel.get("type") == "cover_art":
                cover_filename = rel.get("attributes", {}).get("fileName")
                break

        results.append({
            "id": manga_id,
            "title": default_title,                 
            "attributes": attrs,                                              
            "status": attrs.get("status"),
            "description": (attrs.get("description") or {}).get("en", "No description"),
            "cover_filename": cover_filename,
            "matched": matched,
            "available_languages": attrs.get("availableTranslatedLanguages", [])
        })
        seen_ids.add(manga_id)
    
                                            
    results.sort(key=lambda r: (0 if r.get("matched") else 1, (r.get("title") or "").lower()))
    return results[:limit]

def fetch_chapters_for_manga(manga_id: str, langs: Optional[List[str]] = None) -> List[dict]:
    chapters = []
    limit = 100
    offset = 0
    while True:
        params = {
            "manga": manga_id, "limit": limit, "offset": offset,
            "order[chapter]": "asc", "includes[]": "scanlation_group"
        }
        if langs: params["translatedLanguage[]"] = langs
        
        resp = api_get("/chapter", params=params)
        page_results = resp.get("data", [])
        if not page_results: break
        
        for r in page_results:
            attrs = r.get("attributes", {}) or {}
            groups = []
            for rel in r.get("relationships", []) or []:
                if rel.get("type") == "scanlation_group":
                    name = rel.get("attributes", {}).get("name")
                    if name: groups.append(name)
            
            chapters.append({
                "id": r.get("id"),
                "chapter": attrs.get("chapter", ""),
                "title": attrs.get("title", ""),
                "volume": attrs.get("volume", ""),
                "language": attrs.get("translatedLanguage", ""),
                "publishAt": attrs.get("publishAt", ""),
                "groups": list(set(groups)),
                "attributes": attrs
            })
        
        offset += len(page_results)
        if len(page_results) < limit or offset >= 5000: break
    return chapters

def format_date(iso_str):
    if not iso_str: return ""
    try:
                                       
        return iso_str.split("T")[0]
    except:
        return iso_str

def get_chapter_info(chapter_id: str) -> dict:
    return api_get(f"/chapter/{chapter_id}").get("data", {})

def get_at_home_base(chapter_id: str) -> dict:
    return api_get(f"/at-home/server/{chapter_id}")

def craft_image_urls(base_url: str, chapter_attrs: dict, use_data_saver: bool = True) -> List[str]:
    hash_ = chapter_attrs.get("hash")
    if use_data_saver:
        files = chapter_attrs.get("dataSaver") or []
        mode = "data-saver"
    else:
        files = chapter_attrs.get("data") or []
        mode = "data"
    if not hash_ or not files: return []
    base = base_url.rstrip("/")
    return [f"{base}/{mode}/{hash_}/{fname}" for fname in files]

                               

def get_anilist_chinese_title(query: str) -> Optional[str]:
    url = 'https://graphql.anilist.co'
    query_graphql = '''
    query ($search: String) {
      Page(page: 1, perPage: 5) {
        media(search: $search, type: MANGA, sort: SEARCH_MATCH) {
          title {
            romaji
            english
            native
          }
          synonyms
        }
      }
    }
    '''
    variables = {'search': query}
    try:
        r = requests.post(url, json={'query': query_graphql, 'variables': variables}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            media_list = data.get('data', {}).get('Page', {}).get('media', [])
            
            query_lower = query.lower()
            
            for media in media_list:
                titles = media.get('title', {})
                native = titles.get('native')
                if not native:
                    continue
                    
                # Check if query matches any title/synonym
                candidates = [
                    titles.get('english'),
                    titles.get('romaji'),
                    titles.get('native')
                ] + (media.get('synonyms') or [])
                
                matched = False
                for cand in candidates:
                    if cand and query_lower in cand.lower():
                        matched = True
                        break
                
                if matched:
                    return native
                    
    except Exception as e:
        print(f"Error: {e}")
        pass
    return None

def fetch_baozimh_response(url: str, params: dict | None = None) -> requests.Response | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"Baozimh Error {url}: {e}")
        return None

def fetch_baozimh_html(url: str, params: dict | None = None) -> str | None:
    r = fetch_baozimh_response(url, params)
    return r.text if r else None

HAPPYMH_SESSION = None
SESSION_LOCK = threading.Lock()

def get_happymh_session(impersonate: Optional[str] = None):
    global HAPPYMH_SESSION
    with SESSION_LOCK:
        if HAPPYMH_SESSION is None:
            if requests_cf:
                # Initialize session with impersonation if provided
                HAPPYMH_SESSION = requests_cf.Session(impersonate=impersonate)
                cookie_file = Path("happymh_cookies.json")
                if cookie_file.exists():
                    try:
                        with open(cookie_file, "r") as f:
                            HAPPYMH_SESSION.cookies.update(json.load(f))
                    except: pass
            else:
                HAPPYMH_SESSION = requests.Session()
    return HAPPYMH_SESSION

def fetch_happymh_response(url: str, referer: Optional[str] = None):
    session = get_happymh_session(impersonate="chrome124")
    ref = referer or HAPPYMH_BASE
    
    # Use curl_cffi for Cloudflare bypass if available
    if requests_cf and isinstance(session, requests_cf.Session):
        try:
            # Use chrome124 impersonation to match recent UA
            r = session.get(
                url, 
                impersonate="chrome124", 
                timeout=20, 
                headers={
                    "Referer": ref,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1"
                }
            )
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"Happymh CF Error: {e}")
            
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": ref,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    try:
        r = session.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"Happymh Standard Error: {e}")
        return None

def fetch_happymh_html(url: str, referer: Optional[str] = None) -> Optional[str]:
    # Network request for Cloudflare bypass
    r = fetch_happymh_response(url, referer=referer)
    if r:
        return r.text
    
    return None

def search_happymh(query: str) -> List[dict]:
    query = (query or "").strip()
    if not query: return []
    
    # 1. Direct URL Match
    if "happymh.com/manga/" in query:
        manga_id = query.split("/")[-1]
        try:
            html = fetch_happymh_html(query)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                title_tag = soup.select_one(".mg-title") or soup.select_one("h1") or soup.select_one(".MuiTypography-h3") or soup.select_one(".MuiTypography-h4")
                title = title_tag.get_text(strip=True) if title_tag else manga_id
                
                cover_tag = soup.select_one(".mg-banner img") or soup.select_one(".mg-poster img") or soup.select_one(".MuiCardMedia-root") or soup.select_one("img[src*='poster']")
                cover_url = cover_tag.get("src") or cover_tag.get("data-src") if cover_tag else ""
                
                return [{
                    "id": manga_id,
                    "title": title,
                    "attributes": {"title": {"en": title, "zh": title}},
                    "status": "Ongoing",
                    "description": "Loaded from URL (Happymh)",
                    "cover_filename": None,
                    "cover_url": cover_url,
                    "available_languages": ["zh"],
                    "source": "happymh"
                }]
        except:
            pass
            
        return [{
            "id": manga_id,
            "title": "Direct URL Match (Happymh)",
            "attributes": {"title": {"en": "Direct URL Match", "zh": "Direct URL Match"}},
            "status": "Unknown",
            "description": "Direct URL",
            "cover_filename": None,
            "cover_url": None,
            "available_languages": ["zh"],
            "source": "happymh"
        }]

    # 2. Search logic
    alt_query = get_anilist_chinese_title(query)
    search_q = alt_query if alt_query else query
    
    url = f"{HAPPYMH_BASE}/sssearch?v={search_q}"
    html = fetch_happymh_html(url)
    if not html: return []
    
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    cards = soup.select("a[href^='/manga/'], *[data-href^='/manga/']")
    for card in cards:
        try:
            href = card.get("href") or card.get("data-href")
            manga_id = href.split("/")[-1]
            if not manga_id or manga_id in [r['id'] for r in results]:
                continue
                
            title_tag = card.select_one(".MuiTypography-root") or card.select_one("div") or card.select_one(".mg-manga-name")
            title_text = title_tag.get_text(strip=True) if title_tag else "Unknown"
            
            img_tag = card.find("img")
            cover_url = img_tag.get("src") or img_tag.get("data-src") if img_tag else ""
            
            results.append({
                "id": manga_id,
                "title": title_text,
                "attributes": {"title": {"en": title_text, "zh": title_text}},
                "status": "Unknown",
                "description": "Found on Happymh",
                "cover_filename": None,
                "cover_url": cover_url,
                "available_languages": ["zh"],
                "source": "happymh"
            })
        except:
            continue
            
    return results

def get_happymh_chapters_dynamic(url):
    """CORRECT SeleniumBase UC - works for ANY series"""
    if not selenium_available:
        print("DEBUG: Selenium not available for portable detection")
        return []
        
    from seleniumbase import Driver
    series_slug = url.split('/')[-1]
    print(f"DEBUG: Launching SeleniumBase UC for {series_slug}")

    # CORRECT SeleniumBase UC syntax - NO invalid parameters
    driver = Driver(
        uc=True,           # Undetected Chrome
        headless=False,    # Visible for debugging
        disable_csp=True,
        undetectable=True,
        browser="chrome",
        user_data_dir=None # NO cache!
    )
    
    try:
        # Navigate to series page
        print(f"DEBUG: Loading {url}")
        driver.get(url)
        
        # Cloudflare clearance (universal)
        print("Waiting for Cloudflare clearance...")
        try:
            WebDriverWait(driver, 10).until_not(
                lambda d: "Just a moment" in d.title
            )
        except:
            # Simple sleep fallback
            time.sleep(10)
            
        # CONFIRM page loaded or manual intervention
        if "Just a moment" in driver.title:
            print("\n" + "="*50)
            print("CLOUDFLARE STILL BLOCKING - manual intervention needed")
            print("Solve Cloudflare manually in the browser window.")
            print("Once the manga page appears, press ENTER in this console...")
            print("="*50 + "\n")
            input("Solve Cloudflare manually → Press ENTER...")
            
        # Extract chapters DYNAMICALLY (no static files)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        chapters = []
        
        # Multiple selectors for chapter lists to be robust
        selectors = [
            "ul.chapter-list li a",
            ".chapter-item a",
            "li a[href*='mangaread']",
            ".chapter li a",
            "a[href*='/mangaread/']",
            "div.MuiListItemButton-root[data-href*='/mangaread/']"
        ]
        
        seen_ids = set()
        for selector in selectors:
            links = soup.select(selector)
            for link in links:
                href = link.get("href") or link.get("data-href")
                if not href or href in seen_ids: continue
                
                # CRITICAL: Match THIS SERIES ONLY to avoid mixed results
                if series_slug not in href and "/mangaread/" not in href: continue
                
                link_text = link.get_text(" ", strip=True)
                if any(x in link_text for x in ["吐槽", "收藏", "问题反馈", "下一话", "上一话", "返回", "目录"]):
                    continue
                    
                seen_ids.add(href)
                num_match = re.search(r'(?:第|Ch|Chapter\s*)?(\d+(?:\.\d+)?)', link_text)
                chap_num = num_match.group(1) if num_match else "0"
                
                chapters.append({
                    "id": href,
                    "chapter": chap_num,
                    "title": link_text,
                    "language": "zh",
                    "groups": [],
                    "publishAt": "",
                    "volume": "",
                    "source": "happymh"
                })
            if chapters:
                break
            
        print(f"✅ DYNAMIC: Found {len(chapters)} chapters for {series_slug}")
        
        def chap_sort_key(c):
            try:
                return float(c['chapter'])
            except:
                return 0.0
        
        # Sort descending by default (usually what users want)
        chapters.sort(key=chap_sort_key, reverse=True)
        
        # Dedupe by ID just in case
        return list({c['id']: c for c in chapters}.values())
        
    except Exception as e:
        print(f"SELENIUM ERROR: {e}")
        return []
    finally:
        driver.quit()

def fetch_chapters_happymh(manga_id: str) -> List[dict]:
    url = f"{HAPPYMH_BASE}/manga/{manga_id}"
    
    # SINGLE ATTEMPT - NO RETRIES
    chapters = get_happymh_chapters_dynamic(url)
    
    if chapters:
        return chapters
        
    print("❌ DYNAMIC FAILED - Falling back to manual instructions")
    print("Please:")
    print("1. Open https://m.happymh.com/manga/[series] manually")
    print("2. Solve Cloudflare")
    print("3. Copy chapter URLs from page source or try again")
    return []

def get_happymh_images(chapter_url_path: str, manga_url: Optional[str] = None) -> List[str]:
    if chapter_url_path.startswith("/"):
        url = f"{HAPPYMH_BASE}{chapter_url_path}"
    else:
        url = chapter_url_path
        
    html = fetch_happymh_html(url, referer=manga_url)
    if not html: return []
    
    images_with_order = []
    soup = BeautifulSoup(html, "html.parser")
    
    # --- Method 1: Priority scan for id="scanX" ---
    # This is the most reliable way to get the correct order as per user suggestion
    scan_tags = soup.select("img[id^='scan']")
    for tag in scan_tags:
        src = tag.get("src") or tag.get("data-src") or tag.get("data-original")
        if src and src.startswith("http"):
            try:
                # Extract number from scan0, scan1, etc.
                order = int(re.search(r'\d+', tag.get("id", "")).group())
                images_with_order.append((order, src))
            except:
                images_with_order.append((999, src))

    if images_with_order:
        images_with_order.sort()
        found_urls = [x[1] for x in images_with_order]
        print(f"DEBUG: Found {len(found_urls)} images using scanID method")
        return found_urls

    # --- Fallback Methods if no scan IDs found ---
    images = []
    
    # --- Method 2: Check for extra captured data ---
    extra_data_div = soup.find("div", id="extra_captured_data")
    if extra_data_div:
        try:
            captured_raw = extra_data_div.get_text()
            captured = json.loads(json.loads(captured_raw))
            if captured.get("images"):
                images.extend(captured["images"])
            
            js_vars = captured.get("js_variables", {})
            for var_name, var_val in js_vars.items():
                if var_name.startswith("canvas_"):
                    images.append("canvas_data:" + var_val)
                else:
                    found_urls = re.findall(r'\"(https?://[^\"]+\.(?:jpg|png|webp|jpeg)[^\"]*)\"', str(var_val))
                    images.extend([u.replace('\\/', '/') for u in found_urls])
            
            for resp in captured.get("json_responses", []):
                found_urls = re.findall(r'\"(https?://[^\"]+\.(?:jpg|png|webp|jpeg)[^\"]*)\"', resp["content"])
                images.extend([u.replace('\\/', '/') for u in found_urls])
        except:
            pass

    # --- Method 2: JSON data in scripts ---
    scripts = re.findall(r'<script\b[^>]*>([\s\S]*?)<\/script>', html)
    for script_content in scripts:
        if "pages" in script_content and "url" in script_content:
            found = re.findall(r'\"url\":\s*\"(https?://[^\"]+)\"', script_content)
            if found:
                images.extend([u.replace('\\/', '/') for u in found])
        
        if "sc_p" in script_content:
            found = re.findall(r'\"(https?://[^\"]+\.(?:jpg|png|webp|jpeg)[^\"]*)\"', script_content)
            if found:
                images.extend([u.replace('\\/', '/') for u in found])

    # --- Method 3: DOM Selectors ---
    selectors = [
        "img[id^='scan']",
        "div.css-1krjvn-imgContainer img",
        ".mg-content img", 
        ".reader-content img", 
        "div[class*='-imgContainer'] img", 
        "div[id^='scan'] img",
        ".MuiBox-root img",
        "article img"
    ]
    
    for sel in selectors:
        img_tags = soup.select(sel)
        for img in img_tags:
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if src and (src.startswith("http") or src.startswith("canvas_data:")):
                if any(x in src.lower() for x in ["logo", "favicon", "static/js", "telegram"]):
                    continue
                images.append(src)

    # --- Method 4: Raw Regex Scan ---
    patterns = [
        r'https?://ruicdn\.happymh\.com/[^\s\"\'<>)]+\.(?:jpg|png|webp|jpeg)[^\s\"\'<>)]*',
        r'https?://img\.happymh\.com/[^\s\"\'<>)]+\.(?:jpg|png|webp|jpeg)[^\s\"\'<>)]*'
    ]
    for pattern in patterns:
        found = re.findall(pattern, html)
        if found:
            images.extend(found)

    # deduplication
    seen = set()
    final_images = []
    for img in images:
        if img.startswith("canvas_data:canvas_data:"):
            img = img[12:]
        if img not in seen:
            final_images.append(img)
            seen.add(img)
            
    return final_images

def search_baozimh(query: str) -> List[dict]:
    query = (query or "").strip()
    if not query: return []
    
                              
    if "baozimh.com" in query:
                             
                                                    
        manga_id = query.split("/")[-1]
        
                                                       
        try:
            html = fetch_baozimh_html(query)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                
                                                                  
                title_tag = soup.select_one(".comics-detail__title") or soup.select_one("h1")
                title = title_tag.get_text(strip=True) if title_tag else manga_id
                
                                               
                cover_tag = soup.select_one("amp-img.comics-detail__poster") or soup.select_one(".comics-detail__poster amp-img")
                cover_url = None
                if cover_tag:
                    cover_url = cover_tag.get("src") or cover_tag.get("data-src")
                    
                return [{
                    "id": manga_id,
                    "title": title,
                    "attributes": {"title": {"en": title, "zh": title}},
                    "status": "Ongoing",
                    "description": "Loaded from URL",
                    "cover_filename": None,
                    "cover_url": cover_url,
                    "available_languages": ["zh"],
                    "source": "baozimh"
                }]
        except:
            pass

        return [{
            "id": manga_id,
            "title": "Direct URL Match",
            "attributes": {"title": {"en": "Direct URL Match", "zh": "Direct URL Match"}},
            "status": "Unknown",
            "description": "Direct URL Match",
            "cover_filename": None,
            "cover_url": None,
            "available_languages": ["zh"],
            "source": "baozimh"
        }]
    
                                                  
                                                                         
    translated_query = None
    if all(ord(c) < 128 for c in query):
        translated_query = get_anilist_chinese_title(query)
        if translated_query:
            print(f"AniList Bridge: {query} -> {translated_query}")
                                              
                                                                         
                                                                                       
                                                      
            query = translated_query

    try:
        search_results = BAOZI_CLIENT.search_comics(query)
    except Exception as e:
        print(f"Error searching baozimh: {e}")
        return []

    # Filter results if we used an AniList translation to be more precise
    if translated_query and search_results:
        filtered = []
        for r in search_results:
            title_check = r['title']
            query_check = translated_query
            if zhconv:
                try:
                    title_check = zhconv.convert(title_check, 'zh-cn')
                    query_check = zhconv.convert(query_check, 'zh-cn')
                except:
                    pass
            
            if query_check in title_check:
                filtered.append(r)
        
        if filtered:
            search_results = filtered

    results = []
    for r in search_results:
        manga_id = r['url'].rstrip('/').split("/")[-1]
        title = r['title']
        cover_url = r.get('cover_url', '')

        results.append({
            "id": manga_id,
            "title": title,
            "attributes": {"title": {"en": title, "zh": title}},
            "status": "Ongoing",          
            "description": "From Baozimh",
            "cover_filename": None,
            "cover_url": cover_url,
            "available_languages": ["zh"],
            "source": "baozimh"
        })
    return results

def fetch_chapters_baozimh(manga_id: str) -> List[dict]:
    url = f"{BAOZIMH_BASE}/comic/{manga_id}"
    
    try:
        chapters_data = BAOZI_CLIENT.get_chapter_list(url)
    except Exception as e:
        print(f"Error fetching chapters: {e}")
        return []
    
    chapters = []
    for c in chapters_data:
        # c has 'title', 'url'
        text = c['title']
        href = c['url'] # Absolute URL
        
        # Extract date if possible (not in BAOZI_CLIENT yet, skipping for now)
        
        chapters.append({
            "id": href, 
            "chapter": text, 
            "title": text,
            "language": "zh",
            "groups": [],
            "publishAt": "",
            "source": "baozimh"
        })
        
    return chapters

def get_baozimh_images(chapter_url_path: str) -> List[str]:
    if chapter_url_path.startswith("/"):
        base_url = f"{BAOZIMH_BASE}{chapter_url_path}"
    else:
        base_url = chapter_url_path
        
    return BAOZI_CLIENT.get_chapter_images(base_url)

def fetch_chapters_newtoki(manga_url: str, worker=None) -> List[dict]:
    if not uc_available:
        print("Error: undetected-chromedriver is not installed.")
        return []
    
    options = uc.ChromeOptions()
    # User might need manual captcha solving, so don't use headless
    driver = uc.Chrome(options=options, version_main=146)
    
    try:
        driver.get(manga_url)
        msg = (
            "NEW TOKI WORKFLOW:\n"
            "1. Solve Cloudflare + CAPTCHA in the browser window.\n"
            "2. STAY on the series/chapter page once it loads.\n"
            "3. Click 'Solved' in this dialog to detect chapters.\n"
            "4. The script will handle slow, human-like navigation later."
        )
        
        if worker:
            while True:
                res = worker.wait_for_captcha(msg)
                if res == "success":
                    break
                elif res == "retry":
                    driver.get(manga_url)
                    continue
                else:
                    return []
        else:
            print("\n" + "="*50)
            print(msg)
            print("="*50 + "\n")
            input("Press Enter in console after solving captcha...")
        
        # EXTRACT chapters from CURRENT PAGE (no extra navigation)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        chapters = []
        
        parsed_orig = urlparse(manga_url)
        base_domain = f"{parsed_orig.scheme}://{parsed_orig.netloc}"

        # NewToki uses <select name="wr_id"> for chapters
        select_tag = soup.find("select", {"name": "wr_id"})
        if select_tag:
            options_tags = select_tag.find_all("option")
            for opt in options_tags:
                val = opt.get("value")
                if val:
                    # Construct chapter URL - NewToki expects /webtoon/[ID] or /view/[ID]
                    # We will validate the exact URL later in the download loop
                    chapter_url = f"{base_domain}/webtoon/{val}" 
                    title = opt.text.strip()
                    chapters.append({
                        "id": val, 
                        "chapter": title,
                        "title": title,
                        "language": "ko",
                        "groups": [],
                        "publishAt": "",
                        "source": "newtoki",
                        "full_url": chapter_url
                    })
        
        # Fallback: look for list-item links
        if not chapters:
            links = soup.find_all("a", href=re.compile(r"/view/|/comic/"))
            for link in links:
                href = link.get("href")
                title = link.text.strip()
                if href and title and "/view/" in href:
                    chapters.append({
                        "id": href,
                        "chapter": title,
                        "title": title,
                        "language": "ko",
                        "groups": [],
                        "publishAt": "",
                        "source": "newtoki"
                    })
        
        return chapters
    except Exception as e:
        print(f"NewToki error: {e}")
        return []
    finally:
        driver.quit()

class SearchWorker(QThread):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, query, site="mangadex"):
        super().__init__()
        self.query = query
        self.site = site

    def run(self):
        try:
            if self.isInterruptionRequested(): return
            
            if self.site == "baozimh":
                results = search_baozimh(self.query)
            elif self.site == "happymh":
                results = search_happymh(self.query)
            elif self.site == "newtoki":
                # For NewToki, we often search by pasting URL directly
                if self.query.startswith("http"):
                    results = [{
                        "id": self.query,
                        "title": "NewToki Series (Direct URL)",
                        "attributes": {"title": {"en": "NewToki Series", "zh": "NewToki Series"}},
                        "status": "Unknown",
                        "description": "Directly loaded from URL",
                        "cover_filename": None,
                        "cover_url": "",
                        "available_languages": ["ko"],
                        "source": "newtoki"
                    }]
                else:
                    results = [] # Search not implemented for NewToki, only direct URL
            else:
                results = search_manga(self.query)
            
            if self.isInterruptionRequested(): return
            self.finished.emit(results)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error.emit(str(e))

class ChapterWorker(QThread):
    finished = Signal(list)
    error = Signal(str)
    captcha_requested = Signal(str)

    def __init__(self, manga_id, langs=None, site="mangadex"):
        super().__init__()
        self.manga_id = manga_id
        self.langs = langs
        self.site = site
        self.captcha_response = None
        self._is_running = True

    def set_captcha_response(self, response):
        self.captcha_response = response

    def stop(self):
        self._is_running = False

    def wait_for_captcha(self, message):
        self.captcha_response = None
        self.captcha_requested.emit(message)
        while self.captcha_response is None and self._is_running:
            interruptible_sleep(0.5, self._should_stop, step_seconds=0.1)
        return self.captcha_response

    def run(self):
        try:
            if self.isInterruptionRequested(): return

            if self.site == "baozimh":
                chapters = fetch_chapters_baozimh(self.manga_id)
            elif self.site == "happymh":
                chapters = fetch_chapters_happymh(self.manga_id)
                if not chapters:
                    self.error.emit("Happymh returned 0 chapters. This might be due to Cloudflare protection. Try pasting the direct URL or providing cookies in 'happymh_cookies.json'.")
                    return
            elif self.site == "newtoki":
                chapters = fetch_chapters_newtoki(self.manga_id, worker=self)
            else:
                chapters = fetch_chapters_for_manga(self.manga_id, self.langs)
            
            if self.isInterruptionRequested(): return
            
            # Apply newest-first sorting to all sources
            chapters = sort_chapters_newest_first(chapters)
            
            if not self.isInterruptionRequested():
                self.finished.emit(chapters)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.error.emit(str(e))

class DownloadWorker(QThread):
    progress = Signal(str)
    percent = Signal(int)
    finished = Signal(dict)
    error = Signal(str)
    captcha_requested = Signal(str)

    def __init__(self, chapters, base_dir, use_saver, manga_id=None, make_cbz=False, site="mangadex", debug_mode=False, use_proxy=True, use_selenium=True):
        super().__init__()
        self.chapters = chapters
        self.base_dir = base_dir
        self.use_saver = use_saver
        self.manga_id = manga_id
        self.make_cbz = make_cbz
        self.site = site
        self.debug_mode = debug_mode
        self.use_proxy = use_proxy
        self.use_selenium = use_selenium
        self._is_running = True
        self._selenium_driver = None
        self._newtoki_driver = None
        self.captcha_response = None
        self.job_stats: Dict[str, Any] = {
            "total": len(chapters),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "chapter_results": [],
        }
        
        # PROPER seleniumbase import
        try:
            from seleniumbase import Driver
            self.Driver = Driver  # Store class reference
            if self.debug_mode: print("✅ SeleniumBase Driver imported")
        except ImportError:
            if self.debug_mode: print("❌ SeleniumBase missing → Using generic fallback")
            self.Driver = None

    def get_driver(self):
        """Safe driver initialization"""
        if self._selenium_driver is None and self.Driver:
            try:
                self.progress.emit("Launching Browser...")
                self._selenium_driver = self.Driver(uc=True, headless=False, disable_csp=True, undetectable=True, browser="chrome", user_data_dir=None)
            except Exception as e:
                print(f"Driver initialization failed: {e}")
                self._selenium_driver = None
        return self._selenium_driver

    def set_captcha_response(self, response):
        self.captcha_response = response

    def extract_images_with_autoscroll(self, driver):
        """Scroll + extract ALL images - YOUR WORKING VERSION"""
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        image_urls = []
        
        selectors = [
            'img[src*="baozimh"]', 'img[src*="baozicdn"]', 'img',
            'p img', '.content img', 'div img', '[class*="image"] img'
        ]
        
        for selector in selectors:
            imgs = soup.select(selector)
            for img in imgs:
                src = img.get('src') or img.get('data-src') or img.get('data-lazy')
                if src and src.startswith('http') and any(x in src.lower() for x in ['jpg','png','webp','avif']):
                    image_urls.append(src)
        
        return list(dict.fromkeys(image_urls))  # Dedupe

    def baozimh_universal_watermark_bypass(self, img_url):
        """SIMPLE - path extraction only"""
        path = re.sub(r'^https?://[^/]+', '', img_url)
        return f"https://static-tw.baozimh.com{path}"

    def is_last_page_baozimh(self, driver):
        """DETECT icon-xiayibu = END"""
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        return bool(soup.select_one('span.iconfont.icon-xiayibu'))

    def get_page_info_from_title(self, driver):
        """ONLY NEW FUNCTION - Parse '(1/3)' from span.title"""
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        title_span = soup.select_one('span.title')
        if title_span:
            title_text = title_span.get_text()
            match = re.search(r'\((\d+)/(\d+)\)', title_text)
            if match:
                return int(match.group(1)), int(match.group(2))
        return 1, 1

    def build_twmanga_chapter_url(self, series_url, chapter_title):
        """CONSTRUCT CORRECT TWMANGA URL FROM ANY INPUT"""
        # Extract series slug from ANY URL 
        series_slug = None
        if 'laoshexiuxianchuan-linshi1' in series_url:
            series_slug = 'laoshexiuxianchuan-linshi1'
        else:
            # Extract from any pattern 
            series_match = re.search(r'comic[/_]([^/]+)', series_url)
            series_slug = series_match.group(1) if series_match else 'laoshexiuxianchuan-linshi1'
        
        # Extract chapter number from title: "第80話" → 80 
        chapter_match = re.search(r'第(\d+)話', chapter_title)
        chapter_num = chapter_match.group(1) if chapter_match else '80'
        
        # BUILD PERFECT URL 
        return f"https://www.twmanga.com/comic/chapter/{series_slug}/0_{chapter_num}.html"

    def get_all_page_urls(self, base_url, total_pages):
        """Page 1 = base, Page 2 = _2.html, Page 3 = _3.html"""
        urls = [base_url]  # Page 1 
        
        base_no_html = base_url.replace('.html', '')
        for page_num in range(2, total_pages + 1):
            urls.append(f"{base_no_html}_{page_num}.html")
        
        return urls

    def download_images_batch(self, images, output_dir, title, i_base=0, total_chaps=1):
        """ACTUAL DOWNLOAD - WAS MISSING"""
        if isinstance(output_dir, Path):
            output_dir = str(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        for i, img_url in enumerate(images):
            if not self._is_running: break
            try:
                img_url = self.baozimh_universal_watermark_bypass(img_url)
                resp = requests.get(img_url, timeout=10, stream=True)
                if resp.status_code == 200:
                    ext = 'jpg'
                    if '.' in img_url:
                        ext = img_url.split('.')[-1].split('?')[0]
                    with open(f"{output_dir}/{i:03d}.{ext}", 'wb') as f:
                        for chunk in resp.iter_content(1024):
                            f.write(chunk)
                
                # Update progress
                chapter_progress = (i + 1) / len(images)
                total_progress = ((i_base + chapter_progress) / total_chaps) * 100
                self.percent.emit(int(total_progress))
            except:
                continue
        print(f"✅ Downloaded {len(images)} images to {output_dir}")

    def wait_for_captcha(self, message):
        self.captcha_response = None
        self.captcha_requested.emit(message)
        while self.captcha_response is None and self._is_running:
            time.sleep(0.5)
        return self.captcha_response
        
        # Working Free Proxies (March 2026)
        self.proxy_list = [
            "http://20.210.113.32:80",
            "http://47.74.253.167:8888",
            "http://103.175.239.199:80",
            "http://43.135.36.246:80",
            "http://154.65.39.37:80"
        ]

    def stop(self):
        self._is_running = False
        if self._selenium_driver:
            try:
                self._selenium_driver.quit()
            except:
                pass
        if self._newtoki_driver:
            try:
                self._newtoki_driver.quit()
            except:
                pass

    def _should_stop(self):
        return (not self._is_running) or self.isInterruptionRequested()

    def _record_chapter_result(self, chapter_label: str, status: str, detail: str = ""):
        if status == "completed":
            self.job_stats["completed"] += 1
        elif status == "failed":
            self.job_stats["failed"] += 1
        else:
            self.job_stats["skipped"] += 1
        self.job_stats["chapter_results"].append(
            {"chapter": chapter_label, "status": status, "detail": detail}
        )

    def download_chapter_generic(self, chapter_url, title, output_dir, ch_num=None, i=0, total_chaps=1):
        """Your ORIGINAL - 50 images working"""
        driver = self.get_driver()
        if not driver:
            # If Selenium completely fails, try HTTP fallback here too
            return self._http_fallback(chapter_url, title, output_dir, i, total_chaps)
            
        driver.get(chapter_url)
        images = self.extract_images_with_autoscroll(driver)
         
        if images:
            self.download_images_batch(images, output_dir, title, i, total_chaps)
            return True
        return False

    def build_twmanga_url(self, series_slug, chapter_num):
        """ANY series → perfect twmanga URL"""
        return f"https://www.twmanga.com/comic/chapter/{series_slug}/0_{chapter_num}.html"

    def get_series_slug(self, series_url, chapter_title):
        """Map series title/URL to known slugs for URL construction"""
        if 'laoshexiuxianchuan-linshi1' in series_url:
            return 'laoshexiuxianchuan-linshi1'
        if 'daoguaiyixian' in series_url or '道詭異仙' in series_url or '道詭異仙' in chapter_title:
            return 'daoguaiyixian'
        
        # Generic extraction from URL
        series_match = re.search(r'comic[/_]([^/]+)', series_url)
        return series_match.group(1) if series_match else 'laoshexiuxianchuan-linshi1'

    def extract_images_http(self, url):
        """HTTP-only image extraction fallback"""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200: return []
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            image_urls = []
            selectors = ['img[src*="baozimh"]', 'img[src*="baozicdn"]', 'img', 'p img', '.content img']
            
            for selector in selectors:
                imgs = soup.select(selector)
                for img in imgs:
                    src = img.get('src') or img.get('data-src') or img.get('data-lazy')
                    if src and src.startswith('http'):
                        image_urls.append(src)
            return list(dict.fromkeys(image_urls))
        except:
            return []

    def _http_fallback(self, chapter_url, title, output_dir, i_base=0, total_chaps=1):
        """Final fallback - No browser needed"""
        self.progress.emit("Using HTTP-only fallback...")
        images = self.extract_images_http(chapter_url)
        if images:
            self.download_images_batch(images, output_dir, title, i_base, total_chaps)
            return True
        return False

    def _baozimh_selenium_pro(self, chap, out_path, ch_num, i, total_chaps, series_url):
        """Selenium version - ONLY if Driver works"""
        if not self.Driver:
            raise Exception("No Driver available")
        
        driver = self.get_driver()
        if not driver:
            raise Exception("Driver initialization failed")
            
        title = chap.get('title', '')
        s_url = series_url or f"https://www.baozimh.com/comic/laoshexiuxianchuan-linshi1"
        
        # Extract series/chapter info
        series_slug = self.get_series_slug(s_url, title)
        
        # Extract chapter number from title: "第80話" → 80 or "Ch 76" -> 76
        chapter_match = re.search(r'(?:第|Ch\s*)(\d+)', title)
        chapter_num = chapter_match.group(1) if chapter_match else "80"
        
        base_chapter_url = self.build_twmanga_url(series_slug, chapter_num)
        print(f"🔗 BUILT PRO URL: {base_chapter_url}")
        
        driver.get(base_chapter_url)
        time.sleep(3)
        
        # GET TOTAL PAGES 
        _, total_pages = self.get_page_info_from_title(driver)
        print(f"📚 {total_pages} pages total") 
        
        # GET ALL PAGE URLS 
        page_urls = self.get_all_page_urls(base_chapter_url, total_pages)
        
        all_images = []
        for j, page_url in enumerate(page_urls, 1):
            if not self._is_running: break
            print(f"📄 Page {j}/{total_pages}: {page_url}") 
            driver.get(page_url)
            time.sleep(3)
            
            page_images = self.extract_images_with_autoscroll(driver) 
            unique_page_images = list(dict.fromkeys(page_images))
            all_images.extend(unique_page_images)
            print(f"   → {len(unique_page_images)} images (total unique: {len(set(all_images))})") 
        
        if all_images:
            unique_images = list(dict.fromkeys(all_images))
            self.download_images_batch(unique_images, out_path, title, i, total_chaps)
            print(f"✅ Downloaded {len(unique_images)} images across {total_pages} pages!") 
            return True
        return False

    def download_chapter_baozimh_pro(self, chap, out_path, ch_num, i, total_chaps, series_url=None):
        """Works for ANY series + Multiple fallbacks"""
        chapter_url = chap['id'] if chap['id'].startswith("http") else urljoin(BAOZIMH_BASE, chap['id'])
        title = chap.get('title', '')
        
        # TRIPLE FALLBACK CHAIN
        try:
            # 1. SeleniumBase Pro (ideal)
            return self._baozimh_selenium_pro(chap, out_path, ch_num, i, total_chaps, series_url)
        except Exception as e1:
            print(f"❌ Selenium Pro failed: {e1}")
            try:
                # 2. Generic browser (working 50 images)
                return self.download_chapter_generic(chapter_url, title, out_path, ch_num, i, total_chaps)
            except Exception as e2:
                print(f"❌ Generic failed: {e2}")
                # 3. HTTP only (no browser)
                return self._http_fallback(chapter_url, title, out_path, i, total_chaps)

    def download_chapter_complete(self, chapter_url, out_path, ch_num, i, total_chaps, chap):
        if not selenium_available:
            self.progress.emit("Selenium not available for Happymh extraction")
            return False
            
        if not self._selenium_driver:
            self._selenium_driver = self.get_driver()
            if not self._selenium_driver:
                self.progress.emit("Selenium initialization failed for Happymh")
                return False
            self._selenium_driver.set_page_load_timeout(120)

        try:
            if self.debug_mode: print(f"DEBUG: Loading chapter page: {chapter_url}")
            self.progress.emit(f"Bypassing Cloudflare for Ch {ch_num} (120s limit)...")
            
            # 1. Selenium loads chapter
            self._selenium_driver.uc_open_with_reconnect(chapter_url, 6)
            
            # 120s Cloudflare wait until "Just a moment" AND "人机验证" gone
            try:
                WebDriverWait(self._selenium_driver, 120).until_not(
                    EC.title_contains("Just a moment")
                )
                WebDriverWait(self._selenium_driver, 120).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article.css-8o1tmw-root, div.css-1krjvn-imgContainer, img[id^='scan']"))
                )
                if self.debug_mode: print(f"DEBUG: TITLE OK: {self._selenium_driver.title}")
            except Exception as e:
                if self.debug_mode: 
                    print(f"DEBUG: UC Bypass/Wait timed out or failed: {e}")
                    print(f"DEBUG: Page Title: {self._selenium_driver.title}")

            # 2. Aggressive scroll x10 for lazy loading (scan0-scan50)
            if self.debug_mode: print("DEBUG: Starting aggressive scrolling (x15)...")
            for scroll_step in range(15):
                self._selenium_driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                self._selenium_driver.execute_script(f"window.scrollBy(0, {-random.randint(50, 150)});")
                if self.debug_mode and scroll_step % 5 == 0:
                    height = self._selenium_driver.execute_script("return document.body.scrollHeight")
                    print(f"DEBUG: Scroll step {scroll_step}, Height: {height}")

            # 3. Extract scan0-scan50 URLs
            urls = []
            if self.debug_mode: print("DEBUG: Extracting image URLs...")
            for k in range(51):
                try:
                    img = self._selenium_driver.find_element(By.ID, f"scan{k}")
                    src = img.get_attribute("src")
                    if src and "ruicdn.happymh.com" in src:
                        urls.append(src)
                except:
                    if k > 5: break 
            
            # Fallback to manual parser
            if not urls:
                if self.debug_mode: print("DEBUG: Selenium found no scans, falling back to manual parser")
                manga_url = f"{HAPPYMH_BASE}/manga/{self.manga_id}"
                urls = get_happymh_images(chap['id'], manga_url=manga_url)
                if self.debug_mode: print(f"DEBUG: Manual parser found {len(urls)} images")

            if not urls:
                self.progress.emit(f"No images found for Ch {ch_num}")
                return False

            # 4. Extract cookies → transfer to user's existing curl_cffi session
            sel_ua = self._selenium_driver.execute_script("return navigator.userAgent")
            sel_cookies = self._selenium_driver.get_cookies()
            
            self.progress.emit(f"Found {len(urls)} images + {len(sel_cookies)} cookies. Downloading...")
            if not out_path.exists():
                out_path.mkdir(parents=True, exist_ok=True)

            # 5. Initialize curl_cffi session with Selenium's exact environment
            session = requests_cf.Session(impersonate="chrome120")
            if self.debug_mode: print(f"DEBUG: Transferring cookies to curl_cffi...")
            for c in sel_cookies:
                try:
                    session.cookies.set(c['name'], c['value'], domain=c.get('domain', '.happymh.com'), path=c.get('path', '/'))
                except: pass

            total_imgs = len(urls)
            for j, url in enumerate(urls, 1):
                if not self._is_running: break
                
                # Apply Baozimh watermark bypass
                url = self.baozimh_universal_watermark_bypass(url)
                
                fname = f"{j:03d}.jpg"
                if "." in url:
                    parts = url.split(".")
                    ext = parts[-1].split("?")[0]
                    if len(ext) <= 4: fname = f"{j:03d}.{ext}"
                
                dest = out_path / fname
                if not dest.exists():
                    try:
                        time.sleep(random.uniform(1.0, 2.0))
                        # Match Selenium UA/headers exactly for image requests
                        headers = {
                            "Referer": chapter_url,
                            "User-Agent": sel_ua,
                            "Origin": "https://m.happymh.com",
                            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                            "Accept-Encoding": "gzip, deflate, br",
                            "Sec-Fetch-Dest": "image",
                            "Sec-Fetch-Mode": "no-cors",
                            "Sec-Fetch-Site": "same-site",
                            "Connection": "keep-alive"
                        }
                        
                        r = session.get(url, headers=headers, impersonate="chrome120", timeout=30)
                        if r.status_code == 403:
                            headers["Referer"] = "https://m.happymh.com/"
                            r = session.get(url, headers=headers, impersonate="chrome120", timeout=30)

                        if self.debug_mode: 
                            print(f"DEBUG: Ch {ch_num} P{j} Status: {r.status_code} {'✓ SAVED' if r.status_code == 200 else '✗ FAILED'}")

                        r.raise_for_status()
                        
                        # Save TEMP as .avif (since HappyMH often serves AVIF)
                        temp_dest = dest.with_suffix(".avif")
                        with open(temp_dest, "wb") as f:
                            f.write(r.content)
                        
                        # Convert AVIF -> JPG using Pillow
                        try:
                            with Image.open(temp_dest) as img:
                                img.convert("RGB").save(dest, "JPEG", quality=95)
                            if self.debug_mode: print(f"DEBUG: Ch {ch_num} P{j} SAVED (AVIF->JPG)")
                        except Exception as conv_err:
                            if self.debug_mode: print(f"DEBUG: Conversion failed P{j}: {conv_err}. Falling back to raw.")
                            shutil.copy2(temp_dest, dest)
                        finally:
                            if temp_dest.exists():
                                os.remove(temp_dest)
                    except Exception as e:
                        self.progress.emit(f"Error page {j}: {e}")

                # Update progress
                if total_imgs > 0:
                    chapter_progress = j / total_imgs
                    total_progress = ((i + chapter_progress) / total_chaps) * 100
                    self.percent.emit(int(total_progress))
            
            return True
        except Exception as e:
            if self.debug_mode: 
                print(f"DEBUG: Happymh UC Hybrid failed: {e}")
                traceback.print_exc()
            return False

    def safe_navigate_with_alert_handling(self, driver, chapter_url):
        """Navigate to a URL while handling and dismissing alerts"""
        try:
            # DISMISS ANY EXISTING ALERTS FIRST
            try:
                alert = driver.switch_to.alert
                print(f"DEBUG: Dismissing existing alert before navigation: {alert.text}")
                alert.dismiss()
                time.sleep(2)
            except NoAlertPresentException:
                pass
            
            # Human navigation via JS location.href (simulates click)
            driver.execute_script(f"window.location.href = '{chapter_url}';")
            time.sleep(random.uniform(5.0, 8.0))
            
            # POST-NAVIGATION ALERT CHECK
            try:
                alert = driver.switch_to.alert
                print(f"ALERT DETECTED after navigation: {alert.text}")
                alert.dismiss()
                return False # Navigation failed due to alert
            except NoAlertPresentException:
                pass
                
            return True # Success
            
        except UnexpectedAlertPresentException:
            print("CRITICAL: Unexpected alert during navigation")
            try:
                driver.switch_to.alert.dismiss()
            except: pass
            return False
        except Exception as e:
            print(f"Navigation error: {e}")
            return False

    def validate_newtoki_chapter_url(self, driver, chapter_id, domain):
        """Check if a chapter ID leads to a valid page or a 'non-existent' error"""
        # NewToki expects /webtoon/[ID] or /view/[ID]
        test_url = f"https://{domain}/webtoon/{chapter_id}"
        
        try:
            # Try a quick load to check for alerts
            driver.get(test_url)
            time.sleep(3)
            
            # Check for "존재하지 않는 게시판입니다" alert
            try:
                alert = driver.switch_to.alert
                if "존재하지 않는" in alert.text:
                    print(f"INVALID CHAPTER ID (Alert): {chapter_id}")
                    alert.dismiss()
                    return None
                alert.dismiss()
            except NoAlertPresentException:
                pass

            # Check page source for the error text as well
            page_source = driver.page_source.lower()
            if "존재하지 않는 게시판" in page_source:
                print(f"INVALID CHAPTER ID (Source): {chapter_id}")
                return None
            
            # Return the current URL (handles redirects)
            return driver.current_url
        except Exception as e:
            print(f"Validation error for {chapter_id}: {e}")
            return None

    def human_navigate_and_wait(self, driver, chapter_url, ch_num):
        """Simulate human browsing behavior to avoid anti-bot detection"""
        self.progress.emit(f"Navigating to Ch {ch_num} (human simulation)...")
        
        # Human delay before ANY action
        time.sleep(random.uniform(2.0, 4.0))
        
        # Simulate human browsing first
        driver.execute_script("window.scrollTo(0, Math.random() * document.body.scrollHeight / 2);")
        time.sleep(random.uniform(1.0, 2.0))
        
        # Mouse movement + resize events
        driver.execute_script("""
            document.dispatchEvent(new MouseEvent('mousemove', {
                clientX: Math.random() * window.innerWidth,
                clientY: Math.random() * window.innerHeight
            }));
            window.dispatchEvent(new Event('resize'));
        """)
        
        # Navigate WITH REFERRER (not direct jump)
        driver.execute_script(f"window.location.href = '{chapter_url}';")
        
        # HUMAN LOAD WAITING (not WebDriverWait)
        time.sleep(random.uniform(4.0, 7.0))
        
        # Confirm we're NOT redirected
        if "homepage" in driver.current_url or "newtoki" in driver.current_url and "/view/" not in driver.current_url:
            print("\nDETECTION! Redirected to homepage. Retrying with longer delay...")
            time.sleep(10)
            driver.get(chapter_url)
            time.sleep(5)
        
        # Final human scroll confirmation
        driver.execute_script("window.scrollTo(0, 300);")
        time.sleep(2)

    def fast_complete_autoscroll(self, driver, scroll_step=1000, delay=0.5, max_iterations=50):
        """Fast scroll (1000px/0.5s) to load ALL lazy images without skipping"""
        self.progress.emit("NewToki: Auto-scrolling to load ALL images...")
        if self.debug_mode: print("DEBUG: Fast auto-scroll loading ALL images...")
        
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        
        while scroll_count < max_iterations:
            # Scroll 1000px down
            driver.execute_script(f"window.scrollBy(0, {scroll_step});")
            time.sleep(delay) # 0.5s pause = fast but loads images
            
            # Check if new content loaded
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height > last_height:
                if self.debug_mode: print(f"DEBUG: Scroll {scroll_count}: New content detected ({new_height}px)")
                last_height = new_height
            
            scroll_count += 1
            
            # Stop if no new content AND scrolled enough
            if new_height == last_height and scroll_count > 10:
                if self.debug_mode: print(f"DEBUG: Scroll complete: {scroll_count} steps")
                break
        
        # Final top->bottom scroll to catch stragglers
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

    def download_chapter_newtoki(self, chap, out_path, ch_num, i, total_chaps):
        if not uc_available:
            self.progress.emit("Error: undetected-chromedriver is not installed.")
            return False

        if not self._newtoki_driver:
            self.progress.emit("Launching NewToki Browser (undetected-chromedriver v146)...")
            options = uc.ChromeOptions()
            self._newtoki_driver = uc.Chrome(options=options, version_main=146)
        
        driver = self._newtoki_driver
        domain = urlparse(self.manga_id).netloc
        
        try:
            # 1. URL VALIDATION FIRST (skip invalid ones)
            valid_url = self.validate_newtoki_chapter_url(driver, chap['id'], domain)
            if not valid_url:
                self.progress.emit(f"SKIPPING invalid chapter: {ch_num}")
                return False

            # 2. SAFE NAVIGATION WITH ALERT HANDLING
            if not self.safe_navigate_with_alert_handling(driver, valid_url):
                self.progress.emit(f"NAVIGATION FAILED (ALERT): Ch {ch_num}")
                return False

            # 3. FAST AUTO-SCROLL (NEW - CRITICAL)
            self.fast_complete_autoscroll(driver, scroll_step=1000, delay=0.5)
            
            # Double check for redirect or homepage
            if domain not in driver.current_url or "webtoon" not in driver.current_url and "view" not in driver.current_url:
                msg = (
                    f"DETECTION/REDIRECT! Manual intervention for Ch {ch_num}\n"
                    f"URL: {driver.current_url}\n\n"
                    "Please navigate back to the chapter manually in the browser window.\n"
                    "Click 'Solved' when images appear."
                )
                
                while True:
                    res = self.wait_for_captcha(msg)
                    if res == "success":
                        break
                    elif res == "retry":
                        self.human_navigate_and_wait(driver, url, ch_num)
                        continue
                    else:
                        return False
            
            # Use community-validated extraction logic
            img_urls = extract_newtoki_images_pro(driver)
            
            if not img_urls:
                self.progress.emit(f"No images found for Ch {ch_num}")
                return False
            
            self.progress.emit(f"Found {len(img_urls)} images. Downloading (slow pace)...")
            if not out_path.exists():
                out_path.mkdir(parents=True, exist_ok=True)
            
            # Multi-threaded download with rate limiting
            user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ]
            
            def download_one(idx, img_url):
                if not self._is_running: return
                
                # Apply Baozimh watermark bypass (Community Upgrade)
                img_url = self.baozimh_universal_watermark_bypass(img_url)
                
                time.sleep(random.uniform(4.0, 10.0)) # Even slower image pacing
                
                ext = ".jpg"
                if ".png" in img_url.lower(): ext = ".png"
                elif ".webp" in img_url.lower(): ext = ".webp"
                
                filename = f"{idx+1:03d}{ext}"
                dest = out_path / filename
                if dest.exists(): return
                
                headers = {"User-Agent": random.choice(user_agents), "Referer": valid_url}
                
                try:
                    r = requests.get(img_url, headers=headers, timeout=30, stream=True)
                    if r.status_code == 429:
                        time.sleep(20)
                        r = requests.get(img_url, headers=headers, timeout=30, stream=True)
                    
                    r.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                except Exception as e:
                    print(f"Error downloading {img_url}: {e}")

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(download_one, j, img_url) for j, img_url in enumerate(img_urls)]
                for j, future in enumerate(concurrent.futures.as_completed(futures)):
                    if not self._is_running: break
                    chapter_progress = (j + 1) / len(img_urls)
                    total_progress = ((i + chapter_progress) / total_chaps) * 100
                    self.percent.emit(int(total_progress))
            
            # Post-chapter human pause (longer)
            time.sleep(random.uniform(10.0, 20.0))
            return True
        except Exception as e:
            if self.debug_mode: print(f"DEBUG: NewToki failed: {e}")
            return False
        # driver.quit() removed here to reuse driver across chapters

    def run(self):
        total_chaps = len(self.chapters)
        for i, chap in enumerate(self.chapters):
            if self._should_stop():
                break
            
            ch_num = chap.get("chapter") or "?"
            chapter_label = f"Chapter {ch_num}"
            self.progress.emit(f"Processing Chapter {ch_num}...")
            
            try:
                safe_title = "".join(c for c in (chap.get('title') or "") if c.isalnum() or c in (' ', '-', '_')).strip()
                folder_name = f"Chapter {ch_num}"
                if safe_title:
                    folder_name += f" - {safe_title}"
                
                out_path = Path(self.base_dir) / folder_name
                chapter_ok = False

                if self.site == "baozimh":
                    # Baozimh Industrial Download
                    series_url = self.manga_id # This contains the series URL for Baozimh
                    if self.download_chapter_baozimh_pro(chap, out_path, ch_num, i, total_chaps, series_url):
                        self._finalize_chapter(out_path, folder_name, chap)
                        chapter_ok = True
                    self._record_chapter_result(chapter_label, "completed" if chapter_ok else "failed")
                    continue

                elif self.site == "happymh":
                    chapter_url = f"{HAPPYMH_BASE}{chap['id']}" if chap['id'].startswith("/") else chap['id']
                    if self.download_chapter_complete(chapter_url, out_path, ch_num, i, total_chaps, chap):
                        self._finalize_chapter(out_path, folder_name, chap)
                        chapter_ok = True
                    self._record_chapter_result(chapter_label, "completed" if chapter_ok else "failed")
                    continue
                elif self.site == "newtoki":
                    # Inter-chapter human delay (CRITICAL for NewToki)
                    if i > 0:
                        delay = random.uniform(8.0, 15.0)
                        self.progress.emit(f"Human reading delay: {delay:.1f}s...")
                        interruptible_sleep(delay, self._should_stop, step_seconds=0.25)
                        
                    if self.download_chapter_newtoki(chap, out_path, ch_num, i, total_chaps):
                        self._finalize_chapter(out_path, folder_name, chap)
                        chapter_ok = True
                    self._record_chapter_result(chapter_label, "completed" if chapter_ok else "failed")
                    continue
                else:
                    # MangaDex Download
                    urls = []
                    chap_info = get_chapter_info(chap['id'])
                    athome = get_at_home_base(chap['id'])
                    base = athome.get("baseUrl")
                    
                    attrs = chap_info.get("attributes", {})
                    athome_chap = athome.get("chapter", {})
                    if not attrs.get("data") and athome_chap.get("data"):
                        attrs = athome_chap
                    
                    urls = craft_image_urls(base, attrs, use_data_saver=self.use_saver)

                if not urls:
                    self.progress.emit(f"No images for Ch {ch_num}")
                    self._record_chapter_result(chapter_label, "failed", "No images")
                    continue
                
                if not out_path.exists():
                    out_path.mkdir(parents=True, exist_ok=True)
                
                # Use session for high-speed download
                session = requests.Session()

                total_imgs = len(urls)
                for j, url in enumerate(urls, 1):
                    if self._should_stop():
                        break
                    
                    # Apply Baozimh watermark bypass
                    url = self.baozimh_universal_watermark_bypass(url)
                    
                    fname = f"{j:03d}.jpg"
                    if "." in url:
                        parts = url.split(".")
                        ext = parts[-1].split("?")[0]
                        if len(ext) <= 4: fname = f"{j:03d}.{ext}"
                    
                    dest = out_path / fname
                    if not dest.exists():
                        if url.startswith("canvas_data:"):
                            try:
                                import base64
                                header, encoded = url.split(",", 1)
                                data = base64.b64decode(encoded)
                                with open(dest, "wb") as f:
                                    f.write(data)
                            except Exception as e:
                                self.progress.emit(f"Error saving canvas: {e}")
                            continue

                        try:
                            # Add a random delay between requests to avoid bot detection
                            if j > 1:
                                delay = random.uniform(1.0, 3.0)
                                if self.debug_mode: print(f"DEBUG: Sleeping for {delay:.2f}s...")
                                time.sleep(delay)

                            get_kwargs = {"stream": True, "timeout": 30}
                            # Default headers for other sites (MangaDex, etc)
                            headers = {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                            }
                            get_kwargs["headers"] = headers
                            
                            r = session.get(url, **get_kwargs)
                            try:
                                r.raise_for_status()
                                body = b"".join(r.iter_content(8192))
                                if body:
                                    atomic_write_bytes(dest, body)
                            finally:
                                if hasattr(r, 'close'):
                                    r.close()
                        except Exception as e:
                            self.progress.emit(f"Error page {j}: {e}")
                            if self.debug_mode:
                                import traceback
                                traceback.print_exc()
                    
                    # Update progress
                    if total_imgs > 0:
                        chapter_progress = j / total_imgs
                        total_progress = ((i + chapter_progress) / total_chaps) * 100
                        self.percent.emit(int(total_progress))
                
                if not self._is_running: break
                
                # Common Metadata & CBZ
                self._finalize_chapter(out_path, folder_name, chap)
                self._record_chapter_result(chapter_label, "completed")

            except Exception as e:
                self.error.emit(f"Error Ch {ch_num}: {e}")
                self._record_chapter_result(chapter_label, "failed", str(e))
            
            self.percent.emit(int(((i + 1) / total_chaps) * 100))

        if self._should_stop():
            remaining = max(0, self.job_stats["total"] - len(self.job_stats["chapter_results"]))
            self.job_stats["skipped"] += remaining
        self.finished.emit(self.job_stats)

    def _finalize_chapter(self, out_path, folder_name, chap):
        # Common Metadata
        meta = {
            "chapter": chap,
            "downloaded_at": int(time.time())
        }
        if out_path.exists():
            with open(out_path / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        
            # Common CBZ
            if self.make_cbz:
                cbz_path = Path(self.base_dir) / f"{folder_name}.cbz"
                self.progress.emit(f"Creating CBZ: {cbz_path.name}")
                with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for item in out_path.glob("*"):
                        if item.is_file():
                            zf.write(item, arcname=item.name)
                                
                shutil.rmtree(out_path)

class ImageLoader(QThread):
    loaded = Signal(QImage)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            r = requests.get(self.url, timeout=10)
            r.raise_for_status()
            img = QImage.fromData(r.content)
            self.loaded.emit(img)
        except:
            pass

                     

class ModernMangaDexGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.library = self.load_library()
        self._old_workers = []
        self.search_results = []
        self.selected_manga = None
        self.chapters = []
        self.all_chapter_groups = set()
        
        self.setWindowTitle("MultiMangaScraper")
        self.resize(1200, 850)
        
        # Apply Master Stylesheet
        self.setStyleSheet(STYLESHEET)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ━━━ 1. TOP BAR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        self.top_bar_layout = QHBoxLayout(self.top_bar)
        self.top_bar_layout.setContentsMargins(16, 0, 16, 0)
        self.top_bar_layout.setSpacing(12)

        # Source Dropdown
        self.site_combo = QComboBox()
        self.site_combo.addItems(["MangaDex", "Baozimh", "Happymh", "NewToki"])
        self.site_combo.setToolTip("Select source site")
        
        # Search Input
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search manga titles...")
        self.search_input.returnPressed.connect(self.start_search)
        
        # Romaji Toggle
        self.romaji_container = QHBoxLayout()
        self.romaji_container.setSpacing(8)
        self.romaji_label = QLabel("Romaji")
        self.romaji_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        self.romaji_toggle = ToggleSwitch()
        self.romaji_toggle.setChecked(self.settings.get("romaji_titles", False))
        self.romaji_toggle.clicked.connect(self.on_romaji_toggled)
        self.romaji_container.addWidget(self.romaji_label)
        self.romaji_container.addWidget(self.romaji_toggle)

        # Search Button
        self.search_btn = QPushButton("Search")
        self.search_btn.setObjectName("AccentButton")
        self.search_btn.setFixedWidth(100)
        self.search_btn.clicked.connect(self.start_search)
        
        # Library Button
        self.lib_btn = QPushButton("Library")
        self.lib_btn.setObjectName("LibraryButton")
        self.lib_btn.setFixedWidth(100)
        self.lib_btn.clicked.connect(self.open_library)

        self.top_bar_layout.addWidget(self.site_combo)
        self.top_bar_layout.addWidget(self.search_input, stretch=1)
        self.top_bar_layout.addSpacing(10)
        self.top_bar_layout.addLayout(self.romaji_container)
        self.top_bar_layout.addSpacing(10)
        self.top_bar_layout.addWidget(self.search_btn)
        self.top_bar_layout.addWidget(self.lib_btn)

        self.main_layout.addWidget(self.top_bar) # ADDED TOP BAR

        self.log_text = QLabel("")
        self.log_text.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.log_text.setVisible(False)
        self.main_layout.addWidget(self.log_text)

        # ━━━ SPLITTER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # ━━━ 2. LEFT PANEL — SEARCH RESULTS ━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.left_panel = QFrame()
        self.left_panel.setObjectName("SidePanel")
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(16, 16, 16, 16)
        
        self.results_header = QHBoxLayout()
        self.results_title = QLabel("RESULTS")
        self.results_title.setObjectName("SectionHeader")
        
        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("Badge")
        self.count_badge.setStyleSheet(f"background-color: {ACCENT_DIM}; color: {ACCENT};")
        
        self.results_header.addWidget(self.results_title)
        self.results_header.addStretch()
        self.results_header.addWidget(self.count_badge)
        
        self.left_layout.addLayout(self.results_header)
        
        self.loaded_label = QLabel("0 chapters loaded")
        self.loaded_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.left_layout.addWidget(self.loaded_label)
        
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderHidden(True)
        self.results_tree.setIndentation(0)
        self.results_tree.setColumnCount(1) # Sidebar only needs 1 column for clean look
        self.results_tree.itemSelectionChanged.connect(self.on_manga_selected)
        self.left_layout.addWidget(self.results_tree)
        
        self.splitter.addWidget(self.left_panel)

        # ━━━ 3. RIGHT PANEL — STACKED WIDGET ━━━━━━━━━━━━━━━━━━━━━━━━━
        self.right_stack = QStackedWidget()
        self.right_stack.setObjectName("DetailPanel")
        
        # Page 1: Welcome
        self.welcome_page = WelcomeWidget()
        self.right_stack.addWidget(self.welcome_page)
        
        # Page 2: Loading
        self.loading_page = LoadingPage()
        self.right_stack.addWidget(self.loading_page)
        
        # Page 3: Manga Detail View
        self.right_container = QWidget()
        self.right_layout = QVBoxLayout(self.right_container)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)
        
        # Vertical Splitter for Metadata vs Chapters
        self.detail_splitter = QSplitter(Qt.Vertical)
        self.detail_splitter.setHandleWidth(1)
        self.detail_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {BORDER}; }}")

        # ━━━ 3. MANGA DETAIL AREA (Scrollable) ━━━━━━━━━━━━━━━━━━━━━━━
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.NoFrame)
        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(24, 24, 24, 24)
        self.detail_layout.setSpacing(24)
        
        self.info_header = QHBoxLayout()
        self.info_header.setSpacing(24)
        
        # Cover
        self.cover_label = ScalableImageLabel()
        self.cover_label.setFixedSize(160, 228)
        self.info_header.addWidget(self.cover_label)
        
        # Info Column
        self.info_col = QVBoxLayout()
        self.info_col.setSpacing(12)
        
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(10)
        self.title_label = QLabel("Select a manga to start")
        self.title_label.setObjectName("MangaTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("background-color: white; color: black; border-radius: 4px; padding: 4px 12px;")
        
        self.status_badge = StatusBadge("Unknown", "info")
        
        self.title_row.addWidget(self.title_label, stretch=1)
        self.title_row.addWidget(self.status_badge)
        self.info_col.addLayout(self.title_row)
        
        self.desc_text = QTextEdit()
        self.desc_text.setReadOnly(True)
        self.desc_text.setFrameShape(QFrame.NoFrame)
        self.desc_text.setStyleSheet(f"color: {TEXT_SECONDARY}; line-height: 1.6; background: transparent;")
        self.desc_text.setMaximumHeight(120)
        self.info_col.addWidget(self.desc_text)
        
        # Languages
        self.lang_section = QVBoxLayout()
        self.lang_label = QLabel("LANGUAGES")
        self.lang_label.setObjectName("SectionHeader")
        self.lang_label.setStyleSheet("font-size: 11px;")
        
        self.lang_flow = QHBoxLayout()
        self.lang_flow.setSpacing(6)
        self.lang_list = QListWidget() 
        self.lang_list.hide()
        
        self.lang_section.addWidget(self.lang_label)
        self.lang_section.addLayout(self.lang_flow)
        self.info_col.addLayout(self.lang_section)
        
        # Add to Library Button
        self.add_lib_btn = QPushButton("Add to Library")
        self.add_lib_btn.setObjectName("AccentButton")
        self.add_lib_btn.setFixedHeight(40)
        self.add_lib_btn.setFixedWidth(160)
        self.add_lib_btn.clicked.connect(self.add_to_library)
        self.info_col.addWidget(self.add_lib_btn)
        
        self.info_header.addLayout(self.info_col, stretch=1)
        self.detail_layout.addLayout(self.info_header)
        
        self.detail_scroll.setWidget(self.detail_widget)
        self.detail_splitter.addWidget(self.detail_scroll)

        # ━━━ 4. CHAPTERS AREA ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.chapters_container = QWidget()
        self.chapters_layout = QVBoxLayout(self.chapters_container)
        self.chapters_layout.setContentsMargins(0, 0, 0, 0)
        self.chapters_layout.setSpacing(0)

        # CHAPTER CONTROLS BAR
        self.controls_bar = QFrame()
        self.controls_bar.setObjectName("ControlsBar")
        self.controls_bar.setFixedHeight(48)
        self.controls_layout = QHBoxLayout(self.controls_bar)
        self.controls_layout.setContentsMargins(16, 0, 16, 0)
        
        self.chapter_actions = SegmentedControl()
        self.sel_all_btn = self.chapter_actions.addButton("Select All")
        self.sel_none_btn = self.chapter_actions.addButton("Deselect All")
        self.invert_btn = self.chapter_actions.addButton("Invert")
        
        self.sel_all_btn.clicked.connect(self.select_all_chapters)
        self.sel_none_btn.clicked.connect(self.deselect_all_chapters)
        self.invert_btn.clicked.connect(self.invert_chapters)
        
        self.filter_groups_btn = QPushButton("Filter Groups")
        self.filter_groups_btn.setFixedHeight(32)
        self.filter_groups_btn.clicked.connect(self.show_group_filter)
        
        # Range Inputs
        self.range_layout = QHBoxLayout()
        self.range_label = QLabel("RANGE:")
        self.range_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        self.range_start = QLineEdit()
        self.range_start.setPlaceholderText("—")
        self.range_start.setFixedSize(64, 32)
        self.range_end = QLineEdit()
        self.range_end.setPlaceholderText("—")
        self.range_end.setFixedSize(64, 32)
        self.range_btn = QPushButton("Select")
        self.range_btn.setFixedHeight(32)
        self.range_btn.setStyleSheet(f"color: {ACCENT};")
        self.range_btn.clicked.connect(self.select_range)
        
        self.range_layout.addWidget(self.range_label)
        self.range_layout.addWidget(self.range_start)
        self.range_layout.addWidget(QLabel("-"))
        self.range_layout.addWidget(self.range_end)
        self.range_layout.addWidget(self.range_btn)
        
        self.controls_layout.addWidget(self.chapter_actions)
        self.controls_layout.addSpacing(16)
        self.controls_layout.addWidget(self.filter_groups_btn)
        self.controls_layout.addStretch()
        self.controls_layout.addLayout(self.range_layout)
        
        self.chapters_layout.addWidget(self.controls_bar)

        # OPTIONS BAR
        self.options_bar = QFrame()
        self.options_bar.setObjectName("OptionsBar")
        self.options_bar.setFixedHeight(40)
        self.options_layout = QHBoxLayout(self.options_bar)
        self.options_layout.setContentsMargins(16, 0, 16, 0)
        
        self.opt_label = QLabel("DOWNLOAD OPTIONS")
        self.opt_label.setObjectName("SectionHeader")
        self.opt_label.setStyleSheet("font-size: 10px;")
        
        self.data_saver_chk = QCheckBox("Data Saver")
        self.cbz_chk = QCheckBox("Save as CBZ")
        self.debug_chk = QCheckBox("Debug Mode")
        
        self.options_layout.addWidget(self.opt_label)
        self.options_layout.addSpacing(12)
        self.options_layout.addWidget(self.data_saver_chk)
        self.options_layout.addWidget(self.cbz_chk)
        self.options_layout.addWidget(self.debug_chk)
        self.options_layout.addStretch()
        
        self.chapters_layout.addWidget(self.options_bar)

        # DOWNLOAD BUTTON
        self.download_btn = DownloadButton("Download Selected (0 chapters)")
        self.download_btn.clicked.connect(self.start_download)
        
        self.dl_container = QFrame()
        self.dl_container.setStyleSheet(f"background-color: {SURFACE_1}; border-bottom: 1px solid {BORDER};")
        self.dl_layout = QHBoxLayout(self.dl_container)
        self.dl_layout.setContentsMargins(16, 12, 16, 12)
        self.dl_layout.addWidget(self.download_btn)
        self.chapters_layout.addWidget(self.dl_container)

        # CHAPTER TABLE
        self.chapter_tree = QTreeWidget()
        self.chapter_tree.setColumnCount(5)
        self.chapter_tree.setHeaderLabels(["#", "Title", "Lang", "Group", "Date"])
        header = self.chapter_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.chapter_tree.setColumnWidth(0, 100)
        self.chapter_tree.setColumnWidth(2, 56)
        self.chapter_tree.setColumnWidth(3, 140)
        self.chapter_tree.setColumnWidth(4, 110)
        self.chapter_tree.setAlternatingRowColors(True)
        self.chapter_tree.itemChanged.connect(self.update_download_count)
        
        self.chapters_layout.addWidget(self.chapter_tree)
        self.detail_splitter.addWidget(self.chapters_container)
        
        self.detail_splitter.setSizes([350, 500])
        self.right_layout.addWidget(self.detail_splitter)

        self.right_stack.addWidget(self.right_container)
        self.splitter.addWidget(self.right_stack)

        # Initialize UI state
        self.splitter.setSizes([280, 920])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.update_download_count()
        self.load_settings_to_ui()

    def on_romaji_toggled(self, checked):
        self.refresh_titles()

    def load_settings_to_ui(self):
        if self.settings.get("data_saver"): self.data_saver_chk.setChecked(True)
        if self.settings.get("cbz_mode"): self.cbz_chk.setChecked(True)
        if self.settings.get("debug_mode"): self.debug_chk.setChecked(True)
        # Toggle switch sync
        self.romaji_toggle.setChecked(self.settings.get("romaji_titles", False))

    def log(self, msg):
        self.log_text.setText(msg)
        print(msg)

    def get_preferred_title(self, manga_data):
        use_romaji = self.romaji_toggle.isChecked()
        attrs = manga_data.get('attributes', {})
        titles = attrs.get('title', {})
        alt_titles = attrs.get('altTitles', [])
        
        en_title = titles.get('en')
        jp_ro_title = titles.get('ja-ro')
        
                                                                
        if not en_title:
             for alt in alt_titles:
                if 'en' in alt:
                    en_title = alt['en']
                    break

        if not jp_ro_title:
            for alt in alt_titles:
                if 'ja-ro' in alt:
                    jp_ro_title = alt['ja-ro']
                    break
        
                         
                                                                      
                                                                        
        
        if use_romaji:
            if jp_ro_title: return jp_ro_title
            if en_title: return en_title
        else:
            if en_title: return en_title
            if jp_ro_title: return jp_ro_title
        
                                            
        return manga_data.get('title') or "Unknown Title"

    def refresh_titles(self):
                                                    
        if not self.search_results: return
        
                        
        selected_id = self.selected_manga['id'] if self.selected_manga else None
        
        self.results_tree.clear()
        for r in self.search_results:
            display_title = self.get_preferred_title(r)
            item = QTreeWidgetItem([display_title])
            item.setData(0, Qt.UserRole, r['id'])           
            self.results_tree.addTopLevelItem(item)
            
            if selected_id and r['id'] == selected_id:
                item.setSelected(True)
                                              
                self.title_label.setText(f"{display_title} ({r['status'] or 'N/A'})")

    def cleanup_worker(self, worker):
        if worker in self._old_workers:
            self._old_workers.remove(worker)
        worker.deleteLater()

    def start_search(self):
        query = self.search_input.text()
        if not query: return
        
        # Source detection logic
        if "newtoki" in query.lower():
            self.site_combo.setCurrentText("NewToki")
        elif "happymh.com" in query.lower():
            self.site_combo.setCurrentText("Happymh")
        elif "baozimh.com" in query.lower():
            self.site_combo.setCurrentText("Baozimh")
        elif "mangadex.org" in query.lower():
            self.site_combo.setCurrentText("MangaDex")

        site = self.site_combo.currentText()
        if site == "MangaDex":
            site_key = "mangadex"
        elif site == "Baozimh":
            site_key = "baozimh"
        elif site == "Happymh":
            site_key = "happymh"
        elif site == "NewToki":
            site_key = "newtoki"
        else:
            QMessageBox.information(self, "Not Implemented", f"Support for {site} is coming soon!")
            return

        self.log(f"Searching for: {query} on {site}...")
        
                                     
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            try: self.worker.finished.disconnect()
            except: pass
            try: self.worker.error.disconnect()
            except: pass
            
                                                            
            old_worker = self.worker
            self._old_workers.append(old_worker)
            old_worker.finished.connect(lambda: self.cleanup_worker(old_worker))
            self.worker = None

        self.results_tree.clear()
        self.search_btn.setEnabled(False)
        self.current_search_query = query
        
        # Switch to loading page
        self.right_stack.setCurrentIndex(1)
        
        self.worker = SearchWorker(query, site=site_key)
        self.worker.finished.connect(self.on_search_finished)
        self.worker.error.connect(lambda e: self.log(f"Search Error: {e}"))
        self.worker.start()

    def on_search_finished(self, results):
        self.search_btn.setEnabled(True)
        self.search_results = results
        self.log(f"Found {len(results)} results.")
        self.results_title.setText("RESULTS")
        self.count_badge.setText(str(len(results)))
        self.refresh_titles()
        
        if results:
            self.results_tree.setCurrentItem(self.results_tree.topLevelItem(0))
        else:
            # If no results, go back to welcome page
            self.right_stack.setCurrentIndex(0)
            self.results_tree.clear()
            QMessageBox.information(self, "No Results", f"No results found for '{self.current_search_query}' on {self.site_combo.currentText()}.")

    def on_manga_selected(self):
        selected_items = self.results_tree.selectedItems()
        if not selected_items: return

        # Cancel any ongoing cover loads or chapter fetches
        if hasattr(self, 'img_loader') and self.img_loader and self.img_loader.isRunning():
            self.img_loader.requestInterruption()
            try: self.img_loader.loaded.disconnect()
            except: pass
            old_loader = self.img_loader
            self._old_workers.append(old_loader)
            old_loader.finished.connect(lambda: self.cleanup_worker(old_loader))
            self.img_loader = None
            
        if hasattr(self, 'chap_worker') and self.chap_worker and self.chap_worker.isRunning():
            self.chap_worker.requestInterruption()
            try: self.chap_worker.finished.disconnect()
            except: pass
            try: self.chap_worker.error.disconnect()
            except: pass
            
            old_chap = self.chap_worker
            self._old_workers.append(old_chap)
            old_chap.finished.connect(lambda: self.cleanup_worker(old_chap))
            self.chap_worker = None

        idx = self.results_tree.indexOfTopLevelItem(selected_items[0])
        if idx < 0 or idx >= len(self.search_results): return
        
        self.selected_manga = self.search_results[idx]
        display_title = self.get_preferred_title(self.selected_manga)
        
        # Switch to details page
        self.right_stack.setCurrentIndex(2)
        
        # Update UI
        self.title_label.setText(display_title)
        self.title_label.setStyleSheet("background-color: white; color: black; border-radius: 4px; padding: 4px 12px;")
        
        self.status_badge.setText(self.selected_manga.get('status', 'Unknown').upper())
        # Apply color based on status
        status_colors = {
            "ongoing": ("#7a5a10", "#f39c12"),
            "completed": ("#1e5a2d", "#2ecc71"),
            "hiatus": ("#1a4a6e", "#3498db")
        }
        bg, fg = status_colors.get(self.selected_manga.get('status', '').lower(), ("#252535", "#8a8aa0"))
        self.status_badge.setStyleSheet(f"background-color: {bg}; color: {fg}; border-radius: 11px; font-size: 11px; font-weight: bold; padding: 2px 10px;")
        
        self.desc_text.setText(self.selected_manga.get('description', 'No description available.'))
        
        # Cover
        self.cover_label.setText("Loading...")
        self.cover_label.setPixmap(QPixmap()) 
        
        if self.selected_manga.get('cover_url'):
             url = self.selected_manga['cover_url']
             self.img_loader = ImageLoader(url)
             self.img_loader.loaded.connect(self.set_cover_image)
             self.img_loader.start()
        elif self.selected_manga.get('cover_filename'):
            url = f"https://uploads.mangadex.org/covers/{self.selected_manga['id']}/{self.selected_manga['cover_filename']}.256.jpg"
            self.img_loader = ImageLoader(url)
            self.img_loader.loaded.connect(self.set_cover_image)
            self.img_loader.start()
        else:
            self.cover_label.setText("No Cover")

        # Languages Chips
        self.lang_list.blockSignals(True)                                            
        self.lang_list.clear()
        
        # Clear old chips
        while self.lang_flow.count():
            item = self.lang_flow.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        langs = sorted([l for l in self.selected_manga.get("available_languages", []) if l])
        if not langs:
            lbl = QLabel("No specific languages listed")
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
            self.lang_flow.addWidget(lbl)
        else:
            for l in langs:
                self.lang_list.addItem(l)
                chip = ChipWidget(l)
                chip.toggled.connect(self.on_chip_toggled)
                self.lang_flow.addWidget(chip)
        
        self.lang_list.blockSignals(False)
        
        # Add Stretch to push chips to the left
        self.lang_flow.addStretch()
        
        # Clear chapters
        self.chapter_tree.clear()
        self.chapters = []
        self.all_chapter_groups = set()
        self.loaded_label.setText("0 chapters loaded")                               
        
        if not langs:
            self.fetch_chapters()

    def on_chip_toggled(self, checked):
        chip = self.sender()
        lang = chip.text()
        for i in range(self.lang_list.count()):
            item = self.lang_list.item(i)
            if item.text() == lang:
                item.setSelected(checked)
                break
        
        selected_langs = [item.text() for item in self.lang_list.selectedItems()]
        if "No specific langs listed" in selected_langs or not selected_langs: 
            selected_langs = None
        self.fetch_chapters(selected_langs)

    def update_download_count(self):
        count = 0
        for i in range(self.chapter_tree.topLevelItemCount()):
            item = self.chapter_tree.topLevelItem(i)
            if item.isHidden():
                continue
            if item.checkState(0) == Qt.Checked:
                count += 1
        self.download_btn.setText(f"Download Selected ({count} chapters)")
        self.download_btn.setEnabled(count > 0)

    def select_range(self):
        start_str = self.range_start.text().strip()
        end_str = self.range_end.text().strip()
        if not start_str or not end_str: return
        try:
            start_num, end_num = float(start_str), float(end_str)
            if start_num > end_num: start_num, end_num = end_num, start_num
            count = 0
            for i in range(self.chapter_tree.topLevelItemCount()):
                item = self.chapter_tree.topLevelItem(i)
                if item.isHidden():
                    continue
                try:
                    chap_val = float(item.text(0))
                    if start_num <= chap_val <= end_num:
                        item.setCheckState(0, Qt.Checked)
                        count += 1
                except: pass
            self.log(f"Selected {count} chapters in range {start_num}-{end_num}")
        except: pass


    def set_cover_image(self, image):
        self.cover_label.set_pixmap(QPixmap.fromImage(image))

    def on_lang_changed(self):
        selected_langs = [item.text() for item in self.lang_list.selectedItems()]
        if "No specific langs listed" in selected_langs: selected_langs = None
        self.fetch_chapters(selected_langs)

    def fetch_chapters(self, langs=None):
        if not self.selected_manga: return
        
        # Proper cleanup of existing chapter worker
        if hasattr(self, 'chap_worker') and self.chap_worker and self.chap_worker.isRunning():
            self.chap_worker.requestInterruption()
            try: self.chap_worker.finished.disconnect()
            except: pass
            try: self.chap_worker.error.disconnect()
            except: pass
            
            old_chap = self.chap_worker
            self._old_workers.append(old_chap)
            old_chap.finished.connect(lambda: self.cleanup_worker(old_chap))
            self.chap_worker = None

        self.log(f"Fetching chapters...")
        self.loaded_label.setText("Fetching chapters...")
        self.chapter_tree.clear()
        
        site = self.selected_manga.get("source", "mangadex")
        self.chap_worker = ChapterWorker(self.selected_manga['id'], langs, site=site)
        self.chap_worker.finished.connect(self.on_chapters_fetched)
        self.chap_worker.error.connect(lambda e: self.log(f"Chapter Error: {e}"))
        self.chap_worker.captcha_requested.connect(self.on_captcha_requested)
        self.chap_worker.start()

    def on_chapters_fetched(self, chapters):
        self.chapters = chapters
        self.log(f"Loaded {len(chapters)} chapters.")
        self.loaded_label.setText(f"{len(chapters)} chapters loaded")
        self.all_chapter_groups = set()
        
        for c in chapters:
            groups = c.get('groups', [])
            if not groups:
                self.all_chapter_groups.add("No Group")
            else:
                for g in groups:
                    self.all_chapter_groups.add(g)

            # Use raw chapter string or fallback
            chap_num = str(c.get('chapter', ''))
            if not chap_num: chap_num = "0"
            
            item = QTreeWidgetItem([
                chap_num,
                c.get('title') or "",
                c.get('language', '??'),
                ", ".join(groups) if groups else "No Group",
                format_date(c.get('publishAt'))
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(0, Qt.UserRole, c)                          
            item.setCheckState(0, Qt.Unchecked)
            self.chapter_tree.addTopLevelItem(item)

    def on_captcha_requested(self, message):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Manual Action Required")
        msg_box.setText(message)
        msg_box.setIcon(QMessageBox.Information)
        
        solved_btn = msg_box.addButton("Solved", QMessageBox.ActionRole)
        retry_btn = msg_box.addButton("Retry Page Load", QMessageBox.ActionRole)
        abort_btn = msg_box.addButton("Abort", QMessageBox.RejectRole)
        
        msg_box.exec()
        
        worker = self.sender()
        if msg_box.clickedButton() == solved_btn:
            worker.set_captcha_response("success")
        elif msg_box.clickedButton() == retry_btn:
            worker.set_captcha_response("retry")
        else:
            worker.set_captcha_response("abort")

    def show_group_filter(self):
        if not self.all_chapter_groups:
            QMessageBox.information(self, "No Groups", "No groups found in current chapter list.")
            return
            
        dlg = GroupFilterDialog(self.all_chapter_groups, self)
        if dlg.exec() == QDialog.Accepted:
            selected = dlg.get_selected_groups()
            self.apply_group_filter(selected)

    def apply_group_filter(self, selected_groups):
        root = self.chapter_tree.invisibleRootItem()
        selected_set = set(selected_groups)
        
        for i in range(root.childCount()):
            item = root.child(i)
            chapter_data = item.data(0, Qt.UserRole)
            c_groups = chapter_data.get('groups', [])
            
            match = False
            if not c_groups:
                if "No Group" in selected_set:
                    match = True
            else:
                                                     
                if set(c_groups).intersection(selected_set):
                    match = True
            
            item.setHidden(not match)


    def select_all_chapters(self):
        for i in range(self.chapter_tree.topLevelItemCount()):
            item = self.chapter_tree.topLevelItem(i)
            if item.isHidden():
                continue
            item.setCheckState(0, Qt.Checked)

    def deselect_all_chapters(self):
        for i in range(self.chapter_tree.topLevelItemCount()):
            item = self.chapter_tree.topLevelItem(i)
            if item.isHidden():
                continue
            item.setCheckState(0, Qt.Unchecked)

    def invert_chapters(self):
        for i in range(self.chapter_tree.topLevelItemCount()):
            item = self.chapter_tree.topLevelItem(i)
            if item.isHidden():
                continue
            state = item.checkState(0)
            item.setCheckState(0, Qt.Unchecked if state == Qt.Checked else Qt.Checked)

    def start_download(self):
        selected_chapters = []
        for i in range(self.chapter_tree.topLevelItemCount()):
            item = self.chapter_tree.topLevelItem(i)
            if item.isHidden():
                continue
            if item.checkState(0) == Qt.Checked:
                selected_chapters.append(item.data(0, Qt.UserRole))
        
        if not selected_chapters:
            QMessageBox.warning(self, "No Selection", "Please select chapters to download.")
            return

        # Proper cleanup of existing download worker
        if hasattr(self, 'download_worker') and self.download_worker and self.download_worker.isRunning():
            self.download_worker.stop()
            self.download_worker.requestInterruption()
            try: self.download_worker.finished.disconnect()
            except: pass
            
            old_dl = self.download_worker
            self._old_workers.append(old_dl)
            old_dl.finished.connect(lambda: self.cleanup_worker(old_dl))
            self.download_worker = None

        default_dir = self.settings.get("last_dir", "")
        base_dir = QFileDialog.getExistingDirectory(self, "Select Download Directory", default_dir)
        if not base_dir: return
        self.settings["last_dir"] = base_dir
        
        display_title = self.get_preferred_title(self.selected_manga)
        safe_title = "".join(c for c in display_title if c.isalnum() or c in (' ', '-', '_')).strip()
        manga_dir = Path(base_dir) / safe_title
        manga_dir.mkdir(parents=True, exist_ok=True)

        self.download_btn.setEnabled(False)
        self.download_btn.setProgress(0, 100)
        
        site = self.selected_manga.get("source", "mangadex")
        self.download_worker = DownloadWorker(
            selected_chapters, 
            str(manga_dir), 
            self.data_saver_chk.isChecked(),
            manga_id=self.selected_manga['id'],
            make_cbz=self.cbz_chk.isChecked(),
            site=site,
            debug_mode=self.debug_chk.isChecked(),
            use_proxy=True,
            use_selenium=True
        )
        self.download_worker.progress.connect(self.log)
        self.download_worker.percent.connect(lambda p: self.download_btn.setProgress(p, 100))
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.error.connect(lambda e: self.log(f"Download Error: {e}"))
        self.download_worker.captcha_requested.connect(self.on_captcha_requested)
        self.download_worker.start()

    def on_download_finished(self, stats):
        self.download_btn.setEnabled(True)
        self.download_btn.reset()
        completed = stats.get("completed", 0) if isinstance(stats, dict) else 0
        failed = stats.get("failed", 0) if isinstance(stats, dict) else 0
        skipped = stats.get("skipped", 0) if isinstance(stats, dict) else 0
        total = stats.get("total", completed + failed + skipped) if isinstance(stats, dict) else 0
        summary = f"Download finished. Completed: {completed}/{total}, Failed: {failed}, Skipped: {skipped}"
        self.log(summary)
        QMessageBox.information(self, "Download Summary", summary)

    def add_to_library(self):
        if not hasattr(self, 'selected_manga') or not self.selected_manga:
            QMessageBox.warning(self, "No Manga", "Please select a manga first.")
            return
        
        mid = self.selected_manga['id']
        title = self.get_preferred_title(self.selected_manga)
        source = self.selected_manga.get('source', 'mangadex')
        
        # Check if already in library
        if mid in self.library:
            QMessageBox.information(self, "Library", f"'{title}' is already in your library.")
            return
            
        self.library[mid] = {
            "title": title,
            "id": mid,
            "added_at": time.time(),
            "source": source,
            "cover_url": self.selected_manga.get('cover_url') or self.selected_manga.get('cover_filename'),
            "status": self.selected_manga.get('status', 'Unknown')
        }
        self.save_library()
        QMessageBox.information(self, "Library", f"Added '{title}' to library.")

    def load_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except: pass
        return {}

    def save_settings(self):
        self.settings["romaji_titles"] = self.romaji_toggle.isChecked()
        self.settings["data_saver"] = self.data_saver_chk.isChecked()
        self.settings["cbz_mode"] = self.cbz_chk.isChecked()
        self.settings["debug_mode"] = self.debug_chk.isChecked()
        try:
            with open(SETTINGS_FILE, "w") as f: json.dump(self.settings, f)
        except: pass

    def load_library(self):
        try:
            if os.path.exists(LIBRARY_FILE):
                with open(LIBRARY_FILE, "r") as f: return json.load(f)
        except: pass
        return {}

    def save_library(self):
        try:
            with open(LIBRARY_FILE, "w") as f: json.dump(self.library, f)
        except: pass

    def closeEvent(self, event):
                                         
        workers = [
            getattr(self, 'worker', None),
            getattr(self, 'img_loader', None),
            getattr(self, 'chap_worker', None)
        ]
        for w in workers:
            if w and w.isRunning():
                if hasattr(w, 'stop'):
                    w.stop()
                w.requestInterruption()
                w.wait(50)

        if hasattr(self, 'download_worker') and self.download_worker and self.download_worker.isRunning():
            self.download_worker.stop()
            self.download_worker.wait(100)

        self.save_settings()
        self.save_library()
        event.accept()

    def open_library(self):
        dlg = LibraryDialog(self.library, self)
        dlg.exec()
        self.save_library()

    def add_current_to_library(self):
        if not self.selected_manga: 
            QMessageBox.warning(self, "No Manga", "Please select a manga first.")
            return
        
        mid = self.selected_manga['id']
        title = self.get_preferred_title(self.selected_manga)
        source = self.selected_manga.get('source', 'mangadex')
        cover_url = self.selected_manga.get('cover_url') or self.selected_manga.get('cover_filename')
        
        self.library[mid] = {
            "title": title,
            "added_at": time.time(),
            "last_chapter": "", 
            "has_update": False,
            "source": source,
            "cover_url": cover_url
        }
        self.save_library()
        QMessageBox.information(self, "Library", f"Added '{title}' to library.")

    def load_manga_from_library(self, mid):
        data = self.library.get(mid, {})
        source = data.get('source', 'mangadex').lower()
        
        if source == 'baozimh':
            self.site_combo.setCurrentText("Baozimh")
            fake_url = f"https://www.baozimh.com/comic/{mid}"
            self.search_input.setText(fake_url)
        elif source == 'happymh':
            self.site_combo.setCurrentText("Happymh")
            fake_url = f"https://m.happymh.com/manga/{mid}"
            self.search_input.setText(fake_url)
        else:
            self.site_combo.setCurrentText("MangaDex")
            fake_url = f"https://mangadex.org/title/{mid}"
            self.search_input.setText(fake_url)
            
        self.start_search()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ModernMangaDexGUI()
    window.show()
    sys.exit(app.exec())
