import json
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify, current_app, Response, make_response
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
DEFAULT_GST_RATE = 0.18 # 18% as a default example
DEFAULT_SHIPPING_CHARGE = 150.00 # Default shipping charge

# --- FOLDERS FOR UPLOADS AND INVOICES ---
PAYMENT_SCREENSHOTS_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'payment_screenshots')
QR_CODES_FOLDER = os.path.join(app.config['UPLOAD_FOLDER'], 'qr_codes') 
INVOICE_PDFS_FOLDER = os.path.join('static', 'invoices') # IMPORTANT: This needs to be static to be served

# Ensure necessary directories exist on startup
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(PAYMENT_SCREENSHOTS_FOLDER, exist_ok=True)
os.makedirs(QR_CODES_FOLDER, exist_ok=True)
os.makedirs(INVOICE_PDFS_FOLDER, exist_ok=True)


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


# --- Utility Functions (OTP generation, email sending, Order ID generation, Phone Masking) ---
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

def generate_unique_invoice_number():
    """Generates a unique invoice number (e.g., KFI-YYYYMMDD-XXXX)."""
    # Using a simple timestamp-based ID with a random suffix for uniqueness
    timestamp_part = datetime.now().strftime("%Y%m%d")
    random_part = ''.join(random.choices('0123456789', k=4))
    return f"KFI-{timestamp_part}-{random_part}"

