import re
import html as html_mod
import os
from urllib.parse import urlparse
from curl_cffi import requests

FACEBOOK_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"

RE_OG_TITLE = re.compile(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']*)["\']', re.IGNORECASE)
RE_OG_TITLE_ALT = re.compile(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:title["\']', re.IGNORECASE)

RE_OG_DESC = re.compile(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\']*)["\']', re.IGNORECASE)
RE_OG_DESC_ALT = re.compile(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:description["\']', re.IGNORECASE)

RE_OG_IMAGE = re.compile(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']*)["\']', re.IGNORECASE)
RE_OG_IMAGE_ALT = re.compile(r'<meta[^>]*content=["\']([^"\']*)["\'][^>]*property=["\']og:image["\']', re.IGNORECASE)

RE_URL_DASH_I = re.compile(r'-i\.(\d+)\.(\d+)')
RE_URL_PRODUCT = re.compile(r'product/(\d+)/(\d+)')

def resolve_url(url):
    m = RE_URL_DASH_I.search(url)
    if m:
        shop_id, item_id = m.group(1), m.group(2)
        domain = urlparse(url).netloc or "shopee.vn"
        return f"https://{domain}/product/{shop_id}/{item_id}"
    m = RE_URL_PRODUCT.search(url)
    if m:
        shop_id, item_id = m.group(1), m.group(2)
        domain = urlparse(url).netloc or "shopee.vn"
        return f"https://{domain}/product/{shop_id}/{item_id}"
    return url

def fetch_shopee_product(url):
    """
    Fetches a Shopee URL using curl_cffi with chrome124 TLS impersonation.
    """
    url = resolve_url(url)
    
    try:
        resp = requests.get(
            url, 
            impersonate="chrome124", 
            headers={"User-Agent": FACEBOOK_UA}, 
            timeout=15,
            allow_redirects=True
        )
        html = resp.text
    except Exception as e:
        print(f"Lỗi khi cào link: {e}")
        return None
        
    info = {"title": "", "description": "", "image_url": ""}
    
    # 1. Extract Title
    m_title = RE_OG_TITLE.search(html) or RE_OG_TITLE_ALT.search(html)
    if m_title:
        title = html_mod.unescape(m_title.group(1))
        for sep in [" | Shopee", " - Shopee"]:
            idx = title.find(sep)
            if idx > 0:
                title = title[:idx]
                break
        info["title"] = title.strip()
        
    # Check if blocked by generic fallback
    if "Mua và Bán Trên Ứng Dụng" in info["title"]:
        print("Bị chặn bởi anti-bot (Shopee trả về trang xác minh).")
        return None
        
    # 2. Extract Description
    m_desc = RE_OG_DESC.search(html) or RE_OG_DESC_ALT.search(html)
    if m_desc:
        info["description"] = html_mod.unescape(m_desc.group(1)).strip()
        
    # 3. Extract Image
    m_img = RE_OG_IMAGE.search(html) or RE_OG_IMAGE_ALT.search(html)
    if m_img:
        img_url = html_mod.unescape(m_img.group(1)).strip()
        if "@resize" in img_url:
            img_url = img_url.split("@resize")[0]
        info["image_url"] = img_url
        
    return info

def download_image(url, save_dir):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    if not filename:
        filename = "image.jpg"
    elif "." not in filename:
        filename += ".jpg"
        
    save_path = os.path.join(save_dir, filename)
    
    try:
        resp = requests.get(url, impersonate="chrome124", headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        with open(save_path, "wb") as f:
            f.write(resp.content)
        return save_path
    except Exception as e:
        print(f"Lỗi tải ảnh {url}: {e}")
        return None
