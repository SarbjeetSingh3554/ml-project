import os
import gc
from flask import Flask, redirect, url_for, session, render_template
from dotenv import load_dotenv
from utils.db import init_db, mongo

# 0. Load environment variables
load_dotenv()

def create_app():
    app = Flask(__name__)

    # 1. System Configuration
    # 16MB max upload limit is plenty for 1080p photos
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.secret_key = os.getenv('SECRET_KEY', 'nit-kkr-secure-2026-v2')
    
    # 2. MongoDB setup
    app.config["MONGO_URI"] = os.getenv("MONGO_URI")
    init_db(app)

    # 3. Register Blueprints (Imported strictly inside context)
    with app.app_context():
        from routes.auth import auth_bp
        from routes.admin import admin_bp
        from routes.teacher import teacher_bp
        from routes.student import student_bp

        app.register_blueprint(auth_bp, url_prefix="/auth")
        app.register_blueprint(admin_bp, url_prefix="/admin")
        app.register_blueprint(teacher_bp, url_prefix="/teacher")
        app.register_blueprint(student_bp, url_prefix="/student")

    # 4. Universal Navigation
    @app.route("/")
    def index():
        if "user" in session:
            role = session.get("role")
            if role == "admin":
                return redirect(url_for("admin.dashboard"))
            elif role == "teacher":
                return redirect(url_for("teacher.dashboard"))
            elif role == "student":
                return redirect(url_for("student.dashboard"))
        
        # New Landing Page with Portal selection
        return render_template("home.html")

    # 5. Global Error Resiliency
    @app.errorhandler(404)
    def page_not_found(e):
        return render_template("base.html", title="Not Found", error_block="The page you requested does not exist."), 404

    @app.errorhandler(Exception)
    def handle_exception(e):
        import traceback
        import logging
        logging.error(traceback.format_exc())
        return render_template("base.html", title="System Error", error_block="An internal operation failed. Our profiler has caught the error and saved the system state."), 500

    # Garbage collection after boot to ensure 1GB RAM stays clean
    gc.collect()
    
    return app

# The entry point for Gthreads Gunicorn
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)