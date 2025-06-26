import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify, current_app, Response, make_response, g
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

# --- ReportLab Imports for PDF Generation ---
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER

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

# --- YOUR BUSINESS DETAILS (for Invoicing) ---
OUR_BUSINESS_NAME = "Karthikafutures"
OUR_BUSINESS_ADDRESS = "Annapoornna Apartment, Sahapur Colony, New Alipore, Kolkata - 700053"
OUR_GSTIN = "08EXIPR1212L1ZO"
OUR_PAN = "CTMPS6841J"
DEFAULT_GST_RATE_PERCENTAGE = 18.0 # 18% as a default example, stored as percentage
DEFAULT_SHIPPING_CHARGE = 150.00 # Default shipping charge

# --- Define DATA_DIR and ensure it exists FIRST ---
DATA_DIR = os.path.join(app.root_path, 'data')

# Ensure the data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"INFO: Data directory created at {DATA_DIR}")
else:
    print(f"INFO: Data directory already exists at {DATA_DIR}. Skipping creation.")

# --- Define file paths using DATA_DIR ---
ARTWORK_FILE = os.path.join(DATA_DIR, 'artworks.json')
USER_FILE = os.path.join(DATA_DIR, 'users.json')
ORDER_FILE = os.path.join(DATA_DIR, 'orders.json')
CATEGORY_FILE = os.path.join(DATA_DIR, 'categories.json')

# --- FOLDERS FOR UPLOADS AND INVOICES ---
PAYMENT_SCREENSHOTS_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'payment_screenshots')
QR_CODES_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'qr_codes')
INVOICE_PDFS_FOLDER = os.path.join('static', 'invoices') # IMPORTANT: This needs to be static to be served

# Ensure necessary directories exist on startup
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
os.makedirs(QR_CODES_FOLDER, exist_ok=True)
os.makedirs(INVOICE_PDFS_FOLDER, exist_ok=True)

# --- Helper Functions for JSON Data Management (Define these BEFORE use) ---
# --- Helper Functions for JSON Data Management (Define these BEFORE use) ---
def load_json(filepath):
    """Loads JSON data from a file, returning a dict (for users.json) or list (for others)."""
    
    if not os.path.exists(filepath):
        # Determine default structure based on common filenames
        if 'users.json' in filepath:
            return {}
        else: # artworks.json, orders.json, categories.json
            return []
    
    if os.path.getsize(filepath) == 0:
        if 'users.json' in filepath:
            return {}
        else:
            return []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            if 'users.json' in filepath:
                if isinstance(data, list):
                    converted_data = {item.get('email'): item for item in data if item.get('email')}
                    return converted_data
                elif isinstance(data, dict):
                    return data
                else:
                    print(f"WARNING: load_json: Unexpected JSON structure in {os.path.basename(filepath)}. Expected dict or list for users.json. Returning empty dict.")
                    return {}
            else: # For artworks.json, orders.json, categories.json (all should be lists)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict): # Allow for old dict format, convert to list of values
                    print(f"DEBUG: load_json: Converted {os.path.basename(filepath)} dictionary to list of values.")
                    return list(data.values())
                else:
                    print(f"WARNING: load_json: Unexpected JSON structure in {os.path.basename(filepath)}. Expected list. Returning empty list.")
                    return []
    except json.JSONDecodeError as e:
        print(f"ERROR: load_json: JSONDecodeError in {os.path.basename(filepath)}: {e}. File might be corrupted. Returning empty structure.")
        return {} if 'users.json' in filepath else []
    except Exception as e:
        print(f"ERROR: load_json: An unexpected error occurred loading {os.path.basename(filepath)}: {e}. Returning empty structure.")
        return {} if 'users.json' in filepath else []

def save_json(data, filepath): # Corrected order: data, then filepath
    """Saves data (dict or list) to a JSON file."""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"ERROR: save_json: Failed to save data to {os.path.basename(filepath)}: {e}")

# --- Helper Functions for Specific Data Types (Use load_json/save_json here) ---
# These functions now correctly pass the full file path to load_json/save_json
def load_categories():
    return load_json(CATEGORY_FILE)

def save_categories(categories_data):
    save_json(categories_data, CATEGORY_FILE)

def load_artworks():
    return load_json(ARTWORK_FILE)

def save_artworks(artworks_data):
    save_json(artworks_data, ARTWORK_FILE)

def load_users():
    return load_json(USER_FILE)

def save_users(users_data):
    save_json(users_data, USER_FILE)

def load_orders():
    return load_json(ORDER_FILE)

def save_orders(orders_data):
    save_json(orders_data, ORDER_FILE)


# --- Ensure all JSON files exist and are initialized (run this once on startup) ---
# This part should come AFTER all load/save functions are defined.
if not os.path.exists(CATEGORY_FILE) or os.stat(CATEGORY_FILE).st_size == 0:
    with open(CATEGORY_FILE, 'w') as f:
        json.dump([], f, indent=4)
    print(f"INFO: {CATEGORY_FILE} initialized as empty list.")
else:
    print(f"INFO: {CATEGORY_FILE} already exists and is not empty. Skipping initialization.")

if not os.path.exists(ARTWORK_FILE) or os.stat(ARTWORK_FILE).st_size == 0:
    with open(ARTWORK_FILE, 'w') as f:
        json.dump([], f, indent=4) # Artworks are a list
    print(f"INFO: {ARTWORK_FILE} initialized as empty list.")
else:
    print(f"INFO: {ARTWORK_FILE} already exists and is not empty. Skipping initialization.")

if not os.path.exists(USER_FILE) or os.stat(USER_FILE).st_size == 0:
    with open(USER_FILE, 'w') as f:
        json.dump({}, f, indent=4) # Users are a dictionary
    print(f"INFO: {USER_FILE} initialized as empty dictionary.")
else:
    print(f"INFO: {USER_FILE} already exists and is not empty. Skipping initialization.")

if not os.path.exists(ORDER_FILE) or os.stat(ORDER_FILE).st_size == 0:
    with open(ORDER_FILE, 'w') as f:
        json.dump([], f, indent=4) # Orders are a list
    print(f"INFO: {ORDER_FILE} initialized as empty list.")
else:
    print(f"INFO: {ORDER_FILE} already exists and is not empty. Skipping initialization.")


# Ensure default admin user exists
def initialize_admin_user():
    users = load_users() # Use load_users() to get the dict
    if SENDER_EMAIL and SENDER_EMAIL not in users:
        print(f"INFO: Initializing default admin user: {SENDER_EMAIL}")
        if not os.environ.get('ADMIN_PASSWORD_HASH'):
            print("WARNING: ADMIN_PASSWORD_HASH environment variable not set. Using default 'admin123' hash. CHANGE THIS IN PRODUCTION!")
        
        admin_user_id = ADMIN_USERNAME
        
        users[SENDER_EMAIL] = {
            'id': str(uuid.uuid4()), # Always ensure a fresh UUID for the admin when initializing
            'email': SENDER_EMAIL,
            'password_hash': ADMIN_PASSWORD_HASH,
            'name': 'Karthika Futures Admin',
            'phone': '9999999999',
            'address': OUR_BUSINESS_ADDRESS,
            'pincode': '000000',
            'role': 'admin'
        }
        save_users(users) # THIS IS THE CORRECT CALL
        print("INFO: Default admin user created/updated.")
    else:
        print("INFO: Default admin user already exists and is configured. Skipping initialization.")

initialize_admin_user() # This function must be called globally to run on app startup

# Ensure necessary upload directories exist on startup (already done correctly above DATA_DIR)
# Redundant if already handled, but harmless if exists:
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
os.makedirs(QR_CODES_FOLDER, exist_ok=True)
os.makedirs(INVOICE_PDFS_FOLDER, exist_ok=True)
# This line should be at the global level, below the function definition
initialize_admin_user()

if not os.path.exists(ORDER_FILE) or os.stat(ORDER_FILE).st_size == 0:
    with open(ORDER_FILE, 'w') as f:
        json.dump([], f, indent=4) # Orders are a list
    print(f"INFO: {ORDER_FILE} initialized as empty list.")
else:
    print(f"INFO: {ORDER_FILE} already exists and is not empty. Skipping initialization.")


# --- User Model for Flask-Login ---
class User(UserMixin):
    # ... (User class definition as you had it)
    def __init__(self, id, email, name=None, phone=None, address=None, pincode=None, role='user', password_hash=None):
        self.id = str(id)
        self.email = email
        self.name = name
        self.phone = phone
        self.address = address
        self.pincode = pincode
        self.role = role
        self.password_hash = password_hash # Store hashed password here

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
        return self.role == 'admin'

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    users_data = load_users() # Use the proper load_users() function

    if user_id == ADMIN_USERNAME: # Special handling for hardcoded admin login
        # This branch ensures the hardcoded admin can log in without being in users.json
        # However, it's generally better to manage all users, including admin, in users.json
        # The initialize_admin_user() function now attempts to put admin in users.json.
        # This 'if' block can stay for robustness/legacy, but ideally load from users_data
        admin_user_data = users_data.get(SENDER_EMAIL)
        if admin_user_data and admin_user_data['role'] == 'admin':
             return User(
                id=admin_user_data['id'],
                email=admin_user_data['email'],
                name=admin_user_data.get('name', "Admin User"),
                role='admin',
                password_hash=admin_user_data['password_hash']
            )
        # Fallback for old style or if SENDER_EMAIL admin isn't in JSON yet
        return User(
            id=ADMIN_USERNAME,
            email=SENDER_EMAIL,
            name="Admin User",
            role='admin',
            password_hash=ADMIN_PASSWORD_HASH
        )


    # Regular user lookup by ID
    for u_email, u_info in users_data.items():
        if str(u_info.get('id')) == str(user_id):
            return User(
                u_info['id'],
                u_info['email'],
                u_info.get('name'),
                u_info.get('phone'),
                u_info.get('address'),
                u_info.get('pincode'),
                u_info.get('role'),
                u_info.get('password_hash')
            )
    return None

def load_user_by_email(email):
    users_data = load_users() # Use the proper load_users() function
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
            user_info.get('password_hash')
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
        # print(f"DEBUG: admin_required decorator for route {f.__name__}. User authenticated: {current_user.is_authenticated}, Is Admin: {getattr(current_user, 'is_admin', False)}") # Too verbose
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'info')
            # print("DEBUG: admin_required: Not authenticated, redirecting to admin login.")
            return redirect(url_for('admin_login'))
        if not getattr(current_user, 'is_admin', False): 
            flash('Access denied. You must be an administrator to view this page.', 'danger')
            # print(f"DEBUG: admin_required: User '{getattr(current_user, 'email', 'N/A')}' is not an admin, redirecting to index.")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# --- Utility Functions (OTP generation, email sending, Order ID generation, Phone Masking) ---
def generate_otp(length=6): 
    """Generates a 6-digit OTP."""
    return str(random.randint(10**(length-1), (10**length) - 1))

def generate_unique_order_id():
    """Generates a unique 8-digit random order ID."""
    orders = load_json('orders.json') 
    existing_ids = {order.get('order_id') for order in orders}
    
    while True:
        new_id = str(random.randint(10**7, (10**8) - 1)) 
        if new_id not in existing_ids:
            return new_id

def generate_unique_invoice_number():
    """Generates a unique invoice number (e.g., KFI-YYYYMMDD-XXXX)."""
    # Using a simple timestamp-based ID with a random suffix for uniqueness
    timestamp_part = datetime.now().strftime("%Y%m%d")
    random_part = ''.join(random.choices('0123456789', k=4))
    return f"KFI-{timestamp_part}-{random_part}"

def mask_phone_number(phone_number):
    """Masks a phone number for privacy (e.g., +91XXXXX1234)."""
    if not phone_number or not isinstance(phone_number, str) or len(phone_number) < 4:
        return phone_number # Not enough digits or not a string to mask meaningfully
    
    # Assuming standard international format for now.
    # Keep first 3 digits and last 4 digits visible, mask middle.
    # Example: +919876543210 -> +91XXXXX3210
    visible_prefix_len = 3 # e.g., for +91
    visible_suffix_len = 4 # last 4 digits
    
    # Handle numbers shorter than required visible parts
    if len(phone_number) <= visible_prefix_len + visible_suffix_len:
        # Mask all but the last 4 if too short, or show as is if extremely short
        return 'X' * max(0, len(phone_number) - visible_suffix_len) + phone_number[-visible_suffix_len:] if len(phone_number) >= 4 else phone_number

    return phone_number[:visible_prefix_len] + 'X' * (len(phone_number) - visible_prefix_len - visible_suffix_len) + phone_number[-visible_suffix_len:]

# Register mask_phone_number as a Jinja2 filter
app.jinja_env.filters['mask_phone_number'] = mask_phone_number


