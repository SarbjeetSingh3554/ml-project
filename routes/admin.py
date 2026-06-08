import os
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from utils.auth import role_required
from utils.db import get_db
from utils.face import extract_face_encodings
import uuid
import cloudinary.uploader
import io
import gc

admin_bp = Blueprint("admin", __name__)

@admin_bp.before_request
@role_required('admin')
def check_admin():
    pass

@admin_bp.route("/dashboard")
def dashboard():
    db = get_db()
    students_count = db.students.count_documents({})
    teachers_count = db.teachers.count_documents({})
    classes_count = db.classes.count_documents({})
    return render_template("admin/dashboard.html", sc=students_count, tc=teachers_count, cc=classes_count)

# --- Teacher Management ---
@admin_bp.route("/teachers", methods=["GET", "POST"])
def manage_teachers():
    db = get_db()
    if request.method == "POST":
        email = request.form.get("email").strip().lower()
        name = request.form.get("name").strip()
        
        if db.teachers.find_one({"email": email}):
            flash("Teacher email already exists", "error")
        else:
            db.teachers.insert_one({"email": email, "name": name, "subjects": []})
            flash("Teacher account created successfully", "success")
        return redirect(url_for("admin.manage_teachers"))
        
    teachers = list(db.teachers.find())
    return render_template("admin/teachers.html", teachers=teachers)

# --- Class & Subject Management ---
@admin_bp.route("/classes", methods=["GET", "POST"])
def manage_classes():
    db = get_db()
    if request.method == "POST":
        class_name = request.form.get("class_name").strip()
        if db.classes.find_one({"name": class_name}):
            flash("Class already exists", "error")
        else:
            db.classes.insert_one({"_id": str(uuid.uuid4()), "name": class_name, "subjects": []})
            flash("Class added to system", "success")
        return redirect(url_for("admin.manage_classes"))
        
    classes = list(db.classes.find())
    teachers = list(db.teachers.find())
    return render_template("admin/classes.html", classes=classes, teachers=teachers)

@admin_bp.route("/classes/<class_id>/subjects", methods=["POST"])
def add_subject(class_id):
    db = get_db()
    subject_name = request.form.get("subject_name").strip()
    teacher_email = request.form.get("teacher_email", "").strip()
    
    cls = db.classes.find_one({"_id": class_id})
    if not cls:
        return redirect(url_for("admin.manage_classes"))

    existing_subj = next((s for s in cls.get("subjects", []) if s.get("name").lower() == subject_name.lower()), None)

    if existing_subj:
        # Update existing subject's teacher
        subject_id = existing_subj.get("subject_id")
        old_teacher = existing_subj.get("teacher_email")
        
        if old_teacher and old_teacher != teacher_email:
            db.teachers.update_one({"email": old_teacher}, {"$pull": {"subjects": {"class_id": class_id, "subject_id": subject_id}}})
            
        if teacher_email and old_teacher != teacher_email:
            db.teachers.update_one({"email": teacher_email}, {"$push": {"subjects": {"class_id": class_id, "subject_id": subject_id, "name": existing_subj.get("name")}}})
            
        db.classes.update_one({"_id": class_id, "subjects.subject_id": subject_id}, {"$set": {"subjects.$.teacher_email": teacher_email}})
        flash(f"Subject '{subject_name}' teacher mapping updated.", "success")
    else:
        # Create new subject
        subject_id = str(uuid.uuid4())
        subject = {"subject_id": subject_id, "name": subject_name, "teacher_email": teacher_email, "total_lectures": 0}
        db.classes.update_one({"_id": class_id}, {"$push": {"subjects": subject}})
        if teacher_email:
            db.teachers.update_one({"email": teacher_email}, {"$push": {"subjects": {"class_id": class_id, "subject_id": subject_id, "name": subject_name}}})
        flash("New subject linked to class", "success")
        
    return redirect(url_for("admin.manage_classes"))

@admin_bp.route("/classes/delete/<class_id>", methods=["POST"])
def delete_class(class_id):
    db = get_db()
    # Unbind subjects from teachers first
    cls = db.classes.find_one({"_id": class_id})
    if cls and "subjects" in cls:
        for sub in cls["subjects"]:
            if sub.get("teacher_email"):
                db.teachers.update_one(
                    {"email": sub["teacher_email"]},
                    {"$pull": {"subjects": {"class_id": class_id, "subject_id": sub["subject_id"]}}}
                )
    db.classes.delete_one({"_id": class_id})
    db.students.delete_many({"class_id": class_id}) # Remove students in that class
    flash("Class and associated data removed.", "success")
    return redirect(url_for("admin.manage_classes"))

