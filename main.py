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

# --- برمجة ahmed si - النسخة v32 Final ---

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
        selectors = ["article", "main", "div.content", "body"]
        
        for selector in selectors:
            try:
                article_element = driver.find_element(By.CSS_SELECTOR, selector)
                if article_element:
                    print(f"    ✓ تم العثور على المحتوى في: {selector}")
                    break
            except:
                continue
        
        if not article_element:
            article_element = driver.find_element(By.TAG_NAME, "body")
        
        # التمرير لتحميل الصور
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        print("    🔎 البحث عن الصور...")
        
        img_elements = article_element.find_elements(By.TAG_NAME, "img")
        print(f"    📊 عدد الصور: {len(img_elements)}")
        
        for img in img_elements:
            try:
                src = img.get_attribute("src") or img.get_attribute("data-src") or img.get_attribute("data-lazy-src")
                
                if not src:
                    continue
                
                alt_text = img.get_attribute("alt") or ""
                
                # تنظيف الرابط
                clean_url = src
                if not clean_url.startswith("http"):
                    if clean_url.startswith("//"):
                        clean_url = "https:" + clean_url
                    elif clean_url.startswith("/"):
                        from urllib.parse import urljoin
                        clean_url = urljoin(article_url, clean_url)
                
                if is_valid_article_image(clean_url):
                    # تجنب التكرار
                    if not any(img_data['url'] == clean_url for img_data in images_data):
                        images_data.append({
                            'url': clean_url,
                            'alt': alt_text
                        })
                        print(f"    ✅ صورة: {clean_url[:60]}...")
                        
            except:
                continue
        
        print(f"--- ✅ تم العثور على {len(images_data)} صورة")
        
    except Exception as e:
        print(f"--- ⚠️ خطأ في Selenium: {e}")
    finally:
        driver.quit()
    
    return images_data

def get_best_images_for_article(article_url, rss_image=None):
    """الحصول على أفضل صورتين"""
    scraped_images_data = scrape_article_images_with_alt(article_url)
    
    all_images_data = []
    all_images_data.extend(scraped_images_data)
    
    # إضافة صورة RSS كاحتياطي
    if rss_image and is_valid_article_image(rss_image):
        if not any(img['url'] == rss_image for img in all_images_data):
            all_images_data.append({
                'url': rss_image,
                'alt': 'Featured recipe image'
            })
    
    # اختيار صورتين
    if len(all_images_data) >= 2:
        image1_data = all_images_data[0]
        image2_data = all_images_data[min(2, len(all_images_data)-1)] if len(all_images_data) > 2 else all_images_data[1]
    elif len(all_images_data) == 1:
        image1_data = image2_data = all_images_data[0]
    else:
        image1_data = image2_data = None
    
    return image1_data, image2_data

def create_mid_cta(original_link):
    """CTA للمنتصف"""
    return f'<p>💡 <em>Want the full recipe? Visit <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em></p>'

def create_final_cta(original_link):
    """CTA للنهاية"""
    return f'''<br><hr>
    <h3>Ready to Make This Recipe?</h3>
    <p><strong>Get the complete recipe with all ingredients and instructions at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></strong></p>'''

def rewrite_content_with_gemini(title, content_html, original_link):
    if not GEMINI_API_KEY:
        return None
    
    print("--- 💬 Gemini API...")
    clean_content = re.sub('<[^<]+?>', ' ', content_html)[:1500]
    
    prompt = f"""Rewrite this recipe article for Medium. Create engaging SEO content.
    Title: {title}
    Content: {clean_content}
    
    Requirements:
    - New catchy title (60-70 chars)
    - 600-700 words
    - Use HTML: p, h2, h3, ul, ol, li, strong, em
    - Add placeholders: INSERT_IMAGE_1_HERE and INSERT_IMAGE_2_HERE
    - Suggest 5 tags
    
    Return JSON with: new_title, new_html_content, tags"""
    
    api_url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}'
    
    try:
        response = requests.post(api_url, 
            headers={'Content-Type': 'application/json'},
            data=json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 4096}
            }), timeout=30)
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            print("--- ✅ Gemini نجح")
            return {
                "title": result.get("new_title", title),
                "content": result.get("new_html_content", content_html),
                "tags": result.get("tags", [])
            }
    except:
        pass
    
    return None

def prepare_final_content(content_html, image1_data, image2_data, original_link):
    """إعداد المحتوى النهائي"""
    
    # الصورة الأولى
    if image1_data:
        alt1 = f"{image1_data['alt']} | {SITE_DOMAIN}" if image1_data['alt'] else f"Recipe | {SITE_DOMAIN}"
        image1_html = f'<img src="{image1_data["url"]}" alt="{alt1}"><p><em>{alt1}</em></p>'
    else:
        image1_html = ""
    
    # الصورة الثانية
    if image2_data:
        alt2 = f"{image2_data['alt']} | {SITE_DOMAIN}" if image2_data['alt'] else f"Final dish | {SITE_DOMAIN}"
        image2_html = f'<img src="{image2_data["url"]}" alt="{alt2}"><p><em>{alt2}</em></p>'
    else:
        image2_html = ""
    
    # استبدال العلامات
    content_html = content_html.replace("INSERT_IMAGE_1_HERE", image1_html)
    content_html = content_html.replace("INSERT_IMAGE_2_HERE", image2_html)
    
    # إضافة CTAs
    mid_cta = create_mid_cta(original_link)
    final_cta = create_final_cta(original_link)
    
    # إذا لم توجد علامات، ضع الصور يدوياً
    if "INSERT_IMAGE" not in content_html and image1_html:
        # ضع الصورة الأولى في البداية
        content_html = image1_html + content_html
    
    return content_html + mid_cta + final_cta