# --- PDF GENERATION LOGIC (Invoice) ---
def generate_invoice_pdf(order_data):
    """
    Generates an invoice PDF for a given order and returns the path to the saved PDF.
    Order data must include 'invoice_details' sub-dictionary.
    """
    if not order_data or 'invoice_details' not in order_data:
        print("ERROR: Invalid order_data or missing invoice_details for PDF generation.")
        return None

    invoice_details = order_data['invoice_details']
    
    # Define PDF filename and path
    invoice_filename = f"invoice_{order_data['order_id']}_{invoice_details.get('invoice_number', 'N/A')}.pdf" # Use get with default
    pdf_filepath = os.path.join(INVOICE_PDFS_FOLDER, invoice_filename)

    doc = SimpleDocTemplate(pdf_filepath, pagesize=letter,
                            rightMargin=inch/2, leftMargin=inch/2,
                            topMargin=inch/2, bottomMargin=inch/2)
    
    styles = getSampleStyleSheet()
    
    # Define custom styles
    styles.add(ParagraphStyle(name='TitleStyle', fontSize=24, leading=28, alignment=TA_CENTER, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='Heading2', fontSize=14, leading=16, fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='NormalRight', alignment=TA_RIGHT, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='NormalLeft', alignment=TA_LEFT, fontName='Helvetica'))
    styles.add(ParagraphStyle(name='NormalBold', fontName='Helvetica-Bold'))
    styles.add(ParagraphStyle(name='SmallText', fontSize=8, leading=10, fontName='Helvetica'))
    
    story = []

    # --- Header ---
    story.append(Paragraph("TAX INVOICE", styles['TitleStyle']))
    story.append(Spacer(1, 0.2 * inch))

    # Business Details and Invoice Details (Side by Side Table)
    header_data = [
        [Paragraph(f"<b>Sold By:</b> {invoice_details.get('business_name', OUR_BUSINESS_NAME)}", styles['NormalLeft']),
         Paragraph(f"<b>Invoice No:</b> {invoice_details.get('invoice_number', 'N/A')}", styles['NormalRight'])],
        [Paragraph(invoice_details.get('business_address', OUR_BUSINESS_ADDRESS), styles['NormalLeft']),
         Paragraph(f"<b>Invoice Date:</b> {invoice_details.get('invoice_date', 'N/A')}", styles['NormalRight'])],
        [Paragraph(f"GSTIN: {invoice_details.get('gst_number', OUR_GSTIN)}", styles['NormalLeft']),
         Paragraph(f"<b>Order ID:</b> {order_data.get('order_id', 'N/A')}", styles['NormalRight'])],
        [Paragraph(f"PAN: {invoice_details.get('pan_number', OUR_PAN)}", styles['NormalLeft']),
         Paragraph(f"<b>Order Date:</b> {order_data.get('placed_on', 'N/A')}", styles['NormalRight'])],
    ]
    header_table = Table(header_data, colWidths=[4.25 * inch, 3.25 * inch])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.2 * inch))

    # Customer and Shipping Details
    customer_name = order_data.get('customer_name', 'N/A')
    # Use the camouflaged phone from invoice_details if available, else mask directly
    customer_phone_display = invoice_details.get('customer_phone_camouflaged', mask_phone_number(order_data.get('customer_phone', 'N/A')))
    customer_address = order_data.get('customer_address', 'N/A')
    customer_pincode = order_data.get('customer_pincode', 'N/A')
    customer_email = order_data.get('user_email', 'N/A')
    billing_address = invoice_details.get('billing_address', customer_address) # Use stored billing address


    story.append(Paragraph("<b>Bill To / Ship To:</b>", styles['Heading2']))
    story.append(Paragraph(customer_name, styles['NormalLeft']))
    story.append(Paragraph(billing_address, styles['NormalLeft'])) # Use billing address from invoice details
    story.append(Paragraph(f"Pincode: {customer_pincode}", styles['NormalLeft']))
    story.append(Paragraph(f"Phone: {customer_phone_display}", styles['NormalLeft']))
    story.append(Paragraph(f"Email: {customer_email}", styles['NormalLeft']))
    story.append(Spacer(1, 0.2 * inch))

    # Items Table
    item_data = [['#', 'Description', 'Qty', 'Unit Price (₹)', 'Total (₹)']]
    for i, item in enumerate(order_data.get('items', [])): # Safely get items
        description = f"{item.get('name', 'N/A')}"
        if item.get('size') and item['size'] != 'Original': description += f" (Size: {item['size']})"
        if item.get('frame') and item['frame'] != 'None': description += f" (Frame: {item['frame']})"
        if item.get('glass') and item['glass'] != 'None': description += f" (Glass: {item['glass']})"
        
        # item.get('total_price') now includes GST for the item in cart calculations
        item_data.append([
            str(i + 1),
            Paragraph(description, styles['NormalLeft']),
            str(item.get('quantity', 1)),
            f"{item.get('unit_price_before_gst', 0.0):.2f}", # Display unit price before GST
            f"{item.get('total_price', 0.0):.2f}" # Display total price of item WITH GST
        ])

    item_table = Table(item_data, colWidths=[0.5 * inch, 4 * inch, 0.75 * inch, 1.25 * inch, 1.25 * inch])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007bff')), # Header background
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white), # Header text color
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'), # Header alignment
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')), # Row background
        ('GRID', (0,0), (-1,-1), 1, colors.grey), # Grid lines
        ('BOX', (0,0), (-1,-1), 1, colors.black), # Box around table
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'), # # column
        ('ALIGN', (2, 1), (2, -1), 'CENTER'), # Qty column
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'), # Prices columns
        ('RIGHTPADDING', (3, 1), (-1, -1), 10),
        ('LEFTPADDING', (3, 1), (-1, -1), 10),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 0.2 * inch))

    # Totals Section
    subtotal_before_gst = order_data.get('subtotal_before_gst', 0.0)
    gst_rate_for_display = invoice_details.get('gst_rate_applied', DEFAULT_GST_RATE_PERCENTAGE)
    total_gst_amount = invoice_details.get('total_gst_amount', 0.0)
    cgst_amount = invoice_details.get('cgst_amount', 0.0)
    sgst_amount = invoice_details.get('sgst_amount', 0.0)
    shipping_charge = invoice_details.get('shipping_charge', 0.0)
    final_invoice_amount = invoice_details.get('final_invoice_amount', subtotal_before_gst + total_gst_amount + shipping_charge)

    totals_data = [
        ['Subtotal:', f"₹{subtotal_before_gst:.2f}"],
        [f'GST ({gst_rate_for_display:.2f}%):', ''], # GST row, no amount here for main row
        ['&nbsp;&nbsp;&nbsp;&nbsp;CGST:', f"₹{cgst_amount:.2f}"], # CGST indented
        ['&nbsp;&nbsp;&nbsp;&nbsp;SGST:', f"₹{sgst_amount:.2f}"], # SGST indented
        ['Shipping Charges:', f"₹{shipping_charge:.2f}"],
        ['Total Invoice Amount:', f"₹{final_invoice_amount:.2f}"]
    ]
    totals_table = Table(totals_data, colWidths=[5.5 * inch, 2 * inch])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,1), 'Helvetica-Bold'), # Subtotal and GST % label
        ('FONTNAME', (0,2), (-1,3), 'Helvetica'), # CGST/SGST amounts
        ('FONTNAME', (0,4), (-1,4), 'Helvetica-Bold'), # Shipping
        ('FONTNAME', (0,5), (-1,5), 'Helvetica-Bold'), # Final Total
        ('BOTTOMPADDING', (0,0), (-1,4), 6),
        ('TOPPADDING', (0,5), (-1,5), 6),
        ('LINEBELOW', (0,4), (-1,4), 1, colors.black), # Line above shipping
        ('LINEABOVE', (0,5), (-1,5), 1, colors.black), # Line above final total
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e0e0e0')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 0.5 * inch))

    # Footer/Terms
    story.append(Paragraph("Thank you for your business!", styles['NormalBold']))
    story.append(Paragraph("This is a system generated invoice and does not require a signature.", styles['SmallText']))
    story.append(Spacer(1, 0.2 * inch))

    try:
        doc.build(story)
        # print(f"DEBUG: Invoice PDF generated successfully at {pdf_filepath}") # Too verbose
        return os.path.join('invoices', invoice_filename) # Return path relative to static
    except Exception as e:
        print(f"ERROR: Failed to build invoice PDF: {e}")
        return None


