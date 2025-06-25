import json
import uuid
from datetime import datetime, timedelta # Import timedelta for session lifetime
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify, current_app, Response
from flask_mail import Mail, Message
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import random
import re
import os
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from urllib.parse import urlparse, urljoin, quote_plus
import qrcode 
from qrcode.image.pil import PilImage 
from PIL import Image 
from werkzeug.utils import secure_filename
import csv 
import io 

# --- Import and Load dotenv ---
from dotenv import load_dotenv
load_dotenv() 

# --- Flask App Initialization and Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_key_for_your_app') 
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

# Session Configuration for idle timeout
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30) 

# Flask-Mail Configuration 
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.environ.get('SENDER_EMAIL') 
app.config['MAIL_PASSWORD'] = os.environ.get('SENDER_PASSWORD') 
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('SENDER_EMAIL') 

mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'user_login'
login_manager.login_message_category = 'info'

# --- ADMIN CREDENTIALS & UPI PAYMENT DETAILS ---
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH', generate_password_hash('admin123')) 
SENDER_EMAIL = os.environ.get('SENDER_EMAIL') 

# UPI Payment Details
UPI_ID = "smarasada@okaxis"
BANKING_NAME = "SUBHASH S" 

PAYMENT_SCREENSHOTS_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'payment_screenshots')
QR_CODES_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'qr_codes') 


# --- Helper Functions for JSON Data Management ---
def load_json(filename):
    """Loads JSON data from a file, returning a dict (for users.json) or list (for others)."""
    filepath = os.path.join(os.path.dirname(__file__), 'data', filename)
    
    if not os.path.exists(filepath):
        print(f"DEBUG: {filename} not found at {filepath}. Returning empty structure: {{}} if users.json, [] otherwise.")
        return {} if filename == 'users.json' else []
    
    if os.path.getsize(filepath) == 0:
        print(f"DEBUG: {filename} is empty. Returning empty structure: {{}} if users.json, [] otherwise.")
        return {} if filename == 'users.json' else []

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            
            if filename == 'users.json':
                if isinstance(data, list): 
                    converted_data = {item.get('email'): item for item in data if item.get('email')}
                    print(f"DEBUG: Converted {filename} list to dictionary.")
                    return converted_data
                elif isinstance(data, dict):
                    return data
                else:
                    print(f"WARNING: Unexpected JSON structure in {filename}. Expected dict or list. Returning empty dict.")
                    return {}
            else: 
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and filename == 'artworks.json': 
                    print(f"DEBUG: Converted {filename} dictionary to list.")
                    return list(data.values())
                else:
                    print(f"WARNING: Unexpected JSON structure in {filename}. Expected list. Returning empty list.")
                    return []
    except json.JSONDecodeError as e:
        print(f"ERROR: JSONDecodeError in {filename}: {e}. File might be corrupted. Returning empty structure: {{}} if users.json, [] otherwise.")
        return {} if filename == 'users.json' else []
    except Exception as e:
        print(f"ERROR: An unexpected error occurred loading {filename}: {e}. Returning empty structure: {{}} if users.json, [] otherwise.")
        return {} if filename == 'users.json' else []

def save_json(filename, data):
    """Saves data (dict or list) to a JSON file."""
    filepath = os.path.join(os.path.dirname(__file__), 'data', filename)
    try:
        if filename == 'users.json' and isinstance(data, dict):
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
        elif filename == 'artworks.json' and isinstance(data, dict):
             with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
        elif isinstance(data, list):
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4)
        else:
            print(f"WARNING: save_json received unexpected data type for {filename}: {type(data)}. Saving as is, but might cause issues.")
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=4) 

        print(f"DEBUG: Saved data to {filename}.")
    except Exception as e:
        print(f"ERROR: Failed to save data to {filename}: {e}")

# --- User Model for Flask-Login ---
class User(UserMixin):
    def __init__(self, id, email, name=None, phone=None, address=None, pincode=None, role='user', password=None, is_admin_user=False):
        self.id = str(id)
        self.email = email
        self.name = name
        self.phone = phone
        self.address = address
        self.pincode = pincode
        self.role = role
        self.password = password 
        self.is_admin_user = is_admin_user 

    def get_id(self):
        return self.id

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    @property
    def is_authenticated(self):
        return True

    @property
    def is_admin(self):
        return self.role == 'admin' and self.is_admin_user 


# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    print(f"DEBUG: load_user called for user_id: {user_id}")
    
    if user_id == ADMIN_USERNAME:
        print(f"DEBUG: load_user attempting to load hardcoded admin: {ADMIN_USERNAME}")
        return User(
            id=ADMIN_USERNAME,
            email=SENDER_EMAIL,
            name="Admin User",
            role='admin',
            is_admin_user=True
        )

    users_data = load_json('users.json') 
    user_info = None
    found_email = None

    for email_key, u_info in users_data.items():
        if u_info.get('id') == user_id:
            user_info = u_info
            found_email = email_key
            break

    if user_info and found_email:
        print(f"DEBUG: load_user found regular user with ID: {user_id} (email: {found_email})")
        return User(
            user_info['id'],
            found_email, 
            user_info.get('name'),
            user_info.get('phone'),
            user_info.get('address'),
            user_info.get('pincode'),
            user_info.get('role'),
            user_info.get('password'),
            is_admin_user=(user_info.get('role') == 'admin') 
        )
    print(f"DEBUG: load_user found no user for ID: {user_id}")
    return None

def load_user_by_email(email):
    """Helper to load a user by email, specific for OTP flow."""
    users_data = load_json('users.json') 
    user_info = users_data.get(email) 
    
    if user_info:
        return User(
            user_info['id'],
            user_info['email'],
            user_info.get('name'),
            user_info.get('phone'),
            user_info.get('address'),
            user_info.get('pincode'),
            user_info.get('role'),
            user_info.get('password'),
            is_admin_user=(user_info.get('role') == 'admin')
        )
    return None


# --- URL Safety Check ---
def is_safe_url(target):
    """Checks if a URL is safe for redirection to prevent open redirect vulnerabilities."""
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

# --- Decorator for Admin Access Control ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        print(f"DEBUG: admin_required decorator for route {f.__name__}. User authenticated: {current_user.is_authenticated}, Is Admin: {getattr(current_user, 'is_admin_user', False)}")
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'info')
            print("DEBUG: admin_required: Not authenticated, redirecting to admin login.")
            return redirect(url_for('admin_login'))
        if not getattr(current_user, 'is_admin_user', False): 
            flash('Access denied. You must be an administrator to view this page.', 'danger')
            print(f"DEBUG: admin_required: User '{getattr(current_user, 'email', 'N/A')}' is not an admin, redirecting to index.")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# --- Utility Functions (OTP generation, email sending, Order ID generation) ---
