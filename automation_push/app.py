import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json
import os
import google.generativeai as genai
from flask import Flask, jsonify
from dotenv import load_dotenv

load_dotenv()  # Loads variables from .env file

app = Flask(__name__)

def get_todays_current_affairs():
    """Scrapes today's current affairs from StudyIQ."""
    url = "https://www.studyiq.com/articles/current-affairs/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to fetch {url}")
        return []
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # StudyIQ is a WordPress site, typically using <article> tags or specific wrapper classes
    articles = soup.find_all('article')
    if not articles:
        # Fallback if the theme uses a generic div
        articles = soup.select('div.post, div.type-post, li.lcp_catlist_item')

    today_str = datetime.now().strftime("%b %d, %Y") # Example format, adjust if StudyIQ date format varies
    # Actually, a more robust way for automation without strict date-text matching 
    # is to fetch the top N latest articles, as 'today's' are always first.
    # For this script, we'll fetch the first 5 articles to send to ChatGPT
    # ChatGPT can evaluate based on relevance.
    
    scraped_data = []
    
    for article in articles[:5]: # Get top 5 recent articles
        # Find the article link
        link_tag = article.find('a', href=True)
        if not link_tag:
            continue
            
        article_url = link_tag['href']
        if not article_url.startswith('http'):
            continue
            
        # Fetch the individual article page to get high-res image and proper title
        try:
            art_response = requests.get(article_url, headers=headers)
            if art_response.status_code == 200:
                art_soup = BeautifulSoup(art_response.text, 'html.parser')
                
                # Extract high-res image from meta og:image
                og_image = art_soup.find('meta', property='og:image')
                img_url = og_image['content'] if og_image else None
                
                if not img_url:
                    # fallback to first large image
                    img_tag = art_soup.find('img', class_=lambda c: c and 'wp-post-image' in c)
                    img_url = img_tag['src'] if img_tag else None
                        
                # Extract proper title from h1
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
       * Use psychologically strong hooks such as: “Important for UPSC”, “Don’t Miss”, “Explained”, “Can Be Asked”, “Everyone’s Reading”, “UPSC Alert”, “Must Revise”
       * Prefer short, punchy wording with emotional triggers
       * don't use emojis
       * Avoid generic or formal language
    4. Write a compelling push notification Description (maximum 120 characters) optimized to maximize opens and induce curiosity/FOMO.
       The description should:
       * Make the user feel they might miss an important UPSC topic if they ignore it
       * Emphasize Prelims/Mains relevance whenever applicable
       * Create an “I should check this now” feeling
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
        # Sanitize the prompt to remove any weird unicode surrogates coming from the scraped text
        clean_prompt = prompt.encode('utf-8', 'ignore').decode('utf-8')
        response = model.generate_content(clean_prompt)
        output_text = response.text.strip()
        
        # Clean markdown code blocks if Gemini returns them
        if output_text.startswith("```json"):
            output_text = output_text[7:-3]
        elif output_text.startswith("```"):
            output_text = output_text[3:-3]
        parsed_json = json.loads(output_text)
        
        # Forcefully strip out any stubborn emojis that Gemini hallucinated
        if "push_title" in parsed_json:
            parsed_json["push_title"] = parsed_json["push_title"].encode("ascii", "ignore").decode("ascii")
        if "push_description" in parsed_json:
            parsed_json["push_description"] = parsed_json["push_description"].encode("ascii", "ignore").decode("ascii")
            
        return parsed_json
    except Exception as e:
        print(f"Error calling Gemini: {e}")
        return None

def append_to_google_sheet(result, scraped_data):
    """Updates specific columns of the 'PUSH 1' row in Google Sheets via Google Apps Script Web App.
    Only title, image_link, TE1, and MS1 are overwritten; all other columns remain unchanged.
    """
    try:
        # Apps Script Web App URL
        apps_script_url = os.getenv("APPS_SCRIPT_URL")

        # Target "PUSH 1" row — only the four dynamic columns will be overwritten
        push_id = "PUSH 1"

        # action="update" tells the Apps Script to locate the row by id
        # and patch ONLY the specified columns, leaving CTA1, link, etc. untouched.
        payload = {
            "action": "update",                          # Tells Apps Script to update, not append
            "id": push_id,                               # A: id — used to locate the correct row
            "title": result.get("selected_heading"),     # B: title  → selected_heading
            "image_link": result.get("image_link"),      # C: image_link → image_link
            "TE1": result.get("push_title"),             # D: TE1   → push_title
            "MS1": result.get("push_description")        # E: MS1   → push_description
            # CTA1 (F) and link (G) are intentionally omitted — Apps Script will leave them as-is
        }

        # Send the POST request to Google Apps Script
        print(f"Sending update payload to Google Apps Script: {json.dumps(payload, indent=2)}")
        response = requests.post(apps_script_url, json=payload, timeout=15)
        
        if response.status_code == 200:
            response_json = response.json()
            if response_json.get("status") == "Success":
                print("Successfully updated PUSH 1 row in Google Sheet!")
                return True
            else:
                print(f"Apps Script reported failure: {response_json.get('error')}")
                return False
        else:
            print(f"Failed to connect to Apps Script. Status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error updating Google Sheet: {e}")
        return False

@app.route('/generate-push', methods=['GET', 'POST'])
def generate_push_api():
    print("Scraping StudyIQ...")
    data = get_todays_current_affairs()
    
    if data:
        print(f"Found {len(data)} articles. Evaluating with Gemini...")
        result = evaluate_and_generate_copy(data)
        
        if result:
            print("\n--- FINAL OUTPUT FOR N8N / GOOGLE SHEETS ---")
            print(json.dumps(result, indent=2))
            
            # Update specific columns of PUSH 1 row in Google Sheet
            sheet_success = append_to_google_sheet(result, data)
            if sheet_success:
                result["sheet_status"] = "Updated PUSH 1 row successfully"
            else:
                result["sheet_status"] = "Failed to update sheet"
                
            return jsonify(result), 200
        else:
            print("Failed to generate copy.")
            return jsonify({"error": "Failed to generate copy"}), 500
    else:
        print("No articles found.")
        return jsonify({"error": "No articles found"}), 404

if __name__ == "__main__":
    print("Starting Flask API Server on port 5001...")
    app.run(host="0.0.0.0", port=5001)
