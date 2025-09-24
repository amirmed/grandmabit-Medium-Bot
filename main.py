import feedparser
import os
import time
import re
import requests
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth

# --- برمجة ahmed si - النسخة v34 Optimized ---

# ====== إعدادات الموقع - غيّر هنا فقط ======
SITE_NAME = "grandmabites"  # اسم الموقع بدون .com
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

# وضع الاختبار - ضعه True للاختبار بدون نشر فعلي
TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
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

def is_recipe_image(url, alt_text=""):
    """التحقق من أن الصورة متعلقة بالوصفة"""
    food_keywords = ['recipe', 'food', 'dish', 'meal', 'cook', 'ingredient']
    if any(keyword in url.lower() or keyword in alt_text.lower() for keyword in food_keywords):
        return True
    
    if any(path in url for path in IMAGE_PATHS):
        return True
    
    if SITE_DOMAIN in url:
        return True
    
    return False

def scrape_article_images_with_alt(article_url):
    """كشط الصور مع نصوص alt من داخل المقال"""
    print(f"--- 🔍 كشط صور المقال بـ Selenium من: {article_url}")
    
    options = webdriver.FirefoxOptions() # التغيير هنا
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    
    service = FirefoxService(GeckoDriverManager().install()) # التغيير هنا
    driver = webdriver.Firefox(service=service, options=options) # التغيير هنا
    
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True)
    
    images_data = []
    
    try:
        print("    ⏳ تحميل الصفحة...")
        driver.get(article_url)
        time.sleep(3)
        
        wait = WebDriverWait(driver, 10)
        
        article_element = None
        selectors = [
            "article.article",
            "article",
            "div.article-content",
            "div.entry-content",
            "div.post-content",
            "div.content",
            "main",
            "div.recipe-content"
        ]
        
        for selector in selectors:
            try:
                article_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                print(f"    ✓ تم العثور على المحتوى في: {selector}")
                break
            except:
                continue
        
        if not article_element:
            print("    ⚠️ لم أجد منطقة المحتوى، سأبحث في الصفحة كاملة")
            article_element = driver.find_element(By.TAG_NAME, "body")
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/4);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight*3/4);")
        time.sleep(1)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        print("    🔎 البحث عن الصور...")
        
        all_images = driver.find_elements(By.TAG_NAME, "img")
        print(f"    📊 عدد الصور الكلي في الصفحة: {len(all_images)}")
        
        img_elements = article_element.find_elements(By.TAG_NAME, "img")
        print(f"    📊 عدد الصور في المقال: {len(img_elements)}")
        
        for img in img_elements:
            try:
                src = None
                src_attrs = ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-srcset']
                
                for attr in src_attrs:
                    src = img.get_attribute(attr)
                    if src:
                        break
                
                if not src:
                    src = driver.execute_script("return arguments[0].currentSrc || arguments[0].src;", img)
                
                if not src:
                    continue
                
                if ' ' in src and ',' in src:
                    srcset_parts = src.split(',')
                    src = srcset_parts[-1].strip().split(' ')[0]
                
                alt_text = img.get_attribute("alt") or img.get_attribute("title") or ""
                
                width = img.get_attribute("width") or driver.execute_script("return arguments[0].naturalWidth;", img)
                height = img.get_attribute("height") or driver.execute_script("return arguments[0].naturalHeight;", img)
                
                print(f"    🔍 فحص صورة: {src[:50]}... | Alt: {alt_text[:30]}... | Size: {width}x{height}")
                
                clean_url = src
                
                if "/cdn-cgi/image/" in clean_url:
                    match = re.search(r'/(wp-content/uploads/[^"]+)', clean_url)
                    if match:
                        clean_url = f"https://{SITE_DOMAIN}" + match.group(1)
                    else:
                        match = re.search(r'/([^/]+\.(jpg|jpeg|png|webp))', clean_url, re.IGNORECASE)
                        if match:
                            clean_url = f"https://{SITE_DOMAIN}/wp-content/uploads/" + match.group(1)
                
                if not clean_url.startswith("http"):
                    if clean_url.startswith("//"):
                        clean_url = "https:" + clean_url
                    elif clean_url.startswith("/"):
                        from urllib.parse import urljoin
                        clean_url = urljoin(article_url, clean_url)
                
                if is_valid_article_image(clean_url):
                    try:
                        width_int = int(width) if width else 0
                        if width_int < 200 and width_int > 0:
                            print(f"    ❌ صورة صغيرة جداً: {width_int}px")
                            continue
                    except:
                        pass
                    
                    image_exists = False
                    for img_data in images_data:
                        if img_data['url'] == clean_url:
                            image_exists = True
                            break
                    
                    if not image_exists:
                        images_data.append({
                            'url': clean_url,
                            'alt': alt_text
                        })
                        print(f"    ✅ تمت إضافة الصورة: {clean_url[:60]}...")
                else:
                    print(f"    ❌ صورة مرفوضة: {clean_url[:60]}...")
                        
            except Exception as e:
                print(f"    ⚠️ خطأ في معالجة صورة: {e}")
                continue
        
        if len(images_data) < 2:
            print("    🔎 البحث في عناصر picture...")
            picture_elements = article_element.find_elements(By.TAG_NAME, "picture")
            for picture in picture_elements:
                try:
                    sources = picture.find_elements(By.TAG_NAME, "source")
                    for source in sources:
                        srcset = source.get_attribute("srcset")
                        if srcset:
                            urls = re.findall(r'(https?://[^\s]+)', srcset)
                            if urls:
                                url = urls[-1]
                                if is_valid_article_image(url):
                                    images_data.append({
                                        'url': url,
                                        'alt': 'Recipe image'
                                    })
                                    print(f"    ✅ صورة من picture: {url[:60]}...")
                                    break
                except:
                    continue
        
        print(f"--- ✅ تم العثور على {len(images_data)} صورة صالحة من المقال")
        
        for i, img in enumerate(images_data, 1):
            print(f"    📸 الصورة {i}: {img['url']}")
        
    except Exception as e:
        print(f"--- ⚠️ خطأ في Selenium: {e}")
    finally:
        driver.quit()
    
    return images_data

