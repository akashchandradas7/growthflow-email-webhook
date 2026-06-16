import os
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import random

# ==========================================
# 1. Load Environment Variables
# ==========================================
def load_env(filepath=".env"):
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
REPLY_TO_EMAIL = os.environ.get("REPLY_TO_EMAIL", "hello@support.growthflow.ltd")

# ==========================================
# 2. Google Sheets Setup
# ==========================================
SHEET_LINK = "https://docs.google.com/spreadsheets/d/1rANALl9K97olxQbVP-Bjrhv0aHboIhMzFfiwCgyYFg8/edit"

def get_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json_str:
        import json
        creds_dict = json.loads(creds_json_str)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        # Fallback to local file if running locally
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        
    client = gspread.authorize(creds)
    
    spreadsheet = client.open_by_url(SHEET_LINK)
    main_sheet = spreadsheet.sheet1
    try:
        inbox_sheet = spreadsheet.worksheet("Inbox")
    except:
        inbox_sheet = None
    return main_sheet, inbox_sheet

# ==========================================
# 3. Brevo Email Sending Function
# ==========================================
def send_email_via_brevo(to_email, to_name, subject, html_content):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"name": SENDER_NAME, "email": SENDER_EMAIL},
        "to": [{"email": to_email, "name": to_name}],
        "replyTo": {"email": REPLY_TO_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "htmlContent": html_content
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.status_code in [200, 201, 202]

def get_initial_email_html(name, business_name, industry):
    html = f"""
    <p style="font-family: Arial, sans-serif; font-size: 14px; color: #222222;">
      Hi {name},<br><br>
      We have yet to be properly introduced. I was researching {business_name} and noticed your impressive growth in the {industry} sector.<br><br>
      As founders scale, they often find themselves drowning in operational chaos—too many emails, open loops, and follow-ups. I'm reaching out because GrowthFlow builds custom AI Employees that completely automate this busywork, allowing your team to reclaim their time.<br><br>
      I know you likely already have an operations process in place, but our fully managed AI workforce integrates seamlessly to handle the repetitive tasks that shouldn't be eating up your day. We handle everything from infrastructure to proactive maintenance.<br><br>
      Do you have time over the next week or two to learn more? Let me know what works for you.<br><br>
      Best regards,<br><br>
      <strong>GrowthFlow Team</strong><br>
      <a href="https://growthflow.ltd/" style="color: #1a73e8; text-decoration: none;">growthflow.ltd</a>
    </p>
    """
    return html

def get_followup_email_html(name, business_name, industry):
    html = f"""
    <p style="font-family: Arial, sans-serif; font-size: 14px; color: #222222;">
      Hi {name},<br><br>
      I just wanted to see if you had a chance to read my previous email.<br><br>
      We are helping companies in the {industry} space save countless hours by deploying AI agents that work 24/7 without limits. I'd love to share a quick 3-step strategy on how this could work specifically for {business_name}.<br><br>
      Do you have time over the next week or two for a brief chat? Let me know what works for you.<br><br>
      Best regards,<br><br>
      <strong>GrowthFlow Team</strong><br>
      <a href="https://growthflow.ltd/" style="color: #1a73e8; text-decoration: none;">growthflow.ltd</a>
    </p>
    """
    return html

# ==========================================
# 4. Main Logic
# ==========================================
def main():
    print("Connecting to Google Sheets...")
    sheet, inbox_sheet = get_google_sheets()
def run_outbound_campaign():
    try:
        main_sheet, inbox_sheet = get_google_sheets()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return {"status": "error", "message": f"Failed to connect to Google Sheets: {str(e)}", "traceback": tb}
    
    headers = main_sheet.row_values(1)
    if "Status" not in headers:
        main_sheet.update_cell(1, len(headers) + 1, "Status")
        headers.append("Status")
        
    status_col_idx = headers.index("Status") + 1
    records = main_sheet.get_all_records()
    
    outbound_allowed = True
        
    # Get Replied Emails
    replied_emails = set()
    if inbox_sheet:
        inbox_records = inbox_sheet.get_all_records()
        for r in inbox_records:
            ce = str(r.get("Client Email", "")).strip().lower()
            if ce:
                replied_emails.add(ce)
    
    total_sent = sum(1 for row in records if str(row.get("Status", "")).startswith("Sent"))
    daily_limit = 20 if total_sent < 200 else 50
    
    sent_today = 0
    followups_sent_today = 0
    now = datetime.now()
    
    hooks = ["AI Workflow", "Automate Busywork", "AI Automation", "Scale Effortlessly"]
    
    for index, row in enumerate(records):
        row_num = index + 2
        email = str(row.get("Email", "")).strip()
        if not email: continue
        
        name = row.get("Contact Name", "") or "Valued Client"
        business_name = row.get("Business Name", "") or "your business"
        industry = row.get("Industry", "") or "your"
        status = str(row.get("Status", "")).strip()
        
        # Determine if they replied
        if email.lower() in replied_emails:
            if "Replied" not in status:
                main_sheet.update_cell(row_num, status_col_idx, "Replied")
            continue
            
        # INITIAL EMAIL LOGIC
        if status == "" or status == "None":
            if sent_today >= daily_limit:
                continue
                
            if not outbound_allowed:
                continue
                
            hook = random.choice(hooks)
            subject = f"{hook} + {industry} + {business_name}"
            html_content = get_initial_email_html(name, business_name, industry)
            
            if send_email_via_brevo(email, name, subject, html_content):
                main_sheet.update_cell(row_num, status_col_idx, f"Sent - {now.strftime('%Y-%m-%d %H:%M:%S')}")
                sent_today += 1
            else:
                main_sheet.update_cell(row_num, status_col_idx, "Failed")
                
        # FOLLOW-UP EMAIL LOGIC
        elif status.startswith("Sent - "):
            timestamp_str = status.replace("Sent - ", "").strip()
            try:
                sent_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                if now - sent_time > timedelta(hours=48):
                    hook = random.choice(hooks)
                    subject = f"{hook} + {industry} + {business_name}"
                    html_content = get_followup_email_html(name, business_name, industry)
                    
                    if send_email_via_brevo(email, name, subject, html_content):
                        main_sheet.update_cell(row_num, status_col_idx, f"Followup Sent - {now.strftime('%Y-%m-%d %H:%M:%S')}")
                        followups_sent_today += 1
            except Exception as e:
                pass

    return {
        "status": "success",
        "initial_sent": sent_today,
        "followups_sent": followups_sent_today,
        "total_ever_sent": total_sent + sent_today
    }

if __name__ == "__main__":
    result = run_outbound_campaign()
    print(result)