def generate_otp(otp_type='general', length=6): 
    """Generates a 6-digit OTP."""
    return str(random.randint(10**(length-1), (10**length) - 1))

def is_otp_valid(user_otp, otp_type='general'):
    """Checks if the provided OTP is valid and not expired."""
    session_key = 'otp_data_login' if otp_type == 'login' else 'otp_data_signup'
    session_otp_data = session.get(session_key)

    if not session_otp_data:
        return False, "No OTP found or it has expired. Please request a new one."

    stored_otp = session_otp_data.get('otp')
    otp_timestamp_str = session_otp_data.get('timestamp')

    if not stored_otp or not otp_timestamp_str:
        return False, "OTP data incomplete or corrupted. Please request a new one."

    try:
        otp_timestamp = datetime.fromisoformat(otp_timestamp_str)
    except ValueError:
        return False, "Invalid OTP timestamp format. Please request a new one."

    if (datetime.now() - otp_timestamp).total_seconds() > 300: 
        session.pop(session_key, None) 
        if otp_type == 'login': 
            session.pop('temp_email_for_otp', None)
        else: 
            session.pop('temp_email_signup', None)
            session.pop('signup_data', None)
        return False, "OTP has expired. Please request a new one."

    if user_otp == stored_otp:
        return True, "OTP is valid."
    else:
        return False, "Invalid OTP. Please try again."

def generate_unique_order_id():
    """Generates a unique 8-digit random order ID."""
    orders = load_json('orders.json') 
    existing_ids = {order.get('order_id') for order in orders}
    
    while True:
        new_id = str(random.randint(10**7, 10**8 - 1)) 
        if new_id not in existing_ids:
            return new_id


# --- ROUTES ---

# General User Logout
@app.route('/logout')
@login_required
def logout():
    """Logs out the current user (general user)."""
    print("\n--- DEBUG: Entering /logout route (general user) ---")
    if current_user.is_authenticated:
        logout_user()
        session.clear() 
        flash("You have been logged out successfully.", "info")
        print("DEBUG: General user logged out.")
    else:
        flash("You were not logged in.", "warning")
        print("DEBUG: Logout attempted for unauthenticated user.")
    return redirect(url_for('user_login'))


# Admin Logout
@app.route('/admin-logout')
@login_required
def admin_logout():
    print("\n--- DEBUG: Entering /admin-logout route ---")
    if current_user.is_authenticated and getattr(current_user, 'is_admin_user', False):
        logout_user()
        session.clear() 
        flash("Admin logged out successfully.", "info")
        print("DEBUG: Admin logged out.")
    else:
        flash("You are not logged in as an admin or your session is invalid.", "warning")
        logout_user() 
        session.clear()
        print("DEBUG: Non-admin or invalid session logout attempt.")
    return redirect(url_for('admin_login'))

# Admin Login
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    print("\n--- DEBUG: Entering /admin-login route ---")

    if current_user.is_authenticated and not getattr(current_user, 'is_admin_user', False):
        flash('Logging out current user to allow admin access.', 'info')
        logout_user()
        session.clear() 
        print("DEBUG: Regular user logged out to allow admin login.")

    if current_user.is_authenticated and getattr(current_user, 'is_admin_user', False):
        flash('You are already logged in as admin.', 'info')
        print("DEBUG: Admin already authenticated, redirecting to admin panel.")
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        print(f"DEBUG: Admin login POST request received for email: '{email}'")
        print(f"DEBUG: Admin login POST request received for password (first 4 chars): '{password[:4]}'") 

        if not email or not password:
            flash('Both email and password are required for admin login.', 'danger')
            print("DEBUG: Missing email or password for admin login.")
            return render_template('admin_login.html')

        if email == SENDER_EMAIL and check_password_hash(ADMIN_PASSWORD_HASH, password):
            admin_flask_user = User(
                id=ADMIN_USERNAME,
                email=email,
                name="Admin User",
                role='admin',
                is_admin_user=True 
            )
            login_user(admin_flask_user)
            session.permanent = True 
            flash('Admin logged in successfully!', 'success')
            print(f"DEBUG: Admin '{email}' logged in successfully. Redirecting to admin panel.")
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid admin credentials.', 'danger')
            print(f"DEBUG: Admin login failed: Credentials mismatch for email: '{email}'.")
            return render_template('admin_login.html')

    print("DEBUG: Rendering admin_login.html for GET request.")
    return render_template('admin_login.html')

# Admin Panel
@app.route('/admin-panel')
@admin_required
def admin_panel():
    print("\n--- DEBUG: Entering /admin-panel route ---")
    artworks = load_json('artworks.json') 
    orders = load_json('orders.json') 

    artworks_dict_by_sku = {art.get('sku'): art for art in artworks}

    print(f"DEBUG: Admin user '{getattr(current_user, 'email', 'N/A')}' successfully accessed admin dashboard.")
    return render_template('admin_panel.html', artworks=artworks_dict_by_sku.values(), orders=orders) 

# Add Artwork
@app.route('/add-artwork', methods=['GET', 'POST'])
@admin_required
def add_artwork():
    if request.method == 'POST':
        name = request.form['name']
        sku = request.form['sku']
        category = request.form['category']
        original_price = float(request.form['original_price'])
        stock = int(request.form['stock'])
        description = request.form.get('description', '')

        frame_wooden = float(request.form.get('frame_wooden', 0.0))
        frame_metal = float(request.form.get('frame_metal', 0.0))
        frame_pvc = float(request.form.get('frame_pvc', 0.0))
        glass_price = float(request.form.get('glass_price', 0.0))
        size_a4 = float(request.form.get('size_a4', 0.0))
        size_a5 = float(request.form.get('size_a5', 0.0))
        size_letter = float(request.form.get('size_letter', 0.0))
        size_legal = float(request.form.get('size_legal', 0.0))

        image_file = request.files['image']

        artworks = load_json('artworks.json') 
        artworks_dict_by_sku = {art.get('sku'): art for art in artworks} 

        if any(a.get('sku') == sku for a in artworks): 
            flash('Artwork with this SKU already exists.', 'danger')
            return render_template('add_artwork.html', **request.form)

        image_url = None
        if image_file and image_file.filename != '':
            filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(image_file.filename))[1]
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
                image_file.save(image_path)
                image_url = f'uploads/{filename}'
            except Exception as e:
                flash(f"Error saving image: {e}", "danger")
                return render_template('add_artwork.html', **request.form)
        else:
            flash("Image file is required for adding artwork.", "danger")
            return render_template('add_artwork.html', **request.form)

        new_artwork = {
            'sku': sku,
            'name': name,
            'category': category,
            'original_price': original_price,
            'stock': stock,
            'description': description,
            'image': image_url,
            'frame_wooden': frame_wooden,
            'frame_metal': frame_metal,
            'frame_pvc': frame_pvc,
            'glass_price': glass_price,
            'size_a4': size_a4,
            'size_a5': size_a5,
            'size_letter': size_letter,
            'size_legal': size_legal
        }

        artworks.append(new_artwork) 
        save_json('artworks.json', artworks) 
        flash('Artwork added successfully!', 'success')
        return redirect(url_for('admin_panel'))
    
    return render_template('add_artwork.html')

