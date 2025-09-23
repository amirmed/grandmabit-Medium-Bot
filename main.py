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
from selenium.webdriver.common.action_chains import ActionChains
from selenium_stealth import stealth

# --- برمجة ahmed si - النسخة النهائية والمصقولة (v37) ---

# ====== إعدادات الموقع - غيّر هنا فقط ======
SITE_NAME = "grandmabites"  # اسم الموقع بدون .com
SITE_DOMAIN = f"{SITE_NAME}.com"
RSS_URL = f"https://{SITE_DOMAIN}/feed"

# مسارات الصور المحتملة
IMAGE_PATHS = [
    "/assets/images/",
    "/wp-content/uploads/",
    "/images/",
    "/media/",
    "/static/images/",
    "/content/images/",
    f"/{SITE_NAME}",
    "/recipes/images/",
]
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
    """استخراج أول صورة من RSS feed"""
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
    """التحقق من أن الصورة صالحة للمقال"""
    small_sizes = ['16', '32', '48', '64', '96', '128', '150', '160']
    for size in small_sizes:
        if f'width={size}' in url or f'w={size}' in url or f'-{size}x' in url or f'_{size}x' in url:
            return False
    
    exclude_keywords = [
        'avatar', 'author', 'profile', 'logo', 'icon', 
        'thumbnail', 'thumb', 'placeholder', 'blank',
        'advertising', 'banner', 'badge', 'button'
    ]
    url_lower = url.lower()
    if any(keyword in url_lower for keyword in exclude_keywords):
        return False
    
    if any(x in url_lower for x in ['pixel', 'tracking', 'analytics', '.gif']):
        return False
    
    valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
    has_valid_extension = any(ext in url_lower for ext in valid_extensions)
    
    return has_valid_extension

def scrape_article_images_with_alt(article_url):
    """كشط الصور مع نصوص alt من داخل المقال"""
    print(f"--- 🔍 كشط صور المقال بـ Selenium من: {article_url}")
    
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True)
    
    images_data = []
    
    try:
        print("    ⏳ تحميل الصفحة...")
        driver.get(article_url)
        time.sleep(3)
        
        wait = WebDriverWait(driver, 10)
        
        article_element = None
        selectors = ["article.article", "article", "div.entry-content", "main"]
        for selector in selectors:
            try:
                article_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                print(f"    ✓ تم العثور على المحتوى في: {selector}")
                break
            except: continue
        if not article_element:
            print("    ⚠️ لم أجد منطقة المحتوى، سأبحث في الصفحة كاملة")
            article_element = driver.find_element(By.TAG_NAME, "body")
        
        for i in range(1, 5):
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight*{i}/4);")
            time.sleep(1)

        print("    🔎 البحث عن الصور...")
        img_elements = article_element.find_elements(By.TAG_NAME, "img")
        print(f"    📊 عدد الصور في المقال: {len(img_elements)}")
        for img in img_elements:
            try:
                src = None
                for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-srcset']:
                    src = img.get_attribute(attr)
                    if src: break
                if not src: src = driver.execute_script("return arguments[0].currentSrc || arguments[0].src;", img)
                if not src: continue
                if ' ' in src and ',' in src: src = src.split(',')[-1].strip().split(' ')[0]
                
                alt_text = img.get_attribute("alt") or img.get_attribute("title") or ""
                
                if not src.startswith("http"):
                    from urllib.parse import urljoin
                    src = urljoin(article_url, src)

                if is_valid_article_image(src):
                    width = img.get_attribute("width") or driver.execute_script("return arguments[0].naturalWidth;", img)
                    try:
                        if int(width) < 200: continue
                    except: pass
                    if not any(d['url'] == src for d in images_data):
                        images_data.append({'url': src, 'alt': alt_text})
                        print(f"    ✅ تمت إضافة الصورة: {src[:60]}...")
            except Exception as e:
                print(f"    ⚠️ خطأ في معالجة صورة: {e}")
        print(f"--- ✅ تم العثور على {len(images_data)} صورة صالحة من المقال")
    except Exception as e:
        print(f"--- ⚠️ خطأ في Selenium: {e}")
    finally:
        driver.quit()
    return images_data

def get_best_images_for_article(article_url, rss_image=None):
    scraped_images_data = scrape_article_images_with_alt(article_url)
    all_images_data = list(scraped_images_data)
    if rss_image and is_valid_article_image(rss_image) and not any(d['url'] == rss_image for d in all_images_data):
        all_images_data.append({'url': rss_image, 'alt': 'Featured recipe image'})
    
    if len(all_images_data) >= 2:
        return all_images_data[0], all_images_data[1]
    elif len(all_images_data) == 1:
        return all_images_data[0], all_images_data[0]
    return None, None

def create_mid_cta(original_link, recipe_title="this recipe"):
    import hashlib
    cta_variations = [
        f'💡 <em>Want to see the exact measurements and timing? Check out <a href="{original_link}" rel="noopener" target="_blank">the full recipe on {SITE_DOMAIN}</a></em>',
        f'👉 <em>Get all the ingredients and detailed steps for {recipe_title} on <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>',
    ]
    index = int(hashlib.md5(original_link.encode()).hexdigest(), 16) % len(cta_variations)
    return f'<p>{cta_variations[index]}</p>'