def get_best_images_for_article(article_url, rss_image=None):
    """الحصول على أفضل صورتين مع alt text"""
    scraped_images_data = scrape_article_images_with_alt(article_url)
    
    all_images_data = []
    all_images_data.extend(scraped_images_data)
    
    if rss_image and is_valid_article_image(rss_image):
        rss_exists = False
        for img_data in all_images_data:
            if img_data['url'] == rss_image:
                rss_exists = True
                break
        
        if not rss_exists:
            all_images_data.append({
                'url': rss_image,
                'alt': 'Featured recipe image'
            })
    
    if len(all_images_data) >= 2:
        image1_data = all_images_data[0]
        if len(all_images_data) >= 3:
            image2_data = all_images_data[2]
        else:
            image2_data = all_images_data[1]
    elif len(all_images_data) == 1:
        image1_data = image2_data = all_images_data[0]
    else:
        image1_data = image2_data = None
    
    return image1_data, image2_data

def create_mid_cta(original_link, recipe_title="this recipe"):
    """إنشاء CTA خفيف للمنتصف"""
    cta_variations = [
        f'💡 <em>Want to see the exact measurements and timing? Check out <a href="{original_link}" rel="noopener" target="_blank">the full recipe on {SITE_DOMAIN}</a></em>',
        f'👉 <em>Get all the ingredients and detailed steps for {recipe_title} on <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>',
        f'📖 <em>Find the printable version with nutrition facts at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>',
        f'🍳 <em>See step-by-step photos and pro tips on <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em>'
    ]
    
    import hashlib
    index = int(hashlib.md5(original_link.encode()).hexdigest(), 16) % len(cta_variations)
    return f'<p>{cta_variations[index]}</p>'

def create_final_cta(original_link):
    """إنشاء CTA قوي للنهاية"""
    final_cta = f'''
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
    <p><strong>👉 Visit <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a> for the full recipe and more delicious ideas!</strong></p>
    '''
    return final_cta

