import feedparser
import os
import time
import re
import requests
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from selenium.webdriver.common.action_chains import ActionChains

# --- برمجة ahmed si - النسخة v31.2 Direct Publish ---

# ====== إعدادات الموقع - غيّر هنا فقط ======
SITE_NAME = "grandmabites"  # اسم الموقع بدون .com
SITE_DOMAIN = f"{SITE_NAME}.com"
RSS_URL = f"https://{SITE_DOMAIN}/feed"
# ==========================================

POSTED_LINKS_FILE = "posted_links.txt"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def get_posted_links():
    if not os.path.exists(POSTED_LINKS_FILE): return set()
    with open(POSTED_LINKS_FILE, "r", encoding='utf-8') as f: return set(line.strip() for line in f)

def add_posted_link(link):
    with open(POSTED_LINKS_FILE, "a", encoding='utf-8') as f: f.write(link + "\n")

def get_next_post_to_publish():
    print(f"--- 1. البحث عن مقالات في: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)
    if not feed.entries: return None
    print(f"--- تم العثور على {len(feed.entries)} مقالات.")
    posted_links = get_posted_links()
    for entry in reversed(feed.entries):
        if entry.link not in posted_links:
            print(f">>> تم تحديد المقال: {entry.title}")
            return entry
    return None

def extract_image_url_from_entry(entry):
    """أول صورة من الـ RSS كاحتياطي"""
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if 'url' in media and media.get('medium') == 'image': return media['url']
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enclosure in entry.enclosures:
            if 'href' in enclosure and 'image' in enclosure.get('type', ''): return enclosure.href
    content_html = ""
    if 'content' in entry and entry.content: content_html = entry.content[0].value
    else: content_html = entry.summary
    match = re.search(r'<img[^>]+src="([^">]+)"', content_html)
    if match: return match.group(1)
    return None

def is_valid_article_image(url):
    """تصفية الصور غير المناسبة"""
    small_sizes = ['16', '32', '48', '64', '96', '128', '150', '160']
    for size in small_sizes:
        if f'width={size}' in url or f'w={size}' in url or f'-{size}x' in url or f'_{size}x' in url:
            return False
    exclude_keywords = ['avatar', 'author', 'profile', 'logo', 'icon', 'thumbnail', 'thumb', 'placeholder', 'blank', 'advertising', 'banner', 'badge', 'button', 'pixel', 'tracking', 'analytics']
    ul = url.lower()
    if any(k in ul for k in exclude_keywords): return False
    return any(ext in ul for ext in ['.jpg', '.jpeg', '.png', '.webp'])

def scrape_article_images_with_alt(article_url):
    """كشط الصور + alt من داخل المقال فقط"""
    print(f"--- 🔍 كشط صور المقال بـ Selenium من: {article_url}")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)

    images_data = []
    try:
        driver.get(article_url)
        time.sleep(3)
        wait = WebDriverWait(driver, 10)

        # منطقة المقال
        article_element = None
        selectors = ["article.article", "article", "div.entry-content", "main", "div.article-content", "div.post-content", "div.content", "div.recipe-content"]
        for sel in selectors:
            try:
                article_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                print(f"    ✓ المحتوى: {sel}")
                break
            except:
                continue
        if not article_element:
            print("    ⚠️ لم أجد article، سأستخدم body")
            article_element = driver.find_element(By.TAG_NAME, "body")

        # تمرير لتحميل الصور الكسولة
        for frac in [0.25, 0.5, 0.75, 1.0]:
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight*{frac});")
            time.sleep(1)

        imgs = article_element.find_elements(By.TAG_NAME, "img")
        print(f"    📊 صور داخل المقال: {len(imgs)}")
        for img in imgs:
            try:
                src = (img.get_attribute("src") or img.get_attribute("data-src") or img.get_attribute("data-lazy-src") or img.get_attribute("data-original") or "")
                if not src:
                    src = driver.execute_script("return arguments[0].currentSrc || arguments[0].src;", img)
                if not src: continue

                # srcset (خذ الأكبر)
                if (',' in src and ' ' in src):
                    src = src.split(',')[-1].strip().split(' ')[0]

                alt = img.get_attribute("alt") or img.get_attribute("title") or ""
                clean_url = src

                # روابط CDN -> استخرج الأصل إن أمكن
                if "/cdn-cgi/image/" in clean_url:
                    m = re.search(r'/([^/]+\.(?:jpg|jpeg|png|webp))', clean_url, re.IGNORECASE)
                    if m:
                        clean_url = f"https://{SITE_DOMAIN}/{m.group(1)}"

                # نسبي -> مطلق
                if not clean_url.startswith("http"):
                    if clean_url.startswith("//"): clean_url = "https:" + clean_url
                    elif clean_url.startswith("/"):
                        from urllib.parse import urljoin
                        clean_url = urljoin(article_url, clean_url)

                if is_valid_article_image(clean_url):
                    if clean_url not in [d['url'] for d in images_data]:
                        images_data.append({'url': clean_url, 'alt': alt})
                        print(f"    ✅ صورة: {clean_url[:80]} | alt: {alt[:40]}")
            except:
                continue
    finally:
        driver.quit()
    print(f"--- ✅ صور صالحة: {len(images_data)}")
    return images_data

