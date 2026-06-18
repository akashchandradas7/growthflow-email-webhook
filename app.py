import os
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from openai import OpenAI
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# Load environment variables
def load_env(filepath="../.env"):
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip('"').strip("'")
                    except ValueError:
                        pass

load_env()

BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_NAME = os.environ.get("SENDER_NAME")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
SHEET_LINK = "https://docs.google.com/spreadsheets/d/1rANALl9K97olxQbVP-Bjrhv0aHboIhMzFfiwCgyYFg8/edit"

def get_google_sheet(sheet_name="Inbox"):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Fallback for local testing if running on PC
        creds = ServiceAccountCredentials.from_json_keyfile_name("../credentials.json", scope)
    
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_url(SHEET_LINK)
    
    try:
        sheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")
        sheet.append_row(["Timestamp", "Client Email", "Client Name", "Client Message", "AI Draft", "Status"])
        
    return sheet

# Initialize Nvidia NIM client (OpenAI compatible)
client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = NVIDIA_API_KEY
)

def read_obsidian_brain():
    brain_text = ""
    brain_dir = "GrowthFlow_Brain"
    if os.path.exists(brain_dir):
        for filename in sorted(os.listdir(brain_dir)):
            if filename.endswith(".md"):
                with open(os.path.join(brain_dir, filename), "r", encoding="utf-8") as f:
                    brain_text += f"\n\n--- {filename} ---\n{f.read()}"
    return brain_text

def generate_ai_reply(incoming_email_text, sender_name):
    # Using deepseek-v4-pro for the best intelligence and reasoning
    model_name = "deepseek-ai/deepseek-v4-pro"
    
    brain_knowledge = read_obsidian_brain()
    
    system_prompt = f"""You are an intelligent and professional AI assistant managing email replies for {SENDER_NAME}.
First, you must classify the incoming email. 
We receive many automated emails (Facebook notifications, account verification codes, spam, phishing). You MUST IGNORE these.
You must ONLY reply to legitimate, human-written emails regarding business, inquiries, questions, or responses to our outreach.

Output your response STRICTLY as a JSON object with the following keys:
1. "is_human_business_inquiry": boolean (true if it's a legitimate human business email, false if it's spam, notification, automated, or phishing)
2. "reason": string (brief reason for your classification)
3. "reply_body": string (If true, write a polite, professional, persuasive reply. Do not include subject lines or headers. End with a professional sign-off from {SENDER_NAME}. If false, leave this empty)

IMPORTANT KNOWLEDGE BASE & RULES TO FOLLOW:
{brain_knowledge}
"""

    user_prompt = f"Here is the email from {sender_name}:\n\n{incoming_email_text}\n\nPlease generate the JSON."

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role":"system","content":system_prompt}, {"role":"user","content":user_prompt}],
            temperature=0.3,
            max_tokens=1024,
            response_format={"type": "json_object"}
        )
        content = completion.choices[0].message.content
        # Sometimes models wrap json in markdown block, try to clean it
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
            
        import json
        return json.loads(content)
    except Exception as e:
        print(f"AI Generation Error: {e}")
        return None

def send_reply_via_brevo(to_email, subject, reply_text):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    
    # Format the text with basic HTML line breaks
    formatted_text = reply_text.replace('\n', '<br>')
    html_content = f"<html><body><p>{formatted_text}</p></body></html>"
    
    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": to_email}],
        "replyTo": {"email": "hello@support.growthflow.ltd", "name": SENDER_NAME},
        "subject": f"Re: {subject}",
        "htmlContent": html_content
    }
    
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code in [200, 201]:
        print(f"✅ Auto-Reply successfully sent to {to_email}")
    else:
        print(f"❌ Failed to send reply to {to_email}. Error: {response.text}")

@app.route('/brevo-webhook', methods=['POST'])
def brevo_webhook():
    data = request.json
    print("\n--- New Webhook Received ---")
    
    try:
        # Brevo's inbound webhook usually sends data directly or inside an 'items' array
        items = data.get("items", []) if "items" in data else [data]
            
        for item in items:
            from_email = item.get("From", {}).get("Address", "")
            from_name = item.get("From", {}).get("Name", "Customer")
            subject = item.get("Subject", "Reply")
            
            # Extract text body (fallback to html if text is missing)
            text_body = item.get("TextBody", "") or item.get("RawHtmlBody", "")
            
            # Ignore automated bounces or emails sent by ourselves
            if not from_email or from_email == SENDER_EMAIL:
                continue
                
            print(f"Processing inbound email from {from_email}: {subject}")
            
            # Generate AI Classification & Draft
            ai_response = generate_ai_reply(text_body, from_name)
            
            if ai_response and isinstance(ai_response, dict):
                is_valid = ai_response.get("is_human_business_inquiry", False)
                reason = ai_response.get("reason", "No reason provided")
                reply_body = ai_response.get("reply_body", "")
                
                print(f"AI Classification: Valid={is_valid}, Reason={reason}")
                
                try:
                    sheet = get_google_sheet("Inbox")
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if is_valid and reply_body:
                        # Actually send the email immediately
                        send_reply_via_brevo(from_email, subject, reply_body)
                        status = "Auto-Replied"
                    else:
                        status = f"Filtered: {reason}"
                        
                    sheet.append_row([timestamp, from_email, from_name, text_body, reply_body, status])
                    print(f"✅ Saved to Google Sheets Inbox with status: {status}")
                except Exception as sheet_e:
                    print(f"❌ Failed to save to sheet or send reply: {sheet_e}")
            
    except Exception as e:
        print(f"Webhook processing error: {e}")
        
    return jsonify({"status": "success", "message": "Webhook processed successfully"}), 200

@app.route('/', methods=['GET'])
def home():
    return "GrowthFlow AI Webhook Server is Running and listening for emails!"

import traceback
import send_emails_cloud

@app.route('/trigger-emails', methods=['GET', 'POST'])
def trigger_emails():
    try:
        result = send_emails_cloud.run_outbound_campaign()
        return jsonify(result), 200
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({"status": "error", "message": str(e), "traceback": tb}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