# --- Invoice Automation Logic (Simulated Background Task) ---
def process_pending_invoices():
    """
    Checks for orders that need an invoice generated and emailed.
    This simulates a background task for the demo.
    """
    # print("\nDEBUG: process_pending_invoices called.") # Too verbose
    orders = load_json('orders.json')
    artworks_data = load_json('artworks.json') # Load artworks once for efficiency
    artworks_dict_by_sku = {art.get('sku'): art for art in artworks_data}
    updated_orders = False

    for order_idx, order in enumerate(orders):
        # Ensure 'invoice_details' exists for existing orders before processing
        if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
            # print(f"DEBUG: Initializing invoice_details for order {order.get('order_id')}.") # Too verbose
            order['invoice_details'] = {
                "invoice_status": "Not Applicable",
                "is_held_by_admin": False,
                "last_edited_by_admin": None,
                "invoice_number": None,
                "invoice_date": None,
                "gst_number": OUR_GSTIN,
                "pan_number": OUR_PAN,
                "business_name": OUR_BUSINESS_NAME,
                "business_address": OUR_BUSINESS_ADDRESS,
                "total_gst_amount": 0.0,
                "cgst_amount": 0.0,
                "sgst_amount": 0.0,
                "gst_rate_applied": 0.0, # Will be set on shipping or edit
                "shipping_charge": 0.0,
                "final_invoice_amount": order.get('total_amount', 0.0), # Initial subtotal (pre-GST)
                "invoice_pdf_path": None,
                "customer_phone_camouflaged": mask_phone_number(order.get('customer_phone', 'N/A')),
                "billing_address": order.get('customer_address', 'N/A')
            }
            updated_orders = True # Mark as updated if we just added invoice_details

        # Only process orders marked 'Shipped' that haven't had an invoice 'Sent' or 'Held'
        if order.get('status') == 'Shipped' and \
           order['invoice_details'].get('invoice_status') not in ['Sent', 'Held']:
            
            shipped_time_str = order.get('shipped_on')
            if not shipped_time_str:
                print(f"WARNING: Order {order.get('order_id')} shipped but no 'shipped_on' timestamp. Skipping invoice processing.")
                continue

            try:
                shipped_time = datetime.fromisoformat(shipped_time_str) 
                # Check if 24 hours have passed AND invoice is not 'Held' by admin
                if (datetime.now() - shipped_time) >= timedelta(hours=24) and \
                   not order['invoice_details'].get('is_held_by_admin', False):
                    
                    # print(f"DEBUG: Processing invoice for Order ID: {order.get('order_id')} (24h passed, not held).") # Too verbose

                    # Use existing invoice number or generate new one
                    order['invoice_details']['invoice_number'] = order['invoice_details'].get('invoice_number', generate_unique_invoice_number())
                    order['invoice_details']['invoice_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Recalculate amounts for consistency and to apply GST from artwork
                    total_amount_items_subtotal = 0.0 # This will be the sum of item prices BEFORE GST
                    total_gst_on_items = 0.0

                    for item in order.get('items', []): # Safely iterate items
                        # Use unit_price_before_gst from item data if present, otherwise calculate from total_price / (1+GST)
                        # This ensures consistency even if data was older
                        item_price_before_gst_calc = float(item.get('unit_price_before_gst', 0.0)) * int(item.get('quantity', 1))
                        total_amount_items_subtotal += item_price_before_gst_calc
                        
                        # Use item's stored gst_percentage, or artwork's, or default
                        item_gst_rate_percent = item.get('gst_percentage') 
                        if item_gst_rate_percent is None:
                            artwork_for_gst = artworks_dict_by_sku.get(item.get('sku'))
                            item_gst_rate_percent = artwork_for_gst.get('gst_percentage', DEFAULT_GST_RATE_PERCENTAGE) if artwork_for_gst else DEFAULT_GST_RATE_PERCENTAGE
                        
                        total_gst_on_items += item_price_before_gst_calc * (item_gst_rate_percent / 100)

                    # Update order's total_amount with the re-calculated subtotal (before GST)
                    order['subtotal_before_gst'] = round(total_amount_items_subtotal, 2)

                    # If invoice_details had a total_gst_amount, prioritize it, otherwise use the dynamically calculated one
                    if 'total_gst_amount' in order['invoice_details'] and order['invoice_details']['total_gst_amount'] > 0:
                        calculated_gst_amount = order['invoice_details']['total_gst_amount'] 
                    else:
                        calculated_gst_amount = total_gst_on_items
                        order['invoice_details']['total_gst_amount'] = round(calculated_gst_amount, 2)

                    order['invoice_details']['cgst_amount'] = round(calculated_gst_amount / 2, 2)
                    order['invoice_details']['sgst_amount'] = round(calculated_gst / 2, 2)
                    order['invoice_details']['gst_rate_applied'] = round((calculated_gst_amount / total_amount_items_subtotal) * 100, 2) if total_amount_items_subtotal else 0.0

                    # Use admin's edited shipping charge if present, otherwise default
                    shipping_charge = order['invoice_details'].get('shipping_charge', DEFAULT_SHIPPING_CHARGE) 
                    final_amount = total_amount_items_subtotal + calculated_gst_amount + shipping_charge
                    
                    order['invoice_details']['shipping_charge'] = round(shipping_charge, 2) 
                    order['invoice_details']['final_invoice_amount'] = round(final_amount, 2)
                    
                    # Ensure OUR details are always current in the invoice_details sub-dict,
                    # but allow admin edits to override for specific invoice if they exist.
                    order['invoice_details'].setdefault('gst_number', OUR_GSTIN)
                    order['invoice_details'].setdefault('pan_number', OUR_PAN)
                    order['invoice_details'].setdefault('business_name', OUR_BUSINESS_NAME)
                    order['invoice_details'].setdefault('business_address', OUR_BUSINESS_ADDRESS)
                    order['invoice_details'].setdefault('customer_phone_camouflaged', mask_phone_number(order.get('customer_phone', 'N/A')))
                    order['invoice_details'].setdefault('billing_address', order.get('customer_address', 'N/A'))


                    pdf_relative_path = generate_invoice_pdf(order)

                    if pdf_relative_path:
                        order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
                        
                        # Send email
                        try:
                            msg = Message(f"Karthika Futures - Your Invoice for Order #{order['order_id']}",
                                          recipients=[order.get('user_email')])
                            msg.body = render_template('email/invoice_email.txt', order=order, 
                                                       OUR_BUSINESS_NAME=OUR_BUSINESS_NAME, # Pass business details
                                                       OUR_BUSINESS_ADDRESS=OUR_BUSINESS_ADDRESS) 
                            
                            # Attach PDF
                            with app.open_resource(os.path.join('static', pdf_relative_path)) as fp:
                                msg.attach(f"invoice_{order['order_id']}.pdf", "application/pdf", fp.read())
                            
                            with app.app_context(): # Ensure app context for mail.send
                                mail.send(msg)
                            order['invoice_details']['invoice_status'] = 'Sent'
                            print(f"DEBUG: Invoice for Order {order['order_id']} emailed successfully.")
                            # flash(f"Invoice for Order {order['order_id']} sent to customer.", "success") # Don't flash in background task
                            updated_orders = True
                        except Exception as e:
                            order['invoice_details']['invoice_status'] = 'Email Failed'
                            print(f"ERROR: Failed to send invoice email for Order {order['order_id']}: {e}")
                            # flash(f"Failed to send invoice email for Order {order['order_id']}.", "danger") # Don't flash in background task
                            updated_orders = True
                    else:
                        order['invoice_details']['invoice_status'] = 'PDF Gen Failed'
                        print(f"ERROR: PDF generation failed for Order {order['order_id']}.")
                        # flash(f"Failed to generate invoice PDF for Order {order['order_id']}.", "danger") # Don't flash in background task
                        updated_orders = True
                elif order['invoice_details'].get('is_held_by_admin', False):
                    # print(f"DEBUG: Invoice for Order {order.get('order_id')} is on HOLD by admin.") # Too verbose
                    order['invoice_details']['invoice_status'] = 'Held' # Ensure status reflects held
                    # No need to mark updated_orders = True if status is already Held
                else:
                    # Update status to Prepared if not sent/held and time not passed
                    if order['invoice_details'].get('invoice_status') not in ['Prepared', 'Sent', 'Email Failed', 'PDF Gen Failed', 'Edited', 'Cancelled']:
                        order['invoice_details']['invoice_status'] = 'Prepared' # Ready to be sent
                        updated_orders = True
                    # print(f"DEBUG: Invoice for Order {order.get('order_id')} not yet due for sending or processing.") # Too verbose

            except ValueError as ve:
                print(f"ERROR: Invalid date format for order {order.get('order_id')} shipped_on: {shipped_time_str} - {ve}")
            except Exception as ex:
                print(f"ERROR: Unexpected error in process_pending_invoices for order {order.get('order_id')}: {ex}")

    if updated_orders:
        save_json('orders.json', orders)

# Context processor to make current_year available globally
@app.before_request
def before_request():
    g.current_year = datetime.now().year
    # Set session permanent on every request to keep it alive
    session.permanent = True 


# --- ROUTES ---

# General User Logout
@app.route('/logout')
@login_required
def logout():
    # print("\n--- DEBUG: Entering /logout route (general user) ---") # Too verbose
    if current_user.is_authenticated:
        logout_user()
        session.clear() 
        flash("You have been logged out successfully.", "info")
        # print("DEBUG: General user logged out.") # Too verbose
    else:
        flash("You were not logged in.", "warning")
        # print("DEBUG: Logout attempted for unauthenticated user.") # Too verbose
    return redirect(url_for('user_login'))


# Admin Logout
@app.route('/admin-logout')
@login_required
def admin_logout():
    # print("\n--- DEBUG: Entering /admin-logout route ---") # Too verbose
    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        logout_user()
        session.clear() 
        flash("Admin logged out successfully.", "info")
        # print("DEBUG: Admin logged out.") # Too verbose
    else:
        flash("You are not logged in as an admin or your session is invalid.", "warning")
        logout_user() 
        session.clear()
        # print("DEBUG: Non-admin or invalid session logout attempt.") # Too verbose
    return redirect(url_for('admin_login'))

# Admin Login
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    # print("\n--- DEBUG: Entering /admin-login route ---") # Too verbose

    if current_user.is_authenticated and not getattr(current_user, 'is_admin', False):
        flash('Logging out current user to allow admin access.', 'info')
        logout_user()
        session.clear() 
        # print("DEBUG: Regular user logged out to allow admin login.") # Too verbose

    if current_user.is_authenticated and getattr(current_user, 'is_admin', False):
        flash('You are already logged in as admin.', 'info')
        # print("DEBUG: Admin already authenticated, redirecting to admin panel.") # Too verbose
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        # print(f"DEBUG: Admin login POST request received for email: '{email}'") # Too verbose
        # print(f"DEBUG: Admin login POST request received for password (first 4 chars): '{password[:4]}'") # Too verbose

        if not email or not password:
            flash('Both email and password are required for admin login.', 'danger')
            # print("DEBUG: Missing email or password for admin login.") # Too verbose
            return render_template('admin_login.html')

        # Check hardcoded admin credentials first (for initial setup)
        if email == SENDER_EMAIL and check_password_hash(ADMIN_PASSWORD_HASH, password):
            admin_flask_user = User(
                id=ADMIN_USERNAME, # Use ADMIN_USERNAME as ID for the built-in admin
                email=email,
                name="Admin User",
                role='admin',
                password_hash=ADMIN_PASSWORD_HASH
            )
            login_user(admin_flask_user)
            session.permanent = True 
            flash('Admin logged in successfully!', 'success')
            # print(f"DEBUG: Admin '{email}' logged in successfully. Redirecting to admin panel.") # Too verbose
            return redirect(url_for('admin_panel'))
        
        # Also check if an admin user exists in users.json (for later admin users)
        users_data = load_json('users.json')
        user_info = users_data.get(email)
        
        if user_info and user_info.get('role') == 'admin' and check_password_hash(user_info.get('password_hash', ''), password):
            admin_flask_user = User(
                id=user_info['id'],
                email=user_info['email'],
                name=user_info['name'],
                role=user_info['role'],
                password_hash=user_info['password_hash']
            )
            login_user(admin_flask_user)
            session.permanent = True 
            flash('Admin logged in successfully!', 'success')
            # print(f"DEBUG: Admin '{email}' from users.json logged in successfully. Redirecting to admin panel.") # Too verbose
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid admin credentials.', 'danger')
            # print(f"DEBUG: Admin login failed: Credentials mismatch for email: '{email}'.") # Too verbose
            return render_template('admin_login.html')

    # print("DEBUG: Rendering admin_login.html for GET request.") # Too verbose
    return render_template('admin_login.html')

# Admin Panel (Dashboard Summary)
@app.route('/admin-panel')
@admin_required
def admin_panel():
    # print("\n--- DEBUG: Entering /admin-panel route (Dashboard) ---") # Too verbose
    
    # Trigger pending invoice processing on admin panel load
    process_pending_invoices()

    artworks = load_json('artworks.json') 
    orders = load_json('orders.json') 

    # print(f"DEBUG: Admin user '{getattr(current_user, 'email', 'N/A')}' successfully accessed admin dashboard.") # Too verbose
    # print(f"DEBUG: Number of orders loaded for admin panel: {len(orders)}") # Too verbose
    # print(f"DEBUG: Sample order data for admin panel: {orders[:2]}") # Too verbose
    return render_template('admin_panel.html', artworks=artworks, orders=orders) 

# New: Admin Artworks Management View
@app.route('/admin/artworks')
@admin_required
def admin_artworks_view():
    # print("\n--- DEBUG: Entering /admin/artworks route ---") # Too verbose
    artworks = load_json('artworks.json')
    # print(f"DEBUG: Loaded {len(artworks)} artworks for admin_artworks_view.") # Too verbose
    return render_template('admin_artworks_view.html', artworks=artworks)

# New: Admin Orders Management View
@app.route('/admin/orders')
@admin_required
def admin_orders_view():
    # print("\n--- DEBUG: Entering /admin/orders route ---") # Too verbose
    process_pending_invoices() # Ensure invoices are processed before displaying orders
    orders = load_json('orders.json')
    # print(f"DEBUG: Loaded {len(orders)} orders for admin_orders_view.") # Too verbose
    # print(f"DEBUG: Sample order data for admin_orders_view: {orders[:2]}") # Too verbose
    return render_template('admin_orders_view.html', orders=orders)


# Add Artwork
@app.route('/add-artwork', methods=['GET', 'POST'])
@admin_required
def add_artwork():
    # print("\n--- DEBUG: Entering /add-artwork route ---") # Too verbose
    categories = load_json('categories.json') # Load categories for dropdown
    if request.method == 'POST':
        sku = request.form['sku']
        name = request.form['name']
        category = request.form['category']
        original_price = float(request.form['original_price'])
        stock = int(request.form['stock'])
        description = request.form.get('description', '')
        gst_percentage = float(request.form.get('gst_percentage', DEFAULT_GST_RATE_PERCENTAGE)) # New GST field

        frame_wooden = float(request.form.get('frame_wooden', 0.0))
        frame_metal = float(request.form.get('frame_metal', 0.0))
        frame_pvc = float(request.form.get('frame_pvc', 0.0))
        glass_price = float(request.form.get('glass_price', 0.0))
        size_a4 = float(request.form.get('size_a4', 0.0))
        size_a5 = float(request.form.get('size_a5', 0.0))
        size_letter = float(request.form.get('size_letter', 0.0))
        size_legal = float(request.form.get('size_legal', 0.0))

        image_files = request.files.getlist('images') # Get list of files
        # print(f"DEBUG: add_artwork: Received {len(image_files)} image files.") # Too verbose

        artworks = load_json('artworks.json') 

        if any(a.get('sku') == sku for a in artworks): 
            flash('Artwork with this SKU already exists.', 'danger')
            return render_template('add_artwork.html', categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE, **request.form)

        image_urls = []
        if image_files and all(f.filename != '' for f in image_files):
            for image_file in image_files:
                filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(image_file.filename))[1]
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
                    image_file.save(image_path)
                    image_urls.append(f'uploads/{filename}')
                    # print(f"DEBUG: add_artwork: Saved image {filename}.") # Too verbose
                except Exception as e:
                    flash(f"Error saving image: {e}", "danger")
                    print(f"ERROR: add_artwork: Failed to save image: {e}")
                    return render_template('add_artwork.html', categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE, **request.form)
        else:
            flash("At least one image file is required for adding artwork.", "danger")
            return render_template('add_artwork.html', categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE, **request.form)

        new_artwork = {
            'sku': sku,
            'name': name,
            'category': category,
            'original_price': original_price,
            'stock': stock,
            'description': description,
            'images': image_urls, # Store as a list of image URLs
            'gst_percentage': gst_percentage, # Save GST percentage
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
        return redirect(url_for('admin_artworks_view')) # Redirect to new artworks view
    
    return render_template('add_artwork.html', categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE)

# Edit Artwork
@app.route('/edit-artwork/<sku>', methods=['GET', 'POST'])
@admin_required
def edit_artwork(sku):
    # print(f"\n--- DEBUG: Entering /edit-artwork/{sku} route ---") # Too verbose
    artworks = load_json('artworks.json') 
    artwork_obj = next((a for a in artworks if a.get('sku') == sku), None)
    categories = load_json('categories.json') # Load categories for dropdown

    if not artwork_obj:
        flash('Artwork not found.', 'danger')
        # print(f"ERROR: edit_artwork: Artwork {sku} not found.") # Too verbose
        return redirect(url_for('admin_artworks_view'))

    if request.method == 'POST':
        # print(f"DEBUG: edit_artwork: POST request for SKU {sku}.") # Too verbose
        artwork_obj['name'] = request.form.get('name', artwork_obj['name'])
        artwork_obj['category'] = request.form.get('category', artwork_obj['category'])
        artwork_obj['original_price'] = float(request.form.get('original_price', artwork_obj['original_price']))
        artwork_obj['stock'] = int(request.form.get('stock', artwork_obj['stock']))
        artwork_obj['description'] = request.form.get('description', artwork_obj['description'])
        artwork_obj['gst_percentage'] = float(request.form.get('gst_percentage', artwork_obj.get('gst_percentage', DEFAULT_GST_RATE_PERCENTAGE))) # Update GST

        artwork_obj['frame_wooden'] = float(request.form.get('frame_wooden', artwork_obj.get('frame_wooden', 0.0)))
        artwork_obj['frame_metal'] = float(request.form.get('frame_metal', artwork_obj.get('frame_metal', 0.0)))
        artwork_obj['frame_pvc'] = float(request.form.get('frame_pvc', artwork_obj.get('frame_pvc', 0.0)))
        artwork_obj['glass_price'] = float(request.form.get('glass_price', artwork_obj.get('glass_price', 0.0)))
        artwork_obj['size_a4'] = float(request.form.get('size_a4', artwork_obj.get('size_a4', 0.0)))
        artwork_obj['size_a5'] = float(request.form.get('size_a5', artwork_obj.get('size_a5', 0.0)))
        artwork_obj['size_letter'] = float(request.form.get('size_letter', artwork_obj.get('size_letter', 0.0)))
        artwork_obj['size_legal'] = float(request.form.get('size_legal', artwork_obj.get('size_legal', 0.0)))

        # Handle existing images to delete
        images_to_keep_str = request.form.get('images_to_keep', '[]')
        images_to_keep = json.loads(images_to_keep_str)
        
        current_images = artwork_obj.get('images', [])
        new_image_list = []
        for img_url in current_images:
            if img_url in images_to_keep:
                new_image_list.append(img_url)
            else:
                # Delete image file from server
                try:
                    filepath = os.path.join('static', img_url)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        # print(f"DEBUG: edit_artwork: Deleted old image: {filepath}") # Too verbose
                except Exception as e:
                    print(f"ERROR: edit_artwork: Failed to delete image file {filepath}: {e}")

        # Handle new image uploads
        new_image_files = request.files.getlist('new_images')
        # print(f"DEBUG: edit_artwork: Received {len(new_image_files)} new image files.") # Too verbose
        if new_image_files and any(f.filename != '' for f in new_image_files):
            for image_file in new_image_files:
                if image_file.filename != '':
                    filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(image_file.filename))[1]
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    try:
                        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
                        image_file.save(image_path)
                        new_image_list.append(f'uploads/{filename}')
                        # print(f"DEBUG: edit_artwork: Saved new image {filename}.") # Too verbose
                    except Exception as e:
                        flash(f"Error saving new image: {e}", "danger")
                        print(f"ERROR: edit_artwork: Failed to save new image: {e}")
                        return render_template('edit_artwork.html', artwork=artwork_obj, categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE)

        artwork_obj['images'] = new_image_list # Update with modified image list

        save_json('artworks.json', artworks) 
        flash('Artwork updated successfully!', 'success')
        return redirect(url_for('edit_artwork', sku=sku))

    return render_template('edit_artwork.html', artwork=artwork_obj, categories=categories, default_gst_percentage=DEFAULT_GST_RATE_PERCENTAGE) 

# Delete Artwork (Admin only)
@app.route('/delete-artwork/<sku>')
@admin_required
def delete_artwork(sku):
    # print(f"\n--- DEBUG: Entering /delete-artwork/{sku} route ---") # Too verbose
    artworks = load_json('artworks.json') 
    initial_count = len(artworks)
    
    artwork_to_delete = next((a for a in artworks if a.get('sku') == sku), None)

    updated_artworks = [a for a in artworks if a.get('sku') != sku]
    
    if len(updated_artworks) < initial_count: 
        save_json('artworks.json', updated_artworks)
        flash("Artwork deleted successfully.", "info")
        if artwork_to_delete and 'images' in artwork_to_delete and artwork_to_delete['images']:
            for image_url in artwork_to_delete['images']:
                image_filepath = os.path.join('static', image_url)
                if os.path.exists(image_filepath):
                    try:
                        os.remove(image_filepath)
                        # print(f"DEBUG: Image file deleted: {image_filepath}") # Too verbose
                    except Exception as e:
                        print(f"Error deleting image file {image_filepath}: {e}")
    else:
        flash("Artwork not found.", "warning")

    return redirect(url_for('admin_artworks_view')) # Redirect to new artworks view

# Delete Order (Admin only)
@app.route('/delete-order/<order_id>')
@admin_required
def delete_order(order_id):
    # print(f"\n--- DEBUG: Entering /delete-order/{order_id} route ---") # Too verbose
    orders = load_json('orders.json') 
    
    # Find the order to delete using its ID
    order_to_delete_from_list = None
    for order in orders:
        if order.get('order_id') == order_id:
            order_to_delete_from_list = order
            break
    
    if order_to_delete_from_list:
        orders.remove(order_to_delete_from_list) # Remove the found order from the list
        save_json('orders.json', orders) # Save the modified list
        flash(f"Order {order_id} deleted successfully!", "success")
        # print(f"DEBUG: Order {order_id} deleted by admin. {len(orders)} orders remaining.") # Too verbose
    else:
        flash(f"Order {order_id} not found.", "warning")
        # print(f"DEBUG: Admin attempted to delete non-existent order {order_id}.") # Too verbose

    return redirect(url_for('admin_orders_view')) # Redirect to new orders view