def get_best_images_for_article(article_url, rss_image=None):
    data = scrape_article_images_with_alt(article_url)
    if rss_image and is_valid_article_image(rss_image) and rss_image not in [d['url'] for d in data]:
        data.append({'url': rss_image, 'alt': 'Featured recipe image'})
    if len(data) >= 2:
        return data[0], (data[2] if len(data) >= 3 else data[1])
    elif len(data) == 1:
        return data[0], data[0]
    else:
        return None, None

def create_mid_cta(original_link, recipe_title="this recipe"):
    ctas = [
        f'💡 <em>Exact measurements and timing here: <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a></em>',
        f'👉 <em>Ingredients + detailed steps for {recipe_title}: <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a></em>',
        f'📖 <em>Printable version with nutrition at <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a></em>',
        f'🍳 <em>Step-by-step photos + pro tips: <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a></em>'
    ]
    import hashlib
    i = int(hashlib.md5(original_link.encode()).hexdigest(), 16) % len(ctas)
    return f"<p>{ctas[i]}</p>"

def create_final_cta(original_link):
    return f'''
<br>
<hr>
<h3>Ready to Make This Recipe?</h3>
<p><strong>🎯 Get the complete recipe with:</strong></p>
<ul>
  <li>Exact measurements and ingredients list</li>
  <li>Step-by-step instructions with photos</li>
  <li>Prep and cooking times</li>
  <li>Nutritional information</li>
  <li>Storage and serving suggestions</li>
</ul>
<p><strong>👇 Visit <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a> for the full recipe and more delicious ideas!</strong></p>
'''

def rewrite_content_with_gemini(title, content_html, original_link, image1_alt="", image2_alt=""):
    if not GEMINI_API_KEY:
        print("!!! تحذير: لا يوجد GEMINI_API_KEY، سيتم استخدام المحتوى الأصلي")
        return None
    print("--- 💬 التواصل مع Gemini API...")
    clean = re.sub('<[^<]+?>', ' ', content_html)
    alt_info = ""
    if image1_alt: alt_info += f"\n- Image 1 description: {image1_alt}"
    if image2_alt and image2_alt != image1_alt: alt_info += f"\n- Image 2 description: {image2_alt}"
    prompt = """
You are a professional SEO copywriter for Medium.
Rewrite the recipe for engagement and SEO.

Original Title: "%s"
Original Content: "%s"
Link: "%s"%s

Requirements:
- 600-700 words, clean HTML (p, h2, h3, ul, ol, li, strong, em, br)
- Do NOT add <img> or links
- Insert placeholders exactly:
  INSERT_IMAGE_1_HERE
  INSERT_MID_CTA_HERE
  INSERT_IMAGE_2_HERE
- Provide 5 tags
- Provide captions: caption1, caption2

Return ONLY valid JSON with keys:
new_title, new_html_content, tags, caption1, caption2
""" % (title, clean[:1500], original_link, alt_info)
    api_url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7}}
    try:
        r = requests.post(api_url, headers=headers, data=json.dumps(data), timeout=180)
        r.raise_for_status()
        j = r.json()
        raw = j['candidates'][0]['content']['parts'][0]['text']
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m: raise ValueError("No JSON in Gemini response")
        res = json.loads(m.group(0))
        print("--- ✅ تم الاستلام من Gemini")
        return {
            "title": res.get("new_title", title),
            "content": res.get("new_html_content", content_html),
            "tags": res.get("tags", []),
            "caption1": res.get("caption1", ""),
            "caption2": res.get("caption2", "")
        }
    except Exception as e:
        print(f"!!! خطأ Gemini: {e}")
        return None

