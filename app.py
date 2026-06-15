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

def generate_ai_reply(incoming_email_text, sender_name):
    # Using deepseek-v4-pro for the best intelligence and reasoning
    model_name = "deepseek-ai/deepseek-v4-pro"
    
    system_prompt = f"""You are an intelligent and professional AI assistant managing email replies for {SENDER_NAME}.
You will receive an email from a customer or lead. Your job is to write a polite, professional, and highly contextual reply.
Keep the reply concise, persuasive, and to the point.
Do not include subject lines or headers in your output, just the body of the email.
End the email with a professional sign-off from {SENDER_NAME}."""

    user_prompt = f"Here is the email from {sender_name}:\n\n{incoming_email_text}\n\nPlease generate a professional reply."

    try:
        completion = client.chat.completions.create(
            model=model_name,
            messages=[{"role":"system","content":system_prompt}, {"role":"user","content":user_prompt}],
            temperature=0.6,
            max_tokens=1024
        )
        return completion.choices[0].message.content
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
            
            # Generate AI Draft
            ai_draft = generate_ai_reply(text_body, from_name)
            
            if ai_draft:
                print("Generated AI Draft, saving to Google Sheets Inbox...")
                try:
                    sheet = get_google_sheet("Inbox")
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sheet.append_row([timestamp, from_email, from_name, text_body, ai_draft, "Pending"])
                    print("✅ Saved to Google Sheets Inbox.")
                except Exception as sheet_e:
                    print(f"❌ Failed to save to sheet: {sheet_e}")
                    # Fallback to sending immediately if sheet fails? No, keep it failed to avoid duplicate chaos
            
    except Exception as e:
        print(f"Webhook processing error: {e}")
        
    return jsonify({"status": "success", "message": "Webhook processed successfully"}), 200

@app.route('/', methods=['GET'])
def home():
    return "GrowthFlow AI Webhook Server is Running and listening for emails!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
