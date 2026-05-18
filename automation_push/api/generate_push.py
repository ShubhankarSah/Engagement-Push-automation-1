import requests
from bs4 import BeautifulSoup
import json
import os
import google.generativeai as genai
from http.server import BaseHTTPRequestHandler


# ── Scraper ───────────────────────────────────────────────────────────────────

def get_todays_current_affairs():
    """Scrapes today's current affairs from StudyIQ."""
    url = "https://www.studyiq.com/articles/current-affairs/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    articles = soup.find_all('article')
    if not articles:
        articles = soup.select('div.post, div.type-post, li.lcp_catlist_item')

    scraped_data = []

    for article in articles[:5]:
        link_tag = article.find('a', href=True)
        if not link_tag:
            continue

        article_url = link_tag['href']
        if not article_url.startswith('http'):
            continue

        try:
            art_response = requests.get(article_url, headers=headers)
            if art_response.status_code == 200:
                art_soup = BeautifulSoup(art_response.text, 'html.parser')

                og_image = art_soup.find('meta', property='og:image')
                img_url = og_image['content'] if og_image else None

                if not img_url:
                    img_tag = art_soup.find('img', class_=lambda c: c and 'wp-post-image' in c)
                    img_url = img_tag['src'] if img_tag else None

                h1_tag = art_soup.find('h1')
                heading = h1_tag.text.strip() if h1_tag else None

                if heading and img_url:
                    scraped_data.append({
                        "heading": heading,
                        "image_link": img_url,
                        "article_url": article_url
                    })
        except Exception as e:
            print(f"Failed to fetch details for {article_url}: {e}")

    return scraped_data


# ── Gemini ────────────────────────────────────────────────────────────────────

def evaluate_and_generate_copy(scraped_data):
    """Sends data to Gemini to select the best article and write push copy."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})

    prompt = f"""
    You are an expert UPSC strategist and a master copywriter for EdTech.
    I have scraped the latest daily current affairs from our platform.
    
    Here is the data:
    {json.dumps(scraped_data, indent=2)}
    
    Task:
    1. Evaluate the provided current affairs and pick the SINGLE most engaging and relevant topic for a UPSC aspirant. Focus on high-impact topics (e.g., International Relations, Economy, major polity events).
    2. The selected heading will typically have two parts separated by a colon (":"). Use the part BEFORE the colon as the basis for the Title, and the part AFTER the colon as the basis for the Description.
    3. Write an ultra-engaging push notification Title (maximum 40 characters) optimized for high CTR among UPSC aspirants.
       The title should:
       * Create curiosity, urgency, FOMO, or exam relevance
       * Sound like a high-performing growth marketing notification, NOT a news headline
       * Use psychologically strong hooks such as: "Important for UPSC", "Don't Miss", "Explained", "Can Be Asked", "Everyone's Reading", "UPSC Alert", "Must Revise"
       * Prefer short, punchy wording with emotional triggers
       * don't use emojis
       * Avoid generic or formal language
    4. Write a compelling push notification Description (maximum 120 characters) optimized to maximize opens and induce curiosity/FOMO.
       The description should:
       * Make the user feel they might miss an important UPSC topic if they ignore it
       * Emphasize Prelims/Mains relevance whenever applicable
       * Create an "I should check this now" feeling
       * Use conversational, engaging wording instead of informational summaries
       * Sound like top-performing EdTech/growth notifications
       * Avoid clickbait that feels fake or spammy
       * Keep the tone smart, urgent, and aspirant-focused
       * Do NOT use any short forms and absolutely NO emojis. I need just the text words.
       * If there is no colon in the original heading, intelligently split the title yourself into a short catchy Title and an engaging Description following these rules.
    
    Respond strictly in valid JSON format with exactly these keys:
    {{
        "selected_heading": "The original heading of the selected topic",
        "image_link": "The original image link of the selected topic",
        "push_title": "Your generated title",
        "push_description": "Your generated description"
    }}
    """

    try:
        clean_prompt = prompt.encode('utf-8', 'ignore').decode('utf-8')
        response = model.generate_content(clean_prompt)
        output_text = response.text.strip()

        if output_text.startswith("```json"):
            output_text = output_text[7:-3]
        elif output_text.startswith("```"):
            output_text = output_text[3:-3]
        parsed_json = json.loads(output_text)

        if "push_title" in parsed_json:
            parsed_json["push_title"] = parsed_json["push_title"].encode("ascii", "ignore").decode("ascii")
        if "push_description" in parsed_json:
            parsed_json["push_description"] = parsed_json["push_description"].encode("ascii", "ignore").decode("ascii")

        return parsed_json
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return None


# ── Google Sheets ──────────────────────────────────────────────────────────────

def update_google_sheet(result):
    """Updates only title, image_link, TE1, MS1 of the PUSH 1 row in Google Sheets."""
    try:
        apps_script_url = os.getenv("APPS_SCRIPT_URL")

        payload = {
            "action": "update",
            "id": "PUSH 1",
            "title": result.get("selected_heading"),
            "image_link": result.get("image_link"),
            "TE1": result.get("push_title"),
            "MS1": result.get("push_description")
            # CTA1 and link are intentionally omitted — Apps Script leaves them as-is
        }

        response = requests.post(apps_script_url, json=payload, timeout=15)
        if response.status_code == 200:
            return response.json().get("status") == "Success"
        return False
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        return False


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline():
    data = get_todays_current_affairs()
    if not data:
        return {"error": "No articles found"}, 404

    result = evaluate_and_generate_copy(data)
    if not result:
        return {"error": "Failed to generate copy"}, 500

    sheet_success = update_google_sheet(result)
    result["sheet_status"] = "Updated PUSH 1 row successfully" if sheet_success else "Failed to update sheet"
    return result, 200


# ── Vercel Handler ─────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result, status_code = run_pipeline()
        body = json.dumps(result).encode()
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.do_GET()