def prepare_html_with_images_and_ctas(content_html, image1, image2, original_link, original_title, caption1="", caption2=""):
    print("--- 🎨 تجهيز المحتوى النهائي...")
    # الصورة 1
    if image1:
        alt1 = image1.get('alt') or "Recipe preparation"
        full_alt1 = f"{alt1} | {SITE_DOMAIN}"
        img1_html = f'<img src="{image1["url"]}" alt="{full_alt1}">'
        cap1 = caption1 or (f"{image1.get('alt','').strip()} | {SITE_DOMAIN}" if image1.get('alt') else f"Step-by-step preparation | {SITE_DOMAIN}")
        img1_block = f'{img1_html}<p><em>{cap1}</em></p>'
    else:
        img1_block = ""
    # CTA وسط
    mid_cta = create_mid_cta(original_link, original_title)
    # الصورة 2
    if image2:
        alt2 = image2.get('alt') or "Final dish"
        full_alt2 = f"{alt2} | {SITE_DOMAIN}"
        img2_html = f'<img src="{image2["url"]}" alt="{full_alt2}">'
        if caption2:
            cap2 = caption2
        elif image2.get('alt') and image2['alt'] != image1.get('alt', ''):
            cap2 = f"{image2['alt']} | {SITE_DOMAIN}"
        elif image1 and image2['url'] == image1.get('url', ''):
            cap2 = f"Another view of this delicious recipe | {SITE_DOMAIN}"
        else:
            cap2 = f"The final result - absolutely delicious! | {SITE_DOMAIN}"
        img2_block = f'{img2_html}<p><em>{cap2}</em></p>'
    else:
        img2_block = ""

    html = content_html.replace("INSERT_IMAGE_1_HERE", img1_block)
    html = html.replace("INSERT_MID_CTA_HERE", mid_cta)
    html = html.replace("INSERT_IMAGE_2_HERE", img2_block)
    final_cta = create_final_cta(original_link)
    return html + final_cta

