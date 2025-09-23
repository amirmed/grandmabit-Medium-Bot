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

# --- برمجة ahmed si - النسخة v30.2 (ينشر مباشرة، لا يبقى مسودة) ---

# ====== إعدادات الموقع - غيّر هنا فقط ======
SITE_NAME = "grandmabites"  # اسم الموقع بدون .com
SITE_DOMAIN = f"{SITE_NAME}.com"
RSS_URL = f"https://{SITE_DOMAIN}/feed"
# ==========================================

# مسارات الصور المحتملة (أضف مسار موقعك إن كان مختلفاً)
IMAGE_PATHS = [
    "/assets/images/",          # grandmabites
    "/wp-content/uploads/",     # WordPress
    "/images/",
    "/media/",
    "/static/images/",
    "/content/images/",
    f"/{SITE_NAME}",
    "/recipes/images/",
]

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
    """استخراج أول صورة من RSS feed"""
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if 'url' in media and media.get('medium') == 'image': return media['url']
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enclosure in entry.enclosures:
            if 'href' in enclosure and 'image' in enclosure.get('type', ''): return enclosure.href
    content_html = entry.content[0].value if ('content' in entry and entry.content) else entry.summary
    match = re.search(r'<img[^>]+src="([^">]+)"', content_html)
    if match: return match.group(1)
    return None

def is_valid_article_image(url):
    """التحقق من أن الصورة صالحة للمقال"""
    small_sizes = ['16', '32', '48', '64', '96', '128', '150', '160']
    for size in small_sizes:
        if (f'width={size}' in url) or (f'w={size}' in url) or (f'-{size}x' in url) or (f'_{size}x' in url):
            return False
    exclude_keywords = [
        'avatar','author','profile','logo','icon',
        'thumbnail','thumb','placeholder','blank',
        'advertising','banner','badge','button',
        'pixel','tracking','analytics','.gif'
    ]
    url_lower = url.lower()
    if any(k in url_lower for k in exclude_keywords): return False
    return any(ext in url_lower for ext in ['.jpg','.jpeg','.png','.webp'])

def scrape_article_images_with_alt(article_url):
    """كشط الصور مع نصوص alt من داخل المقال"""
    print(f"--- 🔍 كشط صور المقال بـ Selenium من: {article_url}")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # يعمل جيداً مع Clipboard في Actions
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US","en"], vendor="Google Inc.", platform="Win32",
            webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)

    images_data = []
    try:
        print("    ⏳ تحميل الصفحة...")
        driver.get(article_url)
        time.sleep(3)
        wait = WebDriverWait(driver, 10)

        # إيجاد منطقة المقال
        article_element = None
        selectors = [
            "article.article","article","div.article-content","div.entry-content",
            "div.post-content","div.content","main","div.recipe-content"
        ]
        for selector in selectors:
            try:
                article_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                print(f"    ✓ تم العثور على المحتوى في: {selector}")
                break
            except:
                continue
        if not article_element:
            print("    ⚠️ لم أجد منطقة المحتوى، سأبحث في الصفحة كاملة")
            article_element = driver.find_element(By.TAG_NAME, "body")

        # تمرير لتحميل الصور الكسولة
        for frac in [0.25, 0.5, 0.75, 1.0]:
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight*{frac});")
            time.sleep(1)

        # صور داخل المقال فقط
        img_elements = article_element.find_elements(By.TAG_NAME, "img")
        print(f"    📊 عدد الصور في المقال: {len(img_elements)}")

        for img in img_elements:
            try:
                src = None
                for attr in ['src','data-src','data-lazy-src','data-original','data-srcset']:
                    src = img.get_attribute(attr)
                    if src: break
                if not src:
                    src = driver.execute_script("return arguments[0].currentSrc || arguments[0].src;", img)
                if not src: continue

                # srcset -> خذ الأكبر
                if (',' in src and ' ' in src):
                    src = src.split(',')[-1].strip().split(' ')[0]

                alt_text = img.get_attribute("alt") or img.get_attribute("title") or ""
                width = img.get_attribute("width") or driver.execute_script("return arguments[0].naturalWidth;", img)
                try:
                    if width and int(width) < 200:  # تجنب الصغيرة جداً
                        continue
                except: pass

                clean_url = src
                if "/cdn-cgi/image/" in clean_url:
                    m = re.search(r'/([^/]+\.(jpg|jpeg|png|webp))', clean_url, re.IGNORECASE)
                    if m:
                        clean_url = f"https://{SITE_DOMAIN}/{m.group(1)}"

                if not clean_url.startswith("http"):
                    if clean_url.startswith("//"):
                        clean_url = "https:" + clean_url
                    elif clean_url.startswith("/"):
                        from urllib.parse import urljoin
                        clean_url = urljoin(article_url, clean_url)

                if is_valid_article_image(clean_url):
                    if clean_url not in [d['url'] for d in images_data]:
                        images_data.append({'url': clean_url, 'alt': alt_text})
                        print(f"    ✅ صورة: {clean_url[:80]} | Alt: {alt_text[:40]}")
            except:
                continue

        print(f"--- ✅ تم العثور على {len(images_data)} صورة صالحة من المقال")
    finally:
        driver.quit()
    return images_data