def main():
    print(f"--- بدء الروبوت v32 لموقع {SITE_DOMAIN} ---")
    
    post_to_publish = get_next_post_to_publish()
    if not post_to_publish:
        print(">>> لا توجد مقالات جديدة.")
        return

    # الحصول على الكوكيز
    sid_cookie = os.environ.get("MEDIUM_SID_COOKIE")
    uid_cookie = os.environ.get("MEDIUM_UID_COOKIE")
    
    if not sid_cookie or not uid_cookie:
        print("!!! خطأ: لم يتم العثور على الكوكيز.")
        return

    original_title = post_to_publish.title
    original_link = post_to_publish.link
    
    # استخراج الصور
    rss_image = extract_image_url_from_entry(post_to_publish)
    image1_data, image2_data = get_best_images_for_article(original_link, rss_image)
    
    if image1_data:
        print(f"--- 🖼️ الصورة 1: {image1_data['url'][:60]}...")
    if image2_data:
        print(f"--- 🖼️ الصورة 2: {image2_data['url'][:60]}...")
    
    # المحتوى الأصلي
    if 'content' in post_to_publish and post_to_publish.content:
        original_content = post_to_publish.content[0].value
    else:
        original_content = post_to_publish.summary
    
    # إعادة كتابة بـ Gemini
    final_title = original_title
    ai_tags = []
    
    if GEMINI_API_KEY:
        rewritten = rewrite_content_with_gemini(original_title, original_content, original_link)
        if rewritten:
            final_title = rewritten["title"]
            original_content = rewritten["content"]
            ai_tags = rewritten.get("tags", [])
    
    # إعداد المحتوى النهائي
    full_html_content = prepare_final_content(original_content, image1_data, image2_data, original_link)
    
    # --- بدء النشر على Medium (الطريقة القديمة الناجحة) ---
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    stealth(driver, 
            languages=["en-US", "en"], 
            vendor="Google Inc.", 
            platform="Win32", 
            webgl_vendor="Intel Inc.", 
            renderer="Intel Iris OpenGL Engine", 
            fix_hairline=True)
    
    try:
        print("--- 2. إعداد الجلسة...")
        driver.get("https://medium.com/")
        driver.add_cookie({"name": "sid", "value": sid_cookie, "domain": ".medium.com"})
        driver.add_cookie({"name": "uid", "value": uid_cookie, "domain": ".medium.com"})
        
        print("--- 3. الانتقال إلى محرر المقالات...")
        driver.get("https://medium.com/new-story")
        
        wait = WebDriverWait(driver, 30)
        
        print("--- 4. كتابة العنوان والمحتوى...")
        # العنوان
        title_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'h3[data-testid="editorTitleParagraph"]')))
        title_field.click()
        title_field.send_keys(final_title)
        
        # المحتوى
        story_field = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'p[data-testid="editorParagraphText"]')))
        story_field.click()
        
        # لصق المحتوى (الطريقة القديمة الناجحة)
        js_script = "const html = arguments[0]; const blob = new Blob([html], { type: 'text/html' }); const item = new ClipboardItem({ 'text/html': blob }); navigator.clipboard.write([item]);"
        driver.execute_script(js_script, full_html_content)
        story_field.send_keys(Keys.CONTROL, 'v')
        time.sleep(5)  # انتظار رفع الصور
        
        print("--- 5. بدء عملية النشر...")
        publish_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')))
        publish_button.click()
        
        print("--- 6. إضافة الوسوم...")
        try:
            tags_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="publishTopicsInput"]')))
            tags_input.click()
            
            # إضافة الوسوم من RSS أو Gemini
            tags_to_add = []
            if ai_tags:
                tags_to_add = ai_tags[:5]
            elif hasattr(post_to_publish, 'tags'):
                tags_to_add = [tag.term for tag in post_to_publish.tags[:5]]
            
            for tag in tags_to_add:
                tags_input.send_keys(tag)
                time.sleep(0.5)
                tags_input.send_keys(Keys.ENTER)
                time.sleep(1)
            
            if tags_to_add:
                print(f"--- تمت إضافة الوسوم: {', '.join(tags_to_add)}")
        except:
            print("--- تخطي الوسوم")
        
        print("--- 7. إرسال أمر النشر النهائي...")
        # استخدام نفس الطريقة القديمة الناجحة تماماً
        publish_now_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')))
        time.sleep(2)  # انتظار استباقي
        driver.execute_script("arguments[0].click();", publish_now_button)
        
        print("--- 8. انتظار نهائي للسماح بمعالجة النشر...")
        time.sleep(15)
        
        add_posted_link(post_to_publish.link)
        print(">>> 🎉🎉🎉 تم إرسال أمر النشر بنجاح! 🎉🎉🎉")
        
    except Exception as e:
        print(f"!!! حدث خطأ: {e}")
        driver.save_screenshot("error_screenshot.png")
        with open("error_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        raise e
    finally:
        driver.quit()
        print("--- تم إغلاق الروبوت ---")

if __name__ == "__main__":
    main()