# Edit Artwork
@app.route('/edit-artwork/<sku>', methods=['GET', 'POST'])
@admin_required
def edit_artwork(sku):
    artworks = load_json('artworks.json') 
    artwork_obj = next((a for a in artworks if a.get('sku') == sku), None)

    if not artwork_obj:
        flash('Artwork not found.', 'danger')
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        artwork_obj['name'] = request.form.get('name', artwork_obj['name'])
        artwork_obj['category'] = request.form.get('category', artwork_obj['category'])
        artwork_obj['original_price'] = float(request.form.get('original_price', artwork_obj['original_price']))
        artwork_obj['stock'] = int(request.form.get('stock', artwork_obj['stock']))
        artwork_obj['description'] = request.form.get('description', artwork_obj['description'])

        artwork_obj['frame_wooden'] = float(request.form.get('frame_wooden', artwork_obj.get('frame_wooden', 0.0)))
        artwork_obj['frame_metal'] = float(request.form.get('frame_metal', artwork_obj.get('frame_metal', 0.0)))
        artwork_obj['frame_pvc'] = float(request.form.get('frame_pvc', artwork_obj.get('frame_pvc', 0.0)))
        artwork_obj['glass_price'] = float(request.form.get('glass_price', artwork_obj.get('glass_price', 0.0)))
        artwork_obj['size_a4'] = float(request.form.get('size_a4', artwork_obj.get('size_a4', 0.0)))
        artwork_obj['size_a5'] = float(request.form.get('size_a5', artwork_obj.get('size_a5', 0.0)))
        artwork_obj['size_letter'] = float(request.form.get('size_letter', artwork_obj.get('size_letter', 0.0)))
        artwork_obj['size_legal'] = float(request.form.get('size_legal', artwork_obj.get('size_legal', 0.0)))

        image_file = request.files.get('image')
        if image_file and image_file.filename != '':
            filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(image_file.filename))[1]
            image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            try:
                if 'image' in artwork_obj and artwork_obj['image'] and os.path.exists(os.path.join('static', artwork_obj['image'])):
                    os.remove(os.path.join('static', artwork_obj['image'])) 
                    print(f"DEBUG: Old image removed: {artwork_obj['image']}")
                
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
                image_file.save(image_path)
                artwork_obj['image'] = f'uploads/{filename}'
                print(f"DEBUG: New image uploaded: {artwork_obj['image']}")
            except Exception as e:
                flash(f"Error saving new image: {e}", "danger")
                return render_template('edit_artwork.html', artwork=artwork_obj)

        save_json('artworks.json', artworks) 
        flash('Artwork updated successfully!', 'success')
        return redirect(url_for('edit_artwork', sku=sku))

    return render_template('edit_artwork.html', artwork=artwork_obj) 

# Delete Artwork (Admin only)
@app.route('/delete-artwork/<sku>')
@admin_required
def delete_artwork(sku):
    artworks = load_json('artworks.json') 
    initial_count = len(artworks)
    
    artwork_to_delete = next((a for a in artworks if a.get('sku') == sku), None)

    updated_artworks = [a for a in artworks if a.get('sku') != sku]
    
    if len(updated_artworks) < initial_count: 
        save_json('artworks.json', updated_artworks)
        flash("Artwork deleted successfully.", "info")
        if artwork_to_delete and 'image' in artwork_to_delete and artwork_to_delete['image']:
            image_filepath = os.path.join('static', artwork_to_delete['image'])
            if os.path.exists(image_filepath):
                try:
                    os.remove(image_filepath)
                    print(f"DEBUG: Image file deleted: {image_filepath}")
                except Exception as e:
                    print(f"Error deleting image file {image_filepath}: {e}")
    else:
        flash("Artwork not found.", "warning")

    return redirect(url_for('admin_panel'))

# Delete Order (Admin only)
@app.route('/delete-order/<order_id>')
@admin_required
def delete_order(order_id):
    orders = load_json('orders.json') 
    initial_count = len(orders)
    
    updated_orders = [o for o in orders if o.get('order_id') != order_id] 

    if len(updated_orders) < initial_count:
        save_json('orders.json', updated_orders)
        flash(f"Order {order_id} deleted successfully!", "success")
    else:
        flash(f"Order {order_id} not found.", "warning")

    return redirect(url_for('admin_panel'))

# Admin Orders (Update Status/Shipping)
@app.route('/admin-orders', methods=['GET', 'POST'])
@admin_required
def admin_orders():
    orders = load_json('orders.json') 

    if request.method == 'POST':
        order_id = request.form.get('order_id')
        new_status = request.form.get('status')
        courier = request.form.get('courier', '')
        tracking_number = request.form.get('tracking_number', '')

        print(f"DEBUG: Admin order update POST received for Order ID: {order_id}, Status: {new_status}")

        order_found = False
        for order in orders:
            if order.get('order_id') == order_id:
                order_found = True
                order['status'] = new_status
                order['courier'] = courier
                order['tracking_number'] = tracking_number
                break
        
        if order_found:
            save_json('orders.json', orders)
            flash(f"Order {order_id} updated to '{new_status}'.", "success")
        else:
            flash(f"Order {order_id} not found.", "danger")
        
        return redirect(url_for('admin_panel')) 

    return redirect(url_for('admin_panel')) 


# Home Route
@app.route('/')
def index():
    print("\n--- DEBUG: Entering / route (homepage) ---")
    # Load all artworks for the homepage display
    all_artworks = load_json('artworks.json') 
    
    print(f"DEBUG: Total artworks loaded for homepage: {len(all_artworks)}")

    return render_template(
        'index.html', 
        artworks=all_artworks, # Pass all artworks directly
        current_year=datetime.now().year
    )

# All Products Route
@app.route('/all_products')
def all_products():
    print(f"\n--- DEBUG: Entering /all_products route ---")
    artworks_data = load_json('artworks.json') 
    all_artworks = list(artworks_data) 
    print(f"DEBUG: Loaded {len(all_artworks)} artworks for /all_products.")
    return render_template('all_products.html', artworks=all_artworks)