def create_final_cta(original_link):
    return f'''<br><hr><h3>Ready to Make This Recipe?</h3><p><strong>🎯 Get the complete recipe with exact measurements, step-by-step instructions, and nutritional information.</strong></p><p><strong>👇 Visit <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a> for the full recipe!</strong></p>'''

def rewrite_content_with_gemini(title, content_html, original_link, image1_alt="", image2_alt=""):
    if not GEMINI_API_KEY:
        print("!!! تحذير: لم يتم العثور على مفتاح GEMINI_API_KEY.")
        return None
    print("--- 💬 التواصل مع Gemini API لإنشاء مقال احترافي...")
    clean_content = re.sub('<[^<]+?>', ' ', content_html)
    alt_info = f"\n- Image 1 description: {image1_alt}" if image1_alt else ""
    if image2_alt and image2_alt != image1_alt: alt_info += f"\n- Image 2 description: {image2_alt}"
    prompt = f"""You are a professional SEO copywriter for Medium. Rewrite a recipe article for maximum engagement.
    **Original Data:**
    - Title: "{title}"
    - Content: "{clean_content[:1500]}"
    - Link: "{original_link}"{alt_info}
    **Requirements:**
    1. **New Title:** Engaging, SEO-optimized title (60-70 characters).
    2. **Article Body:** 600-700 words in clean HTML (p, h2, h3, ul, ol, li, strong, em, br).
       - Compelling intro, practical tips, headers.
       - **IMPORTANT**: Insert these EXACT placeholders: INSERT_IMAGE_1_HERE, INSERT_MID_CTA_HERE, INSERT_IMAGE_2_HERE.
       - NO other links or CTAs.
    3. **Tags:** 5 relevant Medium tags.
    4. **Image Captions:** Engaging captions for the images.
    **Output Format:** Return ONLY a valid JSON object with keys: "new_title", "new_html_content", "tags", "caption1", "caption2".
    """
    api_url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
    headers = {'Content-Type': 'application/json'}
    data = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.7}}
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(data), timeout=180)
        response.raise_for_status()
        raw_text = response.json()['candidates'][0]['content']['parts'][0]['text']
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
    image1_html = image2_html = ""
    if image1_data:
        alt1 = image1_data['alt'] or "Recipe preparation"
        cap1 = caption1 or f"{alt1} | {SITE_DOMAIN}"
        image1_html = f'<img src="{image1_data["url"]}" alt="{alt1} | {SITE_DOMAIN}"><p><em>{cap1}</em></p>'
    if image2_data:
        alt2 = image2_data['alt'] or "Final dish"
        cap2 = caption2 or f"{alt2} | {SITE_DOMAIN}"
        image2_html = f'<img src="{image2_data["url"]}" alt="{alt2} | {SITE_DOMAIN}"><p><em>{cap2}</em></p>'
    
    content_html = content_html.replace("INSERT_IMAGE_1_HERE", image1_html)
    content_html = content_html.replace("INSERT_MID_CTA_HERE", create_mid_cta(original_link, original_title))
    content_html = content_html.replace("INSERT_IMAGE_2_HERE", image2_html)
    return content_html + create_final_cta(original_link)

