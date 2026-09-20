import sys
sys.stdout.reconfigure(encoding='utf-8')
from urllib.request import urlopen, Request
import re
import html as html_mod

url = 'https://shopee.vn/%C3%81o-thun-nam-tay-ng%E1%BA%AFn-c%E1%BB%95-tr%C3%B2n-d%C3%A1ng-slimfit-cotton-cao-c%E1%BA%A5p-m%E1%BB%81m-m%E1%BB%8Bn-tho%C3%A1ng-m%C3%A1t-i.46274415.7118335123'
req = Request(url, headers={'User-Agent': 'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)'})
resp = urlopen(req, timeout=10)
html = resp.read().decode('utf-8')

title_m = re.search(r'<meta property="og:title" content="(.*?)"', html)
img_m = re.search(r'<meta property="og:image" content="(.*?)"', html)
desc_m = re.search(r'<meta property="og:description" content="(.*?)"', html)

print('Title:', html_mod.unescape(title_m.group(1)) if title_m else 'None')
print('Image:', html_mod.unescape(img_m.group(1)) if img_m else 'None')
print('Desc length:', len(html_mod.unescape(desc_m.group(1))) if desc_m else 'None')