def get_best_images_for_article(article_url, rss_image=None):
    scraped = scrape_article_images_with_alt(article_url)
    all_imgs = list(scraped)
    if rss_image and is_valid_article_image(rss_image):
        if rss_image not in [d['url'] for d in all_imgs]:
            all_imgs.append({'url': rss_image, 'alt': 'Featured recipe image'})
    if len(all_imgs) >= 2:
        return all_imgs[0], (all_imgs[2] if len(all_imgs) >= 3 else all_imgs[1])
    elif len(all_imgs) == 1:
        return all_imgs[0], all_imgs[0]
    else:
        return None, None

def create_mid_cta(original_link, recipe_title="this recipe"):
    ctas = [
        f'💡 <em>Want to see the exact measurements and timing? Check out <a href="{original_link}" rel="noopener" target="_blank">the full recipe on {SITE_DOMAIN}</a></em>',
        f'👉 <em>Get all the ingredients and detailed steps for {recipe_title} on <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>',
        f'📖 <em>Find the printable version with nutrition facts at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>',
        f'🍳 <em>See step-by-step photos and pro tips on <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>'
    ]
    import hashlib
    i = int(hashlib.md5(original_link.encode()).hexdigest(), 16) % len(ctas)
    return f'<p>{ctas[i]}</p>'

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
    <p><strong>👇 Visit <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a> for the full recipe and more delicious ideas!</strong></p>
    '''

def rewrite_content_with_gemini(title, content_html, original_link, image1_alt="", image2_alt=""):
    if not GEMINI_API_KEY:
        print("!!! تحذير: لم يتم العثور على مفتاح GEMINI_API_KEY.")
        return None
    print("--- 💬 التواصل مع Gemini API لإنشاء مقال احترافي...")
    clean_content = re.sub('<[^<]+?>', ' ', content_html)
    alt_info = ""
    if image1_alt: alt_info += f"\n- Image 1 description: {image1_alt}"
    if image2_alt and image2_alt != image1_alt: alt_info += f"\n- Image 2 description: {image2_alt}"
    prompt = """
    You are a professional SEO copywriter for Medium.
    Your task is to rewrite a recipe article for maximum engagement and SEO.

    **Original Data:**
    - Original Title: "%s"
    - Original Content: "%s"
    - Link to full recipe: "%s"%s

    **Requirements:**
    1. **New Title:** Create an engaging, SEO-optimized title (60-70 characters)
    2. **Article Body:** Write 600-700 words in clean HTML format
       - Start with a compelling introduction
       - Include practical tips and insights
       - Use headers (h2, h3) for structure
       - Add numbered or bulleted lists where appropriate
       - **IMPORTANT**: Use ONLY simple HTML tags (p, h2, h3, ul, ol, li, strong, em, br)
       - **DO NOT** use img, figure, or complex tags
       - Insert these EXACT placeholders AS WRITTEN:
         * INSERT_IMAGE_1_HERE (after the introduction paragraph)
         * INSERT_MID_CTA_HERE (after the first image, natural placement)
         * INSERT_IMAGE_2_HERE (in the middle section of the article)
       - DO NOT add any call-to-action or links in the content (they will be added automatically)
    3. **Tags:** Suggest 5 relevant Medium tags
    4. **Image Captions:** Create engaging captions that relate to the images

    **Output Format:**
    Return ONLY a valid JSON object with these keys:
    - "new_title": The new title
    - "new_html_content": The HTML content with placeholders (NO links or CTAs)
    - "tags": Array of 5 tags
    - "caption1": A short engaging caption for the first image
    - "caption2": A short engaging caption for the second image
    """ % (title, clean_content[:1500], original_link, alt_info)

    api_url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7}
    }
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(data), timeout=180)
        response.raise_for_status()
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            print("--- ✅ تم استلام مقال محسّن من Gemini.")
            return {
                "title": result.get("new_title", title),
                "content": result.get("new_html_content", content_html),
                "tags": result.get("tags", []),
                "caption1": result.get("caption1", ""),
                "caption2": result.get("caption2", "")
            }
    except Exception as e:
        print(f"!!! خطأ في Gemini: {e}")
        return None

def prepare_html_with_multiple_images_and_ctas(content_html, image1_data, image2_data, original_link, original_title, caption1="", caption2=""):
    print("--- 🎨 إعداد المحتوى النهائي مع الصور وCTAs...")
    if image1_data:
        alt1 = image1_data['alt'] or "Recipe preparation"
        full_alt1 = f"{alt1} | {SITE_DOMAIN}"
        image1_html = f'<img src="{image1_data["url"]}" alt="{full_alt1}">'
        image_caption1 = caption1 or (f"{image1_data['alt']} | {SITE_DOMAIN}" if image1_data['alt'] else f"Step-by-step preparation | {SITE_DOMAIN}")
        image1_with_caption = f'{image1_html}<p><em>{image_caption1}</em></p>'
    else:
        image1_with_caption = ""
    mid_cta = create_mid_cta(original_link, original_title)
    if image2_data:
        alt2 = image2_data['alt'] or "Final dish"
        full_alt2 = f"{alt2} | {SITE_DOMAIN}"
        image2_html = f'<img src="{image2_data["url"]}" alt="{full_alt2}">'
        if caption2:
            image_caption2 = caption2
        elif image2_data['alt'] and image1_data and image2_data['alt'] != image1_data.get('alt', ''):
            image_caption2 = f"{image2_data['alt']} | {SITE_DOMAIN}"
        elif image1_data and image2_data['url'] == image1_data.get('url', ''):
            image_caption2 = f"Another view of this delicious recipe | {SITE_DOMAIN}"
        else:
            image_caption2 = f"The final result - absolutely delicious! | {SITE_DOMAIN}"
        image2_with_caption = f'{image2_html}<p><em>{image_caption2}</em></p>'
    else:
        image2_with_caption = ""

    html = content_html.replace("INSERT_IMAGE_1_HERE", image1_with_caption)
    html = html.replace("INSERT_MID_CTA_HERE", mid_cta)
    html = html.replace("INSERT_IMAGE_2_HERE", image2_with_caption)
    final_cta = create_final_cta(original_link)
    return html + final_cta

# === الجديد هنا: انتظار postId وتحقق النشر ===
def wait_until_ready_to_publish(driver, wait, timeout=45):
    """ينتظر حتى يُنشأ postId (url يحتوي /p/.../edit) أو يختفي class 'js-buttonDisabledPrimary' من زر Publish"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        url = driver.current_url
        if "/p/" in url and "/edit" in url:
            print("    ✓ تم توليد postId (URL أصبح /p/.../edit)")
            return True
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')
            classes = (btn.get_attribute("class") or "").lower()
            if "js-buttondisabledprimary" not in classes:
                print("    ✓ زر Publish أصبح مفعّلاً (ليس Disabled)")
                return True
        except:
            pass
        time.sleep(1)
    print("    ⚠️ لم أتحقق من postId خلال المهلة، سأكمل بالرغم من ذلك.")
    return False

def ensure_published(driver, timeout=30):
    """تحقق أن القصة منشورة (وليس مسودة): URL يحتوي /p/ بدون /edit أو og:url منشور"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        url = driver.current_url
        if "/p/" in url and "/edit" not in url:
            return True
        try:
            metas = driver.find_elements(By.CSS_SELECTOR, 'meta[property="og:url"]')
            for m in metas:
                c = m.get_attribute("content") or ""
                if "/p/" in c and "/edit" not in c:
                    return True
        except:
            pass
        time.sleep(1)
    return False

def main():
    print(f"--- بدء تشغيل الروبوت الناشر v30.2 لموقع {SITE_DOMAIN} ---")
    post_to_publish = get_next_post_to_publish()
    if not post_to_publish:
        print(">>> النتيجة: لا توجد مقالات جديدة.")
        return

    original_title = post_to_publish.title
    original_link = post_to_publish.link

    rss_image = extract_image_url_from_entry(post_to_publish)
    if rss_image:
        print(f"--- 📷 صورة RSS احتياطية: {rss_image[:80]}...")

    image1_data, image2_data = get_best_images_for_article(original_link, rss_image)
    if image1_data:
        print(f"--- 🖼️ الصورة الأولى: {image1_data['url'][:60]}...")
    if image2_data:
        print(f"--- 🖼️ الصورة الثانية: {image2_data['url'][:60]}...")

    original_content_html = post_to_publish.content[0].value if ('content' in post_to_publish and post_to_publish.content) else post_to_publish.summary
    image1_alt = image1_data['alt'] if image1_data else ""
    image2_alt = image2_data['alt'] if image2_data else ""

    rewritten_data = rewrite_content_with_gemini(original_title, original_content_html, original_link, image1_alt, image2_alt)
    if rewritten_data:
        final_title = rewritten_data["title"]
        ai_content = rewritten_data["content"]
        ai_tags = rewritten_data.get("tags", [])
        caption1 = rewritten_data.get("caption1", "")
        caption2 = rewritten_data.get("caption2", "")
        full_html_content = prepare_html_with_multiple_images_and_ctas(ai_content, image1_data, image2_data, original_link, original_title, caption1, caption2)
    else:
        print("--- ⚠️ سيتم استخدام المحتوى الأصلي.")
        final_title = original_title
        ai_tags = []
        image1_html = f'<img src="{image1_data["url"]}" alt="{(image1_data.get("alt") or "Recipe image")+" | "+SITE_DOMAIN}">' if image1_data else ""
        image2_html = f'<br><img src="{image2_data["url"]}" alt="{(image2_data.get("alt") or "Recipe detail")+" | "+SITE_DOMAIN}">' if image2_data and (not image1_data or image2_data["url"] != image1_data.get("url","")) else ""
        mid_cta = f'<p><em>👉 See the full recipe at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em></p>'
        final_cta = create_final_cta(original_link)
        full_html_content = image1_html + mid_cta + original_content_html + image2_html + final_cta

    # --- النشر على Medium ---
    sid_cookie = os.environ.get("MEDIUM_SID_COOKIE")
    uid_cookie = os.environ.get("MEDIUM_UID_COOKIE")
    if not sid_cookie or not uid_cookie:
        print("!!! خطأ: لم يتم العثور على الكوكيز.")
        return

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")

    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US","en"], vendor="Google Inc.", platform="Win32",
            webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)

    try:
        print("--- 2. إعداد الجلسة...")
        driver.get("https://medium.com/")
        driver.add_cookie({"name": "sid", "value": sid_cookie, "domain": ".medium.com"})
        driver.add_cookie({"name": "uid", "value": uid_cookie, "domain": ".medium.com"})
        driver.refresh()
        time.sleep(2)

        print("--- 3. الانتقال إلى محرر المقالات...")
        driver.get("https://medium.com/new-story")

        wait = WebDriverWait(driver, 30)

        print("--- 4. كتابة العنوان...")
        title_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'h3[data-testid="editorTitleParagraph"]')))
        title_field.click()
        title_field.send_keys(final_title)

        print("--- 5. إدراج المحتوى مع الصور وCTAs...")
        story_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'p[data-testid="editorParagraphText"]')))
        story_field.click()

        # لصق عبر Clipboard (شغّال معك) + انتظار بسيط
        js_script = """
        const html = arguments[0];
        const blob = new Blob([html], { type: 'text/html' });
        const item = new ClipboardItem({ 'text/html': blob });
        navigator.clipboard.write([item]);
        """
        driver.execute_script(js_script, full_html_content)
        story_field.send_keys(Keys.CONTROL, 'v')

        # انتظر رفع الصور قليلاً
        time.sleep(8)

        # الجديد: انتظر postId أو تفعيل زر Publish قبل فتح نافذة النشر
        print("--- ⏳ التأكد أن القصة أصبحت جاهزة للنشر (postId)...")
        wait_until_ready_to_publish(driver, wait, timeout=45)

        print("--- 6. بدء النشر...")
        publish_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')))
        driver.execute_script("arguments[0].click();", publish_button)
        time.sleep(2)

        print("--- 7. إضافة الوسوم...")
        final_tags = []
        try:
            if rewritten_data:
                final_tags = rewritten_data.get("tags", [])[:5]
            if not final_tags:
                final_tags = ["recipe", "food", "cooking"]
            tags_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="publishTopicsInput"]')))
            tags_input.click()
            for tag in final_tags:
                tags_input.send_keys(tag)
                time.sleep(0.5)
                tags_input.send_keys(Keys.ENTER)
                time.sleep(1)
            print(f"--- تمت إضافة الوسوم: {', '.join(final_tags)}")
        except:
            print("--- تخطي الوسوم (اختياري)")

        print("--- 8. النشر النهائي...")
        publish_now_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')))
        time.sleep(1)
        driver.execute_script("arguments[0].click();", publish_now_button)

        print("--- 9. التحقق من الخروج من المسودة...")
        if ensure_published(driver, timeout=30):
            print("    ✅ تم النشر (الخروج من المسودة).")
        else:
            print("    ⚠️ لم أتحقق من النشر، إعادة محاولة الضغط على Publish now...")
            try:
                publish_now_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')))
                driver.execute_script("arguments[0].click();", publish_now_button)
                if not ensure_published(driver, timeout=25):
                    print("    ❌ ما زالت مسودة. سأحفظ لقطات التشخيص.")
                    driver.save_screenshot("error_screenshot.png")
                    with open("error_page_source.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
            except Exception as ee:
                print(f"    ❌ فشل إعادة المحاولة: {ee}")

        add_posted_link(post_to_publish.link)
        print(f">>> 🎉🎉🎉 تم النشر على {SITE_DOMAIN} (مع تحقق postId) ! 🎉🎉🎉")

    except Exception as e:
        print(f"!!! خطأ: {e}")
        driver.save_screenshot("error_screenshot.png")
        with open("error_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        raise e
    finally:
        driver.quit()
        print("--- تم إغلاق الروبوت ---")

if __name__ == "__main__":
    main()