# Product Detail Route 
@app.route('/product/<sku>')
def product_detail(sku):
    print(f"\n--- DEBUG: Entering /product-detail/{sku} route ---") 
    artworks = load_json('artworks.json') 
    artwork = next((item for item in artworks if item.get('sku') == sku), None)
    if artwork:
        print(f"DEBUG: Found artwork: {artwork.get('name')}") 
        return render_template('product_detail.html', artwork=artwork)
    flash('Product not found.', 'danger')
    print(f"ERROR: Artwork with SKU '{sku}' not found for product detail.") 
    return redirect(url_for('index'))

# User Login Route 
@app.route('/login', methods=['GET', 'POST'])
def user_login():
    next_url_param = request.args.get('next')
    next_url = next_url_param if next_url_param is not None and next_url_param != '' else url_for('index')

    print(f"\n--- DEBUG: Entering /login route. Next page: {next_url} ---")

    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        print("DEBUG: User already authenticated, redirecting to user_dashboard.")
        return redirect(url_for('user_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        print(f"DEBUG: Login POST request received for email: {email}")

        if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Please enter a valid email address.', 'danger')
            print("DEBUG: Invalid email format submitted.")
            return render_template('user_login.html', next_url=next_url) 

        users_data = load_json('users.json') 
        user_info = users_data.get(email) 
        
        if not user_info:
            flash('No account found with that email address. Please register.', 'danger')
            print(f"DEBUG: No user found for email: {email}")
            return render_template('user_login.html', next_url=next_url) 

        otp_code = generate_otp(otp_type='login') 
        
        session['temp_email_for_otp'] = email
        session['otp_data_login'] = {
            'otp': otp_code,
            'timestamp': datetime.now().isoformat()
        }
        session['redirect_after_login'] = next_url 

        print(f"DEBUG: Generated OTP {otp_code} for {email} (Login)")

        try:
            msg = Message('Your Login OTP', recipients=[email])
            msg.body = f'Your One-Time Password for Karthika Futures login is: {otp_code}\n\nThis OTP is valid for a short period. Do not share it.'
            
            print("\n--- DEBUG: SMTP Login Attempt (OTP Email) ---")
            print(f" SENDER_EMAIL being used: '{app.config.get('MAIL_USERNAME')}'")
            print(f" SENDER_PASSWORD length: {len(app.config.get('MAIL_PASSWORD', '') if app.config.get('MAIL_PASSWORD') else 0)}")
            print(f" SENDER_PASSWORD starts with: '{app.config.get('MAIL_PASSWORD', '')[:4]}'")
            print(f" SENDER_PASSWORD ends with: '{app.config.get('MAIL_PASSWORD', '')[-4:]}'")
            print("------------------------------------------------\n")

            mail.send(msg)
            flash('An OTP has been sent to your email address. Please check your inbox (and spam folder).', 'info')
            print("DEBUG: OTP email sent successfully.")
            return redirect(url_for('verify_otp', next=next_url, otp_type='login')) 

        except Exception as e:
            flash('Failed to send OTP. Please check your email address, internet connection, or try again later.', 'danger')
            print(f"ERROR: Failed to send OTP email: {e}")
            session.pop('otp_data_login', None)
            session.pop('temp_email_for_otp', None)
            return render_template('user_login.html', next_url=next_url) 

    print("DEBUG: Rendering user_login.html for GET request.")
    return render_template('user_login.html', next_url=next_url)

# Verify OTP Route
@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        return redirect(url_for('index'))

    otp_type = request.args.get('otp_type', session.get('otp_flow_type', 'login'))
    session['otp_flow_type'] = otp_type 

    temp_email_key = 'temp_email_for_otp' if otp_type == 'login' else 'temp_email_signup'
    otp_data_key = 'otp_data_login' if otp_type == 'login' else 'otp_data_signup'
    
    if otp_type == 'login':
        next_url_param = request.args.get('next')
        next_url = next_url_param if next_url_param is not None and next_url_param != '' else \
                     session.get('redirect_after_login', url_for('index'))
    else: 
        next_url = url_for('user_dashboard') 
        if 'signup_data' not in session: 
            flash("Signup process incomplete. Please start registration again.", "danger")
            return redirect(url_for('signup'))


    if not is_safe_url(next_url): 
        print(f"SECURITY WARNING: next_url was unsafe ('{next_url}'). Defaulting to index.")
        flash("Unsafe redirect attempt. Redirecting to homepage.", "warning") 
        next_url = url_for('index') 
    
    email_for_otp = session.get(temp_email_key)

    if not email_for_otp:
        flash("Please enter your email to receive an OTP first.", "warning")
        if otp_type == 'login':
            return redirect(url_for('user_login', next=next_url))
        else: 
            return redirect(url_for('signup'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        is_valid, message = is_otp_valid(user_otp, otp_type=otp_type) 

        if is_valid:
            user_email = session.pop(temp_email_key)
            session.pop(otp_data_key, None) 
            session.pop('otp_flow_type', None) 

            users_data = load_json('users.json') 

            user_info = None 

            if otp_type == 'signup' and 'signup_data' in session:
                new_user_data = session.pop('signup_data')
                new_user_data['id'] = str(uuid.uuid4()) 
                new_user_data['email'] = user_email 
                users_data[user_email] = new_user_data 
                save_json('users.json', users_data) 
                flash('Account created and logged in successfully!', 'success')
                print(f"DEBUG: User '{user_email}' signed up and logged in successfully.")
                user_info = new_user_data 
            elif otp_type == 'login':
                user_info = users_data.get(user_email)
                if not user_info:
                    flash("Email not registered. Please sign up first.", "danger")
                    session.pop('redirect_after_login', None)
                    return redirect(url_for('signup', email=user_email))
                flash("Logged in successfully.", "success")
            else:
                flash("An unexpected error occurred. Please try again.", "danger")
                return redirect(url_for('signup')) 

            if user_info: 
                flask_user = User(
                    user_info['id'],
                    user_info['email'],
                    user_info.get('name'),
                    user_info.get('phone'),
                    user_info.get('address'),
                    user_info.get('pincode'),
                    user_info.get('role', 'user'),
                    user_info.get('password'), 
                    is_admin_user=(user_info.get('role') == 'admin') 
                )
                login_user(flask_user)
                session.permanent = True 

                session.pop('redirect_after_login', None) 

                return redirect(next_url) 
            else:
                flash("Could not find user information to log in. Please try again.", "danger")
                if otp_type == 'login':
                    return redirect(url_for('user_login'))
                else:
                    return redirect(url_for('signup'))

        else:
            flash(message, "danger") 

    return render_template('verify_otp.html', email=email_for_otp, next_url=next_url)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    print(f"\n--- DEBUG: Entering /signup route ---")
    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        password = request.form.get('password') 
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        pincode = request.form.get('pincode') 

        print(f"DEBUG: Signup POST received for email: {email}")
        print(f"DEBUG: Signup form data - Name: {name}, Phone: {phone}, Address: {address}, Pincode: {pincode}") 

        if not all([email, password, name, phone, address, pincode]):
            flash('All fields are required.', 'danger')
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Please enter a valid email address.', 'danger')
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        users = load_json('users.json') 
        print(f"DEBUG: Users data for signup check (keys): {list(users.keys()) if isinstance(users, dict) else 'Not a dict'}") 
        print(f"DEBUG: Attempting to register email: {email}") 

        if email in users: 
            flash('Email already registered. Please log in.', 'danger')
            print(f"DEBUG: Signup failed: Email '{email}' already exists.")
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        hashed_password = generate_password_hash(password)

        session['signup_data'] = {
            'email': email,
            'password': hashed_password, 
            'name': name,
            'phone': phone,
            'address': address,
            'pincode': pincode,
            'role': 'user' 
        }
        session['temp_email_signup'] = email 
        session['otp_flow_type'] = 'signup' 

        otp_code = generate_otp(otp_type='signup') 
        session['otp_data_signup'] = {
            'otp': otp_code,
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"DEBUG: Generated OTP {otp_code} for {email} (Signup)")

        try:
            msg = Message('Your Signup OTP', recipients=[email])
            msg.body = f'Your One-Time Password for Karthika Futures signup is: {otp_code}\n\nThis OTP is valid for a short period. Do not share it.'
            mail.send(msg)
            flash('An OTP has been sent to your email address. Please check your inbox (and spam folder).', 'info')
            print("DEBUG: Signup OTP email sent successfully.")
            return redirect(url_for('verify_otp', otp_type='signup'))

        except Exception as e:
            flash('Failed to send OTP. Please check your email address, internet connection, or try again later.', 'danger')
            print(f"ERROR: Failed to send signup OTP email: {e}")
            session.pop('signup_data', None)
            session.pop('temp_email_signup', None)
            session.pop('otp_data_signup', None)
            session.pop('otp_flow_type', None)
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

    return render_template('signup.html')


# Cart Update Session (AJAX) Route
@app.route('/update_cart_session', methods=['POST'])
def update_cart_session():
    try:
        data = request.get_json()
        client_cart = data.get('cart', {})

        processed_cart = {}
        if isinstance(client_cart, list):
            for item in client_cart:
                if item.get('id'):
                    if 'total_price' not in item and 'unit_price' in item and 'quantity' in item:
                        try:
                            item['total_price'] = float(item['unit_price']) * int(item['quantity'])
                        except (ValueError, TypeError):
                            item['total_price'] = 0.0
                    processed_cart[item['id']] = item
            print("DEBUG: Client sent list, converted to dict for session.")
        elif isinstance(client_cart, dict):
            for item_id, item_data in client_cart.items():
                if 'total_price' not in item_data and 'unit_price' in item_data and 'quantity' in item_data:
                    try:
                        item_data['total_price'] = float(item_data['unit_price']) * int(item_data['quantity'])
                    except (ValueError, TypeError):
                        item_data['total_price'] = 0.0
                processed_cart[item_id] = item_data
            print("DEBUG: Client sent dict, processed for session.")
        else:
            print(f"WARNING: Unexpected client_cart type: {type(client_cart)}. Resetting session cart.")

        session['cart'] = processed_cart
        
        print(f"\n--- DEBUG: Server session['cart'] updated via AJAX: {session['cart']} ---")
        return jsonify(success=True, message="Cart session updated successfully"), 200
    except Exception as e:
        print(f"ERROR: Failed to update server session cart: {e}")
        return jsonify(success=False, message=f"Failed to update cart: {e}"), 500

# Cart Page
@app.route('/cart')
def cart():
    print("\n--- DEBUG: Entering /cart route ---")
    print(f"DEBUG: session['cart'] at /cart start: {session.get('cart')}")

    cart_items_for_display = []
    grand_total_cart = 0.0

    current_session_cart = session.get('cart', {})

    if isinstance(current_session_cart, list):
        print("DEBUG: /cart found session['cart'] as a list, converting to dict.")
        current_session_cart = {item.get('id'): item for item in current_session_cart if item.get('id')}
        session['cart'] = current_session_cart
    elif not isinstance(current_session_cart, dict):
        print(f"WARNING: /cart found session['cart'] as unexpected type {type(current_session_cart)}, resetting to empty.")
        current_session_cart = {}
        session['cart'] = current_session_cart

    if current_session_cart:
        try:
            print("\n--- DEBUG: Processing cart for /cart page display ---")
            for item_id, item_data_original in current_session_cart.items():
                item_data = item_data_original.copy()
                
                unit_price_val = float(item_data.get('unit_price', 0.0))
                quantity_val = int(item_data.get('quantity', 1))

                item_total_price = unit_price_val * quantity_val
                grand_total_cart += item_total_price
                
                item_data['calculated_display_price'] = item_total_price 
                cart_items_for_display.append(item_data)
                
                print(f"  Item ID: {item_id}, Name: {item_data.get('name')}, Qty: {quantity_val}, Unit Price: {unit_price_val}, Total for item: {item_total_price}")
            
            print(f"  FINAL grand_total_cart for /cart page: {grand_total_cart:.2f}")
            print("--------------------------------------------------\n")

            if not cart_items_for_display:
                flash('Your cart is empty. Please add items before checking out.', 'info')

        except Exception as e:
            print(f"ERROR: Error processing cart from session for /cart page: {e}")
            flash('There was an error loading your cart. Please try again.', 'danger')
            cart_items_for_display = []
            grand_total_cart = 0.0
    else:
        flash('Your cart is empty. Please add items before checking out.', 'info')

    return render_template('cart.html', cart_items=cart_items_for_display, grand_total=grand_total_cart)

# Purchase Form
@app.route('/purchase-form', methods=['GET', 'POST'])
@login_required 
def purchase_form():
    user = current_user

    print("\n--- DEBUG: Entering /purchase-form route ---")
    print(f"DEBUG: request.method: {request.method}")
    print(f"DEBUG: session['cart'] at /purchase-form start: {session.get('cart')}")

    if request.method == 'POST':
        print(f"\n--- DEBUG: POST Request Form Data Received (Overall) ---")
        print(request.form)
        print(f"--------------------------------------------------\n")

        cart_json = request.form.get('cart_json')

        if 'name' not in request.form: 
            print("DEBUG: This is the FIRST POST (from cart.html) to /purchase-form.")
            
            processed_items_for_display = [] 
            calculated_grand_total = 0.0

            if not cart_json:
                print("DEBUG: cart_json is empty in First POST, redirecting to /cart.")
                return redirect(url_for('cart')) 
            
            try:
                items_from_cart = json.loads(cart_json)
                
                print(f"DEBUG (First POST): Result of json.loads(cart_json): {items_from_cart}")
                print(f"DEBUG (First POST): Type of items_from_cart: {type(items_from_cart)}")
                print(f"DEBUG (First POST): Is items_from_cart empty? {not items_from_cart}")

                if not items_from_cart:
                    print("DEBUG: items_from_cart is empty after JSON load, redirecting to /cart.")
                    return redirect(url_for('cart'))

                print("\n--- DEBUG: Calculating grand_total for FIRST POST (rendering form) ---")
                
                for item_data in items_from_cart:
                    item = item_data.copy() 
                    
                    unit_price_val = float(item.get('unit_price', 0.0))
                    quantity_val = int(item.get('quantity', 1))
                    item_total = unit_price_val * quantity_val
                    
                    calculated_grand_total += item_total
                    item['price'] = item_total 
                    processed_items_for_display.append(item)

                    print(f"  Item: {item.get('name', 'N/A')}, unit_price: {unit_price_val}, quantity: {quantity_val}, item_total: {item_total}")

                print(f"  FINAL grand_total_from_server_calc (FIRST POST): {calculated_grand_total:.2f}")
                print("--------------------------------------------------\n")

                context = {
                    'prefill_name': user.name or '',
                    'prefill_email': user.email or '',
                    'prefill_email_type': 'text',
                    'prefill_phone': user.phone or '',
                    'prefill_address': user.address or '',
                    'prefill_pincode': user.pincode or '',
                    'cart_json': cart_json,
                    'items_for_display': processed_items_for_display,
                    'grand_total': calculated_grand_total
                }
                return render_template('purchase-form.html', **context)

            except json.JSONDecodeError:
                flash('Error processing cart data. Please try again.', 'danger')
                print(f"DEBUG (First POST): JSON Decode Error for cart_json: {cart_json}")
                return redirect(url_for('cart'))
            except Exception as e:
                flash(f'An unexpected error occurred during cart processing: {e}', 'danger')
                print(f"DEBUG (First POST): Unexpected error processing cart: {e}")
                return redirect(url_for('cart'))


        else: 
            print("DEBUG: This is the SECOND POST (from purchase-form.html) to /purchase-form.")
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            address = request.form.get('address')
            pincode = request.form.get('pincode')

            if not all([name, phone, address, pincode]):
                flash('All fields (Name, Phone, Address, Pincode) are required.', 'danger')
                return redirect(url_for('purchase_form')) 
            if not cart_json:
                flash('Cart data is missing from the form. Please try adding items to your cart again.', 'danger')
                print("DEBUG: cart_json is missing in Second POST, redirecting to /cart.")
                return redirect(url_for('cart'))

            try:
                items_from_cart = json.loads(cart_json)
                
                print(f"DEBUG (Second POST): Result of json.loads(cart_json): {items_from_cart}")
                print(f"DEBUG (Second POST): Type of items_from_cart: {type(items_from_cart)}")
                print(f"DEBUG (Second POST): Is items_from_cart empty? {not items_from_cart}")

                if not items_from_cart:
                    print("DEBUG: items_from_cart is empty after JSON load in Second POST, redirecting to /cart.")
                    return redirect(url_for('cart'))

                grand_total_from_server_calc = 0.0
                print("\n--- DEBUG: Calculating grand_total for SECOND POST (order processing) ---")
                for item in items_from_cart:
                    unit_price_val = float(item.get('unit_price', 0.0))
                    quantity_val = int(item.get('quantity', 1))
                    item_total = unit_price_val * quantity_val
                    grand_total_from_server_calc += item_total
                    print(f"  Item: {item.get('name', 'N/A')}, unit_price: {unit_price_val}, quantity: {quantity_val}, item_total: {item_total}")
                print(f"  FINAL grand_total_from_server_calc (SECOND POST): {grand_total_from_server_calc:.2f}")
                print("--------------------------------------------------\n")

                orders = load_json('orders.json')

                order_id = generate_unique_order_id() 
                new_order = {
                    "order_id": order_id,
                    "user_id": user.id,
                    "user_email": user.email,
                    "customer_name": name,
                    "customer_phone": phone,
                    "customer_address": address,
                    "customer_pincode": pincode,
                    "total_amount": grand_total_from_server_calc,
                    "items": items_from_cart, 
                    "status": "Pending Payment",
                    "courier": "",
                    "tracking_number": "",
                    "placed_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                orders.append(new_order)
                save_json('orders.json', orders)

                session.pop('cart', None) 

                flash('Your order has been created. Redirecting to payment!', 'info')
                return redirect(url_for('payment_initiate', order_id=order_id, amount=grand_total_from_server_calc))

            except json.JSONDecodeError:
                flash('Error processing cart data. Please try again.', 'danger')
                print(f"DEBUG (Second POST): JSON Decode Error for cart_json: {cart_json}")
                return redirect(url_for('purchase_form'))
            except Exception as e:
                flash(f'An unexpected error occurred while placing your order: {e}', 'danger')
                print(f"DEBUG (Second POST): Unexpected error placing order: {e}")
                return redirect(url_for('purchase_form'))

    elif request.method == 'GET':
        print("DEBUG: This is a GET request to /purchase-form.")
        current_cart_items_for_display = [] 
        calculated_grand_total = 0.0

        cart_data_from_session = session.get('cart', {})

        if isinstance(cart_data_from_session, list):
            print("DEBUG: GET /purchase-form found session['cart'] as a list, converting to dict.")
            cart_data_from_session = {item.get('id'): item for item in cart_data_from_session if item.get('id')}
            session['cart'] = cart_data_from_session 
        elif not isinstance(cart_data_from_session, dict):
            print(f"WARNING: GET /purchase-form found session['cart'] as unexpected type {type(cart_data_from_session)}, resetting to empty dict.")
            cart_data_from_session = {}
            session['cart'] = cart_data_from_session 


        cart_json_for_template = json.dumps(list(cart_data_from_session.values())) 

        if cart_data_from_session:
            try:
                print("\n--- DEBUG: Calculating grand_total for GET request (rendering form) ---")
                for item_id, item_data_original in cart_data_from_session.items():
                    item_data = item_data_original.copy() 
                    
                    unit_price_val = float(item_data.get('unit_price', 0.0))
                    quantity_val = int(item_data.get('quantity', 1))

                    item_total_price = unit_price_val * quantity_val
                    calculated_grand_total += item_total_price
                    item_data['price'] = item_total_price 
                    current_cart_items_for_display.append(item_data)

                    print(f"  Item ID: {item_id}, unit_price: {unit_price_val}, quantity: {quantity_val}, item_total_price: {item_total_price}")

                print(f"  FINAL calculated_grand_total (GET): {calculated_grand_total:.2f}")
                print("--------------------------------------------------\n")

                if not current_cart_items_for_display:
                    print("DEBUG: current_cart_items_for_display is empty, redirecting to /cart.")
                    return redirect(url_for('cart'))
            except Exception as e:
                print(f"DEBUG (GET): Error processing cart from session: {e}")
                flash('There was an error loading your cart. Please try again.', 'danger')
                return redirect(url_for('cart'))
        else:
            print("DEBUG: Session cart is empty in GET /purchase-form, redirecting to /cart.")
            return redirect(url_for('cart'))

        context = {
            'prefill_name': user.name or '',
            'prefill_email': user.email or '',
            'prefill_email_type': 'text',
            'prefill_phone': user.phone or '',
            'prefill_address': user.address or '',
            'prefill_pincode': user.pincode or '',
            'cart_items': current_cart_items_for_display, 
            'grand_total': calculated_grand_total,
            'cart_json': json.dumps(current_cart_items_for_display) 
        }

        print(f"DEBUG (GET /purchase-form): Grand Total passed to template: {calculated_grand_total:.2f}")
        return render_template('purchase-form.html', **context)
    
    return redirect(url_for('index'))

# Payment Initiate Page
@app.route('/payment-initiate/<order_id>/<float:amount>', methods=['GET'])
@login_required
def payment_initiate(order_id, amount):
    print(f"\n--- DEBUG: Entering /payment-initiate route ---")
    print(f"DEBUG: Received order_id: {order_id}, amount: {amount}")

    upi_id = UPI_ID
    banking_name = BANKING_NAME
    
    orders = load_json('orders.json') 
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        flash('Order not found. Please try again.', 'danger')
        print(f"ERROR: Order with ID {order_id} not found for payment initiation.")
        return redirect(url_for('my_orders')) 

    if abs(order['total_amount'] - amount) > 0.01: 
        flash('Payment amount mismatch. Please try again or contact support.', 'danger')
        print(f"WARNING: Amount mismatch for order {order_id}. Expected {order['total_amount']}, Got {amount}.")
        return redirect(url_for('my_orders'))

    context = {
        'order_id': order_id,
        'amount': amount,
        'upi_id': upi_id,
        'banking_name': banking_name
    }
    print("DEBUG: Rendering payment-initiate.html with context:", context)
    return render_template('payment-initiate.html', **context)

# Confirm Payment Details
@app.route('/confirm_payment', methods=['POST'])
@login_required
def confirm_payment():
    print(f"\n--- DEBUG: Entering /confirm_payment route ---")
    order_id = request.form.get('order_id')
    transaction_id = request.form.get('transaction_id')
    screenshot_file = request.files.get('screenshot')

    print(f"DEBUG: Confirm payment POST received for Order ID: {order_id}, Transaction ID: {transaction_id}")

    if not all([order_id, transaction_id]):
        flash('Order ID and Transaction ID are required.', 'danger')
        print("ERROR: Missing order_id or transaction_id in confirm_payment.")
        return redirect(url_for('my_orders')) 

    orders = load_json('orders.json') 
    order_found = False
    screenshot_path = None

    if screenshot_file and screenshot_file.filename != '':
        try:
            os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
            
            filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(screenshot_file.filename))[1]
            screenshot_path_full = os.path.join(PAYMENT_SCREENSHOTS_FOLDER, filename)
            screenshot_file.save(screenshot_path_full)
            screenshot_path = f'uploads/payment_screenshots/{filename}' 
            print(f"DEBUG: Screenshot saved to: {screenshot_path}")
        except Exception as e:
            print(f"ERROR: Failed to save screenshot: {e}")
            flash('Failed to upload screenshot. Please try again.', 'warning')


    for order in orders:
        if order.get('order_id') == order_id:
            order_found = True
            order['status'] = "Payment Submitted - Awaiting Verification"
            order['transaction_id'] = transaction_id
            if screenshot_path:
                order['payment_screenshot'] = screenshot_path
            order['payment_submitted_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"DEBUG: Order {order_id} status updated to '{order['status']}'.")
            break

    if order_found:
        save_json('orders.json', orders)
        session.pop('cart', None) 
        flash('Payment details submitted successfully. Your order status will be updated after verification.', 'success')
        print("DEBUG: Redirecting to thank_you page.")
        return redirect(url_for('thank_you_page'))
    else:
        flash('Order not found. Please ensure you are submitting details for a valid order.', 'danger')
        print(f"ERROR: Order {order_id} not found when confirming payment.")
        return redirect(url_for('my_orders')) 

@app.route('/thank-you')
def thank_you_page():
    print("\n--- DEBUG: Entering /thank-you route ---")
    return render_template('thank-you.html')


# --- USER SPECIFIC ROUTES ---
@app.route('/my-orders')
@login_required
def my_orders():
    print("\n--- DEBUG: Entering /my-orders route ---")
    print(f"DEBUG: Current user ID for /my-orders: {current_user.id}") 
    orders = load_json('orders.json') 
    user_orders = []
    for order in orders:
        print(f"DEBUG: Checking order ID: {order.get('order_id')}, User ID in order: {order.get('user_id')}, Match: {str(order.get('user_id')) == str(current_user.id)}") 
        if str(order.get('user_id')) == str(current_user.id):
            user_orders.append(order)

    print(f"DEBUG: Found {len(user_orders)} orders for user {current_user.id}.")
    return render_template('my_orders.html', orders=user_orders)

@app.route('/cancel-order/<order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    print(f"\n--- DEBUG: Entering /cancel-order route for order_id: {order_id} ---")
    orders = load_json('orders.json')
    order_found = False
    
    for order_idx, order in enumerate(orders): # Use enumerate to get index for direct modification
        if order.get('order_id') == order_id:
            # Security check: Ensure the current logged-in user owns this order
            if str(order.get('user_id')) == str(current_user.id):
                # Only allow cancellation if the order is in a "cancellable" state
                if order.get('status') in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
                    orders[order_idx]['status'] = "Cancelled by User" # Update using index
                    save_json('orders.json', orders)
                    flash(f"Order {order_id} has been cancelled.", "success")
                    print(f"DEBUG: Order {order_id} cancelled by user {current_user.id}.")
                else:
                    flash(f"Order {order_id} cannot be cancelled at its current status ({order.get('status')}). Please contact support.", "danger")
                    print(f"WARNING: User {current_user.id} attempted to cancel order {order_id} which is in status {order.get('status')}.")
                order_found = True
                break
            else:
                flash("You do not have permission to cancel this order.", "danger")
                print(f"SECURITY ALERT: User {current_user.id} attempted to cancel order {order_id} owned by {order.get('user_id')}.")
                order_found = True # Found the order, but not owned by current user
                break
    
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
        print(f"ERROR: User {current_user.id} attempted to cancel non-existent order {order_id}.")
    
    return redirect(url_for('my_orders'))


@app.route('/user-dashboard')
@login_required
def user_dashboard():
    print("\n--- DEBUG: Entering /user-dashboard route ---")
    return render_template('user_dashboard.html')

@app.route('/profile')
@login_required
def profile():
    print("\n--- DEBUG: Entering /profile route ---")
    user_info = {
        'name': current_user.name,
        'email': current_user.email,
        'phone': current_user.phone,
        'address': current_user.address,
        'pincode': current_user.pincode,
        'role': current_user.role
    }
    print(f"DEBUG: Displaying profile for user {current_user.email}.")
    return render_template('profile.html', user_info=user_info)

# --- CSV Export Routes ---
@app.route('/export-orders-csv')
@admin_required
def export_orders_csv():
    orders = load_json('orders.json')
    
    # Define CSV headers
    fieldnames = [
        "order_id", "user_id", "user_email", "customer_name", "customer_phone", 
        "customer_address", "customer_pincode", "total_amount", "status", 
        "transaction_id", "courier", "tracking_number", "placed_on", "payment_submitted_on",
        "items_details" # Combined item details
    ]

    def generate_csv():
        si = io.StringIO()
        cw = csv.writer(si)

        cw.writerow(fieldnames) 

        for order in orders:
            items_details = []
            if 'items' in order and isinstance(order['items'], list):
                for item in order['items']:
                    item_unit_price = f"{item.get('unit_price', 0.0):.2f}"
                    item_total_calc = float(item.get('unit_price', 0.0)) * int(item.get('quantity', 1))
                    item_total_formatted = f"{item_total_calc:.2f}"

                    details = f"{item.get('name', 'N/A')} (SKU: {item.get('sku', 'N/A')}," \
                              f" Qty: {item.get('quantity', 1)}," \
                              f" UnitPrice: {item_unit_price}," \
                              f" ItemTotal: {item_total_formatted}," \
                              f" Size: {item.get('size', 'N/A')}," \
                              f" Frame: {item.get('frame', 'N/A')}," \
                              f" Glass: {item.get('glass', 'N/A')})"
                    items_details.append(details)
            items_details_str = "; ".join(items_details) 

            row = [
                str(order.get('order_id', 'N/A')),
                str(order.get('user_id', 'N/A')),
                str(order.get('user_email', 'N/A')),
                str(order.get('customer_name', 'N/A')),
                str(order.get('customer_phone', 'N/A')),
                str(order.get('customer_address', 'N/A')),
                str(order.get('customer_pincode', 'N/A')),
                f"{order.get('total_amount', 0.0):.2f}", 
                str(order.get('status', 'N/A')),
                str(order.get('transaction_id', 'N/A')), 
                str(order.get('courier', 'N/A')),
                str(order.get('tracking_number', 'N/A')),
                str(order.get('placed_on', 'N/A')),
                str(order.get('payment_submitted_on', 'N/A')),
                items_details_str
            ]
            cw.writerow(row)
            yield si.getvalue()
            si.seek(0)
            si.truncate(0)

    response = Response(generate_csv(), mimetype='text/csv')
    response.headers["Content-Disposition"] = f"attachment; filename=orders_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return response

@app.route('/export-artworks-csv')
@admin_required
def export_artworks_csv():
    artworks = load_json('artworks.json')

    # Define CSV headers
    fieldnames = [
        "sku", "name", "category", "original_price", "stock", "description",
        "frame_wooden_price", "frame_metal_price", "frame_pvc_price", 
        "glass_price", "size_a4_price", "size_a5_price", "size_letter_price", "size_legal_price"
    ]

    def generate_csv():
        si = io.StringIO()
        cw = csv.writer(si)

        cw.writerow(fieldnames) 

        for artwork in artworks:
            row = [
                str(artwork.get('sku', 'N/A')),
                str(artwork.get('name', 'N/A')),
                str(artwork.get('category', 'N/A')),
                f"{artwork.get('original_price', 0.0):.2f}", 
                str(artwork.get('stock', 0)),
                str(artwork.get('description', 'N/A')),
                f"{artwork.get('frame_wooden', 0.0):.2f}", 
                f"{artwork.get('frame_metal', 0.0):.2f}", 
                f"{artwork.get('frame_pvc', 0.0):.2f}", 
                f"{artwork.get('glass_price', 0.0):.2f}", 
                f"{artwork.get('size_a4', 0.0):.2f}", 
                f"{artwork.get('size_a5', 0.0):.2f}", 
                f"{artwork.get('size_letter', 0.0):.2f}", 
                f"{artwork.get('size_legal', 0.0):.2f}" 
            ]
            cw.writerow(row)
            yield si.getvalue()
            si.seek(0)
            si.truncate(0)

    response = Response(generate_csv(), mimetype='text/csv')
    response.headers["Content-Disposition"] = f"attachment; filename=artworks_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return response

if __name__ == '__main__':
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(data_dir, exist_ok=True)
    print(f"Ensured data directory exists: {data_dir}")

    for filename in ['users.json', 'artworks.json', 'orders.json']:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            with open(filepath, 'w') as f:
                if filename in ['orders.json', 'artworks.json']: 
                    json.dump([], f) 
                else: 
                    json.dump({}, f) 
            print(f"Created empty {filename} in data/ directory.")

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
    os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
    os.makedirs(QR_CODES_FOLDER, exist_ok=True)
    print(f"Ensured upload directories exist: {app.config['UPLOAD_FOLDER']}, {PAYMENT_SCREENSHOTS_FOLDER}, {QR_CODES_FOLDER}")

    if os.environ.get('ADMIN_PASSWORD_HASH') is None:
        print("WARNING: ADMIN_PASSWORD_HASH not found in environment variables. Using default 'admin123'. Change this in production!")
        pass 

    app.run(debug=True)