def ensure_published(wait, driver, timeout=30):
    """تحقق أن المقال نُشر فعلاً (وليس مسودة). يعيد True عند النشر."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            url = driver.current_url
            # منشور عادة يكون /p/{id} أو /@username/
            if "/p/" in url or "/@" in url:
                return True
            # تحقق من وجود عنصر يشير لصفحة منشورة (عنوان منشور)
            if driver.find_elements(By.CSS_SELECTOR, 'article'):
                # أحياناً تبقى نفس الـ URL، لكن الصفحة تتغير إلى صفحة المنشور
                meta_urls = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:url"]')
                for m in meta_urls:
                    c = m.get_attribute("content") or ""
                    if "/p/" in c or "/@" in c:
                        return True
        except:
            pass
        time.sleep(1)
    return False

def click_publish_flow(wait, driver, ai_tags):
    """نفس منطق v19 تماماً + إعادة محاولة + تحقق نشر"""
    print("--- 5. بدء عملية النشر (منطق v19)...")
    # زر فتح نافذة النشر
    publish_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')))
    publish_button.click()
    time.sleep(1)

    # الوسوم (اختياري)
    if ai_tags:
        try:
            print("--- 6. إضافة الوسوم...")
            tags_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="publishTopicsInput"]')))
            tags_input.click()
            for tag in ai_tags[:5]:
                tags_input.send_keys(tag)
                time.sleep(0.5)
                tags_input.send_keys(Keys.ENTER)
                time.sleep(0.8)
            print(f"--- تمت إضافة الوسوم: {', '.join(ai_tags[:5])}")
        except:
            print("--- تخطي الوسوم (لم أعثر على الحقل)")

    # زر التأكيد للنشر
    print("--- 7. إرسال أمر النشر النهائي...")
    publish_now_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')))
    time.sleep(1.5)
    try:
        ActionChains(driver).move_to_element(publish_now_button).pause(0.3).click(publish_now_button).perform()
    except:
        driver.execute_script("arguments[0].click();", publish_now_button)

    # تحقق النشر، وإذا فشل نعيد المحاولة مرة ثانية
    if ensure_published(wait, driver, timeout=25):
        print("    ✅ تأكد النشر")
        return True

    print("    ⚠️ لم يتم التأكد، إعادة المحاولة...")
    time.sleep(2)
    # حاول فتح نافذة النشر مرة أخرى
    try:
        publish_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')))
        publish_button.click()
        time.sleep(1)
        publish_now_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')))
        driver.execute_script("arguments[0].click();", publish_now_button)
    except:
        pass

    ok = ensure_published(wait, driver, timeout=25)
    if ok:
        print("    ✅ تم النشر بعد إعادة المحاولة")
    else:
        print("    ❌ ما زال في المسودات (سأحفظ اللقطات للتشخيص)")
    return ok

def main():
    print(f"--- بدء تشغيل الروبوت الناشر v31.2 Direct Publish لموقع {SITE_DOMAIN} ---")
    post = get_next_post_to_publish()
    if not post:
        print(">>> لا توجد مقالات جديدة.")
        return

    original_title = post.title
    original_link = post.link
    rss_image = extract_image_url_from_entry(post)
    if rss_image:
        print(f"--- 📷 صورة RSS احتياطية: {rss_image[:80]}...")

    image1_data, image2_data = get_best_images_for_article(original_link, rss_image)
    if image1_data: print(f"--- 🖼️ الصورة الأولى: {image1_data['url'][:80]}...")
    if image2_data: print(f"--- 🖼️ الصورة الثانية: {image2_data['url'][:80]}...")

    # المحتوى الأصلي
    original_content_html = post.content[0].value if ('content' in post and post.content) else post.summary

    # تحسين بالموديل
    image1_alt = image1_data['alt'] if image1_data else ""
    image2_alt = image2_data['alt'] if image2_data else ""
    rewritten = rewrite_content_with_gemini(original_title, original_content_html, original_link, image1_alt, image2_alt)

    if rewritten:
        final_title = rewritten["title"]
        ai_content = rewritten["content"]
        ai_tags = rewritten.get("tags", [])
        caption1 = rewritten.get("caption1", "")
        caption2 = rewritten.get("caption2", "")
        full_html_content = prepare_html_with_images_and_ctas(ai_content, image1_data, image2_data, original_link, original_title, caption1, caption2)
    else:
        print("--- ⚠️ استخدام المحتوى الأصلي.")
        final_title = original_title
        ai_tags = []
        img1 = f'<img src="{image1_data["url"]}" alt="{(image1_data.get("alt") or "Recipe image")+" | "+SITE_DOMAIN}">' if image1_data else ""
        img2 = f'<br><img src="{image2_data["url"]}" alt="{(image2_data.get("alt") or "Recipe detail")+" | "+SITE_DOMAIN}">' if image2_data and (not image1_data or image2_data["url"] != image1_data.get("url","")) else ""
        mid_cta = f'<p><em>👉 See the full recipe at <a href="{original_link}" target="_blank" rel="noopener">{SITE_DOMAIN}</a></em></p>'
        final_cta = create_final_cta(original_link)
        full_html_content = img1 + mid_cta + original_content_html + img2 + final_cta

    # --- النشر على Medium (نفس منطق v19) ---
    sid_cookie = os.environ.get("MEDIUM_SID_COOKIE")
    uid_cookie = os.environ.get("MEDIUM_UID_COOKIE")
    if not sid_cookie or not uid_cookie:
        print("!!! خطأ: لم يتم العثور على الكوكيز.")
        return

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32", webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)

    try:
        print("--- 2. إعداد الجلسة...")
        driver.get("https://medium.com/")
        driver.add_cookie({"name": "sid", "value": sid_cookie, "domain": ".medium.com"})
        driver.add_cookie({"name": "uid", "value": uid_cookie, "domain": ".medium.com"})
        driver.get("https://medium.com/new-story")
        wait = WebDriverWait(driver, 35)

        print("--- 3. كتابة العنوان...")
        title_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'h3[data-testid="editorTitleParagraph"]')))
        title_field.click()
        title_field.send_keys(final_title)

        print("--- 4. إدراج المحتوى...")
        story_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'p[data-testid="editorParagraphText"]')))
        story_field.click()
        js_script = """
        const html = arguments[0];
        const blob = new Blob([html], { type: 'text/html' });
        const item = new ClipboardItem({ 'text/html': blob });
        navigator.clipboard.write([item]);
        """
        driver.execute_script(js_script, full_html_content)
        story_field.send_keys(Keys.CONTROL, 'v')
        time.sleep(6)  # مهلة لرفع الصور

        # عملية النشر (v19) + تحقق
        ok = click_publish_flow(wait, driver, ai_tags)
        if not ok:
            # حفظ للتشخيص
            driver.save_screenshot("error_screenshot.png")
            with open("error_page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            raise RuntimeError("لم أستطع التأكد من النشر (قد تكون مسودة)")

        add_posted_link(post.link)
        print(f">>> 🎉🎉🎉 تم نشر المقال بنجاح على {SITE_DOMAIN}! 🎉🎉🎉")

    except Exception as e:
        print(f"!!! حدث خطأ: {e}")
        try:
            driver.save_screenshot("error_screenshot.png")
            with open("error_page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        except:
            pass
        raise e
    finally:
        driver.quit()
        print("--- تم إغلاق الروبوت ---")

if __name__ == "__main__":
    main()
