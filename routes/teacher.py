import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from utils.auth import role_required
from utils.db import get_db
from utils.face import match_faces_in_group
import gc

teacher_bp = Blueprint("teacher", __name__)

@teacher_bp.before_request
@role_required('teacher')
def check_teacher():
    pass

@teacher_bp.route("/dashboard")
def dashboard():
    db = get_db()
    email = session.get("user")
    teacher = db.teachers.find_one({"email": email})
    
    assigned_subjects = []
    if teacher and "subjects" in teacher:
        for ds in teacher["subjects"]:
            cls_info = db.classes.find_one({"_id": ds["class_id"]})
            class_name = cls_info["name"] if cls_info else "Unknown Class"
            subj_info = next((s for s in cls_info.get("subjects", []) if s["subject_id"] == ds["subject_id"]), None)
            total_lec = subj_info.get("total_lectures", 0) if subj_info else 0
            
            assigned_subjects.append({
                "class_id": ds["class_id"], "subject_id": ds["subject_id"],
                "name": ds["name"], "class_name": class_name, "total_lectures": total_lec
            })
            
    return render_template("teacher/dashboard.html", teacher=teacher, subjects=assigned_subjects)

@teacher_bp.route("/attendance", methods=["GET", "POST"])
def setup_attendance():
    db = get_db()
    email = session.get("user")
    teacher = db.teachers.find_one({"email": email})
    
    if request.method == "POST":
        combined_id = request.form.get("subject_id", "")
        if "|" not in combined_id:
            flash("Session error: Invalid course selection.", "error")
            return redirect(request.url)
            
        class_id, subject_id = combined_id.split("|")
        date_str = request.form.get("date", datetime.date.today().isoformat())
        group_photo = request.files.get("group_photo")
        
        if not group_photo or group_photo.filename == "":
            flash("Upload failure. Group photo missing.", "error")
            return redirect(request.url)

        # Retrieve student markers for this class using projection to save RAM
        students = list(db.students.find({"class_id": class_id}, {"roll_no": 1, "encodings": 1}))
        if not students:
            flash("No students found in this class.", "error")
            return redirect(request.url)
            
        db_encodings = {s["roll_no"]: s.get("encodings", []) for s in students}
            
        # Run ML Inference (InsightFace ONNX Backend)
        # Adaptive scanning returns (results, error_msg)
        img_bytes = group_photo.read()
        identified_rolls, error_msg = match_faces_in_group(img_bytes, db_encodings, tolerance=0.95)
        
        if error_msg:
            flash(f"Vision Engine Notice: {error_msg}", "error")
            return redirect(request.url)
            
        del img_bytes
        del students
        del db_encodings
        gc.collect()
        
        # Temporary storage in session for review step
        session["review_att"] = {
            "class_id": class_id, "subject_id": subject_id,
            "date": date_str, "present_rolls": identified_rolls
        }
        return redirect(url_for("teacher.review_attendance"))
        
    return render_template("teacher/setup_attendance.html", teacher=teacher)

@teacher_bp.route("/attendance/review", methods=["GET", "POST"])
def review_attendance():
    if "review_att" not in session:
        return redirect(url_for("teacher.dashboard"))
        
    att_data = session["review_att"]
    db = get_db()
    
    if request.method == "POST":
        final_present = request.form.getlist("present_rolls")
        
        # Save record
        db.attendance.insert_one({
            "date": att_data["date"], "class_id": att_data["class_id"],
            "subject_id": att_data["subject_id"], "teacher_email": session.get("user"),
            "present_roll_nos": final_present, "created_at": datetime.datetime.utcnow()
        })
        
        # Update lecture count
        db.classes.update_one(
            {"_id": att_data["class_id"], "subjects.subject_id": att_data["subject_id"]},
            {"$inc": {"subjects.$.total_lectures": 1}}
        )
        
        session.pop("review_att")
        flash(f"Success! Attendance recorded for {len(final_present)} students.", "success")
        return redirect(url_for("teacher.dashboard"))
        
    # Sort students by roll no for an easier review view
    students = list(db.students.find({"class_id": att_data["class_id"]}, {"roll_no": 1, "name": 1}).sort("roll_no", 1))
    return render_template("teacher/review_attendance.html", data=att_data, students=students)

@teacher_bp.route("/reports")
def reports():
    db = get_db()
    email = session.get("user")
    logs = list(db.attendance.find({"teacher_email": email}).sort("date", -1))
    
    # Pre-fetch classes to avoid O(N) database queries
    classes_dict = {str(c['_id']): c for c in db.classes.find()}
    
    for log in logs:
        cls_info = classes_dict.get(str(log["class_id"]))
        log["class_name"] = cls_info["name"] if cls_info else "Deleted Class"
        if cls_info:
            subj_info = next((s for s in cls_info.get("subjects", []) if str(s["subject_id"]) == str(log["subject_id"])), None)
            log["subject_name"] = subj_info["name"] if subj_info else "Deleted Subject"
        log["present_count"] = len(log.get("present_roll_nos", []))
            
    return render_template("teacher/reports.html", logs=logs)

@teacher_bp.route("/attendance/delete/<att_id>", methods=["POST"])
def delete_attendance(att_id):
    db = get_db()
    from bson.objectid import ObjectId
    
    record = db.attendance.find_one({"_id": ObjectId(att_id)})
    if not record:
        flash("Attendance record not found.", "error")
        return redirect(url_for("teacher.reports"))
        
    if record["teacher_email"] != session.get("user"):
        flash("Unauthorized action.", "error")
        return redirect(url_for("teacher.reports"))
        
    # Remove record
    db.attendance.delete_one({"_id": ObjectId(att_id)})
    
    # Decrease total_lectures but block at zero (Security check)
    db.classes.update_one(
        {"_id": record["class_id"], "subjects.subject_id": record["subject_id"]},
        {"$inc": {"subjects.$.total_lectures": -1}}
    )
    
    # Secondary cleanup: Ensure it didn't go negative (MongoDB 4.2+ doesn't support $max in atomic $inc logic easily without expressions)
    # We'll just do a quick fix-up if it hit -1
    db.classes.update_one(
        {"_id": record["class_id"], "subjects.subject_id": record["subject_id"], "subjects.total_lectures": {"$lt": 0}},
        {"$set": {"subjects.$.total_lectures": 0}}
    )
    
    flash("Session removed and lecture count updated.", "success")
    return redirect(url_for("teacher.reports"))
