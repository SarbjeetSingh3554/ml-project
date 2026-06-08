import cv2
import numpy as np
from PIL import Image
import io
import gc
import os
import insightface
from insightface.app import FaceAnalysis

# Global pre-initialization specifically designed for 1 CPU / 1GB RAM Railway Environment.
# Using 'buffalo_sc' ensures we stay well under 800MB Docker image size.
try:
    # Synchronous pre-load of the model at application startup to avoid first-request timeout
    # ctx_id=0 means CPU-only mode
    face_app = FaceAnalysis(name='buffalo_sc', providers=['CPUExecutionProvider'])
    face_app.prepare(ctx_id=0, det_size=(640, 640), det_thresh=0.4)
except Exception as e:
    print(f"CRITICAL: Failed to load InsightFace Model on boot: {e}")
    face_app = None

def check_ram_usage(max_percent=90.0):
    """
    Safely checks Linux memory profile to prevent OOM (Out Of Memory) crashes.
    """
    try:
        with open('/proc/meminfo', 'r') as f:
            lines = f.readlines()
        mem_info = {line.split(':')[0]: int(line.split(':')[1].split()[0]) for line in lines}
        total = mem_info.get('MemTotal', 1)
        free = mem_info.get('MemAvailable', mem_info.get('MemFree', 0))
        used_p = ((total - free) / total) * 100.0
        return used_p < max_percent, used_p
    except:
        # Non-linux environment check bypass
        return True, 0.0

def get_optimized_tensor(image_bytes, target_dim=1600):
    """
    Resizes image bytes to an optimized tensor format using OpenCV-direct decoding.
    Crucial for handling various JPEG metadata formats that PIL sometimes skips.
    High resolution (1600px) allows for detecting faces in the 4th/5th rows.
    """
    try:
        # Direct decode from memory buffer to OpenCV BGR format (fastest)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img_cv2 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img_cv2 is None:
            return None, "OpenCV failed to decode image bytes."

        # Scale protection: Downscale large photos to 1600px to ensure CPU-bound speed
        h, w = img_cv2.shape[:2]
        if max(h, w) > target_dim:
            scale = target_dim / max(h, w)
            img_cv2 = cv2.resize(img_cv2, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        return img_cv2, None
    except Exception as e:
        return None, str(e)

def extract_face_encodings(image_bytes):
    """
    Extracts face vectors (embeddings) from raw image bytes.
    Returns list of 512D vectors as Python lists. 
    """
    if not face_app: return []
    
    # RAM Protection circuit
    ok, ram_p = check_ram_usage()
    if not ok:
        print(f"ABORT: Memory usage too high ({ram_p:.1f}%) to process Face ML.")
        return []

    try:
        img_tensor, err = get_optimized_tensor(image_bytes, target_dim=640) # Enrollment uses smaller dim for speed
        if img_tensor is None: 
            print(f"ERROR: {err}")
            return []

        # Run Face Discovery + Recognition
        faces = face_app.get(img_tensor)
        print(f"DEBUG: Found {len(faces)} faces in enrollment photo.")
        
        del img_tensor
        gc.collect()

        # We strictly use normed_embedding for stable Euclidean distance matching
        return [face.normed_embedding.astype(np.float32).tolist() for face in faces]
        
    except Exception as e:
        print(f"Encoding extraction error: {e}")
        return []

def match_faces_in_group(group_image_bytes, known_encodings_dict, tolerance=0.9):
    """
    Matches faces in a group photo against the database list of encodings.
    Vectorized for high-speed calculation to support classes with 60-70 students.
    Returns (list_of_rolls, error_message)
    """
    if not face_app: 
        return [], "AI Engine initialization pending. Please try again in 30 seconds."

    # RAM and CPU safety check
    ok, ram_p = check_ram_usage()
    if not ok: 
        return [], f"Heavy System Load (RAM: {ram_p:.1f}%) detected. Try a smaller image or wait 1 minute."

    try:
        # High resolution (1600px) allows for detecting faces in the 4th/5th rows.
        img_tensor, err = get_optimized_tensor(group_image_bytes, target_dim=1600)
        if img_tensor is None: 
            return [], f"Decoding Failure: {err}"

        # Run Face Discovery - The most CPU-intensive step
        try:
            faces = face_app.get(img_tensor)
        except Exception as ai_err:
            return [], f"Vision Engine Timeout: {ai_err}. Reduce photo size."

        print(f"DEBUG: InsightFace found {len(faces)} potential faces at high density.")
        
        del img_tensor
        gc.collect()

        if not faces:
            return [], "No students detected in the photo. Ensure lighting is clear."

        # PERFORMANCE: Vectorize the identification stage
        # Instead of nested loops, we pre-compile the entire class database into a matrix
        known_matrix = [] # (Number of encodings, 128/512)
        roll_map = []     # (Index back to Roll Number)

        for roll_no, student_encodings in known_encodings_dict.items():
            for s_enc in student_encodings:
                if not s_enc: continue
                s_np = np.array(s_enc, dtype=np.float32)
                known_matrix.append(s_np)
                roll_map.append(roll_no)

        if not known_matrix:
            return [], "No biometric records found for this class group."

        known_matrix = np.array(known_matrix)   # High-speed NumPy matrix
        roll_map = np.array(roll_map)
        
        identified_rolls = set()
        
        # Iterate detected faces and perform Matrix Euclidean Distance (extremely fast)
        for d_face in faces:
            u_enc = d_face.normed_embedding.astype(np.float32)
            
            # Dimension safety (handles mix of buffalo_sc and others)
            if u_enc.shape[0] != known_matrix.shape[1]:
                continue

            # Compute Euclidean distances to all known students at once!
            # Math: sqrt(sum((u - k)^2))
            diffs = known_matrix - u_enc
            dists = np.linalg.norm(diffs, axis=1)
            
            # Find the index of the absolute best match
            best_idx = np.argmin(dists)
            if dists[best_idx] < tolerance:
                identified_rolls.add(roll_map[best_idx])

        print(f"DEBUG: Vectorized identification complete. Matched {len(identified_rolls)} students.")
        return list(identified_rolls), None

    except Exception as GeneralCrash:
        return [], f"Inference Interrupt: {GeneralCrash} (Possible RAM Spike)"
