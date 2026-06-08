import os
import json
import urllib.request
import urllib.error
from functools import wraps
from flask import session, redirect, url_for, flash

# Admin configuration explicitly decoupling arrays from raw code directly onto safe scalable Environmental blocks
def get_admins():
    """
    Returns the list of admin emails from the ENV variable.
    """
    raw_admins = os.getenv("ADMIN_EMAILS", "rk844304@gmail.com,raj05062005@gmail.com")
    return [email.strip().lower() for email in raw_admins.split(",") if email.strip()]

def get_user_role(email, db):
    """
    Determines user role based on email lookup.
    """
    email = email.lower()
    if email in get_admins():
        return "admin"
    if db.teachers.find_one({"email": email}):
        return "teacher"
    if db.students.find_one({"email": email}):
        return "student"
    return None

def send_otp_email(user_email, otp):
    """
    Sends 6-digit OTP using Brevo (Sendinblue) Web API v3.
    Bypasses Port 465/587 blocks on Railway by using Port 443 (HTTPS).
    """
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("MAIL_USER", "raj05062005@gmail.com") 
    
    if not api_key:
        # Check if they are still using the old SENDGRID_API_KEY by mistake
        api_key = os.getenv("SENDGRID_API_KEY")
        if not api_key:
            print(f"CRITICAL: BREVO_API_KEY not found in Railway Variables.")
            print(f"========== [FALLBACK] OTP FOR {user_email}: {otp} ==========")
            return False, "Email Service API Key Missing"

    # Brevo V3 API Endpoint
    url = "https://api.brevo.com/v3/smtp/email"
    
    # Payload for Brevo API
    payload = {
        "sender": {"name": "NIT KKR Attendance", "email": sender_email},
        "to": [{"email": user_email}],
        "subject": "Institutional Verification: OTP Code",
        "htmlContent": f"""
            <html>
                <body style="font-family: Arial, sans-serif; color: #333;">
                    <h2 style="color: #b91c1c;">NIT Kurukshetra Smart Attendance</h2>
                    <p>Your one-time password (OTP) for system access is:</p>
                    <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #d946ef; margin: 20px 0;">
                        {otp}
                    </div>
                    <p>This code is valid for 5 minutes.</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="font-size: 10px; color: #999; text-transform: uppercase;">Biometric Security Gateway | National Institute of Technology</p>
                </body>
            </html>
        """
    }

    headers = {
        "api-key": api_key,
        "content-type": "application/json",
        "accept": "application/json"
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status in [200, 201, 202]:
                print(f"SUCCESS: OTP Delivered via Brevo API to {user_email}")
                return True, "Success"
            else:
                raise Exception(f"Brevo API error: Status {response.status}")
                
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        print(f"FAILED TO SEND EMAIL (Brevo API): {e.code} - {err_body}")
        print(f"========== [FALLBACK] OTP FOR {user_email}: {otp} ==========")
        return False, f"Brevo API Error: {e.code}"
    except Exception as e:
        print(f"SYSTEM OVERHEAD/TIMEOUT (Brevo): {str(e)}")
        print(f"========== [FALLBACK] OTP FOR {user_email}: {otp} ==========")
        return False, "Network Timeout"

# Flask Middleware Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            flash("Log in required to access this portal.", "info")
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user" not in session:
                flash("Log in required to access this portal.", "info")
                return redirect(url_for('auth.login'))
            if session.get("role") != role:
                flash(f"Access Denied. You require {role.capitalize()} privileges.", "error")
                return redirect(url_for('auth.login'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