def rewrite_content_with_gemini(title, content_html, original_link, image1_alt="", image2_alt=""):
    if not GEMINI_API_KEY:
        print("!!! تحذير: لم يتم العثور على مفتاح GEMINI_API_KEY.")
        return None

    print("--- 💬 التواصل مع Gemini API لإنشاء مقال احترافي...")
    clean_content = re.sub('<[^<]+?>', ' ', content_html)
    
    alt_info = ""
    if image1_alt:
        alt_info += f"\n- Image 1 description: {image1_alt}"
    if image2_alt and image2_alt != image1_alt:
        alt_info += f"\n- Image 2 description: {image2_alt}"
    
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
            clean_json_str = json_match.group(0)
            result = json.loads(clean_json_str)
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
    """إعداد HTML النهائي مع الصور وCTAs متعددة"""
    
    print("--- 🎨 إعداد المحتوى النهائي مع الصور وCTAs...")
    
    if image1_data:
        alt1 = image1_data['alt'] or "Recipe preparation"
        full_alt1 = f"{alt1} | {SITE_DOMAIN}" if alt1 else f"Recipe image | {SITE_DOMAIN}"
        
        image1_html = f'<img src="{image1_data["url"]}" alt="{full_alt1}">'
        
        if caption1:
            image_caption1 = caption1
        elif image1_data['alt']:
            image_caption1 = f"{image1_data['alt']} | {SITE_DOMAIN}"
        else:
            image_caption1 = f"Step-by-step preparation | {SITE_DOMAIN}"
        
        image1_with_caption = f'{image1_html}<p><em>{image_caption1}</em></p>'
    else:
        image1_with_caption = ""
    
    mid_cta = create_mid_cta(original_link, original_title)
    
    if image2_data:
        alt2 = image2_data['alt'] or "Final dish"
        full_alt2 = f"{alt2} | {SITE_DOMAIN}" if alt2 else f"Recipe result | {SITE_DOMAIN}"
        
        image2_html = f'<img src="{image2_data["url"]}" alt="{full_alt2}">'
        
        if caption2:
            image_caption2 = caption2
        elif image2_data['alt'] and image2_data['alt'] != image1_data.get('alt', ''):
            image_caption2 = f"{image2_data['alt']} | {SITE_DOMAIN}"
        elif image2_data['url'] == image1_data.get('url', ''):
            image_caption2 = f"Another view of this delicious recipe | {SITE_DOMAIN}"
        else:
            image_caption2 = f"The final result - absolutely delicious! | {SITE_DOMAIN}"
        
        image2_with_caption = f'{image2_html}<p><em>{image_caption2}</em></p>'
    else:
        image2_with_caption = ""
    
    content_html = content_html.replace("INSERT_IMAGE_1_HERE", image1_with_caption)
    content_html = content_html.replace("INSERT_MID_CTA_HERE", mid_cta)
    content_html = content_html.replace("INSERT_IMAGE_2_HERE", image2_with_caption)
    
    final_cta = create_final_cta(original_link)
    
    return content_html + final_cta

def ensure_publish_now_selected(driver):
    """التأكد من تحديد خيار النشر الفوري"""
    print("--- 🎯 التأكد من تحديد 'النشر الفوري'...")
    
    try:
        # محاولة 1: البحث عن radio button للنشر الفوري
        try:
            publish_now_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Publish now')]")
            if publish_now_elements:
                element = publish_now_elements[0]
                driver.execute_script("arguments[0].click();", element)
                print("    ✅ تم تحديد 'Publish now' عبر النص")
                time.sleep(1)
                return True
        except:
            pass
        
        # محاولة 2: البحث عن input radio
        try:
            radio_buttons = driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')
            if radio_buttons:
                # عادة الخيار الأول هو Publish now
                driver.execute_script("arguments[0].click();", radio_buttons[0])
                print("    ✅ تم تحديد أول خيار radio (النشر الفوري)")
                time.sleep(1)
                return True
        except:
            pass
        
        # محاولة 3: البحث في الـ labels
        try:
            labels = driver.find_elements(By.TAG_NAME, "label")
            for label in labels:
                if "publish now" in label.text.lower():
                    driver.execute_script("arguments[0].click();", label)
                    print("    ✅ تم النقر على label 'Publish now'")
                    time.sleep(1)
                    return True
        except:
            pass
        
        print("    ℹ️ خيار النشر الفوري قد يكون محدداً بالفعل")
        return True
        
    except Exception as e:
        print(f"    ⚠️ خطأ في تحديد خيار النشر: {str(e)[:100]}")
        return False