# Admin Orders (Update Status/Shipping)
@app.route('/admin-orders-update', methods=['POST']) # Renamed route to avoid conflict with admin_orders_view
@admin_required
def admin_orders_update():
    # print("\n--- DEBUG: Entering /admin-orders-update route ---") # Too verbose
    orders = load_json('orders.json') 

    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    courier = request.form.get('courier', '')
    tracking_number = request.form.get('tracking_number', '')

    # print(f"DEBUG: Admin order update POST received for Order ID: {order_id}, Status: {new_status}") # Too verbose

    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            order_found = True
            order['status'] = new_status
            order['courier'] = courier
            order['tracking_number'] = tracking_number
            
            # If status changes to Shipped, record timestamp and set initial invoice status
            if new_status == 'Shipped':
                order['shipped_on'] = datetime.now().isoformat()
                # Ensure invoice_details exists or initialize it
                if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
                    order['invoice_details'] = {} # Initialize if missing
                order['invoice_details'].setdefault("invoice_status", "Not Applicable") # Will be updated below
                order['invoice_details'].setdefault("is_held_by_admin", False)
                order['invoice_details'].setdefault("last_edited_by_admin", None)
                order['invoice_details'].setdefault("invoice_number", None)
                order['invoice_details'].setdefault("invoice_date", None)
                order['invoice_details'].setdefault("gst_number", OUR_GSTIN)
                order['invoice_details'].setdefault("pan_number", OUR_PAN)
                order['invoice_details'].setdefault("business_name", OUR_BUSINESS_NAME)
                order['invoice_details'].setdefault("business_address", OUR_BUSINESS_ADDRESS)
                order['invoice_details'].setdefault("total_gst_amount", 0.0) # Placeholder, will be calculated by process_pending_invoices
                order['invoice_details'].setdefault("cgst_amount", 0.0)
                order['invoice_details'].setdefault("sgst_amount", 0.0)
                order['invoice_details'].setdefault("gst_rate_applied", 0.0)
                order['invoice_details'].setdefault("shipping_charge", 0.0) # Placeholder
                order['invoice_details'].setdefault("final_invoice_amount", order.get('subtotal_before_gst', order.get('total_amount', 0.0))) # Initial subtotal
                order['invoice_details'].setdefault("invoice_pdf_path", None)
                order['invoice_details'].setdefault("customer_phone_camouflaged", mask_phone_number(order.get('customer_phone', 'N/A')))
                order['invoice_details'].setdefault("billing_address", order.get('customer_address', 'N/A'))

                order['invoice_details']['invoice_status'] = 'Prepared' # Mark as prepared
                order['invoice_details']['is_held_by_admin'] = False # Ensure not held by default
                order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat() # Track last edit
                # print(f"DEBUG: Order {order_id} marked as Shipped. Invoice status set to 'Prepared'.") # Too verbose

            break
    
    if order_found:
        save_json('orders.json', orders)
        flash(f"Order {order_id} updated to '{new_status}'.", "success")
        # After status update, immediately process pending invoices to update the current list for admin view
        process_pending_invoices() 
    else:
        flash(f"Order {order_id} not found.", "danger")
    
    return redirect(url_for('admin_orders_view')) # Redirect to new orders view

# Admin: Hold Invoice
@app.route('/admin/invoice/hold/<order_id>', methods=['POST'])
@admin_required
def admin_hold_invoice(order_id):
    # print(f"\n--- DEBUG: Entering /admin/invoice/hold/{order_id} route ---") # Too verbose
    orders = load_json('orders.json')
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            # Ensure invoice_details exists before trying to access
            if 'invoice_details' not in order:
                order['invoice_details'] = {} # Initialize if missing
            order['invoice_details']['is_held_by_admin'] = True
            order['invoice_details']['invoice_status'] = 'Held'
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order_id} has been put on hold.", "info")
            order_found = True
            break
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
    return redirect(url_for('admin_orders_view')) # Redirect to new orders view

# Admin: Release/Un-hold Invoice
@app.route('/admin/invoice/release/<order_id>', methods=['POST'])
@admin_required
def admin_release_invoice(order_id):
    # print(f"\n--- DEBUG: Entering /admin/invoice/release/{order_id} route ---") # Too verbose
    orders = load_json('orders.json')
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            # Ensure invoice_details exists before trying to access
            if 'invoice_details' not in order:
                order['invoice_details'] = {} # Initialize if missing
            order['invoice_details']['is_held_by_admin'] = False
            # Reset status to 'Prepared' or 'Shipped' if it was 'Held' and not yet sent
            if order['invoice_details'].get('invoice_status') == 'Held':
                order['invoice_details']['invoice_status'] = 'Prepared' # Re-queue for auto-send
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order_id} has been released (no longer on hold).", "info")
            order_found = True
            break
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
    return redirect(url_for('admin_orders_view')) # Redirect to new orders view