@admin_bp.route("/classes/<class_id>/subjects/delete/<subject_id>", methods=["POST"])
def delete_subject(class_id, subject_id):
    db = get_db()
    cls = db.classes.find_one({"_id": class_id})
    if not cls: return redirect(url_for("admin.manage_classes"))
    
    sub = next((s for s in cls.get("subjects", []) if s["subject_id"] == subject_id), None)
    if sub and sub.get("teacher_email"):
        db.teachers.update_one(
            {"email": sub["teacher_email"]},
            {"$pull": {"subjects": {"class_id": class_id, "subject_id": subject_id}}}
        )
    
    db.classes.update_one({"_id": class_id}, {"$pull": {"subjects": {"subject_id": subject_id}}})
    flash("Subject removed from class.", "success")
    return redirect(url_for("admin.manage_classes"))

@admin_bp.route("/teachers/delete/<email>", methods=["POST"])
def delete_teacher(email):
    db = get_db()
    # Unbind from subjects first to prevent orphans
    db.classes.update_many(
        {"subjects.teacher_email": email},
        {"$set": {"subjects.$.teacher_email": ""}}
    )
    db.teachers.delete_one({"email": email})
    flash("Teacher removed from system.", "success")
    return redirect(url_for("admin.manage_teachers"))

# --- Student Management ---
@admin_bp.route("/students", methods=["GET", "POST"])
def manage_students():
    db = get_db()
    if request.method == "POST":
        roll_no = request.form.get("roll_no").strip()
        name = request.form.get("name").strip()
        email = request.form.get("email").strip().lower()
        class_id = request.form.get("class_id").strip()
        photos = request.files.getlist("photos") # Limit to max 5

        if db.students.find_one({"roll_no": roll_no}):
            flash("Roll number already registered.", "error")
            return redirect(url_for("admin.manage_students"))
            
        encodings = []
        image_urls = []
        
        print(f"INFO: Processing enrollment for {name} ({roll_no}) with {len(photos)} photos.")
        
        for i, file in enumerate(photos[:5]):
            if file and file.filename != '':
                image_bytes = file.read()
                print(f"DEBUG: Photo {i+1} received. Size: {len(image_bytes)} bytes.")
                try:
                    # ML Extraction (InsightFace SCRFD)
                    encs = extract_face_encodings(image_bytes)
                    if encs:
                        encodings.append(encs[0])
                        print(f"DEBUG: Photo {i+1} - Face detected and encoded. (Current Total: {len(encodings)})")
                        
                        # Cloudinary Proof Storage
                        try:
                            upload_res = cloudinary.uploader.upload(io.BytesIO(image_bytes), folder=f"attendance/students/{roll_no}")
                            image_urls.append(upload_res.get("secure_url"))
                            print(f"DEBUG: Photo {i+1} - Uploaded to Cloudinary.")
                        except Exception as cloud_err:
                            print(f"ERROR: Cloudinary Upload Failed for photo {i+1}: {cloud_err}")
                    else:
                        print(f"WARNING: Photo {i+1} - No face detected.")
                except Exception as e:
                    print(f"ERROR: Processing photo {i+1} failed: {e}")
                finally:
                    del image_bytes
                    gc.collect()
        
        if not encodings:
            print(f"ERROR: Enrollment failed for {roll_no}. Zero face encodings captured from {len(photos)} photos.")
            flash("Failed to capture any face embeddings. Use clearer photos.", "error")
            return redirect(url_for("admin.manage_students"))
            
        db.students.insert_one({
            "roll_no": roll_no, "name": name, "email": email,
            "class_id": class_id, "encodings": encodings, "image_urls": image_urls
        })
        flash(f"Student '{name}' added successfully.", "success")
        return redirect(url_for("admin.manage_students"))
        
    students = list(db.students.find())
    classes = list(db.classes.find())
    # Map class IDs to names for cleaner UI display
    class_map = {str(c['_id']): c['name'] for c in classes}
    for stu in students:
        stu['class_name'] = class_map.get(str(stu.get('class_id', '')), "Unassigned")

    return render_template("admin/students.html", students=students, classes=classes)

@admin_bp.route("/students/delete/<roll_no>", methods=["POST"])
def delete_student(roll_no):
    db = get_db()
    db.students.delete_one({"roll_no": roll_no})
    flash("Student removed successfully.", "success")
    return redirect(url_for("admin.manage_students"))