def quick_publish_with_enter(driver):
    """نشر سريع بـ Enter - الطريقة الأكثر نجاحاً"""
    try:
        print("    ⚡ محاولة النشر السريع بـ Enter...")
        
        # التركيز على العنصر النشط
        active = driver.switch_to.active_element
        
        # إرسال Enter مرتين للتأكيد
        active.send_keys(Keys.ENTER)
        time.sleep(1)
        
        # التحقق من وجود زر تأكيد إضافي
        try:
            confirm_buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in confirm_buttons:
                if "publish" in btn.text.lower() or "confirm" in btn.text.lower():
                    driver.execute_script("arguments[0].click();", btn)
                    print("    ✅ تم النقر على زر التأكيد")
                    break
        except:
            pass
        
        print("    ✅ تم النشر بـ Enter بنجاح")
        return True
        
    except Exception as e:
        print(f"    ❌ فشل النشر بـ Enter: {str(e)[:100]}")
        return False

def publish_with_optimized_attempts(driver, wait):
    """محاولات محسّنة للنشر النهائي - Enter أولاً"""
    print("--- 🚀 بدء عملية النشر النهائي (محسّن)...")
    
    # حفظ لقطة شاشة قبل النشر
    driver.save_screenshot("before_final_publish.png")
    print("    📸 تم حفظ لقطة شاشة قبل النشر")
    
    publish_success = False
    
    # المحاولة 1: Enter (الأسرع والأكثر نجاحاً)
    if not publish_success:
        publish_success = quick_publish_with_enter(driver)
    
    # المحاولة 2: البحث عن زر "Publish now" بالنص
    if not publish_success:
        try:
            print("    🔍 المحاولة 2: البحث عن زر 'Publish now'...")
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                btn_text = btn.text.lower()
                if "publish" in btn_text and ("now" in btn_text or not "schedule" in btn_text):
                    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", btn)
                    print(f"    ✅ تم النقر على زر: {btn.text}")
                    publish_success = True
                    break
        except Exception as e:
            print(f"    ❌ فشلت المحاولة 2: {str(e)[:100]}")
    
    # المحاولة 3: استخدام data-testid
    if not publish_success:
        try:
            print("    🔍 المحاولة 3: استخدام data-testid...")
            final_publish_button = driver.find_element(By.CSS_SELECTOR, 'button[data-testid="publishConfirmButton"]')
            
            if final_publish_button:
                # التحقق من نص الزر
                button_text = final_publish_button.text.lower()
                print(f"    📝 نص الزر: {button_text}")
                
                driver.execute_script("arguments[0].click();", final_publish_button)
                print("    ✅ تم النقر على زر النشر عبر data-testid")
                publish_success = True
                
        except Exception as e:
            print(f"    ❌ فشلت المحاولة 3: {str(e)[:100]}")
    
    # المحاولة 4: JavaScript مباشر
    if not publish_success:
        try:
            print("    🔍 المحاولة 4: JavaScript مباشر...")
            js_publish = """
            // البحث عن جميع الأزرار
            const buttons = document.querySelectorAll('button');
            let clicked = false;
            
            // البحث عن زر النشر
            buttons.forEach(btn => {
                const text = btn.textContent.toLowerCase();
                if (!clicked && text.includes('publish') && 
                    (text.includes('now') || (!text.includes('schedule') && !text.includes('draft')))) {
                    btn.click();
                    clicked = true;
                }
            });
            
            if (clicked) return 'Success: Clicked Publish';
            
            // البحث عن زر التأكيد
            const confirmBtn = document.querySelector('[data-testid="publishConfirmButton"]');
            if (confirmBtn) {
                confirmBtn.click();
                return 'Success: Clicked Confirm';
            }
            
            return 'Failed: No button found';
            """
            
            result = driver.execute_script(js_publish)
            print(f"    📝 نتيجة JavaScript: {result}")
            if "Success" in result:
                publish_success = True
                
        except Exception as e:
            print(f"    ❌ فشلت المحاولة 4: {str(e)[:100]}")
    
    # حفظ لقطة شاشة بعد محاولات النشر
    time.sleep(3)
    driver.save_screenshot("after_publish_attempts.png")
    print("    📸 تم حفظ لقطة شاشة بعد محاولات النشر")
    
    if publish_success:
        print("--- ✅ تم إرسال أمر النشر بنجاح!")
    else:
        print("--- ⚠️ جميع المحاولات فشلت، لكن قد يكون النشر تم بالفعل")
    
    return publish_success