# Admin: Edit Invoice Details
@app.route('/admin/invoice/edit/<order_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_invoice(order_id):
    # print(f"\n--- DEBUG: Entering /admin/invoice/edit/{order_id} route ---") # Too verbose
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        # print(f"ERROR: admin_edit_invoice: Order {order_id} not found.") # Too verbose
        return redirect(url_for('admin_orders_view'))

    # Ensure invoice_details exists and is populated
    if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
        # print(f"DEBUG: Initializing invoice_details for order {order_id} in admin_edit_invoice.") # Too verbose
        order['invoice_details'] = {}
    
    # Pre-populate some invoice details if not already present or needs recalculation
    # Use order's subtotal_before_gst for base if present, else total_amount (which was prior subtotal)
    subtotal_before_gst = order.get('subtotal_before_gst', order.get('total_amount', 0.0))

    # Determine default GST rate for form display
    default_gst_rate_for_form = DEFAULT_GST_RATE_PERCENTAGE
    if subtotal_before_gst > 0 and 'total_gst_amount' in order['invoice_details'] and order['invoice_details']['total_gst_amount'] > 0:
        default_gst_rate_for_form = (order['invoice_details']['total_gst_amount'] / subtotal_before_gst) * 100

    order['invoice_details'].setdefault('invoice_number', generate_unique_invoice_number())
    order['invoice_details'].setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    order['invoice_details'].setdefault('total_gst_amount', round(subtotal_before_gst * (default_gst_rate_for_form / 100), 2))
    order['invoice_details'].setdefault('cgst_amount', round(order['invoice_details']['total_gst_amount'] / 2, 2))
    order['invoice_details'].setdefault('sgst_amount', round(order['invoice_details']['total_gst_amount'] / 2, 2))
    order['invoice_details'].setdefault('gst_rate_applied', round(default_gst_rate_for_form, 2)) # Store as percentage
    order['invoice_details'].setdefault('shipping_charge', DEFAULT_SHIPPING_CHARGE)
    order['invoice_details'].setdefault('final_invoice_amount', round(subtotal_before_gst + order['invoice_details']['total_gst_amount'] + order['invoice_details']['shipping_charge'], 2))
    order['invoice_details'].setdefault('gst_number', OUR_GSTIN)
    order['invoice_details'].setdefault('pan_number', OUR_PAN)
    order['invoice_details'].setdefault('business_name', OUR_BUSINESS_NAME)
    order['invoice_details'].setdefault('business_address', OUR_BUSINESS_ADDRESS)
    order['invoice_details'].setdefault('customer_phone_camouflaged', mask_phone_number(order.get('customer_phone', 'N/A')))
    order['invoice_details'].setdefault('billing_address', order.get('customer_address', 'N/A'))
    order['invoice_details'].setdefault('is_held_by_admin', False) # ensure this default is present
    order['invoice_details'].setdefault('invoice_status', 'Prepared') # default to prepared


    if request.method == 'POST':
        # print(f"DEBUG: admin_edit_invoice: POST request for order {order_id}.") # Too verbose
        # Update business details
        order['invoice_details']['business_name'] = request.form.get('business_name', OUR_BUSINESS_NAME)
        order['invoice_details']['business_address'] = request.form.get('business_address', OUR_BUSINESS_ADDRESS)
        order['invoice_details']['gst_number'] = request.form.get('gst_number', OUR_GSTIN)
        order['invoice_details']['pan_number'] = request.form.get('pan_number', OUR_PAN)

        # Update invoice specific details
        order['invoice_details']['invoice_number'] = request.form.get('invoice_number', order['invoice_details']['invoice_number'])
        order['invoice_details']['invoice_date'] = request.form.get('invoice_date', order['invoice_details']['invoice_date'])
        order['invoice_details']['billing_address'] = request.form.get('billing_address', order['invoice_details']['billing_address'])
        
        # Update charges and recalculate final amount
        try:
            shipping_charge = float(request.form.get('shipping_charge', DEFAULT_SHIPPING_CHARGE))
            gst_rate_from_form_percent = float(request.form.get('gst_rate', DEFAULT_GST_RATE_PERCENTAGE))
            gst_rate_from_form_decimal = gst_rate_from_form_percent / 100 # Convert % back to decimal
            
            # Recalculate GST and final amounts based on potentially edited values
            base_total = order.get('subtotal_before_gst', order.get('total_amount', 0.0)) # Subtotal of items in order
            calculated_gst = base_total * gst_rate_from_form_decimal
            final_invoice_amount = base_total + calculated_gst + shipping_charge
            
            order['invoice_details']['shipping_charge'] = round(shipping_charge, 2)
            order['invoice_details']['total_gst_amount'] = round(calculated_gst, 2)
            order['invoice_details']['cgst_amount'] = round(calculated_gst / 2, 2)
            order['invoice_details']['sgst_amount'] = round(calculated_gst / 2, 2)
            order['invoice_details']['gst_rate_applied'] = round(gst_rate_from_form_percent, 2) # Store as percentage
            order['invoice_details']['final_invoice_amount'] = round(final_invoice_amount, 2)
            
            flash('Invoice details updated successfully!', 'success')
            order['invoice_details']['invoice_status'] = 'Edited' # Mark as edited
            order['invoice_details']['is_held_by_admin'] = True # Automatically put on hold if manually edited
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()

        except ValueError:
            flash("Invalid number format for charges. Please enter numeric values.", "danger")
            # print(f"ERROR: admin_edit_invoice: ValueError for numeric input on order {order_id}.") # Too verbose
            # Don't save if values are invalid, let the form render with old values or error
            return render_template('admin_edit_invoice.html', order=order,
                                   our_business_name=OUR_BUSINESS_NAME,
                                   our_business_address=OUR_BUSINESS_ADDRESS,
                                   our_gstin=OUR_GSTIN,
                                   our_pan=OUR_PAN,
                                   default_gst_rate=DEFAULT_GST_RATE_PERCENTAGE, # Pass as percentage for form
                                   now=datetime.now)

        save_json('orders.json', orders)
        return redirect(url_for('admin_edit_invoice', order_id=order_id))

    return render_template('admin_edit_invoice.html', order=order,
                           our_business_name=OUR_BUSINESS_NAME,
                           our_business_address=OUR_BUSINESS_ADDRESS,
                           our_gstin=OUR_GSTIN,
                           our_pan=OUR_PAN,
                           default_gst_rate=DEFAULT_GST_RATE_PERCENTAGE, # Pass as percentage for form
                           now=datetime.now)

# Admin: Send Invoice Email Manually
@app.route('/admin/invoice/send_email/<order_id>', methods=['POST'])
@admin_required
def admin_send_invoice_email(order_id):
    # print(f"\n--- DEBUG: Entering /admin/invoice/send_email/{order_id} route ---") # Too verbose
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        # print(f"ERROR: admin_send_invoice_email: Order {order_id} not found.") # Too verbose
        return redirect(url_for('admin_orders_view'))

    # Ensure invoice_details exists and populate all necessary fields for PDF generation and email
    if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
        # print(f"DEBUG: Initializing invoice_details for order {order_id} in admin_send_invoice_email.") # Too verbose
        order['invoice_details'] = {} 
    
    # Recalculate based on current order data (items, subtotal)
    subtotal_before_gst = order.get('subtotal_before_gst', order.get('total_amount', 0.0))
    # Determine GST rate to apply for this manual send if not already present
    gst_rate_to_apply = order['invoice_details'].get('gst_rate_applied', DEFAULT_GST_RATE_PERCENTAGE)

    total_gst_calc = round(subtotal_before_gst * (gst_rate_to_apply / 100), 2)
    shipping_charge_calc = order['invoice_details'].get('shipping_charge', DEFAULT_SHIPPING_CHARGE)
    final_invoice_calc = round(subtotal_before_gst + total_gst_calc + shipping_charge_calc, 2)

    order['invoice_details'].setdefault("invoice_status", "Not Applicable")
    order['invoice_details'].setdefault("is_held_by_admin", False)
    order['invoice_details'].setdefault("last_edited_by_admin", None)
    order['invoice_details'].setdefault("invoice_number", generate_unique_invoice_number())
    order['invoice_details'].setdefault("invoice_date", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    order['invoice_details'].setdefault("gst_number", OUR_GSTIN)
    order['invoice_details'].setdefault("pan_number", OUR_PAN)
    order['invoice_details'].setdefault("business_name", OUR_BUSINESS_NAME)
    order['invoice_details'].setdefault("business_address", OUR_BUSINESS_ADDRESS)
    order['invoice_details'].setdefault("total_gst_amount", total_gst_calc)
    order['invoice_details'].setdefault("cgst_amount", round(total_gst_calc / 2, 2))
    order['invoice_details'].setdefault("sgst_amount", round(total_gst_calc / 2, 2))
    order['invoice_details'].setdefault("gst_rate_applied", gst_rate_to_apply)
    order['invoice_details'].setdefault("shipping_charge", shipping_charge_calc)
    order['invoice_details'].setdefault("final_invoice_amount", final_invoice_calc)
    order['invoice_details'].setdefault("invoice_pdf_path", None) # Will be set by generate_invoice_pdf
    order['invoice_details'].setdefault("customer_phone_camouflaged", mask_phone_number(order.get('customer_phone', 'N/A')))
    order['invoice_details'].setdefault("billing_address", order.get('customer_address', 'N/A'))
    
    # If PDF path is missing or status is not 'Sent', generate/re-generate the PDF
    pdf_relative_path = order['invoice_details'].get('invoice_pdf_path')
    if (not pdf_relative_path or not os.path.exists(os.path.join('static', pdf_relative_path))) or \
       order['invoice_details'].get('invoice_status') != 'Sent': # Re-generate if status isn't sent
        pdf_relative_path = generate_invoice_pdf(order)

    if pdf_relative_path:
        order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
        
        try:
            msg = Message(f"Karthika Futures - Your Invoice for Order #{order['order_id']} (Manual Send)",
                          recipients=[order.get('user_email')])
            msg.body = render_template('email/invoice_email.txt', order=order,
                                       OUR_BUSINESS_NAME=OUR_BUSINESS_NAME, # Pass business details
                                       OUR_BUSINESS_ADDRESS=OUR_BUSINESS_ADDRESS) 
            
            with app.open_resource(os.path.join('static', pdf_relative_path)) as fp:
                msg.attach(f"invoice_{order['order_id']}.pdf", "application/pdf", fp.read())
            
            with app.app_context(): # Ensure app context for mail.send
                mail.send(msg)
            order['invoice_details']['invoice_status'] = 'Sent'
            order['invoice_details']['is_held_by_admin'] = False # Release hold if sent manually
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order['order_id']} manually sent to customer.", "success")
        except Exception as e:
            order['invoice_details']['invoice_status'] = 'Email Failed'
            save_json('orders.json', orders)
            flash(f"Failed to send invoice email for Order {order['order_id']}: {e}", "danger")
            print(f"ERROR: Manual invoice email send failed for Order {order['order_id']}: {e}")
    else:
        order['invoice_details']['invoice_status'] = 'PDF Gen Failed'
        save_json('orders.json', orders)
        flash(f"Failed to generate invoice PDF for Order {order['order_id']}.", "danger")
        print(f"ERROR: Manual invoice PDF generation failed for Order {order['order_id']}.")

    return redirect(url_for('admin_orders_view')) # Redirect to new orders view


# Route to download the generated invoice PDF
@app.route('/download-invoice/<order_id>')
@login_required
def download_invoice(order_id):
    # print(f"\n--- DEBUG: Entering /download-invoice/{order_id} route ---") # Too verbose
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash("Invoice not found for this order.", "danger")
        # print(f"ERROR: download_invoice: Invoice not found for order {order_id}.") # Too verbose
        return redirect(url_for('my_orders'))

    # Security check: Ensure the current user owns this order OR is an admin
    if str(order.get('user_id')) != str(current_user.id) and not current_user.is_admin:
        flash("You do not have permission to download this invoice.", "danger")
        print(f"SECURITY ALERT: User {current_user.id} tried to download invoice for order {order_id} (owned by {order.get('user_id')}). Access denied.")
        return redirect(url_for('my_orders'))

    # Ensure invoice_details exists
    if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
        # print(f"DEBUG: Initializing invoice_details for order {order_id} in download_invoice as it was missing.") # Too verbose
        order['invoice_details'] = {} # Initialize to prevent error

    # Check if invoice PDF path exists and status allows download
    invoice_details = order.get('invoice_details', {})
    pdf_relative_path = invoice_details.get('invoice_pdf_path')
    invoice_status = invoice_details.get('invoice_status')

    # If PDF doesn't exist on disk but order status indicates it *should* have one, try generating
    if (not pdf_relative_path or not os.path.exists(os.path.join('static', pdf_relative_path))) and \
       order.get('status') == 'Shipped' and \
       invoice_status in ['Prepared', 'Edited', 'Held', 'Email Failed', 'PDF Gen Failed', 'Not Applicable']: # 'Not Applicable' means it hasn't been processed yet
            flash("Invoice PDF not found or outdated. Attempting to generate/regenerate now...", "info")
            # Regenerate PDF with current details
            # Ensure the invoice_details are correctly populated before regeneration
            # This block ensures all needed fields are there for PDF generation if missing
            subtotal_before_gst_for_gen = order.get('subtotal_before_gst', order.get('total_amount', 0.0))
            gst_rate_for_gen = invoice_details.get('gst_rate_applied', DEFAULT_GST_RATE_PERCENTAGE)
            total_gst_for_gen = round(subtotal_before_gst_for_gen * (gst_rate_for_gen / 100), 2)
            shipping_for_gen = invoice_details.get('shipping_charge', DEFAULT_SHIPPING_CHARGE)
            final_for_gen = round(subtotal_before_gst_for_gen + total_gst_for_gen + shipping_for_gen, 2)

            order['invoice_details'].setdefault('invoice_number', generate_unique_invoice_number())
            order['invoice_details'].setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            order['invoice_details'].setdefault('total_gst_amount', total_gst_for_gen)
            order['invoice_details'].setdefault('cgst_amount', round(total_gst_for_gen / 2, 2))
            order['invoice_details'].setdefault('sgst_amount', round(total_gst_for_gen / 2, 2))
            order['invoice_details'].setdefault('gst_rate_applied', gst_rate_for_gen)
            order['invoice_details'].setdefault('shipping_charge', shipping_for_gen)
            order['invoice_details'].setdefault('final_invoice_amount', final_for_gen)
            order['invoice_details'].setdefault('gst_number', OUR_GSTIN)
            order['invoice_details'].setdefault('pan_number', OUR_PAN)
            order['invoice_details'].setdefault('business_name', OUR_BUSINESS_NAME)
            order['invoice_details'].setdefault('business_address', OUR_BUSINESS_ADDRESS)
            order['invoice_details'].setdefault('customer_phone_camouflaged', mask_phone_number(order.get('customer_phone', 'N/A')))
            order['invoice_details'].setdefault('billing_address', order.get('customer_address', 'N/A'))

            pdf_relative_path = generate_invoice_pdf(order)
            if pdf_relative_path:
                order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
                save_json('orders.json', orders) # Save updated path
                # Redirect and try download again immediately
                return redirect(url_for('download_invoice', order_id=order_id)) 
            else:
                flash("Failed to generate invoice PDF. Please contact support.", "danger")
                # print(f"ERROR: download_invoice: Failed to generate invoice PDF for order {order_id} during download attempt.") # Too verbose
                return redirect(url_for('my_orders'))

    # If after potential generation, still no path or file, then fail
    if not pdf_relative_path or not os.path.exists(os.path.join('static', pdf_relative_path)):
        flash("Invoice PDF not found or not yet generated.", "warning")
        # print(f"WARNING: download_invoice: Invoice PDF path missing or file not found for order {order_id}.") # Too verbose
        return redirect(url_for('my_orders'))

    # Only allow download if status is appropriate (e.g., Sent, Prepared, Edited, Email Failed)
    # This prevents users from downloading invoices for cancelled/pending orders even if a PDF somehow exists
    allowed_invoice_statuses = ['Prepared', 'Sent', 'Held', 'Edited', 'Email Failed', 'PDF Gen Failed']
    if invoice_status not in allowed_invoice_statuses:
        flash("Invoice is not yet available for download due to its current status.", "warning")
        # print(f"WARNING: download_invoice: Invoice status '{invoice_status}' for order {order_id} not allowed for download.") # Too verbose
        return redirect(url_for('my_orders'))

    # Provide the PDF for download
    try:
        full_path = os.path.join('static', pdf_relative_path)
        return Response(
            open(full_path, 'rb').read(),
            mimetype='application/pdf',
            headers={"Content-Disposition": f"attachment;filename=invoice_{order_id}.pdf"}
        )
    except FileNotFoundError:
        flash("Invoice PDF file not found on server.", "danger")
        # print(f"ERROR: download_invoice: FileNotFoundError for {full_path}.") # Too verbose
        return redirect(url_for('my_orders'))
    except Exception as e:
        flash(f"Error serving invoice PDF: {e}", "danger")
        print(f"ERROR: download_invoice: Unexpected error serving PDF for {order_id}: {e}")
        return redirect(url_for('my_orders'))


# Home Route
@app.route('/')
def index():
    # print("\n--- DEBUG: Entering / route (homepage) ---") # Too verbose
    # Load all artworks for the homepage display
    all_artworks = load_json('artworks.json') 
    categories = load_json('categories.json')

    # Prepare artworks organized by category
    artworks_by_category = {}
    for category in categories:
        artworks_by_category[category['name']] = [
            artwork for artwork in all_artworks 
            if artwork.get('category') == category['name'] and artwork.get('stock', 0) > 0
        ]
    
    # Also include a list of all distinct categories for the navbar
    distinct_categories = sorted(list(set(cat['name'] for cat in categories)))

    # Testimonial Data (can move to a JSON file later if preferred)
    testimonials = [
        {
            "id": 1,
            "name": "Priya Sharma",
            "image": "https://placehold.co/80x80/007bff/ffffff?text=PS", # Placeholder image
            "rating": 5,
            "feedback": "Absolutely stunning artwork! The paper quality and image clarity are exceptional. The frame is sturdy, and the glass is perfect. Packaging was very secure, and it arrived without a scratch. Highly recommend Karthika Futures for their product quality!",
            "product_id": "SKU001"
        },
        {
            "id": 2,
            "name": "Rajesh Kumar",
            "image": "https://placehold.co/80x80/28a745/ffffff?text=RK", # Placeholder image
            "rating": 5,
            "feedback": "I was amazed by how quickly my order arrived. The delivery was timely and the painting was packed so well, it was completely safe. Payment via UPI was a breeze - so simple and secure. Great experience!",
            "product_id": "SKU002"
        },
        {
            "id": 3,
            "name": "Anjali Singh",
            "image": "https://placehold.co/80x80/ffc107/ffffff?text=AS", # Placeholder image
            "rating": 4,
            "feedback": "Had a small issue with my order, but the return process was incredibly easy and the refund was processed very quickly. Excellent customer service! The artwork itself is beautiful.",
            "product_id": "SKU003"
        },
        {
            "id": 4,
            "name": "Vikram Reddy",
            "image": "https://placehold.co/80x80/dc3545/ffffff?text=VR", # Placeholder image
            "rating": 5,
            "feedback": "The quality of the prints is divine, truly professional. Every detail, from the vibrant colors to the robust framing and crystal-clear glass, speaks of supreme craftsmanship. A joy to behold!",
            "product_id": "SKU004"
        }
    ]

    # print(f"DEBUG: Total artworks loaded for homepage: {len(all_artworks)}") # Too verbose
    return render_template(
        'index.html', 
        all_artworks=all_artworks, # For the 'All Products' section on homepage if desired
        artworks_by_category=artworks_by_category, # For categorized carousels
        categories=distinct_categories, # For dynamic navbar links
        testimonials=testimonials,
        current_user_name=current_user.name if current_user.is_authenticated else None, # For navbar display
        current_year=g.current_year
    )

# All Products Route
@app.route('/all_products')
def all_products():
    # print(f"\n--- DEBUG: Entering /all_products route ---") # Too verbose
    artworks_data = load_json('artworks.json') 
    all_artworks = list(artworks_data) 
    # print(f"DEBUG: Loaded {len(all_artworks)} artworks for /all_products.") # Too verbose
    return render_template('all_products.html', artworks=all_artworks, current_user_name=current_user.name if current_user.is_authenticated else None)

# Product Detail Route 
@app.route('/product/<sku>')
def product_detail(sku):
    # print(f"\n--- DEBUG: Entering /product-detail/{sku} route ---") # Too verbose
    artworks = load_json('artworks.json') 
    artwork = next((item for item in artworks if item.get('sku') == sku), None)
    if artwork:
        # print(f"DEBUG: Found artwork: {artwork.get('name')}. Images: {artwork.get('images', [])}") # Too verbose
        return render_template('product_detail.html', artwork=artwork, current_user_name=current_user.name if current_user.is_authenticated else None)
    flash('Product not found.', 'danger')
    # print(f"ERROR: Artwork with SKU '{sku}' not found for product detail.") # Too verbose
    return redirect(url_for('index'))

# --- User Login/Authentication Routes (Password-based) ---
@app.route('/login', methods=['GET', 'POST'])
def user_login():
    next_url_param = request.args.get('next')
    next_url = next_url_param if next_url_param and is_safe_url(next_url_param) else url_for('index')

    # print(f"\n--- DEBUG: Entering /login route. Next page: {next_url} ---") # Too verbose

    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        # print("DEBUG: User already authenticated, redirecting to user_dashboard.") # Too verbose
        return redirect(url_for('user_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip() # Get password from form
        
        # print(f"DEBUG: Login POST request received for email: {email}") # Too verbose

        if not email or not password:
            flash('Both email and password are required.', 'danger')
            # print("DEBUG: Missing email or password for login.") # Too verbose
            return render_template('user_login.html', next_url=next_url, email=email) 

        users_data = load_json('users.json') 
        user_info = users_data.get(email) 
        
        if user_info and check_password_hash(user_info.get('password_hash', ''), password):
            flask_user = User(
                user_info['id'],
                user_info['email'],
                user_info.get('name'),
                user_info.get('phone'),
                user_info.get('address'),
                user_info.get('pincode'),
                user_info.get('role', 'user'),
                user_info.get('password_hash')
            )
            login_user(flask_user)
            session.permanent = True 
            flash("Logged in successfully.", "success")
            # print(f"DEBUG: User '{email}' logged in successfully.") # Too verbose
            return redirect(next_url)
        else:
            flash('Invalid email or password.', 'danger')
            # print(f"DEBUG: Login failed for {email}: Invalid credentials.") # Too verbose
            return render_template('user_login.html', next_url=next_url, email=email) 

    # print("DEBUG: Rendering user_login.html for GET request.") # Too verbose
    return render_template('user_login.html', next_url=next_url)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # print(f"\n--- DEBUG: Entering /signup route ---") # Too verbose
    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        # print("DEBUG: User already authenticated in signup.") # Too verbose
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        password = request.form.get('password') 
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        pincode = request.form.get('pincode') 

        # print(f"DEBUG: Signup POST received for email: {email}") # Too verbose

        if not all([email, password, name, phone, address, pincode]):
            flash('All fields are required.', 'danger')
            # print("WARNING: Missing required fields for signup.") # Too verbose
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Please enter a valid email address.', 'danger')
            # print("WARNING: Invalid email format for signup.") # Too verbose
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        users = load_json('users.json') 
        # print(f"DEBUG: Users data for signup check (keys): {list(users.keys()) if isinstance(users, dict) else 'Not a dict'}") # Too verbose
        # print(f"DEBUG: Attempting to register email: {email}") # Too verbose

        if email in users: 
            flash('Email already registered. Please log in.', 'danger')
            # print(f"DEBUG: Signup failed: Email '{email}' already exists.") # Too verbose
            return render_template('signup.html', email=email, name=name, phone=phone, address=address, pincode=pincode)

        hashed_password = generate_password_hash(password)

        new_user_data = {
            'id': str(uuid.uuid4()), # Assign a unique ID
            'email': email,
            'password_hash': hashed_password, 
            'name': name,
            'phone': phone,
            'address': address,
            'pincode': pincode,
            'role': 'user' 
        }
        users[email] = new_user_data # Store user data with email as key
        save_users(users)
        
        flash('Account created successfully! Please log in.', 'success')
        # print(f"DEBUG: User '{email}' signed up successfully.") # Too verbose
        return redirect(url_for('user_login')) # Redirect to login page

    return render_template('signup.html')


# --- Password Reset Flow ---
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    # print("\n--- DEBUG: Entering /forgot-password route ---") # Too verbose
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('forgot_password.html')

        user_to_reset = load_user_by_email(email)
        if not user_to_reset:
            flash('No account found with that email address.', 'danger')
            return render_template('forgot_password.html')

        otp_code = generate_otp()
        session['reset_otp_data'] = {
            'email': email,
            'otp': otp_code,
            'timestamp': datetime.now().isoformat()
        }

        try:
            msg = Message('Password Reset OTP for Karthika Futures', recipients=[email])
            msg.body = f'Your One-Time Password for password reset is: {otp_code}\n\nThis OTP is valid for 5 minutes. Do not share it.'
            with app.app_context():
                mail.send(msg)
            flash('A password reset OTP has been sent to your email address. Please check your inbox and spam folder.', 'info')
            return redirect(url_for('reset_password'))
        except Exception as e:
            flash('Failed to send OTP. Please try again later.', 'danger')
            print(f"ERROR: Failed to send password reset OTP to {email}: {e}")
            session.pop('reset_otp_data', None)
            return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    # print("\n--- DEBUG: Entering /reset-password route ---") # Too verbose
    reset_otp_data = session.get('reset_otp_data')
    if not reset_otp_data or 'email' not in reset_otp_data:
        flash('Please initiate the password reset process first.', 'warning')
        return redirect(url_for('forgot_password'))

    email = reset_otp_data['email']

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not user_otp or not new_password or not confirm_password:
            flash('All fields are required.', 'danger')
            return render_template('reset_password.html', email=email)

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', email=email)
        
        # OTP Validation
        stored_otp = reset_otp_data.get('otp')
        otp_timestamp_str = reset_otp_data.get('timestamp')
        
        if not stored_otp or not otp_timestamp_str:
            flash("OTP data incomplete or corrupted. Please request a new one.", "danger")
            session.pop('reset_otp_data', None)
            return redirect(url_for('forgot_password'))

        try:
            otp_timestamp = datetime.fromisoformat(otp_timestamp_str)
        except ValueError:
            flash("Invalid OTP timestamp format. Please request a new one.", "danger")
            session.pop('reset_otp_data', None)
            return redirect(url_for('forgot_password'))

        if (datetime.now() - otp_timestamp).total_seconds() > 300: # 5 minutes
            flash("OTP has expired. Please request a new one.", "danger")
            session.pop('reset_otp_data', None)
            return redirect(url_for('forgot_password'))

        if user_otp != stored_otp:
            flash("Invalid OTP. Please try again.", "danger")
            return render_template('reset_password.html', email=email)

        # OTP is valid, update password
        users_data = load_json('users.json')
        if email in users_data:
            users_data[email]['password_hash'] = generate_password_hash(new_password)
            save_users(users_data)
            session.pop('reset_otp_data', None) # Clear OTP data after successful reset
            flash('Your password has been reset successfully. Please log in with your new password.', 'success')
            return redirect(url_for('user_login'))
        else:
            flash('Account not found. Please try again or register.', 'danger')
            session.pop('reset_otp_data', None)
            return redirect(url_for('signup'))
    
    return render_template('reset_password.html', email=email)


# Cart Update Session (AJAX) Route
@app.route('/update_cart_session', methods=['POST'])
def update_cart_session():
    # print("\n--- DEBUG: Entering /update_cart_session route (AJAX) ---") # Too verbose
    try:
        data = request.get_json()
        client_cart = data.get('cart', {})
        # print(f"DEBUG: update_cart_session: Received client_cart with {len(client_cart)} items.") # Too verbose

        # Load artworks to get GST percentage for each item
        artworks_data = load_json('artworks.json')
        artworks_dict_by_sku = {art.get('sku'): art for art in artworks_data}

        processed_cart = {} # This will store items as a dictionary for easier lookup by ID
        
        items_to_process = []
        if isinstance(client_cart, list):
            items_to_process = client_cart
        elif isinstance(client_cart, dict):
            items_to_process = list(client_cart.values()) # Convert dict to list of values for consistent iteration
        else:
            print(f"WARNING: Unexpected client_cart type in update_cart_session: {type(client_cart)}. Resetting session cart.")
            session['cart'] = {}
            return jsonify(success=False, message="Invalid cart data received."), 400

        for item_data_from_client in items_to_process:
            item = item_data_from_client.copy() # Work on a copy

            item_id = item.get('id')
            if not item_id:
                print(f"WARNING: Item without ID found in cart: {item}. Skipping.")
                continue

            sku = item.get('sku')
            artwork_info = artworks_dict_by_sku.get(sku)

            # Get artwork-specific GST percentage, default if not found
            gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_RATE_PERCENTAGE) if artwork_info else DEFAULT_GST_RATE_PERCENTAGE
            item['gst_percentage'] = gst_percentage # Store in cart item

            unit_price_val = float(item.get('unit_price', 0.0))
            quantity_val = int(item.get('quantity', 1))

            # Calculate price before GST
            item_price_before_gst = unit_price_val * quantity_val
            item['unit_price_before_gst'] = unit_price_val # Store unit price before GST
            item['total_price_before_gst'] = item_price_before_gst # Store total price of this item before GST

            # Calculate GST amount for this item
            item_gst_amount = item_price_before_gst * (gst_percentage / 100)
            item['gst_amount'] = round(item_gst_amount, 2) # Store GST amount for this item

            # Calculate total price including GST for this item
            item_total_price_with_gst = item_price_before_gst + item_gst_amount
            item['total_price'] = round(item_total_price_with_gst, 2) # Store total price including GST

            processed_cart[item_id] = item
        
        session['cart'] = processed_cart
        
        # print(f"DEBUG: Server session['cart'] updated via AJAX. Items: {len(session['cart']) if session['cart'] else 0} ---") # Too verbose
        return jsonify(success=True, message="Cart session updated successfully"), 200
    except Exception as e:
        print(f"ERROR: Failed to update server session cart: {e}")
        return jsonify(success=False, message=f"Failed to update cart: {e}"), 500

# Cart Page
@app.route('/cart')
def cart():
    # print("\n--- DEBUG: Entering /cart route ---") # Too verbose
    # print(f"DEBUG: session['cart'] at /cart start: {session.get('cart')}") # Too verbose

    cart_items_for_display = []
    subtotal_before_gst = 0.0
    total_gst_amount = 0.0
    cgst_amount = 0.0
    sgst_amount = 0.0
    shipping_charge = 0.0 # Default to 0 for display, will be set to DEFAULT_SHIPPING_CHARGE if items exist
    grand_total = 0.0

    current_session_cart = session.get('cart', {})

    if isinstance(current_session_cart, list):
        # print("DEBUG: /cart found session['cart'] as a list, converting to dict.") # Too verbose
        current_session_cart = {item.get('id'): item for item in current_session_cart if item.get('id')}
        session['cart'] = current_session_cart
    elif not isinstance(current_session_cart, dict):
        # print(f"WARNING: /cart found session['cart'] as unexpected type {type(current_session_cart)}, resetting to empty.") # Too verbose
        current_session_cart = {}
        session['cart'] = current_session_cart

    if current_session_cart:
        try:
            # print("\n--- DEBUG: Processing cart for /cart page display ---") # Too verbose
            for item_id, item_data_original in current_session_cart.items():
                item_data = item_data_original.copy()
                
                # These values should already be calculated by update_cart_session
                item_total_price_before_gst = item_data.get('total_price_before_gst', 0.0)
                item_gst_amount = item_data.get('gst_amount', 0.0)
                item_total_price_with_gst = item_data.get('total_price', 0.0)

                subtotal_before_gst += item_total_price_before_gst
                total_gst_amount += item_gst_amount
                
                item_data['calculated_display_price'] = item_total_price_with_gst 
                cart_items_for_display.append(item_data)
                
                # print(f" Item ID: {item_id}, Name: {item_data.get('name')}, Qty: {item_data.get('quantity')}, Unit Price (Pre-GST): {item_data.get('unit_price_before_gst')}, Item Total (With GST): {item_total_price_with_gst}") # Too verbose
            
            # Apply shipping charge only if there are items in the cart
            if subtotal_before_gst > 0:
                shipping_charge = DEFAULT_SHIPPING_CHARGE

            cgst_amount = round(total_gst_amount / 2, 2)
            sgst_amount = round(total_gst_amount / 2, 2)
            grand_total = round(subtotal_before_gst + total_gst_amount + shipping_charge, 2)

            # print(f" FINAL Subtotal (Pre-GST) for /cart page: {subtotal_before_gst:.2f}") # Too verbose
            # print(f" FINAL Total GST Amount for /cart page: {total_gst_amount:.2f}") # Too verbose
            # print(f" FINAL CGST Amount for /cart page: {cgst_amount:.2f}") # Too verbose
            # print(f" FINAL SGST Amount for /cart page: {sgst_amount:.2f}") # Too verbose
            # print(f" FINAL Shipping Charge for /cart page: {shipping_charge:.2f}") # Too verbose
            # print(f" FINAL Grand Total for /cart page: {grand_total:.2f}") # Too verbose
            # print("--------------------------------------------------\n") # Too verbose

            if not cart_items_for_display:
                flash('Your cart is empty. Please add items before checking out.', 'info')

        except Exception as e:
            print(f"ERROR: Error processing cart from session for /cart page: {e}")
            flash('There was an error loading your cart. Please try again.', 'danger')
            cart_items_for_display = []
            subtotal_before_gst = 0.0
            total_gst_amount = 0.0
            cgst_amount = 0.0
            sgst_amount = 0.0
            shipping_charge = 0.0 # Reset to 0 on error
            grand_total = 0.0
    else:
        flash('Your cart is empty. Please add items before checking out.', 'info')

    return render_template('cart.html', 
                           cart_items=cart_items_for_display, 
                           subtotal_before_gst=subtotal_before_gst,
                           total_gst_amount=total_gst_amount,
                           cgst_amount=cgst_amount,
                           sgst_amount=sgst_amount,
                           shipping_charge=shipping_charge, # This will be 0 if cart is empty
                           grand_total=grand_total,
                           current_user_name=current_user.name if current_user.is_authenticated else None)

# Purchase Form
@app.route('/purchase-form', methods=['GET', 'POST'])
@login_required 
def purchase_form():
    user = current_user

    # print("\n--- DEBUG: Entering /purchase-form route ---") # Too verbose
    # print(f"DEBUG: request.method: {request.method}") # Too verbose
    # print(f"DEBUG: session['cart'] at /purchase-form start: {session.get('cart')}") # Too verbose

    # Load artworks data once to get GST percentages
    artworks_data = load_json('artworks.json')
    artworks_dict_by_sku = {art.get('sku'): art for art in artworks_data}

    if request.method == 'POST':
        # print(f"\n--- DEBUG: POST Request Form Data Received (Overall) ---") # Too verbose
        
        cart_from_session = session.get('cart', {})
        items_from_cart = list(cart_from_session.values()) # Get current server-side cart items

        # This logic handles both the initial POST from cart.html (which just displays the form)
        # and the final POST from purchase-form.html (which places the order).
        # We differentiate by checking for the presence of customer details.
        if 'name' not in request.form or not request.form.get('name'): 
            # This is likely the initial POST from cart.html (or an invalid submission)
            # print("DEBUG: This is the FIRST POST (from cart.html) to /purchase-form (or initial load issues).") # Too verbose
            
            # Use cart_json from form for initial display if provided, otherwise use session cart
            cart_json_from_form = request.form.get('cart_json')
            if cart_json_from_form:
                try:
                    items_from_cart_raw = json.loads(cart_json_from_form)
                    if not items_from_cart_raw:
                        flash('Your cart is empty. Please add items before checking out.', 'info')
                        # print("DEBUG: cart_json is empty in First POST (from form), redirecting to /cart.") # Too verbose
                        return redirect(url_for('cart')) 
                    
                    # Process items from raw JSON from form to populate display data
                    processed_items_for_display = []
                    subtotal_before_gst = 0.0
                    total_gst_amount = 0.0
                    shipping_charge_from_form = float(request.form.get('shipping_charge', 0.0)) # Get from form for display
                    if subtotal_before_gst > 0: # Ensure shipping is only added if there are items
                        shipping_charge_from_form = DEFAULT_SHIPPING_CHARGE


                    for item_data in items_from_cart_raw:
                        item = item_data.copy() 
                        sku = item.get('sku')
                        artwork_info = artworks_dict_by_sku.get(sku)
                        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_RATE_PERCENTAGE) if artwork_info else DEFAULT_GST_RATE_PERCENTAGE
                        
                        unit_price_val = float(item.get('unit_price', 0.0))
                        quantity_val = int(item.get('quantity', 1))
                        
                        item_price_before_gst = unit_price_val * quantity_val
                        item_gst_amount = item_price_before_gst * (gst_percentage / 100)
                        item_total_price_with_gst = item_price_before_gst + item_gst_amount
                        
                        subtotal_before_gst += item_price_before_gst
                        total_gst_amount += item_gst_amount
                        
                        item['price'] = round(item_total_price_with_gst, 2) # Price for display
                        item['unit_price_before_gst'] = unit_price_val
                        item['total_price_before_gst'] = round(item_price_before_gst, 2)
                        item['gst_percentage'] = gst_percentage
                        item['gst_amount'] = round(item_gst_amount, 2)
                        item['total_price'] = round(item_total_price_with_gst, 2) # Final total for item
                        
                        processed_items_for_display.append(item)

                    # print(f"DEBUG (First POST): Calculating totals based on cart_json from form.") # Too verbose
                    cgst_amount = round(total_gst_amount / 2, 2)
                    sgst_amount = round(total_gst_amount / 2, 2)
                    grand_total_final = round(subtotal_before_gst + total_gst_amount + shipping_charge_from_form, 2)

                    context = {
                        'prefill_name': user.name or '',
                        'prefill_email': user.email or '',
                        'prefill_email_type': 'text', # Always text if logged in, to show value
                        'prefill_phone': user.phone or '',
                        'prefill_address': user.address or '',
                        'prefill_pincode': user.pincode or '',
                        'cart_json': json.dumps(processed_items_for_display), # Save processed items back to JSON
                        'items_for_display': processed_items_for_display,
                        'subtotal_before_gst': subtotal_before_gst,
                        'total_gst_amount': total_gst_amount,
                        'cgst_amount': cgst_amount,
                        'sgst_amount': sgst_amount,
                        'shipping_charge': shipping_charge_from_form,
                        'grand_total': grand_total_final,
                        'current_user_name':current_user.name # For navbar display
                    }
                    return render_template('purchase-form.html', **context)

                except json.JSONDecodeError:
                    flash('Error processing cart data. Please try again.', 'danger')
                    # print(f"DEBUG (First POST): JSON Decode Error for cart_json: {cart_json_from_form}") # Too verbose
                    return redirect(url_for('cart'))
                except Exception as e:
                    flash(f'An unexpected error occurred during cart processing: {e}', 'danger')
                    print(f"DEBUG (First POST): Unexpected error processing cart: {e}")
                    return redirect(url_for('cart'))
            else:
                flash('Cart data missing. Please go back to cart and try again.', 'danger')
                # print("DEBUG: Initial POST to /purchase-form without cart_json from form. Redirecting to /cart.") # Too verbose
                return redirect(url_for('cart'))

        else: # This is the SECOND POST (from purchase-form.html) - Final submission
            # print("DEBUG: This is the SECOND POST (from purchase-form.html) to /purchase-form. Final order submission.") # Too verbose
            name = request.form.get('name')
            email = request.form.get('email') # Should be user's email if logged in
            phone = request.form.get('phone')
            address = request.form.get('address')
            pincode = request.form.get('pincode')
            shipping_charge_final = float(request.form.get('shipping_charge', DEFAULT_SHIPPING_CHARGE))

            if not all([name, phone, address, pincode]):
                flash('All fields (Name, Phone, Address, Pincode) are required.', 'danger')
                # print("WARNING: Missing required delivery details on final purchase form submission.") # Too verbose
                # Re-render form with current data if validation fails
                current_cart_items_for_display = []
                subtotal_before_gst = 0.0
                total_gst_amount = 0.0
                try:
                    # Reconstruct display items from the session cart for re-rendering
                    for item_data in items_from_cart: # Use items_from_cart (from session)
                        item = item_data.copy()
                        subtotal_before_gst += item.get('total_price_before_gst', 0.0)
                        total_gst_amount += item.get('gst_amount', 0.0)
                        current_cart_items_for_display.append(item)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"ERROR: Failed to re-process cart JSON on form validation error: {e}")
                
                cgst_amount = round(total_gst_amount / 2, 2)
                sgst_amount = round(total_gst_amount / 2, 2)
                grand_total_final_on_error = round(subtotal_before_gst + total_gst_amount + shipping_charge_final, 2)

                context_on_error = {
                    'prefill_name': name,
                    'prefill_email': email,
                    'prefill_email_type': 'text',
                    'prefill_phone': phone,
                    'prefill_address': address,
                    'prefill_pincode': pincode,
                    'cart_json': json.dumps(current_cart_items_for_display), # Send current state back
                    'items_for_display': current_cart_items_for_display,
                    'subtotal_before_gst': subtotal_before_gst,
                    'total_gst_amount': total_gst_amount,
                    'cgst_amount': cgst_amount,
                    'sgst_amount': sgst_amount,
                    'shipping_charge': shipping_charge_final,
                    'grand_total': grand_total_final_on_error,
                    'current_user_name':current_user.name # For navbar display
                }
                return render_template('purchase-form.html', **context_on_error)
            
            if not items_from_cart: # Check if server-side cart is empty
                flash('Your cart is empty. Please add items before checking out.', 'danger')
                # print("DEBUG: Server-side cart is empty in Second POST, redirecting to /cart.") # Too verbose
                return redirect(url_for('cart'))

            try:
                subtotal_before_gst = 0.0
                total_gst_amount = 0.0
                # print("\n--- DEBUG: Calculating grand_total for SECOND POST (order processing) ---") # Too verbose
                for item in items_from_cart: # Use server-side cart
                    item_price_before_gst = item.get('total_price_before_gst', 0.0)
                    item_gst_amount = item.get('gst_amount', 0.0)
                    
                    subtotal_before_gst += item_price_before_gst
                    total_gst_amount += item_gst_amount
                    # print(f" Item: {item.get('name', 'N/A')}, Total Price (Pre-GST): {item_price_before_gst:.2f}, Item GST Amt: {item_gst_amount:.2f}") # Too verbose
                
                # Ensure shipping charge is applied if there are items, otherwise 0
                if subtotal_before_gst == 0:
                    shipping_charge_final = 0.0

                cgst_amount = round(total_gst_amount / 2, 2)
                sgst_amount = round(total_gst_amount / 2, 2)
                grand_total_final = round(subtotal_before_gst + total_gst_amount + shipping_charge_final, 2)

                # print(f" FINAL Subtotal (Pre-GST) (SECOND POST): {subtotal_before_gst:.2f}") # Too verbose
                # print(f" FINAL Total GST Amount (SECOND POST): {total_gst_amount:.2f}") # Too verbose
                # print(f" FINAL CGST Amount (SECOND POST): {cgst_amount:.2f}") # Too verbose
                # print(f" FINAL SGST Amount (SECOND POST): {sgst_amount:.2f}") # Too verbose
                # print(f" FINAL Shipping Charge (SECOND POST): {shipping_charge_final:.2f}") # Too verbose
                # print(f" FINAL Grand Total (SECOND POST): {grand_total_final:.2f}") # Too verbose
                # print("--------------------------------------------------\n") # Too verbose

                orders = load_json('orders.json')
                # print(f"DEBUG: Current orders list size before new order: {len(orders)}") # Too verbose

                order_id = generate_unique_order_id() 
                new_order = {
                    "order_id": order_id,
                    "user_id": user.id,
                    "user_email": user.email,
                    "customer_name": name,
                    "customer_phone": phone,
                    "customer_address": address,
                    "customer_pincode": pincode,
                    "subtotal_before_gst": subtotal_before_gst, # Store subtotal before GST
                    "total_amount": grand_total_final, # total_amount now represents the grand total for payment
                    "items": items_from_cart, # Items now contain GST breakdown
                    "status": "Pending Payment",
                    "courier": "",
                    "tracking_number": "",
                    "placed_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "shipped_on": None, # Initialize shipped_on for new orders
                    "payment_submitted_on": None, # Initialize payment_submitted_on
                    # New invoice details
                    "invoice_details": {
                        "invoice_status": "Not Applicable", # Default status before Shipped
                        "is_held_by_admin": False,
                        "last_edited_by_admin": None,
                        "invoice_number": None,
                        "invoice_date": None,
                        "gst_number": OUR_GSTIN,
                        "pan_number": OUR_PAN,
                        "business_name": OUR_BUSINESS_NAME,
                        "business_address": OUR_BUSINESS_ADDRESS,
                        "total_gst_amount": total_gst_amount,
                        "cgst_amount": cgst_amount,
                        "sgst_amount": sgst_amount,
                        "gst_rate_applied": round((total_gst_amount / subtotal_before_gst) * 100, 2) if subtotal_before_gst else 0.0,
                        "shipping_charge": shipping_charge_final,
                        "final_invoice_amount": grand_total_final, # Matches total_amount
                        "invoice_pdf_path": None,
                        "customer_phone_camouflaged": mask_phone_number(phone),
                        "billing_address": address # Assuming shipping address is billing address
                    },
                    "remark": "" # Initialize remark field for new orders
                }
                orders.append(new_order)
                save_json('orders.json', orders) # Ensure save is explicitly called here
                # print(f"DEBUG: New order {order_id} appended and saved to orders.json. New list size: {len(orders)}") # Too verbose

                session.pop('cart', None) # Clear server-side cart after order is placed

                flash('Your order has been created. Redirecting to payment!', 'info')
                return redirect(url_for('payment_initiate', order_id=order_id, amount=grand_total_final))

            except Exception as e:
                flash(f'An unexpected error occurred while placing your order: {e}', 'danger')
                print(f"ERROR: (Second POST): Unexpected error placing order: {e}")
                # Re-render form with current data if order placement fails
                current_cart_items_for_display = []
                subtotal_before_gst = 0.0
                total_gst_amount = 0.0
                try:
                    for item_data in items_from_cart: 
                        item = item_data.copy()
                        subtotal_before_gst += item.get('total_price_before_gst', 0.0)
                        total_gst_amount += item.get('gst_amount', 0.0)
                        current_cart_items_for_display.append(item)
                except (json.JSONDecodeError, KeyError) as e:
                    print(f"ERROR: Failed to re-process cart JSON on order placement error: {e}")
                
                cgst_amount = round(total_gst_amount / 2, 2)
                sgst_amount = round(total_gst_amount / 2, 2)
                grand_total_final_on_error = round(subtotal_before_gst + total_gst_amount + shipping_charge_final, 2)

                context_on_error = {
                    'prefill_name': name,
                    'prefill_email': email,
                    'prefill_email_type': 'text',
                    'prefill_phone': phone,
                    'prefill_address': address,
                    'prefill_pincode': pincode,
                    'cart_json': json.dumps(current_cart_items_for_display), # Send current state back
                    'items_for_display': current_cart_items_for_display,
                    'subtotal_before_gst': subtotal_before_gst,
                    'total_gst_amount': total_gst_amount,
                    'cgst_amount': cgst_amount,
                    'sgst_amount': sgst_amount,
                    'shipping_charge': shipping_charge_final,
                    'grand_total': grand_total_final_on_error,
                    'current_user_name':current_user.name # For navbar display
                }
                return render_template('purchase-form.html', **context_on_error)

    elif request.method == 'GET':
        # print("DEBUG: This is a GET request to /purchase-form.") # Too verbose
        current_cart_items_for_display = [] 
        subtotal_before_gst = 0.0
        total_gst_amount = 0.0
        shipping_charge_for_display = 0.0 # Default to 0 for initial GET

        cart_data_from_session = session.get('cart', {})

        if isinstance(cart_data_from_session, list):
            # print("DEBUG: GET /purchase-form found session['cart'] as a list, converting to dict.") # Too verbose
            cart_data_from_session = {item.get('id'): item for item in cart_data_from_session if item.get('id')}
            session['cart'] = cart_data_from_session 
        elif not isinstance(cart_data_from_session, dict):
            # print(f"WARNING: GET /purchase-form found session['cart'] as unexpected type {type(cart_data_from_session)}, resetting to empty dict.") # Too verbose
            cart_data_from_session = {}
            session['cart'] = cart_data_from_session 

        if cart_data_from_session:
            try:
                # print("\n--- DEBUG: Calculating totals for GET request (rendering form) ---") # Too verbose
                for item_id, item_data_original in cart_data_from_session.items():
                    item_data = item_data_original.copy() 
                    
                    # These values should already be calculated by update_cart_session
                    item_price_before_gst = item_data.get('total_price_before_gst', 0.0)
                    item_gst_amount = item_data.get('gst_amount', 0.0)
                    item_total_price_with_gst = item_data.get('total_price', 0.0)

                    subtotal_before_gst += item_price_before_gst
                    total_gst_amount += item_gst_amount
                    
                    item_data['price'] = round(item_total_price_with_gst, 2) # Price for display
                    current_cart_items_for_display.append(item_data)

                    # print(f" Item ID: {item_id}, Unit Price (Pre-GST): {item_data.get('unit_price_before_gst')}, Item Total (With GST): {item_total_price_with_gst:.2f}") # Too verbose

                # Apply shipping charge only if there are items
                if subtotal_before_gst > 0:
                    shipping_charge_for_display = DEFAULT_SHIPPING_CHARGE

                cgst_amount = round(total_gst_amount / 2, 2)
                sgst_amount = round(total_gst_amount / 2, 2)
                grand_total_final = round(subtotal_before_gst + total_gst_amount + shipping_charge_for_display, 2) # Use default shipping for initial GET

                # print(f" FINAL Subtotal (Pre-GST) (GET): {subtotal_before_gst:.2f}") # Too verbose
                # print(f" FINAL Total GST Amount (GET): {total_gst_amount:.2f}") # Too verbose
                # print(f" FINAL CGST Amount (GET): {cgst_amount:.2f}") # Too verbose
                # print(f" FINAL SGST Amount (GET): {sgst_amount:.2f}") # Too verbose
                # print(f" FINAL Shipping Charge (GET): {shipping_charge_for_display:.2f}") # Too verbose
                # print(f" FINAL Grand Total (GET): {grand_total_final:.2f}") # Too verbose
                # print("--------------------------------------------------\n") # Too verbose

                if not current_cart_items_for_display:
                    # print("DEBUG: current_cart_items_for_display is empty, redirecting to /cart.") # Too verbose
                    return redirect(url_for('cart'))
            except Exception as e:
                print(f"DEBUG (GET): Error processing cart from session: {e}")
                flash('There was an error loading your cart. Please try again.', 'danger')
                return redirect(url_for('cart'))
        else:
            # print("DEBUG: Session cart is empty in GET /purchase-form, redirecting to /cart.") # Too verbose
            return redirect(url_for('cart'))

        context = {
            'prefill_name': user.name or '',
            'prefill_email': user.email or '',
            'prefill_email_type': 'text', # Always text if logged in, to show value
            'prefill_phone': user.phone or '',
            'prefill_address': user.address or '',
            'prefill_pincode': user.pincode or '',
            'cart_items': current_cart_items_for_display, 
            'subtotal_before_gst': subtotal_before_gst,
            'total_gst_amount': total_gst_amount,
            'cgst_amount': cgst_amount,
            'sgst_amount': sgst_amount,
            'shipping_charge': shipping_charge_for_display,
            'grand_total': grand_total_final,
            'cart_json': json.dumps(current_cart_items_for_display), # This passes the processed items back
            'current_user_name':current_user.name # For navbar display
        }

        # print(f"DEBUG (GET /purchase-form): Grand Total passed to template: {grand_total_final:.2f}") # Too verbose
        return render_template('purchase-form.html', **context)
    
    # This return should ideally not be reached if previous checks redirect
    return redirect(url_for('index'))