def mask_phone_number(phone_number):
    """Masks a phone number for privacy (e.g., +91XXXXX1234)."""
    if not phone_number or len(phone_number) < 4:
        return phone_number # Not enough digits to mask meaningfully
    
    # Assuming standard international format for now.
    # Keep first 3 digits and last 4 digits visible, mask middle.
    # Example: +919876543210 -> +91XXXXX3210
    visible_prefix_len = 3 # e.g., for +91
    visible_suffix_len = 4 # last 4 digits
    
    # Handle numbers shorter than required visible parts
    if len(phone_number) <= visible_prefix_len + visible_suffix_len:
        return phone_number[:visible_prefix_len] + 'X' * (len(phone_number) - visible_prefix_len - visible_suffix_len) + phone_number[-visible_suffix_len:]

    return phone_number[:visible_prefix_len] + 'X' * (len(phone_number) - visible_prefix_len - visible_suffix_len) + phone_number[-visible_suffix_len:]


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
    invoice_filename = f"invoice_{order_data['order_id']}_{invoice_details['invoice_number']}.pdf"
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
        [Paragraph(f"<b>Sold By:</b> {OUR_BUSINESS_NAME}", styles['NormalLeft']),
         Paragraph(f"<b>Invoice No:</b> {invoice_details.get('invoice_number', 'N/A')}", styles['NormalRight'])],
        [Paragraph(OUR_BUSINESS_ADDRESS, styles['NormalLeft']),
         Paragraph(f"<b>Invoice Date:</b> {invoice_details.get('invoice_date', 'N/A')}", styles['NormalRight'])],
        [Paragraph(f"GSTIN: {OUR_GSTIN}", styles['NormalLeft']),
         Paragraph(f"<b>Order ID:</b> {order_data.get('order_id', 'N/A')}", styles['NormalRight'])],
        [Paragraph(f"PAN: {OUR_PAN}", styles['NormalLeft']),
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
    customer_phone = mask_phone_number(order_data.get('customer_phone', 'N/A'))
    customer_address = order_data.get('customer_address', 'N/A')
    customer_pincode = order_data.get('customer_pincode', 'N/A')
    customer_email = order_data.get('user_email', 'N/A')

    story.append(Paragraph("<b>Bill To / Ship To:</b>", styles['Heading2']))
    story.append(Paragraph(customer_name, styles['NormalLeft']))
    story.append(Paragraph(customer_address, styles['NormalLeft']))
    story.append(Paragraph(f"Pincode: {customer_pincode}", styles['NormalLeft']))
    story.append(Paragraph(f"Phone: {customer_phone}", styles['NormalLeft']))
    story.append(Paragraph(f"Email: {customer_email}", styles['NormalLeft']))
    story.append(Spacer(1, 0.2 * inch))

    # Items Table
    item_data = [['#', 'Description', 'Qty', 'Unit Price (₹)', 'Total (₹)']]
    for i, item in enumerate(order_data.get('items', [])):
        description = f"{item.get('name', 'N/A')}"
        if item.get('size') and item['size'] != 'Original': description += f" (Size: {item['size']})"
        if item.get('frame') and item['frame'] != 'None': description += f" (Frame: {item['frame']})"
        if item.get('glass') and item['glass'] != 'None': description += f" (Glass: {item['glass']})"
        
        item_data.append([
            str(i + 1),
            Paragraph(description, styles['NormalLeft']),
            str(item.get('quantity', 1)),
            f"{item.get('unit_price', 0.0):.2f}",
            f"{item.get('total_price', 0.0):.2f}"
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
    total_amount = order_data.get('total_amount', 0.0) # This is the item subtotal
    gst_amount = invoice_details.get('total_gst_amount', 0.0)
    shipping_charge = invoice_details.get('shipping_charge', 0.0)
    final_invoice_amount = invoice_details.get('final_invoice_amount', total_amount + gst_amount + shipping_charge)

    totals_data = [
        ['Subtotal:', f"₹{total_amount:.2f}"],
        [f'GST ({DEFAULT_GST_RATE*100:.0f}%):', f"₹{gst_amount:.2f}"],
        ['Shipping Charges:', f"₹{shipping_charge:.2f}"],
        ['Total Invoice Amount:', f"₹{final_invoice_amount:.2f}"]
    ]
    totals_table = Table(totals_data, colWidths=[5.5 * inch, 2 * inch])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,2), 'Helvetica-Bold'),
        ('FONTNAME', (0,3), (-1,3), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,2), 6),
        ('TOPPADDING', (0,3), (-1,3), 6),
        ('LINEBELOW', (0,2), (-1,2), 1, colors.black), # Line above final total
        ('LINEABOVE', (0,3), (-1,3), 1, colors.black), # Line above final total
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
        print(f"DEBUG: Invoice PDF generated successfully at {pdf_filepath}")
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
    orders = load_json('orders.json')
    updated_orders = False

    for order_idx, order in enumerate(orders):
        # Only process orders marked 'Shipped' that haven't had an invoice 'Sent' or 'Held'
        if order.get('status') == 'Shipped' and \
           order.get('invoice_details', {}).get('invoice_status') not in ['Sent', 'Held']:
            
            shipped_time_str = order.get('shipped_on')
            if not shipped_time_str:
                print(f"WARNING: Order {order.get('order_id')} shipped but no 'shipped_on' timestamp.")
                continue

            try:
                shipped_time = datetime.fromisoformat(shipped_time_str)
                # Check if 24 hours have passed AND invoice is not 'Held' by admin
                if (datetime.now() - shipped_time) >= timedelta(hours=24) and \
                   not order.get('invoice_details', {}).get('is_held_by_admin', False):
                    
                    print(f"DEBUG: Processing invoice for Order ID: {order.get('order_id')}")

                    # Initialize invoice_details if not present
                    if 'invoice_details' not in order:
                        order['invoice_details'] = {}
                    
                    # Calculate GST and Final Amount
                    total_amount_items = order.get('total_amount', 0.0)
                    gst_amount = total_amount_items * DEFAULT_GST_RATE
                    shipping_charge = order['invoice_details'].get('shipping_charge', DEFAULT_SHIPPING_CHARGE) # Use existing or default
                    final_amount = total_amount_items + gst_amount + shipping_charge

                    order['invoice_details']['invoice_number'] = order['invoice_details'].get('invoice_number', generate_unique_invoice_number())
                    order['invoice_details']['invoice_date'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    order['invoice_details']['total_gst_amount'] = round(gst_amount, 2)
                    order['invoice_details']['shipping_charge'] = round(shipping_charge, 2)
                    order['invoice_details']['final_invoice_amount'] = round(final_amount, 2)
                    order['invoice_details']['gst_number'] = OUR_GSTIN # Store our details in invoice
                    order['invoice_details']['pan_number'] = OUR_PAN
                    order['invoice_details']['business_name'] = OUR_BUSINESS_NAME
                    order['invoice_details']['business_address'] = OUR_BUSINESS_ADDRESS
                    order['invoice_details']['customer_phone_camouflaged'] = mask_phone_number(order.get('customer_phone', 'N/A'))
                    # Assuming billing address is same as shipping for now
                    order['invoice_details']['billing_address'] = order.get('customer_address', 'N/A')


                    pdf_relative_path = generate_invoice_pdf(order)

                    if pdf_relative_path:
                        order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
                        
                        # Send email
                        try:
                            msg = Message(f"Karthika Futures - Your Invoice for Order #{order['order_id']}",
                                          recipients=[order.get('user_email')])
                            msg.body = render_template('email/invoice_email.txt', order=order) # Use a text template
                            
                            # Attach PDF
                            with app.open_resource(os.path.join('static', pdf_relative_path)) as fp:
                                msg.attach(f"invoice_{order['order_id']}.pdf", "application/pdf", fp.read())
                            
                            mail.send(msg)
                            order['invoice_details']['invoice_status'] = 'Sent'
                            print(f"DEBUG: Invoice for Order {order['order_id']} emailed successfully.")
                            flash(f"Invoice for Order {order['order_id']} sent to customer.", "success")
                            updated_orders = True
                        except Exception as e:
                            order['invoice_details']['invoice_status'] = 'Email Failed'
                            print(f"ERROR: Failed to send invoice email for Order {order['order_id']}: {e}")
                            flash(f"Failed to send invoice email for Order {order['order_id']}.", "danger")
                            updated_orders = True
                    else:
                        order['invoice_details']['invoice_status'] = 'PDF Gen Failed'
                        print(f"ERROR: PDF generation failed for Order {order['order_id']}.")
                        flash(f"Failed to generate invoice PDF for Order {order['order_id']}.", "danger")
                        updated_orders = True
                elif order.get('invoice_details', {}).get('is_held_by_admin', False):
                    print(f"DEBUG: Invoice for Order {order.get('order_id')} is on HOLD by admin.")
                    order['invoice_details']['invoice_status'] = 'Held' # Ensure status reflects held
                    updated_orders = True # Mark as updated if status changed
                else:
                    # Update status to Prepared if not sent/held and time not passed
                    if order.get('invoice_details', {}).get('invoice_status') not in ['Prepared', 'Sent', 'Email Failed', 'PDF Gen Failed']:
                         order['invoice_details']['invoice_status'] = 'Prepared' # Ready to be sent
                         updated_orders = True
                    print(f"DEBUG: Invoice for Order {order.get('order_id')} not yet due for sending.")

            except ValueError as ve:
                print(f"ERROR: Invalid date format for order {order.get('order_id')} shipped_on: {shipped_time_str} - {ve}")
            except Exception as ex:
                print(f"ERROR: Unexpected error in process_pending_invoices for order {order.get('order_id')}: {ex}")

    if updated_orders:
        save_json('orders.json', orders)

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
    
    # Trigger pending invoice processing on admin panel load
    process_pending_invoices()

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
                
                # If status changes to Shipped, record timestamp and set initial invoice status
                if new_status == 'Shipped':
                    order['shipped_on'] = datetime.now().isoformat()
                    if 'invoice_details' not in order:
                        order['invoice_details'] = {}
                    order['invoice_details']['invoice_status'] = 'Prepared' # Mark as prepared
                    order['invoice_details']['is_held_by_admin'] = False # Ensure not held by default
                    order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat() # Track last edit
                    print(f"DEBUG: Order {order_id} marked as Shipped. Invoice status set to 'Prepared'.")

                break
        
        if order_found:
            save_json('orders.json', orders)
            flash(f"Order {order_id} updated to '{new_status}'.", "success")
        else:
            flash(f"Order {order_id} not found.", "danger")
        
        return redirect(url_for('admin_panel')) 

    return redirect(url_for('admin_panel')) 

# Admin: Hold Invoice
@app.route('/admin/invoice/hold/<order_id>', methods=['POST'])
@admin_required
def admin_hold_invoice(order_id):
    orders = load_json('orders.json')
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            if 'invoice_details' not in order:
                order['invoice_details'] = {}
            order['invoice_details']['is_held_by_admin'] = True
            order['invoice_details']['invoice_status'] = 'Held'
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order_id} has been put on hold.", "info")
            order_found = True
            break
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
    return redirect(url_for('admin_panel'))