def log_success_stats(title, url):
    """تسجيل إحصائيات النجاح"""
    stats_file = "publishing_stats.json"
    from datetime import datetime
    
    try:
        with open(stats_file, 'r', encoding='utf-8') as f:
            stats = json.load(f)
    except:
        stats = {"total_published": 0, "posts": []}
    
    stats["total_published"] += 1
    stats["posts"].append({
        "date": datetime.now().isoformat(),
        "title": title,
        "url": url,
        "site": SITE_DOMAIN
    })
    
    # الاحتفاظ بآخر 100 مقال فقط
    if len(stats["posts"]) > 100:
        stats["posts"] = stats["posts"][-100:]
    
    with open(stats_file, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    
    print(f"📊 إجمالي المقالات المنشورة: {stats['total_published']}")

def main():
    print(f"--- بدء تشغيل الروبوت الناشر v34 Optimized لموقع {SITE_DOMAIN} ---")
    
    # وضع الاختبار
    if TEST_MODE:
        print("🧪 وضع الاختبار مُفعّل - سيتم إيقاف النشر الفعلي")
    
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
        if image1_data['alt']:
            print(f"      Alt: {image1_data['alt'][:50]}...")
    if image2_data:
        print(f"--- 🖼️ الصورة الثانية: {image2_data['url'][:60]}...")
        if image2_data['alt']:
            print(f"      Alt: {image2_data['alt'][:50]}...")
    
    if not image1_data:
        print("--- ⚠️ لم يتم العثور على صور صالحة للمقال!")
    
    original_content_html = ""
    if 'content' in post_to_publish and post_to_publish.content:
        original_content_html = post_to_publish.content[0].value
    else:
        original_content_html = post_to_publish.summary

    image1_alt = image1_data['alt'] if image1_data else ""
    image2_alt = image2_data['alt'] if image2_data else ""
    
    rewritten_data = rewrite_content_with_gemini(
        original_title, original_content_html, original_link, image1_alt, image2_alt
    )
    
    if rewritten_data:
        final_title = rewritten_data["title"]
        ai_content = rewritten_data["content"]
        ai_tags = rewritten_data.get("tags", [])
        caption1 = rewritten_data.get("caption1", "")
        caption2 = rewritten_data.get("caption2", "")
        
        full_html_content = prepare_html_with_multiple_images_and_ctas(
            ai_content, image1_data, image2_data, original_link, original_title, caption1, caption2
        )
        print("--- ✅ تم إعداد المحتوى المُحسّن مع الصور وDouble CTA.")
    else:
        print("--- ⚠️ سيتم استخدام المحتوى الأصلي.")
        final_title = original_title
        ai_tags = []
        
        if image1_data:
            alt1 = f"{image1_data['alt']} | {SITE_DOMAIN}" if image1_data['alt'] else f"Recipe image | {SITE_DOMAIN}"
            image1_html = f'<img src="{image1_data["url"]}" alt="{alt1}">'
            caption1 = f"<p><em>{alt1}</em></p>"
        else:
            image1_html = ""
            caption1 = ""
        
        mid_cta = f'<p><em>👉 See the full recipe at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a></em></p>'
        
        if image2_data and image2_data['url'] != image1_data.get('url', ''):
            alt2 = f"{image2_data['alt']} | {SITE_DOMAIN}" if image2_data['alt'] else f"Recipe detail | {SITE_DOMAIN}"
            image2_html = f'<br><img src="{image2_data["url"]}" alt="{alt2}">'
            caption2 = f"<p><em>{alt2}</em></p>"
        else:
            image2_html = ""
            caption2 = ""
        
        final_cta = f'<br><p><strong>Get the complete recipe with all ingredients and instructions at <a href="{original_link}" rel="noopener" target="_blank">{SITE_DOMAIN}</a>.</strong></p>'
        
        full_html_content = image1_html + caption1 + mid_cta + original_content_html + image2_html + caption2 + final_cta

    # في وضع الاختبار، نتوقف هنا
    if TEST_MODE:
        print("🧪 وضع الاختبار: توقف قبل النشر الفعلي")
        print(f"    📝 العنوان: {final_title}")
        return

    # --- النشر على Medium ---
    sid_cookie = os.environ.get("MEDIUM_SID_COOKIE")
    uid_cookie = os.environ.get("MEDIUM_UID_COOKIE")
    
    if not sid_cookie or not uid_cookie:
        print("!!! خطأ: لم يتم العثور على الكوكيز.")
        return

    options = webdriver.FirefoxOptions() # التغيير هنا
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    service = FirefoxService(GeckoDriverManager().install()) # التغيير هنا
    driver = webdriver.Firefox(service=service, options=options) # التغيير هنا
    
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
        
        print("--- 4. كتابة العنوان...")
        title_field = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'h3[data-testid="editorTitleParagraph"]')
        ))
        title_field.click()
        title_field.send_keys(final_title)
        
        print("--- 5. إدراج المحتوى مع الصور وCTAs...")
        story_field = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'p[data-testid="editorParagraphText"]')
        ))
        story_field.click()
        
        js_script = """
        const html = arguments[0];
        const blob = new Blob([html], { type: 'text/html' });
        const item = new ClipboardItem({ 'text/html': blob });
        navigator.clipboard.write([item]);
        """
        driver.execute_script(js_script, full_html_content)
        story_field.send_keys(Keys.CONTROL, 'v')
        
        print("--- ⏳ انتظار رفع الصور...")
        time.sleep(12)
        
        # حفظ لقطة شاشة للمحتوى
        driver.save_screenshot("content_ready.png")
        print("    📸 تم حفظ لقطة شاشة للمحتوى")
        
        print("--- 6. بدء النشر (فتح نافذة الخيارات)...")
        publish_button = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, 'button[data-action="show-prepublish"]')
        ))
        publish_button.click()
        
        # انتظار ظهور نافذة النشر
        time.sleep(3)
        
        # حفظ لقطة شاشة لنافذة النشر
        driver.save_screenshot("publish_dialog.png")
        print("    📸 تم حفظ لقطة شاشة لنافذة النشر")
        
        print("--- 7. التأكد من اختيار 'النشر الفوري'...")
        ensure_publish_now_selected(driver)
        
        # النشر النهائي بمحاولات محسّنة
        print("--- 8. النشر النهائي...")
        publish_result = publish_with_optimized_attempts(driver, wait)
        
        print("--- 9. انتظار معالجة النشر...")
        time.sleep(20)  # انتظار أطول للتأكد من إتمام العملية
        
        # حفظ لقطة شاشة نهائية
        driver.save_screenshot("final_result.png")
        print("    📸 تم حفظ لقطة شاشة نهائية")
        
        # التحقق من نجاح النشر
        current_url = driver.current_url
        if "published" in current_url or "@" in current_url or "/p/" in current_url:
            print(f"--- ✅✅✅ تأكيد: تم النشر بنجاح! URL: {current_url}")
            
            # تسجيل الإحصائيات
            log_success_stats(final_title, current_url)
        
        add_posted_link(post_to_publish.link)
        print(f">>> 🎉🎉🎉 تم نشر المقال بنجاح على {SITE_DOMAIN}! 🎉🎉🎉")
        
    except Exception as e:
        print(f"!!! حدث خطأ فادح أثناء عملية النشر: {e}")
        driver.save_screenshot("error_screenshot.png")
        with open("error_page_source.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("--- تم حفظ لقطة الشاشة وHTML للمراجعة")
    finally:
        driver.quit()
        print("--- تم إغلاق الروبوت ---")

if __name__ == "__main__":
    main()