# Payment Initiate Page
@app.route('/payment-initiate/<order_id>/<float:amount>', methods=['GET'])
@login_required
def payment_initiate(order_id, amount):
    # print(f"\n--- DEBUG: Entering /payment-initiate route ---") # Too verbose
    # print(f"DEBUG: Received order_id: {order_id}, amount: {amount}") # Too verbose

    # UPI Payment Details
    upi_id = "smarasada@okaxis"
    banking_name = "SUBHASH S" 
    
    orders = load_json('orders.json') 
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        flash('Order not found. Please try again.', 'danger')
        # print(f"ERROR: Order with ID {order_id} not found for payment initiation.") # Too verbose
        return redirect(url_for('my_orders')) 

    # 'total_amount' in order now represents the final grand total after GST and shipping
    if abs(order.get('total_amount', 0.0) - amount) > 0.01: # Use a small tolerance for float comparison
        flash('Payment amount mismatch. Please try again or contact support.', 'danger')
        # print(f"WARNING: Amount mismatch for order {order_id}. Expected {order.get('total_amount', 0.0):.2f}, Got {amount:.2f}.") # Too verbose
        return redirect(url_for('my_orders'))

    context = {
        'order_id': order_id,
        'amount': amount,
        'upi_id': upi_id,
        'banking_name': banking_name,
        'current_user_name':current_user.name # For navbar display
    }
    # print("DEBUG: Rendering payment-initiate.html with context:", context) # Too verbose
    return render_template('payment-initiate.html', **context)

