import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
import os
import time
import logging
import hashlib
import re
from typing import List, Dict, Generator, Optional, Any
from dataclasses import dataclass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class DownloadEvent:
    type: str  # 'start', 'progress', 'complete', 'error', 'message'
    message: str
    total: int = 0
    current: int = 0
    filepath: str = ""
    data: Any = None

def test_url_works(url, timeout=3):
    """HEAD request + multiple fallbacks"""
    try:
        import requests
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

def baozimh_watermark_bypass(img_url):
    return baozimh_universal_watermark_bypass(img_url)

class BaozimhClient:
    def download_multiple_chapters_generator(self, chapters: List[Dict[str, str]], comic_title: str, base_output_dir: str = "downloads") -> Generator[DownloadEvent, None, None]:
        """
        Download multiple chapters, ensuring each chapter's images go into its own folder.
        Yields DownloadEvent with chapter context in the message.
        """
        safe_comic_title = "".join([c for c in comic_title if c.isalnum() or c in (' ', '-', '_')]).strip()
        for chap in chapters:
            chap_title = chap.get('title', 'Unknown Chapter')
            safe_chap_title = "".join([c for c in chap_title if c.isalnum() or c in (' ', '-', '_')]).strip()
            out_dir = os.path.join(base_output_dir, safe_comic_title, safe_chap_title)
            yield DownloadEvent(type='message', message=f"Starting download for chapter: {chap_title}")
            for event in self.download_chapter_generator(chap['url'], out_dir):
                event.message = f"[{chap_title}] {event.message}"
                yield event
            yield DownloadEvent(type='message', message=f"Finished download for chapter: {chap_title}")

    BASE_URL = "https://www.baozimh.com"
    CDN_DOMAINS = [
        "https://s1.bzcdn.net",
        "https://s2.bzcdn.net",
        "https://tem2.baozimh.com",
        "https://tem3.baozimh.com"
    ]
    # Known CDN patterns
    CDN_TEMPLATES = [
        "https://s1.bzcdn.net/scomic/{comic_id}/0/{chapter_id}/{slot}.jpg",
        "https://s2.bzcdn.net/scomic/{comic_id}/0/{chapter_id}/{slot}.jpg",
        "https://tem2.baozimh.com/scomic/{comic_id}/0/{chapter_id}/{slot}.jpg",
        "https://tem3.baozimh.com/scomic/{comic_id}/0/{chapter_id}/{slot}.jpg"
    ]
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.baozimh.com",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def search_comics(self, query: str) -> List[Dict[str, str]]:
        """Search for comics by keyword."""
        search_url = f"{self.BASE_URL}/search?q={query}"
        try:
            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            results = []
            # Updated selector based on typical structure
            # We want the card container to extract both link and image
            cards = soup.select('div.comics-card')
                
            for card in cards:
                # Poster link
                link = card.select_one('a.comics-card__poster')
                if not link: continue
                
                title = link.get('title') or link.get_text(strip=True)
                href = link.get('href')
                
                # Cover image
                img = link.find('amp-img') or link.find('img')
                cover_url = ""
                if img:
                    cover_url = img.get('src') or img.get('data-src') or ""
                
                if href:
                    results.append({
                        'title': title,
                        'url': urljoin(self.BASE_URL, href),
                        'cover_url': cover_url
                    })
            
            # Deduplicate
            unique_results = []
            seen_urls = set()
            for r in results:
                if r['url'] not in seen_urls:
                    seen_urls.add(r['url'])
                    unique_results.append(r)
                    
            return unique_results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_chapter_list(self, comic_url: str) -> List[Dict[str, str]]:
        """Get list of chapters for a comic."""
        try:
            response = self.session.get(comic_url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            chapters = []
            
            # Strategy: Find all divs with class 'comics-chapters'
            # This covers both "Newest" and "Directory" sections
            divs = soup.find_all('div', class_='comics-chapters')
            
            if not divs:
                 # Broad fallback
                 links = soup.find_all('a', href=True)
                 for link in links:
                     href = link.get('href')
                     if not href: continue
                     
                     # Filter out external links (ads)
                     if 'baozimh.com' not in href and href.startswith('http'):
                         continue
                     
                     if '/chapter/' in href or 'comic/chapter' in href or 'page_direct' in href:
                         text = link.get_text(strip=True)
                         full_url = urljoin(self.BASE_URL, href)
                         chapters.append({'title': text, 'url': full_url, 'slot': -1})
            else:
                for d in divs:
                    link = d.find('a')
                    if not link: continue
                    
                    href = link.get('href')
                    if not href: continue
                    
                    text = link.get_text(strip=True)
                    full_url = urljoin(self.BASE_URL, href)
                    
                    # Try to extract chapter slot for sorting
                    slot = -1
                    try:
                        parsed = urlparse(full_url)
                        qs = parse_qs(parsed.query)
                        if 'chapter_slot' in qs:
                            slot = int(qs['chapter_slot'][0])
                        else:
                            # Try regex from URL path: .../0_{slot}.html
                            match = re.search(r'0_(\d+)\.html', full_url)
                            if match:
                                slot = int(match.group(1))
                            else:
                                # Try data-index from parent div
                                idx = d.get('data-index')
                                if idx is not None:
                                    slot = int(idx)
                    except:
                        pass
                        
                    chapters.append({
                        'title': text, 
                        'url': full_url,
                        'slot': slot
                    })

            # Deduplicate based on URL, keeping the one with valid slot if possible
            unique_chapters = {}
            for c in chapters:
                if c['url'] not in unique_chapters:
                    unique_chapters[c['url']] = c
                else:
                    # Update if we found a better slot info
                    if c['slot'] != -1 and unique_chapters[c['url']]['slot'] == -1:
                        unique_chapters[c['url']] = c
            
            final_list = list(unique_chapters.values())
            
            # Sort by slot if available
            # Filter out -1 slots for sorting purposes, or put them at end
            has_slots = any(c['slot'] != -1 for c in final_list)
            if has_slots:
                final_list.sort(key=lambda x: x['slot'] if x['slot'] != -1 else 999999)
            
            return final_list
        except Exception as e:
            logger.error(f"Failed to get chapter list: {e}")
            return []

    def get_chapter_images(self, chapter_url: str) -> List[str]:
        """Extract image URLs from a chapter page, following multi-page links."""
        all_images = []
        current_page_url = chapter_url
        visited_pages = set()
        
        try:
            while current_page_url and current_page_url not in visited_pages:
                visited_pages.add(current_page_url)
                logger.info(f"Fetching images from page: {current_page_url}")
                
                response = self.session.get(current_page_url, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract images from current page
                page_images = []
                # Strategy 1: Look for specific class
                img_tags = soup.find_all('img', class_='comic-contain_ui-Image_img')
                if img_tags:
                    for img in img_tags:
                        src = img.get('data-src') or img.get('src')
                        if src: page_images.append(src)
                else:
                    # Strategy 2: If no images found, look for any image with known CDN patterns
                    all_imgs = soup.find_all('img')
                    for img in all_imgs:
                        src = img.get('data-src') or img.get('src')
                        if src and ('/scomic/' in src or 'bzcdn' in src):
                            page_images.append(src)
                
                # Apply watermark bypass to each image found
                for img_url in page_images:
                    if img_url not in all_images:
                        all_images.append(img_url)
                
                # Check for next page link: <div class="next_chapter"><a href="...">下一頁</a></div>
                next_link = soup.select_one('div.next_chapter a')
                if next_link and "下一頁" in next_link.get_text():
                    href = next_link.get('href')
                    if href:
                        current_page_url = urljoin(current_page_url, href)
                    else:
                        break
                else:
                    break
                    
            logger.info(f"✅ Complete chapter: {len(all_images)} images extracted across {len(visited_pages)} pages.")
            return all_images
            
        except Exception as e:
            logger.error(f"Failed to get chapter images from {chapter_url}: {e}")
            return all_images

    def get_chapter_id_from_url(self, chapter_url: str) -> Optional[str]:
        """Extract chapter ID from the chapter page URL or content."""
        try:
            # Fetch page content and look for image URLs with ID
            response = self.session.get(chapter_url, timeout=10)
            if response.status_code != 200:
                return None
            
            content = response.text
            # Regex to capture chapter_id from image URLs
            # Pattern: /scomic/{comic_id}/0/{chapter_id}/{num}.jpg
            matches = re.findall(r'/scomic/[^/]+/0/([^/]+)/', content)
            if matches:
                # Return the most common match
                return max(set(matches), key=matches.count)
                
            return None
        except Exception as e:
            logger.error(f"Error extracting chapter ID: {e}")
            return None

    def download_image(self, url: str, filepath: str) -> bool:
        """Download a single image."""
        try:
            # Apply universal watermark bypass (Community Upgrade)
            # Since we can't easily import from md_gui.py, we should have it here or use the local one
            # The local baozimh_watermark_bypass will be updated to match the universal one
            url = baozimh_watermark_bypass(url)
            
            response = self.session.get(url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False

    def download_chapter_by_id_generator(self, comic_id: str, chapter_id: str, output_dir: str, start_num: int = 1, end_num: int = 100) -> Generator[DownloadEvent, None, None]:
        """
        Generator for downloading chapter images by manually constructing the URL with a known chapter ID.
        """
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                yield DownloadEvent(type='error', message=f"Failed to create directory: {e}")
                return
            
        yield DownloadEvent(type='start', message=f"Brute-forcing images for chapter {chapter_id}", total=end_num) # Approximate total
        
        base_cdn = "https://s2.baozicdn.com/w640/scomic"
        success_count = 0
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 20
        
        for i in range(start_num, end_num + 1):
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                yield DownloadEvent(type='message', message=f"Stopping after {MAX_CONSECUTIVE_FAILURES} consecutive failures.")
                break
                
            extensions = [".jpg", ".webp", ".png", ".jpeg"]
            found = False
            
            for ext in extensions:
                url = f"{base_cdn}/{comic_id}/0/{chapter_id}/{i}{ext}"
                filename = os.path.join(output_dir, f"{i:03d}{ext}")
                
                if os.path.exists(filename):
                    found = True
                    consecutive_failures = 0
                    yield DownloadEvent(type='skip', message=f"Skipping existing {i}", current=i)
                    break
                
                if self.download_image(url, filename):
                    success_count += 1
                    consecutive_failures = 0
                    found = True
                    yield DownloadEvent(type='progress', message=f"Downloaded image {i}", current=i, filepath=filename)
                    break
            
            if not found:
                consecutive_failures += 1
                
        yield DownloadEvent(
            type='complete', 
            message=f"Brute-force download complete. {success_count} images saved.", 
            current=success_count, 
            total=success_count
        )

    def get_chapter_images_from_app_endpoint(self, comic_id: str, slot: int) -> List[str]:
        """
        Fetch chapter images using the app endpoint which returns the full HTML with real image URLs.
        This bypasses the placeholder images seen on the main website for locked chapters.
        """
        # Construct the app endpoint URL
        # Pattern: https://appgb3.baozimh.com/baozimhapp/comic/chapter/{comic_id}/0_{slot}.html
        # Note: The '0' likely refers to the section_slot, which is usually 0 for main story.
        url = f"https://appgb3.baozimh.com/baozimhapp/comic/chapter/{comic_id}/0_{slot}.html"
        
        headers = {
            "User-Agent": "baozimh_android/1.0.31/gb/adset",
            "app-id": "cn.sts.xiaoyun.ordermeals",
            "app-version": "1.0.31",
            "device-code": "8ff8b26a65d018060e5936206fc2a3e8",
            "device-id": "TQ3A.230901.001",
            "Host": "appgb3.baozimh.com",
            "referer": "https://appgb.baozimh.com/",
            "Accept-Encoding": "gzip"
        }
        
        logger.info(f"Attempting to fetch images from app endpoint: {url}")
        try:
            response = self.session.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning(f"App endpoint returned status {response.status_code}")
                return []
                
            soup = BeautifulSoup(response.text, 'html.parser')
            images = []
            
            # Look for images with data-src or src containing /scomic/
            for img in soup.find_all('img'):
                src = img.get('data-src') or img.get('src')
                if src and '/scomic/' in src:
                    # Ensure URL is absolute
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin("https://s2.baozicdn.com", src) # Default to a CDN if relative
                        
                    images.append(src)
            
            # Deduplicate while preserving order
            seen = set()
            unique_images = []
            for img in images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            
            return unique_images
            
        except Exception as e:
            logger.error(f"Failed to fetch from app endpoint: {e}")
            return []

    def download_chapter_generator(self, chapter_url: str, output_dir: str) -> Generator[DownloadEvent, None, None]:
        """Yields progress events while downloading a chapter."""
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except OSError as e:
                yield DownloadEvent(type='error', message=f"Failed to create directory: {e}")
                return

        # 1. Try standard web scraping first
        img_urls = self.get_chapter_images(chapter_url)
        
        # Check for placeholders (small number of images or specific known placeholder patterns)
        # User logic: If <= 6 images, they are likely placeholders. If > 6, they are real content.
        is_placeholder = False
        if len(img_urls) <= 6:
             is_placeholder = True
        
        # If standard scraping failed or returned placeholders, try App Endpoint
        if not img_urls or is_placeholder:
             yield DownloadEvent(type='message', message=f"Standard scraping returned {len(img_urls)} images (likely placeholders). Attempting App Endpoint...")
             
             try:
                 # Extract comic_id and slot from chapter_url
                 comic_id = None
                 slot = None
                 
                 # Pattern 1: URL with query params (page_direct)
                 parsed = urlparse(chapter_url)
                 qs = parse_qs(parsed.query)
                 if 'comic_id' in qs and 'chapter_slot' in qs:
                     comic_id = qs['comic_id'][0]
                     slot = int(qs['chapter_slot'][0])
                 
                 # Pattern 2: Standard URL /comic/chapter/comic_id/0_slot.html
                 if not comic_id:
                     match = re.search(r'/comic/chapter/([^/]+)/0_(\d+)', chapter_url)
                     if match:
                         comic_id = match.group(1)
                         slot = int(match.group(2))
                 
                 # Pattern 3: Try to infer from path
                 if not comic_id and 'comic/' in chapter_url:
                     parts = chapter_url.split('/')
                     if 'chapter' in parts:
                        idx = parts.index('chapter')
                        if idx + 1 < len(parts):
                            comic_id = parts[idx+1]
                        if idx + 2 < len(parts):
                            slot_part = parts[idx+2]
                            if '_' in slot_part:
                                try:
                                    slot = int(slot_part.split('_')[1].split('.')[0])
                                except: pass

                 # If we have comic_id and slot, try the app endpoint
                 if comic_id and slot is not None:
                     app_images = self.get_chapter_images_from_app_endpoint(comic_id, slot)
                     # If app endpoint returned images, use them.
                     # We trust app endpoint more if we suspected placeholders.
                     if app_images:
                         img_urls = app_images
                         yield DownloadEvent(type='message', message=f"Successfully fetched {len(img_urls)} images from App Endpoint!")
                         is_placeholder = False
                     else:
                         yield DownloadEvent(type='message', message="App Endpoint failed or returned no images.")
             except Exception as e:
                 logger.error(f"Error parsing URL for app endpoint: {e}")

        # Fallback logic (Brute-force ID)
        if not img_urls or (is_placeholder and len(img_urls) <= 6):
             yield DownloadEvent(type='message', message=f"Still failing. Attempting brute-force ID fallback...")

             chapter_id = self.get_chapter_id_from_url(chapter_url)
             if chapter_id:
                # Try to extract comic_id from URL
                # Handle standard URLs and page_direct URLs
                comic_id = None
                
                # Try standard URL pattern
                match = re.search(r'/comic/chapter/([^/]+)/', chapter_url)
                if match:
                    comic_id = match.group(1)
                
                # Try query param if not found
                if not comic_id:
                    parsed = urlparse(chapter_url)
                    qs = parse_qs(parsed.query)
                    if 'comic_id' in qs:
                        comic_id = qs['comic_id'][0]
                        
                if comic_id:
                    # Delegate to brute-force generator
                    for event in self.download_chapter_by_id_generator(comic_id, chapter_id, output_dir):
                        yield event
                    return
             else:
                 yield DownloadEvent(type='error', message="Could not extract chapter ID for fallback.")

        if not img_urls:
            yield DownloadEvent(type='error', message=f"No images found for chapter: {chapter_url}")
            return

        yield DownloadEvent(type='start', message=f"Found {len(img_urls)} images", total=len(img_urls))
        
        # Download images
        success_count = 0
        for i, img_url in enumerate(img_urls):
            filename = os.path.join(output_dir, f"{i+1:03d}.jpg")
            
            if os.path.exists(filename):
                yield DownloadEvent(type='skip', message=f"Skipping existing {i+1}", current=i+1)
                continue
            
            if self.download_image(img_url, filename):
                success_count += 1
                yield DownloadEvent(type='progress', message=f"Downloaded image {i+1}", current=i+1, filepath=filename)
            else:
                yield DownloadEvent(type='error', message=f"Failed to download image {i+1}")
        
        yield DownloadEvent(type='complete', message=f"Download complete. {success_count}/{len(img_urls)} images saved.", current=success_count, total=len(img_urls))

if __name__ == "__main__":
    # CLI usage example
    client = BaozimhClient()
    query = input("Enter comic name to search: ")
    results = client.search_comics(query)
    
    if not results:
        print("No results found.")
    else:
        for i, res in enumerate(results):
            print(f"{i+1}. {res['title']} ({res['url']})")
        
        sel = int(input("Select comic (number): ")) - 1
        if 0 <= sel < len(results):
            comic = results[sel]
            print(f"Selected: {comic['title']}")
            
            # Fetch chapters
            print("Fetching chapters...")
            chapters = client.get_chapter_list(comic['url'])
            
            if not chapters:
                print("No chapters found.")
            else:
                print(f"Found {len(chapters)} chapters.")
                # Show first 10 and last 10 if many
                if len(chapters) > 20:
                    for i in range(10):
                        print(f"{i+1}. {chapters[i]['title']}")
                    print("...")
                    for i in range(len(chapters)-10, len(chapters)):
                        print(f"{i+1}. {chapters[i]['title']}")
                else:
                    for i, chap in enumerate(chapters):
                        print(f"{i+1}. {chap['title']}")
                
                print("\nOptions:")
                print("- Enter a number to download a specific chapter (e.g. 5)")
                print("- Enter a range to download multiple chapters (e.g. 1-10)")
                print("- Enter 'custom' to manually input a chapter slot (generates page_direct URL)")
                print("- Enter 'id' to manually input a Chapter ID (e.g. 96-9w0i)")
                print("- Enter 'all' to download ALL chapters (batch mode)")

                chap_sel = input("Select option: ").strip()

                target_chap = None
                manual_id_mode = False

                # Detect range input like "1-10"
                range_match = re.fullmatch(r'(\d+)-(\d+)', chap_sel)
                if range_match:
                    range_start = int(range_match.group(1))
                    range_end = int(range_match.group(2))
                    if range_start < 1 or range_end > len(chapters) or range_start > range_end:
                        print(f"Invalid range. Please enter a range between 1 and {len(chapters)}.")
                    else:
                        selected_chapters = chapters[range_start - 1:range_end]
                        print(f"Batch downloading chapters {range_start} to {range_end} ({len(selected_chapters)} chapters)...")
                        for event in client.download_multiple_chapters_generator(selected_chapters, comic['title']):
                            print(event.message)
                        print(f"\nBatch download finished! Check downloads/{comic['title']}/")
                    exit(0)
                elif chap_sel.lower() == 'custom':
                    slot_input = input("Enter chapter slot number (e.g. 0 for preview, 1 for ch.1): ")
                    try:
                        slot = int(slot_input)
                        # Extract comic_id from URL
                        path = urlparse(comic['url']).path
                        comic_id = path.split('/')[-1]

                        custom_url = f"{client.BASE_URL}/user/page_direct?comic_id={comic_id}&section_slot=0&chapter_slot={slot}"
                        target_chap = {
                            'title': f"Chapter Slot {slot}",
                            'url': custom_url
                        }
                    except ValueError:
                        print("Invalid slot number.")
                elif chap_sel.lower() == 'id':
                    chapter_id = input("Enter Chapter ID (e.g. 96-9w0i): ")
                    if chapter_id:
                         # Extract comic_id from URL
                        path = urlparse(comic['url']).path
                        comic_id = path.split('/')[-1]

                        target_chap = {
                            'title': f"Chapter ID {chapter_id}",
                            'url': f"manual:{comic_id}:{chapter_id}"
                        }
                        manual_id_mode = True
                elif chap_sel.lower() == 'all':
                    print("Batch downloading all chapters...")
                    # Use the new batch download generator
                    for event in client.download_multiple_chapters_generator(chapters, comic['title']):
                        print(event.message)
                    print(f"\nBatch download finished! Check downloads/{comic['title']}")
                    exit(0)
                else:
                    try:
                        idx = int(chap_sel) - 1
                        if 0 <= idx < len(chapters):
                            target_chap = chapters[idx]
                        else:
                            print("Invalid chapter selection.")
                    except ValueError:
                        print("Invalid input.")

                if target_chap:
                    safe_title = "".join([c for c in comic['title'] if c.isalnum() or c in (' ', '-', '_')]).strip()
                    safe_chap = "".join([c for c in target_chap['title'] if c.isalnum() or c in (' ', '-', '_')]).strip()
                    out_dir = os.path.join("downloads", safe_title, safe_chap)

                    print(f"Downloading {target_chap['title']} to {out_dir}...")

                    if manual_id_mode:
                        _, cid, chid = target_chap['url'].split(':')
                        print("Starting brute-force download via CDN/API...")
                        for event in client.download_chapter_by_id_generator(cid, chid, out_dir):
                            print(event.message)
                    else:
                        for event in client.download_chapter_generator(target_chap['url'], out_dir):
                            print(event.message)

                    print(f"\nDownload finished! Check {out_dir}")