# Admin: Release/Un-hold Invoice
@app.route('/admin/invoice/release/<order_id>', methods=['POST'])
@admin_required
def admin_release_invoice(order_id):
    orders = load_json('orders.json')
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            if 'invoice_details' not in order:
                order['invoice_details'] = {}
            order['invoice_details']['is_held_by_admin'] = False
            # Reset status to 'Prepared' or 'Shipped' if it was 'Held' and not yet sent
            if order['invoice_details'].get('invoice_status') == 'Held':
                 order['invoice_details']['invoice_status'] = 'Prepared'
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order_id} has been released (no longer on hold).", "info")
            order_found = True
            break
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
    return redirect(url_for('admin_panel'))

# Admin: Edit Invoice Details
@app.route('/admin/invoice/edit/<order_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_invoice(order_id):
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_panel'))

    # Ensure invoice_details exists
    if 'invoice_details' not in order:
        order['invoice_details'] = {}
    
    # Pre-populate some invoice details if not already present
    order['invoice_details'].setdefault('invoice_number', generate_unique_invoice_number())
    order['invoice_details'].setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    order['invoice_details'].setdefault('total_gst_amount', round(order.get('total_amount', 0.0) * DEFAULT_GST_RATE, 2))
    order['invoice_details'].setdefault('shipping_charge', DEFAULT_SHIPPING_CHARGE)
    order['invoice_details'].setdefault('final_invoice_amount', round(order.get('total_amount', 0.0) + order['invoice_details']['total_gst_amount'] + order['invoice_details']['shipping_charge'], 2))
    order['invoice_details'].setdefault('gst_number', OUR_GSTIN)
    order['invoice_details'].setdefault('pan_number', OUR_PAN)
    order['invoice_details'].setdefault('business_name', OUR_BUSINESS_NAME)
    order['invoice_details'].setdefault('business_address', OUR_BUSINESS_ADDRESS)
    order['invoice_details'].setdefault('customer_phone_camouflaged', mask_phone_number(order.get('customer_phone', 'N/A')))
    order['invoice_details'].setdefault('billing_address', order.get('customer_address', 'N/A')) # Assuming same as shipping

    if request.method == 'POST':
        # Update business details
        order['invoice_details']['business_name'] = request.form.get('business_name', OUR_BUSINESS_NAME)
        order['invoice_details']['business_address'] = request.form.get('business_address', OUR_BUSINESS_ADDRESS)
        order['invoice_details']['gst_number'] = request.form.get('gst_number', OUR_GSTIN)
        order['invoice_details']['pan_number'] = request.form.get('pan_number', OUR_PAN)

        # Update invoice specific details
        order['invoice_details']['invoice_number'] = request.form.get('invoice_number', order['invoice_details']['invoice_number'])
        order['invoice_details']['invoice_date'] = request.form.get('invoice_date', order['invoice_details']['invoice_date'])
        
        # Update charges and recalculate final amount
        try:
            shipping_charge = float(request.form.get('shipping_charge', DEFAULT_SHIPPING_CHARGE))
            gst_rate_from_form = float(request.form.get('gst_rate', DEFAULT_GST_RATE * 100)) / 100 # Convert % back to decimal
            
            # Recalculate GST and final amounts based on potentially edited values
            base_total = order.get('total_amount', 0.0)
            calculated_gst = base_total * gst_rate_from_form
            final_invoice_amount = base_total + calculated_gst + shipping_charge
            
            order['invoice_details']['shipping_charge'] = round(shipping_charge, 2)
            order['invoice_details']['total_gst_amount'] = round(calculated_gst, 2)
            order['invoice_details']['final_invoice_amount'] = round(final_invoice_amount, 2)
            
            flash('Invoice details updated successfully!', 'success')
            order['invoice_details']['invoice_status'] = 'Edited' # Mark as edited
            order['invoice_details']['is_held_by_admin'] = True # Automatically put on hold if manually edited
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()

        except ValueError:
            flash("Invalid number format for charges. Please enter numeric values.", "danger")
            # Don't save if values are invalid, let the form render with old values or error
            return render_template('admin_edit_invoice.html', order=order,
                                   our_business_name=OUR_BUSINESS_NAME,
                                   our_business_address=OUR_BUSINESS_ADDRESS,
                                   our_gstin=OUR_GSTIN,
                                   our_pan=OUR_PAN,
                                   default_gst_rate=DEFAULT_GST_RATE * 100) # Pass as percentage for form

        save_json('orders.json', orders)
        return redirect(url_for('admin_edit_invoice', order_id=order_id))

    return render_template('admin_edit_invoice.html', order=order,
                           our_business_name=OUR_BUSINESS_NAME,
                           our_business_address=OUR_BUSINESS_ADDRESS,
                           our_gstin=OUR_GSTIN,
                           our_pan=OUR_PAN,
                           default_gst_rate=DEFAULT_GST_RATE * 100) # Pass as percentage for form

# Admin: Send Invoice Email Manually
@app.route('/admin/invoice/send_email/<order_id>', methods=['POST'])
@admin_required
def admin_send_invoice_email(order_id):
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_panel'))

    if 'invoice_details' not in order or not order['invoice_details'].get('invoice_number'):
        flash(f"Invoice for Order {order_id} not yet prepared. Please edit and save it first.", "warning")
        return redirect(url_for('admin_edit_invoice', order_id=order_id))

    pdf_relative_path = generate_invoice_pdf(order) # Re-generate PDF with current details

    if pdf_relative_path:
        order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
        
        try:
            msg = Message(f"Karthika Futures - Your Invoice for Order #{order['order_id']} (Manual Send)",
                          recipients=[order.get('user_email')])
            msg.body = render_template('email/invoice_email.txt', order=order)
            
            with app.open_resource(os.path.join('static', pdf_relative_path)) as fp:
                msg.attach(f"invoice_{order['order_id']}.pdf", "application/pdf", fp.read())
            
            mail.send(msg)
            order['invoice_details']['invoice_status'] = 'Sent'
            order['invoice_details']['is_held_by_admin'] = False # Release hold if sent manually
            order['invoice_details']['last_edited_by_admin'] = datetime.now().isoformat()
            save_json('orders.json', orders)
            flash(f"Invoice for Order {order_id} manually sent to customer.", "success")
        except Exception as e:
            order['invoice_details']['invoice_status'] = 'Email Failed'
            save_json('orders.json', orders)
            flash(f"Failed to send invoice email for Order {order_id}: {e}", "danger")
            print(f"ERROR: Manual invoice email send failed for Order {order_id}: {e}")
    else:
        order['invoice_details']['invoice_status'] = 'PDF Gen Failed'
        save_json('orders.json', orders)
        flash(f"Failed to generate invoice PDF for Order {order_id}.", "danger")
        print(f"ERROR: Manual invoice PDF generation failed for Order {order_id}.")

    return redirect(url_for('admin_panel'))


# Route to download the generated invoice PDF
@app.route('/download-invoice/<order_id>')
@login_required
def download_invoice(order_id):
    orders = load_json('orders.json')
    order = next((o for o in orders if o.get('order_id') == order_id), None)

    if not order:
        flash("Invoice not found for this order.", "danger")
        return redirect(url_for('my_orders'))

    # Security check: Ensure the current user owns this order OR is an admin
    if str(order.get('user_id')) != str(current_user.id) and not current_user.is_admin:
        flash("You do not have permission to download this invoice.", "danger")
        return redirect(url_for('my_orders'))

    # Check if invoice PDF path exists and status allows download
    invoice_details = order.get('invoice_details', {})
    pdf_relative_path = invoice_details.get('invoice_pdf_path')
    invoice_status = invoice_details.get('invoice_status')

    if not pdf_relative_path or not os.path.exists(os.path.join('static', pdf_relative_path)):
        flash("Invoice PDF not found or not yet generated.", "warning")
        # Attempt to generate if status is 'Prepared'/'Edited' and path is missing
        if invoice_status in ['Prepared', 'Edited', 'Held', 'Email Failed'] and order.get('status') == 'Shipped':
             flash("Attempting to generate invoice PDF now...", "info")
             # Regenerate PDF with current details
             pdf_relative_path = generate_invoice_pdf(order)
             if pdf_relative_path:
                 order['invoice_details']['invoice_pdf_path'] = pdf_relative_path
                 save_json('orders.json', orders)
                 return redirect(url_for('download_invoice', order_id=order_id)) # Retry download

        return redirect(url_for('my_orders'))

    # Only allow download if status is appropriate (e.g., Sent, Prepared, Edited, Email Failed)
    # This prevents users from downloading invoices for cancelled/pending orders even if a PDF somehow exists
    allowed_invoice_statuses = ['Prepared', 'Sent', 'Held', 'Edited', 'Email Failed', 'PDF Gen Failed']
    if invoice_status not in allowed_invoice_statuses:
        flash("Invoice is not yet available for download due to its current status.", "warning")
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
        return redirect(url_for('my_orders'))
    except Exception as e:
        flash(f"Error serving invoice PDF: {e}", "danger")
        return redirect(url_for('my_orders'))


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
            flash('An OTP has been been sent to your email address. Please check your inbox (and spam folder).', 'info')
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
                    "placed_on": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
                        "total_gst_amount": 0.0,
                        "shipping_charge": 0.0,
                        "final_invoice_amount": grand_total_from_server_calc, # Initially just item total
                        "invoice_pdf_path": None,
                        "customer_phone_camouflaged": mask_phone_number(phone),
                        "billing_address": address # Assuming shipping address is billing address
                    }
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

    # UPI Payment Details
    upi_id = "smarasada@okaxis"
    banking_name = "SUBHASH S" 
    
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
    
    # Trigger pending invoice processing on admin panel load
    process_pending_invoices() # Also check here, so user sees updated invoice status

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
                    # Also update invoice status if it exists
                    if 'invoice_details' in orders[order_idx]:
                        orders[order_idx]['invoice_details']['invoice_status'] = 'Cancelled'
                        orders[order_idx]['invoice_details']['is_held_by_admin'] = True # Prevent automatic sending if cancelled
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
        "shipped_on", # New field
        "invoice_status", "invoice_number", "invoice_date", "total_gst_amount", 
        "shipping_charge", "final_invoice_amount", "invoice_held_by_admin", # New fields for invoice
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

            # Extract invoice details with defaults
            invoice_det = order.get('invoice_details', {})
            invoice_status = invoice_det.get('invoice_status', 'N/A')
            invoice_number = invoice_det.get('invoice_number', 'N/A')
            invoice_date = invoice_det.get('invoice_date', 'N/A')
            total_gst_amount = f"{invoice_det.get('total_gst_amount', 0.0):.2f}"
            shipping_charge_inv = f"{invoice_det.get('shipping_charge', 0.0):.2f}"
            final_invoice_amount = f"{invoice_det.get('final_invoice_amount', 0.0):.2f}"
            invoice_held = str(invoice_det.get('is_held_by_admin', False))

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
                str(order.get('shipped_on', 'N/A')), # New field
                invoice_status, invoice_number, invoice_date, total_gst_amount, 
                shipping_charge_inv, final_invoice_amount, invoice_held, # New fields
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
    os.makedirs(INVOICE_PDFS_FOLDER, exist_ok=True) # Ensure invoices directory exists
    print(f"Ensured upload directories exist: {app.config['UPLOAD_FOLDER']}, {PAYMENT_SCREENSHOTS_FOLDER}, {QR_CODES_FOLDER}, {INVOICE_PDFS_FOLDER}")

    if os.environ.get('ADMIN_PASSWORD_HASH') is None:
        print("WARNING: ADMIN_PASSWORD_HASH not found in environment variables. Using default 'admin123'. Change this in production!")
        pass 

    app.run(debug=True)