# Confirm Payment Details
@app.route('/confirm_payment', methods=['POST'])
@login_required
def confirm_payment():
    # print(f"\n--- DEBUG: Entering /confirm_payment route ---") # Too verbose
    order_id = request.form.get('order_id')
    transaction_id = request.form.get('transaction_id')
    screenshot_file = request.files.get('screenshot')

    # print(f"DEBUG: Confirm payment POST received for Order ID: {order_id}, Transaction ID: {transaction_id}") # Too verbose

    if not all([order_id, transaction_id]):
        flash('Order ID and Transaction ID are required.', 'danger')
        # print("ERROR: Missing order_id or transaction_id in confirm_payment.") # Too verbose
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
            # print(f"DEBUG: Screenshot saved to: {screenshot_path}") # Too verbose
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
            # print(f"DEBUG: Order {order_id} status updated to '{order['status']}'.") # Too verbose
            break

    if order_found:
        save_json('orders.json', orders)
        session.pop('cart', None) # Clear server-side cart after order is placed
        # print("DEBUG: Server-side session cart cleared after payment confirmation.") # Too verbose
        flash('Payment details submitted successfully. Your order status will be updated after verification.', 'success')
        # print("DEBUG: Redirecting to thank_you page.") # Too verbose
        # Prevent going back to payment page
        response = make_response(redirect(url_for('thank_you_page')))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    else:
        flash('Order not found. Please ensure you are submitting details for a valid order.', 'danger')
        # print(f"ERROR: Order {order_id} not found when confirming payment.") # Too verbose
        return redirect(url_for('my_orders')) 

@app.route('/thank-you')
def thank_you_page():
    # print("\n--- DEBUG: Entering /thank-you route ---") # Too verbose
    return render_template('thank-you.html', current_user_name=current_user.name if current_user.is_authenticated else None)