def main():
    print(f"--- بدء تشغيل الروبوت الناشر v37 لموقع {SITE_DOMAIN} ---")
    post_to_publish = get_next_post_to_publish()
    if not post_to_publish:
        print(">>> النتيجة: لا توجد مقالات جديدة.")
        return

    original_title, original_link = post_to_publish.title, post_to_publish.link
    rss_image = extract_image_url_from_entry(post_to_publish)
    image1_data, image2_data = get_best_images_for_article(original_link, rss_image)
    
    original_content_html = post_to_publish.content[0].value if 'content' in post_to_publish and post_to_publish.content else post_to_publish.summary
    
    rewritten_data = rewrite_content_with_gemini(
        original_title, original_content_html, original_link,
        image1_data['alt'] if image1_data else "", image2_data['alt'] if image2_data else ""
    )
    
    if rewritten_data:
        final_title = rewritten_data["title"]
        full_html_content = prepare_html_with_multiple_images_and_ctas(
            rewritten_data["content"], image1_data, image2_data, original_link, original_title,
            rewritten_data.get("caption1", ""), rewritten_data.get("caption2", "")
        )
        ai_tags = rewritten_data.get("tags", [])
        print("--- ✅ تم إعداد المحتوى المُحسّن.")
    else:
        print("--- ⚠️ فشل Gemini، سيتم استخدام المحتوى الأصلي.")
        final_title, ai_tags = original_title, []
        full_html_content = prepare_html_with_multiple_images_and_ctas(
            original_content_html, image1_data, image2_data, original_link, original_title
        )

    sid_cookie, uid_cookie = os.environ.get("MEDIUM_SID_COOKIE"), os.environ.get("MEDIUM_UID_COOKIE")
    if not sid_cookie or not uid_cookie:
        print("!!! خطأ: لم يتم العثور على الكوكيز."); return

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    stealth(driver, languages=["en-US", "en"], vendor="Google Inc.", platform="Win32",
            webgl_vendor="Intel Inc.", renderer="Intel Iris OpenGL Engine", fix_hairline=True)
    
    try:
        print("--- 2. إعداد الجلسة...")
        driver.get("https://medium.com/")
        driver.add_cookie({"name": "sid", "value": sid_cookie, "domain": ".medium.com"})
        driver.add_cookie({"name": "uid", "value": uid_cookie, "domain": ".medium.com"})
        
        print("--- 3. الانتقال إلى محرر المقالات...")
        driver.get("https://medium.com/new-story")
        wait = WebDriverWait(driver, 30)
        
        print("--- 4. كتابة العنوان والمحتوى...")
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'h3[data-testid="editorTitleParagraph"]'))).send_keys(final_title)
        story_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'p[data-testid="editorParagraphText"]')))
        driver.execute_script("navigator.clipboard.writeText(arguments[0]);", full_html_content)
        story_field.send_keys(Keys.CONTROL, 'v')
        print("--- ⏳ انتظار رفع الصور..."); time.sleep(15)
        
        print("--- 6. فتح نافذة النشر...");
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="show-prepublish"]'))).click()
        
        print("--- 7. إضافة الوسوم...")
        tags_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="publishTopicsInput"]')))
        if ai_tags:
            tags_input.click()
            for tag in ai_tags[:5]:
                tags_input.send_keys(tag); time.sleep(0.5); tags_input.send_keys(Keys.ENTER); time.sleep(1)
            print(f"--- تمت إضافة الوسوم: {', '.join(ai_tags[:5])}")
        else:
            print("--- لا توجد وسوم لإضافتها.")
        
        # === الحل النهائي المدمج هنا ===
        print("    ... النقر على نافذة الحوار لإزالة التركيز من الوسوم")
        try:
            dialog_element = driver.find_element(By.CSS_SELECTOR, "div[role='dialog']")
            dialog_element.click()
            time.sleep(1)
        except Exception as e:
            print(f"    ⚠️ لم يتمكن من النقر على الحوار لإزالة التركيز (سيستمر): {e}")

        print("--- 8. التحقق من الخيارات الإلزامية...")
        try:
            meter_checkbox = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='checkbox'][id*='meter']")))
            if not meter_checkbox.is_selected():
                print("    ⚠️ خيار تحقيق الدخل غير محدد. سيتم تحديده الآن.")
                driver.execute_script("arguments[0].click();", meter_checkbox); time.sleep(1)
            else: print("    ℹ️ خيار تحقيق الدخل محدد بالفعل.")
        except: print("    ℹ️ لم يتم العثور على خيار تحقيق الدخل (أو ليس مطلوباً).")

        print("--- 9. محاولة النشر (الهجوم الشامل)...")
        final_publish_button_selector = 'button[data-testid="publishConfirmButton"]'
        final_publish_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, final_publish_button_selector)))
        
        print("    ✅ تم العثور على زر النشر. بدء محاكاة النقر البشري المتقدمة...")
        actions = ActionChains(driver)
        actions.move_to_element(final_publish_button).pause(0.5).click().perform()
        print("    - تمت محاولة النقر باستخدام ActionChains."); time.sleep(2)

        try:
            button_check = driver.find_element(By.CSS_SELECTOR, final_publish_button_selector)
            print("    ⚠️ الزر لا يزال موجوداً. النقرة لم تنجح. محاولة أخيرة بـ JavaScript...")
            driver.execute_script("arguments[0].click();", button_check)
            print("    - تمت المحاولة الأخيرة بـ JavaScript.")
        except:
            print("    ✅ يبدو أن النقرة نجحت واختفت النافذة.")
        # ======================= نهاية الحل =======================
        
        print("--- 10. انتظار معالجة النشر (20 ثانية)..."); time.sleep(20)
        
        print("--- 11. التحقق من نجاح النشر...")
        final_url = driver.current_url
        print(f"    🔗 الرابط الحالي بعد النشر: {final_url}")
        
        if "/edit" in final_url or "/draft" in final_url:
            driver.save_screenshot("publish_failed_final_page.png")
            raise Exception("Post was not published, it remained a draft.")
        else:
            add_posted_link(original_link)
            print(f">>> 🎉🎉🎉 تم نشر المقال بنجاح على {SITE_DOMAIN}! 🎉🎉🎉")
        
    except Exception as e:
        print(f"!!! حدث خطأ فادح أثناء عملية النشر: {e}")
        driver.save_screenshot("error_screenshot.png")
        with open("error_page_source.html", "w", encoding="utf-8") as f: f.write(driver.page_source)
    finally:
        driver.quit()
        print("--- تم إغلاق الروبوت ---")

if __name__ == "__main__":
    main()
