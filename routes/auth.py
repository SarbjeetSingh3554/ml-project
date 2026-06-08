import random
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from utils.auth import get_user_role, send_otp_email
from utils.db import get_db

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Role can be pre-set from the 3 portals on the home page
    role_target = request.args.get("role", "")
    
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        role_target = request.form.get("role", "")

        db = get_db()
        actual_role = get_user_role(email, db)
        
        # Universal login validation (no @nitkkr.ac.in restriction)
        if not actual_role or (role_target and actual_role != role_target):
            flash(f"Unauthorized. User '{email}' not found or role mismatch for {role_target.capitalize()} portal.", "error")
            return redirect(url_for("auth.login", role=role_target))

        # Generate 6-digit OTP
        otp = str(random.randint(100000, 999999))
        session["pending_email"] = email
        session["pending_otp"] = otp
        session["pending_role"] = actual_role

        # Send OTP with TLS/SSL protection
        success, err_msg = send_otp_email(email, otp)
        if success:
            flash("A 6-digit verification code has been sent to your email.", "info")
        else:
            flash(f"SMTP Server Timeout. OTP (Debug): {otp}. Error: {err_msg}", "error")
            
        return redirect(url_for("auth.verify_otp"))

    return render_template("login.html", role=role_target)

@auth_bp.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if "pending_email" not in session:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        user_otp = request.form.get("otp").strip()
        if user_otp == session.get("pending_otp"):
            # Login successful
            session["user"] = session.pop("pending_email")
            session["role"] = session.pop("pending_role")
            session.pop("pending_otp")
            
            flash("Welcome! You have successfully signed in.", "success")
            
            if session["role"] == "admin":
                return redirect(url_for("admin.dashboard"))
            elif session["role"] == "teacher":
                return redirect(url_for("teacher.dashboard"))
            elif session["role"] == "student":
                return redirect(url_for("student.dashboard"))
        else:
            flash("Invalid or expired verification code. Please try again.", "error")

    return render_template("verify_otp.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("index"))