# --- USER SPECIFIC ROUTES ---
@app.route('/my-orders')
@login_required
def my_orders():
    # print("\n--- DEBUG: Entering /my-orders route ---") # Too verbose
    
    # Trigger pending invoice processing on admin panel load
    process_pending_invoices() # Also check here, so user sees updated invoice status

    # print(f"DEBUG: Current user ID for /my-orders: {current_user.id}") # Too verbose
    orders = load_json('orders.json') 
    user_orders = []
    for order in orders:
        # print(f"DEBUG: Checking order ID: {order.get('order_id')}, User ID in order: {order.get('user_id')}, Match: {str(order.get('user_id')) == str(current_user.id)}") # Too verbose
        # Ensure 'remark' field exists for all orders before passing to template
        order['remark'] = order.get('remark', '') 
        if str(order.get('user_id')) == str(current_user.id):
            user_orders.append(order)

    # print(f"DEBUG: Found {len(user_orders)} orders for user {current_user.id}.") # Too verbose
    return render_template('my_orders.html', orders=user_orders, current_user_name=current_user.name if current_user.is_authenticated else None)

@app.route('/cancel-order/<order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    # print(f"\n--- DEBUG: Entering /cancel-order route for order_id: {order_id} ---") # Too verbose
    orders = load_json('orders.json')
    order_found = False
    
    for order_idx, order in enumerate(orders): # Use enumerate to get index for direct modification
        if order.get('order_id') == order_id:
            # Security check: Ensure the current logged-in user owns this order
            if str(order.get('user_id')) == str(current_user.id):
                # Only allow cancellation if the order is in a "cancellable" state
                if order.get('status') in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
                    orders[order_idx]['status'] = "Cancelled by User" # Update using index
                    # Also update invoice status if it exists
                    if 'invoice_details' in orders[order_idx]:
                        orders[order_idx]['invoice_details']['invoice_status'] = 'Cancelled'
                        orders[order_idx]['invoice_details']['is_held_by_admin'] = True # Prevent automatic sending if cancelled
                    save_json('orders.json', orders)
                    flash(f"Order {order_id} has been cancelled.", "success")
                    # print(f"DEBUG: Order {order_id} cancelled by user {current_user.id}.") # Too verbose
                else:
                    flash(f"Order {order_id} cannot be cancelled at its current status ({order.get('status')}). Please contact support.", "danger")
                    # print(f"WARNING: User {current_user.id} attempted to cancel order {order_id} which is in status {order.get('status')}.") # Too verbose
                order_found = True
                break
            else:
                flash("You do not have permission to cancel this order.", "danger")
                # print(f"SECURITY ALERT: User {current_user.id} attempted to cancel order {order_id} owned by {order.get('user_id')}.") # Too verbose
                order_found = True # Found the order, but not owned by current user
                break
    
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
        # print(f"ERROR: User {current_user.id} attempted to cancel non-existent order {order_id}.") # Too verbose
    
    return redirect(url_for('my_orders'))


@app.route('/user-dashboard')
@login_required
def user_dashboard():
    # print("\n--- DEBUG: Entering /user-dashboard route ---") # Too verbose
    return render_template('user_dashboard.html', current_user_name=current_user.name if current_user.is_authenticated else None)

@app.route('/profile')
@login_required
def profile():
    # print("\n--- DEBUG: Entering /profile route ---") # Too verbose
    user_info = {
        'name': current_user.name,
        'email': current_user.email,
        'phone': current_user.phone,
        'address': current_user.address,
        'pincode': current_user.pincode,
        'role': current_user.role
    }
    # print(f"DEBUG: Displaying profile for user {current_user.email}.") # Too verbose
    return render_template('profile.html', user_info=user_info, current_user_name=current_user.name if current_user.is_authenticated else None)

# --- CSV Export Routes ---
@app.route('/export-orders-csv')
@admin_required
def export_orders_csv():
    # print("\n--- DEBUG: Entering /export-orders-csv route ---") # Too verbose
    orders = load_json('orders.json')
    
    # Define CSV headers
    fieldnames = [
        "order_id", "user_id", "user_email", "customer_name", "customer_phone", 
        "customer_address", "customer_pincode", 
        "subtotal_before_gst", # New field
        "total_amount", # This is now the Grand Total
        "status", 
        "transaction_id", "courier", "tracking_number", "placed_on", "payment_submitted_on",
        "shipped_on", 
        "invoice_status", "invoice_number", "invoice_date", "gst_rate_applied", # New field
        "total_gst_amount", "cgst_amount", "sgst_amount", # New fields for GST breakdown
        "shipping_charge", "final_invoice_amount", "invoice_held_by_admin", 
        "remark", # NEW: Remark field for CSV export
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
                    # Retrieve the correct values, defaulting if not present in older orders
                    item_unit_price_before_gst = f"{item.get('unit_price_before_gst', item.get('unit_price', 0.0)):.2f}"
                    item_total_price_before_gst = f"{item.get('total_price_before_gst', item.get('unit_price', 0.0) * item.get('quantity', 1)):.2f}"
                    item_gst_percent = item.get('gst_percentage', 0.0)
                    item_gst_amount = f"{item.get('gst_amount', 0.0):.2f}"
                    item_total_price_with_gst = f"{item.get('total_price', 0.0):.2f}"


                    details = f"{item.get('name', 'N/A')} (SKU: {item.get('sku', 'N/A')}," \
                              f" Qty: {item.get('quantity', 1)}," \
                              f" UnitPrice (pre-GST): {item_unit_price_before_gst}," \
                              f" ItemTotal (pre-GST): {item_total_price_before_gst}," \
                              f" Item GST%: {item_gst_percent:.2f}," \
                              f" Item GST Amt: {item_gst_amount}," \
                              f" ItemTotal (with GST): {item_total_price_with_gst}," \
                              f" Size: {item.get('size', 'N/A')}," \
                              f" Frame: {item.get('frame', 'N/A')}," \
                              f" Glass: {item.get('glass', 'N/A')})"
                    items_details.append(details)
            items_details_str = "; ".join(items_details) 

            # Extract invoice details with defaults
            invoice_det = order.get('invoice_details', {})
            invoice_status = invoice_det.get('invoice_status', 'N/A')
            invoice_number = invoice_det.get('invoice_number', 'N/A')
            invoice_date = invoice_det.get('invoice_date', 'N/A')
            gst_rate_applied = f"{invoice_det.get('gst_rate_applied', 0.0):.2f}"
            total_gst_amount_inv = f"{invoice_det.get('total_gst_amount', 0.0):.2f}"
            cgst_amount_inv = f"{invoice_det.get('cgst_amount', 0.0):.2f}"
            sgst_amount_inv = f"{invoice_det.get('sgst_amount', 0.0):.2f}"
            shipping_charge_inv = f"{invoice_det.get('shipping_charge', 0.0):.2f}"
            final_invoice_amount = f"{invoice_det.get('final_invoice_amount', 0.0):.2f}"
            invoice_held = str(invoice_det.get('is_held_by_admin', False))
            remark_val = order.get('remark', '') # NEW: Get remark value for CSV

            row = [
                str(order.get('order_id', 'N/A')),
                str(order.get('user_id', 'N/A')),
                str(order.get('user_email', 'N/A')),
                str(order.get('customer_name', 'N/A')),
                str(order.get('customer_phone', 'N/A')),
                str(order.get('customer_address', 'N/A')),
                str(order.get('customer_pincode', 'N/A')),
                f"{order.get('subtotal_before_gst', 0.0):.2f}", # Subtotal
                f"{order.get('total_amount', 0.0):.2f}", # Grand Total
                str(order.get('status', 'N/A')),
                str(order.get('transaction_id', 'N/A')), 
                str(order.get('courier', 'N/A')),
                str(order.get('tracking_number', 'N/A')),
                str(order.get('placed_on', 'N/A')),
                str(order.get('payment_submitted_on', 'N/A')),
                str(order.get('shipped_on', 'N/A')), 
                invoice_status, invoice_number, invoice_date, gst_rate_applied, total_gst_amount_inv, 
                cgst_amount_inv, sgst_amount_inv, shipping_charge_inv, final_invoice_amount, invoice_held, 
                remark_val, # NEW: Add remark to CSV row
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
    # print("\n--- DEBUG: Entering /export-artworks-csv route ---") # Too verbose
    artworks = load_json('artworks.json')

    # Define CSV headers
    fieldnames = [
        "sku", "name", "category", "original_price", "stock", "description",
        "gst_percentage", # New field
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
                f"{artwork.get('gst_percentage', 0.0):.2f}", # New field
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

# --- Admin Category Management Routes ---
@app.route('/admin/categories')
@admin_required
def admin_categories_view():
    categories = load_json('categories.json')
    return render_template('admin_categories.html', categories=categories)

# CATEGORY MANAGEMENT
@app.route('/admin/categories/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_category():
    categories = load_categories()
    if request.method == 'POST':
        category_name = request.form.get('category_name').strip()

        if not category_name:
            flash('Category name cannot be empty.', 'danger')
            return render_template('add_category.html', categories=categories, category_name=category_name)

        # Check for duplicate category name (case-insensitive)
        for cat in categories:
            if cat['name'].lower() == category_name.lower():
                flash(f'Category "{category_name}" already exists.', 'danger')
                return render_template('add_category.html', categories=categories, category_name=category_name)
        
        # Generate a unique ID for the new category
        new_category_id = str(uuid.uuid4())
        
        # Add new category to the list
        categories.append({'id': new_category_id, 'name': category_name})
        save_categories(categories)
        flash(f'Category "{category_name}" added successfully!', 'success')
        return redirect(url_for('admin_categories_view'))
    
    return render_template('add_category.html', categories=categories)


@app.route('/admin/categories/edit/<string:category_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_category(category_id):
    categories = load_categories()
    category_to_edit = next((cat for cat in categories if cat['id'] == category_id), None)

    if not category_to_edit:
        flash('Category not found.', 'danger')
        return redirect(url_for('admin_categories_view'))

    if request.method == 'POST':
        new_category_name = request.form.get('category_name').strip()

        if not new_category_name:
            flash('Category name cannot be empty.', 'danger')
            return render_template('edit_category.html', category=category_to_edit, categories=categories)

        # Check for duplicate category name (case-insensitive, excluding itself)
        for cat in categories:
            if cat['id'] != category_id and cat['name'].lower() == new_category_name.lower():
                flash(f'Category "{new_category_name}" already exists.', 'danger')
                return render_template('edit_category.html', category=category_to_edit, categories=categories)

        category_to_edit['name'] = new_category_name
        save_categories(categories)
        flash(f'Category "{new_category_name}" updated successfully!', 'success')
        return redirect(url_for('admin_categories_view'))
    
    return render_template('edit_category.html', category=category_to_edit, categories=categories)



@app.route('/admin/categories/delete/<string:category_id>', methods=['POST'])
@login_required
@admin_required
def delete_category(category_id):
    categories = load_categories()
    artworks = load_artworks()

    # Check if any artwork is assigned to this category
    for artwork in artworks:
        if artwork.get('category') and artwork['category'] == next((cat['name'] for cat in categories if cat['id'] == category_id), None):
            flash('Cannot delete category: It is currently assigned to one or more artworks. Please reassign artworks first.', 'danger')
            return redirect(url_for('admin_categories_view'))

    original_len = len(categories)
    categories = [cat for cat in categories if cat['id'] != category_id]

    if len(categories) < original_len:
        save_categories(categories)
        flash('Category deleted successfully!', 'success')
    else:
        flash('Category not found.', 'danger')
    return redirect(url_for('admin_categories_view'))


# --- Search Functionality ---
@app.route('/search')
def search_products():
    query = request.args.get('query', '').strip()
    # print(f"\n--- DEBUG: Entering /search route with query: '{query}' ---") # Too verbose
    
    all_artworks = load_json('artworks.json')
    search_results = []
    
    if query:
        search_lower = query.lower()
        for artwork in all_artworks:
            # Search by name, description, SKU
            if (search_lower in artwork.get('name', '').lower() or
                search_lower in artwork.get('description', '').lower() or
                search_lower in artwork.get('sku', '').lower() or
                search_lower in artwork.get('category', '').lower()): # Search by category too
                
                # Check stock: only show if stock > 0
                if artwork.get('stock', 0) > 0:
                    search_results.append(artwork)
    
    # print(f"DEBUG: Found {len(search_results)} results for query '{query}'.") # Too verbose
    return render_template('search_results.html', query=query, results=search_results, current_user_name=current_user.name if current_user.is_authenticated else None)


if __name__ == '__main__':
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(data_dir, exist_ok=True)
    # print(f"Ensured data directory exists: {data_dir}") # Too verbose

    # Initialize data files only if they don't exist or are empty
    # For JSON files that should be lists by default (artworks, orders, categories)
    for filename in ['artworks.json', 'orders.json', 'categories.json']:
        filepath = os.path.join(data_dir, filename)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([], f) 
            print(f"Created/Re-initialized empty list in {filename}.")
        else:
            print(f"INFO: {filename} already exists and is not empty. Skipping initialization.")

    # For users.json (which should be a dictionary by default)
    users_filepath = os.path.join(data_dir, 'users.json')
    if not os.path.exists(users_filepath) or os.path.getsize(users_filepath) == 0:
        with open(users_filepath, 'w', encoding='utf-8') as f:
            json.dump({}, f) 
        print(f"Created/Re-initialized empty dict in users.json.")
    else:
        print(f"INFO: users.json already exists and is not empty. Skipping initialization.")

    # Create the default admin user if users.json is completely empty or doesn't contain the admin email
    users = load_json('users.json')
    if not users or SENDER_EMAIL not in users or not users[SENDER_EMAIL].get('password_hash'):
        print(f"INFO: Initializing default admin user: {SENDER_EMAIL}")
        # Generate hash for default admin password if not already set in env
        # IMPORTANT: In a real deployment, set ADMIN_PASSWORD_HASH as an env variable
        if not os.environ.get('ADMIN_PASSWORD_HASH'):
            print("WARNING: ADMIN_PASSWORD_HASH environment variable not set. Using default 'admin123' hash. CHANGE THIS IN PRODUCTION!")
        
        # Ensure the hardcoded admin's ID matches the ADMIN_USERNAME global
        admin_user_id = ADMIN_USERNAME # Use the specific ADMIN_USERNAME as ID for the built-in admin
        
        users[SENDER_EMAIL] = {
            'id': admin_user_id,
            'email': SENDER_EMAIL,
            'password_hash': ADMIN_PASSWORD_HASH, # This is the hashed password directly
            'name': 'Karthika Futures Admin',
            'phone': '9999999999',
            'address': OUR_BUSINESS_ADDRESS,
            'pincode': '000000',
            'role': 'admin'
        }
        save_users(users)
        print("INFO: Default admin user created/updated.")
    else:
        print("INFO: Default admin user already exists and is configured. Skipping initialization.")


    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 
    os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
    os.makedirs(QR_CODES_FOLDER, exist_ok=True)
    os.makedirs(INVOICE_PDFS_FOLDER, exist_ok=True) # Ensure invoices directory exists
    # print(f"Ensured upload directories exist: {app.config['UPLOAD_FOLDER']}, {PAYMENT_SCREENSHOTS_FOLDER}, {QR_CODES_FOLDER}, {INVOICE_PDFS_FOLDER}") # Too verbose

    # Run the Flask app
    app.run(debug=True)

