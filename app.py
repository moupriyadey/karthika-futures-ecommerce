import os
import json
import csv
import uuid
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, make_response, g, Response, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import random
import qrcode
import io
import base64
# Email Sending
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# CSRF protection
from flask_wtf.csrf import CSRFProtect, generate_csrf  # ✅ CORRECT


# PDF generation
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

REPORTLAB_AVAILABLE = True

# --- App Initialization ---
app = Flask(__name__)

# --- CSRF Setup ---
csrf = CSRFProtect(app)

# 👤 Admin login credentials (you can change the email & password)
ADMIN_CREDENTIALS = {
    'subhashes@6761': 'Rupadey81#'
}


# ✅ Inject csrf_token into all templates (IMPORTANT!)
@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

# --- Secret Key ---
# IMPORTANT: Use secure key in production
app.config['SECRET_KEY'] = 'THIS_IS_A_SUPER_STABLE_STATIC_CSRF_KEY_12345'

# --- Upload Folders ---
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PRODUCT_IMAGES_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'product_images')
app.config['CATEGORY_IMAGES_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'category_images')
app.config['PAYMENT_SCREENSHOTS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'payment_screenshots')
app.config['INVOICE_PDF_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'invoices')

# --- Email Settings (can override via .env) ---
app.config['SENDER_EMAIL'] = os.environ.get('SENDER_EMAIL', 'your_email@example.com')
app.config['SENDER_PASSWORD'] = os.environ.get('SENDER_PASSWORD', 'your_email_app_password')
app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', 587))

# --- Ensure Upload Folders Exist ---
os.makedirs(app.config['PRODUCT_IMAGES_FOLDER'], exist_ok=True)
os.makedirs(app.config['CATEGORY_IMAGES_FOLDER'], exist_ok=True)
os.makedirs(app.config['PAYMENT_SCREENSHOTS_FOLDER'], exist_ok=True)
os.makedirs(app.config['INVOICE_PDF_FOLDER'], exist_ok=True)

# --- Constants ---
DEFAULT_SHIPPING_CHARGE = Decimal('50.00')
MAX_SHIPPING_COST_FREE_THRESHOLD = Decimal('5000.00')
DEFAULT_GST_PERCENTAGE = Decimal('18.0')
DEFAULT_INVOICE_GST_RATE = Decimal('18.0')

# --- Business Info for Invoices ---
OUR_BUSINESS_NAME = "Karthika Futures"
OUR_GSTIN = "27ABCDE1234F1Z5"
OUR_PAN = "ABCDE1234F"
OUR_BUSINESS_ADDRESS = "No. 123, Temple Road, Spiritual City, Karnataka - 560001"
OUR_BUSINESS_EMAIL = "invoices@karthikafutures.com"

# --- UPI Info ---
UPI_ID = "smarasada@okaxis"
BANKING_NAME = "SUBHASH S"
BANK_NAME = "PNB"

# --- Login Manager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'user_login'


# === CATEGORY HELPERS ===

# Load all categories from JSON
def load_categories():
    try:
        with open("categories.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# Save categories to JSON
def save_categories(categories):
    with open("categories.json", "w") as f:
        json.dump(categories, f, indent=4)

# Get a category by ID
def get_category_by_id(category_id):
    categories = load_categories()
    for cat in categories:
        if cat["id"] == category_id:
            return cat
    return None


# NEW: Register a custom Jinja2 filter for floatformat
@app.template_filter('floatformat')
def floatformat_filter(value, places=2):
    """
    Formats a float/Decimal to a specific number of decimal places.
    Handles non-numeric inputs gracefully by returning '0.00' or original value.
    """
    try:
        # Attempt to convert to string first, then Decimal
        decimal_value = Decimal(str(value)) 
        return f"{decimal_value:.{places}f}"
    except (ValueError, TypeError, AttributeError, InvalidOperation): 
        # Catch InvalidOperation explicitly, along with others.
        app.logger.warning(f"floatformat_filter received invalid value '{value}' (type: {type(value)}). Returning '0.00'.")
        return f"{Decimal('0.00'):.{places}f}" # Return a formatted zero for bad data

login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

# --- Temporary OTP storage (in-memory, volatile) ---
# For production, consider a database or Redis for persistent storage
otp_storage = {} # {'email': {'otp': '123456', 'expiry': datetime_object, 'user_data': { ... }}}


# --- User Model ---
class User(UserMixin):
    def __init__(self, id, email, password, name, phone=None, address=None, pincode=None, role='user'):
        self.id = str(id) # Ensure ID is string for Flask-Login
        self.email = email
        self.password = password
        self.name = name
        self.phone = phone
        self.address = address
        self.pincode = pincode
        self.role = role # 'user' or 'admin'

    def is_admin(self):
        return self.role == 'admin'

    @staticmethod
    def get(user_id):
        users = load_json('users.json')
        for user_data in users:
            if str(user_data['id']) == str(user_id):
                return User(**user_data)
        return None

    @staticmethod
    def find_by_email(email):
        users = load_json('users.json')
        for user_data in users:
            if user_data['email'] == email:
                return User(**user_data)
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required.", "danger")
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


# --- Helper Functions for JSON Data Management ---
def load_json(filename):
    filepath = os.path.join('data', filename)
    if not os.path.exists(filepath):
        # Create empty file with appropriate structure if it doesn't exist
        if filename == 'users.json':
            initial_data = []
        elif filename == 'artworks.json':
            initial_data = []
        elif filename == 'orders.json':
            initial_data = []
        elif filename == 'categories.json':
            initial_data = []
        else:
            initial_data = {} # Default to empty dict for other JSONs

        os.makedirs('data', exist_ok=True) # Ensure 'data' directory exists
        with open(filepath, 'w') as f:
            json.dump(initial_data, f, indent=4)
        return initial_data
    with open(filepath, 'r') as f:
        data = json.load(f)
        return data

class CustomJsonEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Decimal objects."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj) # Convert Decimal to string
        return json.JSONEncoder.default(self, obj)

def save_json(filename, data):
    filepath = os.path.join('data', filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=4, cls=CustomJsonEncoder) # Use custom encoder

# Specific Loaders (Recommended for clarity, ensure these exist and use load_json)
def load_categories_data():
    return load_json('categories.json')

def load_artworks_data():
    # Load raw data and convert price-related fields to Decimal
    artworks = load_json('artworks.json')
    for artwork in artworks:
        for key in ['original_price', 'gst_percentage', 'size_a4', 'size_a5', 'size_letter', 'size_legal',
                    'frame_wooden', 'frame_metal', 'frame_pvc', 'glass_price']:
            if key in artwork and artwork[key] is not None:
                try:
                    artwork[key] = Decimal(str(artwork[key]))
                except InvalidOperation:
                    app.logger.warning(f"Invalid Decimal conversion for artwork SKU {artwork.get('sku')} key {key}: {artwork[key]}. Setting to 0.00")
                    artwork[key] = Decimal('0.00')
            elif key not in artwork or artwork[key] is None: 
                # If key is missing or None, ensure it's a Decimal 0.00 for price fields
                if 'price' in key or 'gst' in key or 'size' in key or 'frame' in key or 'glass' in key:
                    artwork[key] = Decimal('0.00')
                else: # For other missing keys, pass
                    pass

        # Ensure stock is int
        artwork['stock'] = int(artwork.get('stock', 0))
    return artworks

def load_orders_data():
    # Load raw data and convert price-related fields in orders/order_items to Decimal
    orders = load_json('orders.json')
    for order in orders:
        try:
            order['total_amount'] = Decimal(str(order.get('total_amount', '0.00')))
            order['subtotal_before_gst'] = Decimal(str(order.get('subtotal_before_gst', '0.00')))
            order['total_gst_amount'] = Decimal(str(order.get('total_gst_amount', '0.00')))
            order['cgst_amount'] = Decimal(str(order.get('cgst_amount', '0.00')))
            order['sgst_amount'] = Decimal(str(order.get('sgst_amount', '0.00')))
            order['shipping_charge'] = Decimal(str(order.get('shipping_charge', '0.00')))
            order['final_invoice_amount'] = Decimal(str(order.get('final_invoice_amount', '0.00'))) # For invoice details
        except InvalidOperation as e:
            app.logger.error(f"Error converting order level Decimal values for order {order.get('order_id')}: {e}", exc_info=True)
            # Default to 0.00 if conversion fails
            order['total_amount'] = Decimal('0.00')
            order['subtotal_before_gst'] = Decimal('0.00')
            order['total_gst_amount'] = Decimal('0.00')
            order['cgst_amount'] = Decimal('0.00')
            order['sgst_amount'] = Decimal('0.00')
            order['shipping_charge'] = Decimal('0.00')
            order['final_invoice_amount'] = Decimal('0.00')


        # --- IMPORTANT FIX: Ensure 'items' is always a list ---
        if not isinstance(order.get('items'), list):
            app.logger.warning(f"Order ID {order.get('order_id')} has non-list 'items' type: {type(order.get('items'))}. Setting to empty list.")
            order['items'] = [] # Default to an empty list if missing or not a list
        
        processed_items = [] # Create a new list to populate
        for item_data in order['items']:
            if isinstance(item_data, dict): # Ensure each item in the list is a dictionary
                # Convert relevant fields to Decimal
                for key in ['unit_price_before_options', 'unit_price_before_gst', 'gst_percentage',
                            'gst_amount', 'total_price_before_gst', 'total_price']:
                    if key in item_data and item_data[key] is not None:
                        try:
                            item_data[key] = Decimal(str(item_data[key]))
                        except InvalidOperation:
                            app.logger.warning(f"Invalid Decimal conversion for order {order.get('order_id')} item {item_data.get('sku')} key {key}: {item_data[key]}. Setting to 0.00")
                            item_data[key] = Decimal('0.00')
                    elif key not in item_data or item_data[key] is None:
                        item_data[key] = Decimal('0.00') # Default missing numerical fields to Decimal 0
                item_data['quantity'] = int(item_data.get('quantity', 0))
                processed_items.append(item_data)
            else:
                app.logger.warning(f"Order ID {order.get('order_id')} contains a non-dictionary item: {item_data}. Skipping.")
        order['items'] = processed_items # Assign the cleaned list back to order['items']

        # Ensure courier and tracking number fields exist and are strings
        order['courier'] = order.get('courier', '')
        order['tracking_number'] = order.get('tracking_number', '')

    return orders

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_otp(recipient, otp):
    print(f"[DEBUG] Sending OTP {otp} to {recipient}")
    # Here you can use email or SMS logic


# --- NEW: load_users_data helper function ---
def load_users_data():
    """Loads user data from users.json."""
    return load_json('users.json')

# --- Helper Function to get Artwork by SKU ---
# This function is crucial for consistently retrieving artwork details
# and ensuring prices are Decimal types for accurate calculations.
def get_artwork_by_sku(sku):
    artworks_data = load_artworks_data() # Load artworks with Decimal prices
    artwork_info = next((a for a in artworks_data if a.get('sku') == sku), None)
    
    if artwork_info:
        # Return the artwork info directly, as load_artworks_data already
        # ensures correct Decimal types and default values for missing keys.
        return artwork_info
    
    # If artwork not found in JSON, return None
    return None

# --- UPDATED: Function to generate invoice PDF (using ReportLab) ---
def generate_invoice_pdf(order_id, order_details):
    invoice_filename_base = f"invoice_{order_id}"
    invoice_filepath_pdf = os.path.join(app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.pdf")
    invoice_filepath_txt = os.path.join(app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.txt")

    if REPORTLAB_AVAILABLE: # Check if ReportLab is available
       try:
           doc = SimpleDocTemplate(invoice_filepath_pdf, pagesize=letter)
           styles = getSampleStyleSheet()
           
           # Custom style for right-aligned text in tables for amounts
           styles.add(ParagraphStyle(name='RightAlign', alignment=TA_RIGHT))
           styles.add(ParagraphStyle(name='CenterAlign', alignment=TA_CENTER))
           
           story = []

           # Title
           story.append(Paragraph(f"<b>INVOICE</b>", styles['h1']))
           story.append(Spacer(1, 0.2*inch))

           # Invoice Details
           story.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
           story.append(Paragraph(f"<b>Invoice Number:</b> {order_details.get('invoice_details', {}).get('invoice_number', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"<b>Order ID:</b> {order_id}", styles['Normal']))
           story.append(Spacer(1, 0.2*inch))

           # Seller Info
           story.append(Paragraph("<b>Seller:</b>", styles['h3']))
           story.append(Paragraph(f"Name: {OUR_BUSINESS_NAME}", styles['Normal']))
           story.append(Paragraph(f"GSTIN: {OUR_GSTIN}", styles['Normal']))
           story.append(Paragraph(f"PAN: {OUR_PAN}", styles['Normal']))
           story.append(Paragraph(f"Address: {OUR_BUSINESS_ADDRESS}", styles['Normal']))
           story.append(Paragraph(f"Email: {OUR_BUSINESS_EMAIL}", styles['Normal']))
           story.append(Spacer(1, 0.2*inch))

           # Customer Info
           story.append(Paragraph("<b>Customer:</b>", styles['h3']))
           story.append(Paragraph(f"Name: {order_details.get('customer_name', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"Email: {order_details.get('user_email', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"Phone: {order_details.get('customer_phone', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"Address: {order_details.get('customer_address', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"Pincode: {order_details.get('customer_pincode', 'N/A')}", styles['Normal']))
           story.append(Spacer(1, 0.2*inch))

           # Items Table
           data = [
               ['<b>SKU</b>', '<b>Name</b>', '<b>Qty</b>', '<b>Unit Price</b>', '<b>Total Price</b>']
           ]
           for item in order_details.get('items', []):
               data.append([
                   item.get('sku', 'N/A'),
                   item.get('name', 'N/A'),
                   str(item.get('quantity', 0)),
                   f"₹{item.get('unit_price_before_gst', Decimal('0.00')):.2f}",
                   f"₹{item.get('total_price', Decimal('0.00')):.2f}"
               ])
           
           table = Table(data, colWidths=[1.0*inch, 2.5*inch, 0.5*inch, 1.2*inch, 1.2*inch])
           table.setStyle(TableStyle([
               ('BACKGROUND', (0,0), (-1,0), colors.grey),
               ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
               ('ALIGN', (0,0), (-1,-1), 'LEFT'),
               ('ALIGN', (3,0), (-1,-1), 'RIGHT'), # Align price columns right
               ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
               ('BOTTOMPADDING', (0,0), (-1,0), 12),
               ('BACKGROUND', (0,1), (-1,-1), colors.beige),
               ('GRID', (0,0), (-1,-1), 1, colors.black),
               ('BOX', (0,0), (-1,-1), 1, colors.black),
           ]))
           story.append(table)
           story.append(Spacer(1, 0.2*inch))

           # Totals
           story.append(Paragraph(f"<b>Subtotal (Before GST):</b> ₹{order_details.get('subtotal_before_gst', Decimal('0.00')):.2f}", styles['RightAlign']))
           story.append(Paragraph(f"<b>Total GST:</b> ₹{order_details.get('total_gst_amount', Decimal('0.00')):.2f} (CGST: ₹{order_details.get('cgst_amount', Decimal('0.00')):.2f}, SGST: ₹{order_details.get('sgst_amount', Decimal('0.00')):.2f})", styles['RightAlign']))
           story.append(Paragraph(f"<b>Shipping Charge:</b> ₹{order_details.get('shipping_charge', Decimal('0.00')):.2f}", styles['RightAlign']))
           story.append(Paragraph(f"<b>Grand Total:</b> ₹{order_details.get('total_amount', Decimal('0.00')):.2f}", styles['h2']))
           story.append(Spacer(1, 0.5*inch))
           story.append(Paragraph(f"Status: {order_details.get('status', 'N/A')}", styles['Normal']))

           doc.build(story)
           app.logger.info(f"Generated PDF invoice: {invoice_filepath_pdf}")
           return f'uploads/invoices/{invoice_filename_base}.pdf'
       except Exception as e:
           app.logger.error(f"Error generating PDF with ReportLab: {e}", exc_info=True)
           # Fallback to text invoice if PDF generation fails
           pass

    # Fallback: Basic text content for the dummy invoice (executed if ReportLab fails or is not enabled)
    invoice_content = f"""
--- INVOICE ---

Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Invoice Number: {order_details.get('invoice_details', {}).get('invoice_number', 'N/A')}
Order ID: {order_id}

Seller:
  Name: {OUR_BUSINESS_NAME}
  GSTIN: {OUR_GSTIN}
  PAN: {OUR_PAN}
  Address: {OUR_BUSINESS_ADDRESS}
  Email: {OUR_BUSINESS_EMAIL}

Customer:
  Name: {order_details.get('customer_name', 'N/A')}
  Phone: {order_details.get('customer_phone', 'N/A')}
  Address: {order_details.get('customer_address', 'N/A')}
  Pincode: {order_details.get('customer_pincode', 'N/A')}

Items:
{'='*50}
{'SKU':<10} {'Name':<25} {'Qty':<5} {'Unit Price':<12} {'Total Price':<12}
{'='*50}
"""
    for item in order_details.get('items', []):
        # Format Decimal values for the text invoice
        unit_price_formatted = f"{item.get('unit_price_before_gst', Decimal('0.00')):.2f}"
        total_price_formatted = f"{item.get('total_price', Decimal('0.00')):.2f}"
        invoice_content += f"{item.get('sku', 'N/A'):<10} {item.get('name', 'N/A'):<25} {item.get('quantity', 0):<5} {unit_price_formatted:<12} {total_price_formatted:<12}\n"

    invoice_content += f"""
{'='*50}
Subtotal (Before GST): {order_details.get('subtotal_before_gst', Decimal('0.00')):.2f}
Total GST: {order_details.get('total_gst_amount', Decimal('0.00')):.2f} (CGST: {order_details.get('cgst_amount', Decimal('0.00')):.2f}, SGST: {order_details.get('sgst_amount', Decimal('0.00')):.2f})
Shipping Charge: {order_details.get('shipping_charge', Decimal('0.00')):.2f}
Grand Total: {order_details.get('total_amount', Decimal('0.00')):.2f}

Status: {order_details.get('status', 'N/A')}

--- End of Invoice ---
"""

    with open(invoice_filepath_txt, 'w') as f:
        f.write(invoice_content)
    
    # Return the path to the .txt file, but suggest a .pdf extension for consistent email/download
    # If ReportLab generation works, it returns the PDF path. If not, it falls back to TXT path.
    # The MIME type in send_email_with_attachment and download_invoice will adapt.
    return f'uploads/invoices/{invoice_filename_base}.txt' # Return TXT path for fallback

from functools import wraps
from flask import session, redirect, url_for, flash

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in as admin to access this page.", "danger")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

# --- NEW: Function to send email with attachment (using smtplib directly) ---
def send_email_with_attachment(recipient_email, subject, body, attachment_path=None, attachment_filename=None):
    sender_email = app.config.get('SENDER_EMAIL')
    sender_password = app.config.get('SENDER_PASSWORD')
    smtp_server = app.config.get('SMTP_SERVER')
    smtp_port = app.config.get('SMTP_PORT')

    if not all([sender_email, sender_password, smtp_server, smtp_port]):
        app.logger.error("Email sender configuration missing. Cannot send email.")
        return False, "Email server not configured. Please set SENDER_EMAIL, SENDER_PASSWORD, SMTP_SERVER, and SMTP_PORT environment variables."

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    if attachment_path and attachment_filename:
        try:
            # Determine MIME type based on actual file extension
            _maintype, _subtype = ('application', 'pdf') if attachment_path.lower().endswith('.pdf') else ('text', 'plain')
            with open(attachment_path, 'rb') as f:
                attach = MIMEApplication(f.read(), _maintype=_maintype, _subtype=_subtype) 
                attach.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
                msg.attach(attach)
        except FileNotFoundError:
            app.logger.error(f"Attachment file not found at {attachment_path}")
            return False, f"Attachment file not found at {attachment_path}"
        except Exception as e:
            app.logger.error(f"Failed to attach file {attachment_path}: {e}", exc_info=True)
            return False, f"Failed to attach invoice: {e}"

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls() # Secure the connection
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True, "Email sent successfully!"
    except smtplib.SMTPAuthenticationError:
        app.logger.error("SMTP Authentication Error: Check SENDER_EMAIL and SENDER_PASSWORD.")
        return False, "Failed to send email: Authentication failed. Check email credentials."
    except smtplib.SMTPConnectError:
        app.logger.error("SMTP Connection Error: Could not connect to SMTP server.")
        return False, "Failed to send email: Could not connect to email server. Check SMTP_SERVER and SMTP_PORT."
    except Exception as e:
        app.logger.error(f"Failed to send email to {recipient_email}: {e}", exc_info=True)
        return False, f"Failed to send email: {e}"

# --- NEW: Function to generate UPI QR code URL ---
def generate_upi_qr_url(upi_id, payee_name, amount, transaction_note="Payment for artwork"):
    # Using api.qrserver.com for dynamic QR code generation
    # URL format: upi://pay?pa={UPI_ID}&pn={PAYEE_NAME}&am={AMOUNT}&cu=INR&tn={TRANSACTION_NOTE}
    # For QR code, we encode this UPI URI.
    # Ensure amount is formatted to 2 decimal places for UPI URI
    upi_uri = f"upi://pay?pa={upi_id}&pn={payee_name.replace(' ', '%20')}&am={amount:.2f}&cu=INR&tn={transaction_note.replace(' ', '%20')}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={upi_uri}"
    return qr_url

# --- Context Processor to pass global data to all templates ---
@app.context_processor
def inject_global_data():
    categories = load_categories_data() # Use the specific loader
    
    # Placeholder for testimonials data (you might load this from a JSON file later)
    testimonials = [
        {
            'name': 'Radha Devi',
            'image': url_for('static', filename='uploads/testimonial_radha.jpg'),
            'rating': 5,
            'feedback': 'The Krishna painting I received is absolutely divine. It brings so much peace to my home. Highly recommend!',
            'product_sku': 'KP001' # Optional: SKU of product reviewed
        },
        {
            'name': 'Arjuna Sharma',
            'image': url_for('static', filename='uploads/testimonial_arjuna.jpg'),
            'rating': 4,
            'feedback': 'Beautiful craftsmanship on the statue. Delivery was prompt and packaging was secure.',
            'product_sku': 'MS002'
        },
        {
            'name': 'Sita Rani',
            'image': url_for('static', filename='uploads/testimonial_sita.jpg'),
            'rating': 5,
            'feedback': 'The personalized options are fantastic! My framed artwork looks stunning.',
            'product_sku': 'PA003'
        },
        {
            'name': 'Krishna Prasad',
            'image': url_for('static', filename='uploads/testimonial_krishna.jpg'),
            'rating': 5,
            'feedback': 'A true treasure! The quality of the print and the intricate details are mesmerizing.',
            'product_sku': 'PG004'
        }
    ]
    
    # Ensure testimonial images exist or use a generic placeholder
    for t in testimonials:
        if t['image'].startswith('/static/'):
            relative_path_from_static = t['image'][len('/static/'):]
        else:
            relative_path_from_static = t['image']

        full_image_path = os.path.join(app.root_path, 'static', relative_path_from_static)

        if not os.path.exists(full_image_path):
            t['image'] = url_for('static', filename='images/user-placeholder.png') # Fallback placeholder

    return dict(
        categories=categories,
        current_user=current_user,
        current_year=datetime.now().year,
        testimonials=testimonials,
        MAX_SHIPPING_COST_FREE_THRESHOLD=MAX_SHIPPING_COST_FREE_THRESHOLD,
        our_business_name=OUR_BUSINESS_NAME,
        our_gstin=OUR_GSTIN,
        our_pan=OUR_PAN,
        our_business_address=OUR_BUSINESS_ADDRESS,
        our_business_email=OUR_BUSINESS_EMAIL,
        default_gst_rate=DEFAULT_INVOICE_GST_RATE,
        now=datetime.now # For invoice date default
    )

# --- Core Logic for Price & Cart Calculation ---
# Helper function to generate a unique ID for cart items based on SKU and options
# This ensures that 'Painting A, size A4' is different from 'Painting A, size Original' in the cart
def generate_cart_item_id(sku, options):
    """
    Generates a unique string ID for a cart item based on its SKU and selected options.
    Options are expected to be a dictionary like {'size': 'A4', 'frame': 'Wooden', 'glass': 'Standard'}.
    """
    # Sort the options to ensure consistent ID generation regardless of dictionary order
    sorted_options_string = "-".join(f"{k}-{v}" for k, v in sorted(options.items()))
    return f"{sku}-{sorted_options_string}".replace(" ", "_").lower() # Replace spaces for cleaner ID


def calculate_item_price_with_options(artwork, size_option, frame_option, glass_option):
    """Calculates the unit price of an artwork based on selected options (before GST)."""
    # Artwork prices are already Decimal due to load_artworks_data
    unit_price = artwork.get('original_price', Decimal('0.00'))

    # Only apply options if the artwork is a 'Painting' or 'photos'
    if artwork.get('category') in ['Paintings', 'photos']: 
        # Add size price
        if size_option == 'A4' and artwork.get('size_a4') is not None:
            unit_price += artwork['size_a4']
        elif size_option == 'A5' and artwork.get('size_a5') is not None:
            unit_price += artwork['size_a5']
        elif size_option == 'Letter' and artwork.get('size_letter') is not None:
            unit_price += artwork['size_letter']
        elif size_option == 'Legal' and artwork.get('size_legal') is not None:
            unit_price += artwork['size_legal']
        # 'Original' size means no extra charge (price already includes artwork.original_price)

        # Add frame price
        if frame_option == 'Wooden' and artwork.get('frame_wooden') is not None:
            unit_price += artwork['frame_wooden']
        elif frame_option == 'Metal' and artwork.get('frame_metal') is not None:
            unit_price += artwork['frame_metal']
        elif frame_option == 'PVC' and artwork.get('frame_pvc') is not None:
            unit_price += artwork['frame_pvc']
        # 'None' frame means no extra charge

        # Add glass price
        if glass_option == 'Standard' and artwork.get('glass_price') is not None:
            unit_price += artwork['glass_price']
        # 'None' glass means no extra charge

    return unit_price # Return Decimal, rounding happens later for display

def calculate_cart_totals(current_cart_session, artworks_data):
    """
    Recalculates all totals for the cart, including GST and shipping.
    Takes the raw session cart (dict of items) and all artworks data.
    Returns a dict with updated cart items, subtotal, GST, shipping, and grand total.
    Important: This function will also adjust quantities in `current_cart_session` if they exceed stock.
    """
    subtotal_before_gst = Decimal('0.00')
    total_gst_amount = Decimal('0.00')
    shipping_charge = Decimal('0.00')
    
    # Process items to get accurate prices, GST, and stock
    processed_cart_items = []
    items_to_remove = [] # Track items that should be removed due to 0 quantity/stock
    
    # Iterate over a copy to safely modify the original current_cart_session
    for item_id, item_data_original in current_cart_session.copy().items():
        # Ensure item_data is a mutable copy for modification within this function
        item_data = item_data_original.copy()
        
        artwork_sku = item_data.get('sku')
        artwork_info = get_artwork_by_sku(artwork_sku) # Use the new helper function

        if not artwork_info:
            app.logger.warning(f"Artwork SKU {artwork_sku} not found in artworks.json. Marking item for removal from cart.")
            items_to_remove.append(item_id)
            continue # Skip to next item if artwork not found

        item_quantity = int(item_data.get('quantity', 1))
        
        stock_available = artwork_info.get('stock', 0)

        # Clamp quantity to available stock (and ensure non-negative)
        if item_quantity > stock_available:
            item_quantity = stock_available # Clamp quantity to available stock
        
        # If item quantity becomes 0 due to clamping, or was already 0/negative, mark for removal
        if item_quantity <= 0:
            items_to_remove.append(item_id)
            continue # Skip further processing for this item

        # Recalculate unit price based on selected options and original prices from artworks_data
        unit_price_before_gst = calculate_item_price_with_options(
            artwork_info,
            item_data.get('size'),
            item_data.get('frame'),
            item_data.get('glass') 
        )
        
        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE) # Already Decimal
        
        item_total_price_before_gst = unit_price_before_gst * item_quantity
        item_gst_amount = item_total_price_before_gst * (gst_percentage / Decimal('100'))
        item_total_price_with_gst = item_total_price_before_gst + item_gst_amount

        # Populate processed_cart_items with all necessary details for the template
        processed_cart_items.append({
            'id': item_id, # Use the unique key from the session cart
            'sku': artwork_sku,
            'name': artwork_info.get('name'),
            'image': artwork_info.get('images', ['/static/images/placeholder.png'])[0], # Ensure a default image
            'category': artwork_info.get('category'),
            'size': item_data.get('size', 'N/A'),
            'frame': item_data.get('frame', 'N/A'),
            'glass': item_data.get('glass', 'N/A'),
            'quantity': item_quantity, # Ensure quantity reflects any clamping
            'unit_price_before_gst': unit_price_before_gst, # Keep as Decimal for calculations
            'total_price_before_gst': item_total_price_before_gst, # Keep as Decimal
            'gst_percentage': gst_percentage, # Keep as Decimal
            'gst_amount': item_gst_amount, # Keep as Decimal
            'total_price': item_total_price_with_gst, # Keep as Decimal # Total price for THIS specific item (qty * unit_price_with_gst)
            'stock_available': stock_available # Add stock for client-side validation
        })

        subtotal_before_gst += item_total_price_before_gst
        total_gst_amount += item_gst_amount
    
    # Remove items marked for removal from the actual session cart
    for item_id_to_remove in items_to_remove:
        if item_id_to_remove in current_cart_session:
            del current_cart_session[item_id_to_remove]
    
    # Reassigning the dict effectively sets session.modified = True for current_cart_session
    # No need to explicitly save_json('orders.json', orders) here, as this function
    # only calculates the summary, it doesn't persist the cart to a file.
    # The calling routes are responsible for saving the session if the cart changes.
    session['cart'] = current_cart_session # Update the session cart with cleaned items
    session.modified = True # Explicitly set for safety

    # Apply shipping charge based on final subtotal
    if subtotal_before_gst > 0 and subtotal_before_gst < MAX_SHIPPING_COST_FREE_THRESHOLD:
        shipping_charge = DEFAULT_SHIPPING_CHARGE # Already Decimal
    else:
        shipping_charge = Decimal('0.00') # Use Decimal

    cgst_amount = total_gst_amount / Decimal('2')
    sgst_amount = total_gst_amount / Decimal('2')
    grand_total = subtotal_before_gst + total_gst_amount + shipping_charge

    return {
        'cart_items': processed_cart_items, # Return the list of processed items (dictionaries)
        'subtotal_before_gst': subtotal_before_gst,
        'total_gst_amount': total_gst_amount,
        'cgst_amount': cgst_amount,
        'sgst_amount': sgst_amount,
        'shipping_charge': shipping_charge,
        'grand_total': grand_total,
        'total_quantity': sum(item['quantity'] for item in processed_cart_items) # Add total quantity here
    }

def get_all_categories():
    try:
        with open('data/categories.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []


# --- Routes ---

@app.route('/')
def index():
    artworks = load_artworks_data() # Use the specific loader
    
    # Filter and categorize artworks for the homepage display
    featured_artworks = [art for art in artworks if art.get('is_featured')] # Assuming a 'is_featured' flag
    
    # Group artworks by category
    artworks_by_category = defaultdict(list)
    for art in artworks:
        category = art.get('category', 'Uncategorized')
        # Only show a few from each category on homepage, maybe limit to 6
        if len(artworks_by_category[category]) < 6: # You can adjust this limit
            artworks_by_category[category].append(art)
    
    # Convert defaultdict to regular dict for rendering, and ensure 'Paintings' comes first if exists
    # And sort other categories alphabetically
    ordered_categories = sorted(artworks_by_category.keys(), key=lambda x: (0, x) if x == 'Paintings' else (1, x))
    artworks_by_category_dict = {cat: artworks_by_category[cat] for cat in ordered_categories} 
    
    return render_template('index.html',
                           featured_artworks=featured_artworks,
                           artworks_by_category=artworks_by_category_dict)

@app.route('/all-products')
def all_products():
    artworks = load_artworks_data()
    
    search_query = request.args.get('query', '').strip().lower() # Get the search query from URL
    category_filter = request.args.get('category') # Get category filter if present

    filtered_artworks = []
    for artwork in artworks:
        # --- Crucial: Ensure artwork has a SKU before processing ---
        if not artwork.get('sku'):
            app.logger.warning(f"Skipping artwork due to missing or invalid SKU: {artwork.get('name', 'Unknown')}")
            continue # Skip this artwork if SKU is missing or falsy (e.g., '', None)

        # Check for search query match
        name_match = search_query in artwork.get('name', '').lower()
        sku_match = search_query in artwork.get('sku', '').lower()
        description_match = search_query in artwork.get('description', '').lower()
        category_match_search = search_query in artwork.get('category', '').lower()

        is_search_match = not search_query or (name_match or sku_match or description_match or category_match_search)

        # Check for category filter match
        is_category_match = not category_filter or (artwork.get('category') == category_filter)

        if is_search_match and is_category_match:
            filtered_artworks.append(artwork)

    # Sort filtered artworks alphabetically by name for a consistent display
    sorted_artworks = sorted(filtered_artworks, key=lambda x: x.get('name', ''))
    
    return render_template('all_products.html', 
                           artworks=sorted_artworks,
                           search_query=search_query, # Pass the query back to the template
                           selected_category=category_filter # Pass selected category back for dropdown
                          )

@app.route('/product/<string:sku>')
def product_detail(sku):
    """
    Renders the detail page for a single product.
    Fetches product information using SKU and passes it to the template.
    """
    artwork = get_artwork_by_sku(sku) # Use the helper function, returns Decimal prices
    if artwork:
        # Prices are already Decimal due to get_artwork_by_sku and load_artworks_data
        return render_template('product_detail.html', artwork=artwork,
                               our_business_email=OUR_BUSINESS_EMAIL,
                               our_business_address=OUR_BUSINESS_ADDRESS,
                               current_year=datetime.now().year)
    flash("Product not found.", "danger")
    return redirect(url_for('index'))

from decimal import Decimal
from flask import request, session, jsonify

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    try:
        data = request.get_json(silent=True)
        app.logger.debug(f"Headers: {dict(request.headers)}")
        app.logger.debug(f"Raw data: {request.data}")
        app.logger.debug(f"JSON payload: {data}")

        if not data:
            return jsonify({"success": False, "message": "Invalid or missing JSON"}), 400

        sku = data.get('sku')
        quantity_raw = data.get('quantity')
        size = data.get('size', 'Original')
        frame = data.get('frame', 'None')
        glass = data.get('glass', 'None')

        if not sku:
            return jsonify({"success": False, "message": "Missing SKU"}), 400

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                return jsonify({"success": False, "message": "Quantity must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid quantity format"}), 400

        artwork_info = get_artwork_by_sku(sku)
        if not artwork_info:
            return jsonify({"success": False, "message": f"Artwork with SKU '{sku}' not found."}), 404

        stock = int(artwork_info.get('stock', 0))
        if stock < quantity:
            return jsonify({"success": False, "message": f"Only {stock} units available."}), 400

        unit_price = calculate_item_price_with_options(artwork_info, size, frame, glass)
        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE)
        gst_decimal = Decimal(gst_percentage) / Decimal('100')

        item_id = generate_cart_item_id(sku, {'size': size, 'frame': frame, 'glass': glass})
        cart = session.get('cart', {})

        if not isinstance(cart, dict):
            cart = {}
            session['cart'] = cart
            session.modified = True

        if item_id in cart:
            existing_qty = cart[item_id].get('quantity', 0)
            new_qty = existing_qty + quantity

            if new_qty > stock:
                return jsonify({
                    "success": False,
                    "message": f"Adding {quantity} more exceeds stock. Only {stock - existing_qty} left.",
                    "current_quantity": existing_qty,
                    "stock": stock
                }), 400

            cart[item_id]['quantity'] = new_qty
        else:
            if quantity > stock:
                return jsonify({"success": False, "message": f"Requested {quantity}, only {stock} available."}), 400

            cart[item_id] = {
                'id': item_id,
                'sku': sku,
                'name': artwork_info.get('name'),
                'image': artwork_info.get('images', ['/static/images/placeholder.png'])[0],
                'category': artwork_info.get('category'),
                'size': size,
                'frame': frame,
                'glass': glass,
                'quantity': quantity,
                'unit_price_before_gst': float(unit_price),
                'gst_percentage': float(gst_percentage),
                'stock_available': stock
            }

        qty = cart[item_id]['quantity']
        cart[item_id]['total_price_before_gst'] = float(unit_price * qty)
        cart[item_id]['gst_amount'] = float((unit_price * qty) * gst_decimal)
        cart[item_id]['total_price'] = cart[item_id]['total_price_before_gst'] + cart[item_id]['gst_amount']

        session['cart'] = cart
        session.modified = True

        updated_summary = calculate_cart_totals(session['cart'], load_artworks_data())

        return jsonify({
            "success": True,
            "message": f"'{artwork_info.get('name')}' added to cart!",
            "total_quantity": updated_summary['total_quantity'],
            "cart_items": updated_summary['cart_items']
        })

    except Exception as e:
        app.logger.error(f"Cart error: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {str(e)}"}), 500

@app.route('/update_cart_session', methods=['POST'])
# REMOVED @login_required: This endpoint should work for all users to update cart display
def update_cart_session():
    """
    Endpoint for client-side JS to sync its local cart state with the server session,
    or to simply fetch the latest server cart state if no 'cart' is provided in payload.
    It returns the calculated cart summary based on the server's session cart.
    """
    data = request.get_json(silent=True) or {}
    client_cart_payload = data.get('cart')

    

    artworks_data = load_artworks_data() 
    
    current_server_cart = session.get('cart', {})
    
    if client_cart_payload is not None:
        pass # No direct update from client_cart_payload here.
    
    # Always calculate totals based on the server's current session['cart']
    # This will also "clean" the cart, removing invalid items or clamping quantities.
    cart_summary = calculate_cart_totals(current_server_cart, artworks_data)
    
    # Update session with the cleaned/recalculated cart from cart_summary, if it changed
    session['cart'] = {item['id']: item for item in cart_summary['cart_items']}
    session.modified = True 

    return jsonify(success=True, message="Cart synchronized.", **cart_summary)


@app.route('/cart')
@login_required # Keeps the cart page requiring login
def cart():
    """
    Renders the shopping cart page, displaying items currently in the user's session cart.
    Calculates and passes cart totals for display.
    """
    artworks_data = load_artworks_data() # Use the specific loader
    cart_data_from_session = session.get('cart', {})

    # Ensure cart_data_from_session is a dictionary (for robustness)
    if not isinstance(cart_data_from_session, dict):
        app.logger.warning(f"Session cart was not a dictionary on /cart. Resetting cart for session ID: {session.sid}")
        cart_data_from_session = {}
        session['cart'] = cart_data_from_session 
        session.modified = True

    # Recalculate totals and items for display based on the session cart
    # This also handles stock clamping and removing items with zero quantity/stock
    cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)
    
    # Ensure the session cart is updated with the cleaned summary before rendering
    session['cart'] = {item['id']: item for item in cart_summary['cart_items']}
    session.modified = True

    return render_template('cart.html',
                           cart_summary=cart_summary, # PASS THE ENTIRE DICTIONARY
                           MAX_SHIPPING_COST_FREE_THRESHOLD=MAX_SHIPPING_COST_FREE_THRESHOLD)

@app.route('/update_cart_item_quantity', methods=['POST'])
@login_required # Keeps this action requiring login
def update_cart_item_quantity():
    """
    Updates the quantity of a specific item in the user's cart via AJAX POST.
    Performs stock validation and recalculates cart totals.
    """
    try:
        data = request.get_json()
        item_id = data.get('id') # Using 'id' as per JS
        new_quantity_raw = data.get('quantity') # Using 'quantity' as per JS

        if not item_id or new_quantity_raw is None:
            return jsonify(success=False, message="Invalid request data (item_id or new_quantity missing)."), 400

        current_cart_session = session.get('cart', {})
        
        # Store original quantity for potential rollback in JS if error occurs
        original_item_data = current_cart_session.get(item_id)
        original_quantity = original_item_data.get('quantity') if original_item_data else None

        artwork_sku = original_item_data.get('sku') if original_item_data else None
        artwork_info = get_artwork_by_sku(artwork_sku) # Use the helper function

        if not artwork_info:
            # If product details are not found, remove the item from cart
            if item_id in current_cart_session:
                del current_cart_session[item_id]
                session['cart'] = current_cart_session # Update session
                session.modified = True
            updated_cart_summary = calculate_cart_totals(session.get('cart', {}), load_artworks_data())
            return jsonify(success=True, message="Artwork details not found for cart item, item removed.", cart_summary=updated_cart_summary, item_removed=True), 200

        available_stock = artwork_info.get('stock', 0)
        message = ""
        item_removed = False

        try:
            new_quantity = int(new_quantity_raw) # Convert to int
        except (ValueError, TypeError):
            app.logger.warning(f"Invalid new_quantity format for item_id {item_id}: {new_quantity_raw}")
            return jsonify(success=False, message="Invalid quantity format provided.", current_quantity=original_quantity), 400

        if new_quantity < 1: 
            # If quantity is less than 1, remove the item
            if item_id in current_cart_session:
                del current_cart_session[item_id]
                session['cart'] = current_cart_session
                session.modified = True
                message = "Item removed from cart."
                item_removed = True
        elif new_quantity > available_stock:
            # If new quantity exceeds stock, clamp to available stock
            current_cart_session[item_id]['quantity'] = available_stock
            session['cart'] = current_cart_session
            session.modified = True
            message = f"Only {available_stock} of {artwork_info.get('name')} available. Quantity adjusted."
            if available_stock == 0: # If stock is zero, truly remove the item
                del current_cart_session[item_id]
                session['cart'] = current_cart_session
                session.modified = True
                item_removed = True
                message = f"No stock for {artwork_info.get('name')}. Item removed."
        else:
            # Update quantity normally
            current_cart_session[item_id]['quantity'] = new_quantity
            session['cart'] = current_cart_session
            session.modified = True
            message = "Cart updated."

        updated_cart_summary = calculate_cart_totals(session.get('cart', {}), load_artworks_data())

        response_data = {
            'success': True,
            'message': message,
            'cart_summary': updated_cart_summary,
            'item_removed': item_removed,
            'current_quantity': original_quantity # For client-side rollback if needed
        }
        
        # If item was not removed by logic above, try to find its updated details for JS
        if not item_removed:
            updated_item_in_summary = next((item for item in updated_cart_summary['cart_items'] if item['id'] == item_id), None)
            if updated_item_in_summary:
                response_data['updated_item'] = updated_item_in_summary
            else:
                # This scenario means calculate_cart_totals removed it (e.g. stock clamping to 0)
                # It means it was effectively removed, even if not explicitly by `del` in this block.
                response_data['item_removed'] = True
                response_data['message'] = f"Item {artwork_info.get('name')} removed from cart (quantity became 0 or out of stock)."

        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"ERROR: update_cart_item_quantity: {e}", exc_info=True)
        # Return the original quantity to allow JS to revert the UI state
        return jsonify(success=False, message=f"Error updating cart quantity: {e}", current_quantity=original_quantity if original_quantity is not None else 0), 500

@app.route('/remove_from_cart', methods=['POST'])
@login_required # Keeps this action requiring login
def remove_from_cart():
    """
    Removes a specific item from the user's cart via AJAX POST.
    Recalculates and returns updated cart totals.
    """
    try:
        data = request.get_json()
        item_id = data.get('id') # Using 'id' as per JS

        if not item_id:
            return jsonify(success=False, message="Item ID is required."), 400

        current_cart_session = session.get('cart', {})
        if item_id in current_cart_session:
            del current_cart_session[item_id]
            session['cart'] = current_cart_session # Update session
            session.modified = True
        else:
            return jsonify(success=False, message="Item not found in cart."), 404
        
        artworks_data = load_artworks_data()
        updated_cart_summary = calculate_cart_totals(current_cart_session, artworks_data)

        # The JS expects `cart_summary` key in the response
        return jsonify(success=True, message="Item removed.", cart_summary=updated_cart_summary), 200

    except Exception as e:
        app.logger.error(f"ERROR: remove_from_cart: {e}", exc_info=True)
        return jsonify(success=False, message=f"Error removing item from cart: {e}"), 500

# --- NEW: Endpoint to process checkout from cart page ---
@app.route('/process_checkout_from_cart', methods=['POST'])
@login_required
def process_checkout_from_cart():
    """
    Validates the cart and redirects to the purchase form.
    This replaces the direct form submission from cart.html.
    """
    cart_data_from_session = session.get('cart', {})
    if not cart_data_from_session:
        flash("Your cart is empty. Please add items to proceed to checkout.", "danger")
        return redirect(url_for('cart'))

    artworks_data = load_artworks_data()
    cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)

    if not cart_summary['cart_items']:
        flash("Your cart is empty or all items are out of stock. Please add items to proceed.", "danger")
        return redirect(url_for('all_products'))

    # If everything is fine, redirect to the purchase form
    # The purchase_form route will then load the cart data from session['cart']
    return redirect(url_for('purchase_form'))

# --- NEW: Endpoint for direct "Buy Now" functionality ---
@app.route('/create_direct_order', methods=['POST'])
@login_required
def create_direct_order():
    """
    Processes a single item for direct purchase (Buy Now button).
    Stores the item in session as 'direct_purchase_item' and redirects to the purchase form.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data received"}), 400

        sku = data.get('sku')
        quantity_raw = data.get('quantity')
        size = data.get('size', 'Original')
        frame = data.get('frame', 'None')
        glass = data.get('glass', 'None')

        if not sku:
            return jsonify({"success": False, "message": "Missing SKU"}), 400

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                return jsonify({"success": False, "message": "Quantity must be positive"}), 400
        except (ValueError, TypeError):
            app.logger.warning(f"Invalid quantity format received for SKU {sku}: {quantity_raw}")
            return jsonify({"success": False, "message": f"Invalid quantity format received. Please enter a valid number."}), 400

        artwork_info = get_artwork_by_sku(sku)
        if not artwork_info:
            return jsonify({"success": False, "message": f"Artwork with SKU '{sku}' not found."}), 404
        
        artwork_stock = int(artwork_info.get('stock', 0))
        if artwork_stock < quantity:
            return jsonify({"success": False, "message": f"Only {artwork_stock} units of {artwork_info['name']} are available."}), 400

        # Calculate unit price for the specific item with selected options (before GST)
        unit_price_before_options = artwork_info.get('original_price', Decimal('0.00')) # Base price before options added
        unit_price_before_gst = calculate_item_price_with_options(artwork_info, size, frame, glass)
        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE)

        total_price_before_gst = unit_price_before_gst * quantity
        gst_amount = total_price_before_gst * (gst_percentage / Decimal('100'))
        total_price = total_price_before_gst + gst_amount

        # Store the single item's details in session for direct purchase
        session['direct_purchase_item'] = {
            'sku': sku,
            'name': artwork_info.get('name'),
            'image': artwork_info.get('images', ['/static/images/placeholder.png'])[0],
            'category': artwork_info.get('category'),
            'size': size,
            'frame': frame,
            'glass': glass,
            'quantity': quantity,
            'unit_price_before_options': unit_price_before_options, # Original price of item
            'unit_price_before_gst': unit_price_before_gst, # Unit price after options
            'total_price_before_gst': total_price_before_gst,
            'gst_percentage': gst_percentage,
            'gst_amount': gst_amount,
            'total_price': total_price # Total price for this item including GST
        }
        session.pop('cart', None) # Ensure normal cart is cleared if using "Buy Now"
        session.modified = True

        # Redirect to the purchase form
        return jsonify(success=True, message="Proceeding to checkout.", redirect_url=url_for('purchase_form')), 200

    except Exception as e:
        app.logger.error(f"Error creating direct order: {e}", exc_info=True)
        return jsonify(success=False, message=f"An unexpected error occurred: {e}"), 500


@app.route('/purchase_form', methods=['GET', 'POST'])
@login_required
def purchase_form():
    """
    Handles the display and submission of the purchase form.
    Calculates final order details based on cart or direct purchase item.
    """
    if request.method == 'GET':
        item_for_direct_purchase = session.get('direct_purchase_item')

        if item_for_direct_purchase:
            try:
                # Ensure all relevant fields are Decimal objects upon retrieval from session
                item_for_direct_purchase['total_price_before_gst'] = Decimal(str(item_for_direct_purchase.get('total_price_before_gst', '0.00')))
                item_for_direct_purchase['gst_amount'] = Decimal(str(item_for_direct_purchase.get('gst_amount', '0.00')))
                item_for_direct_purchase['total_price'] = Decimal(str(item_for_direct_purchase.get('total_price', '0.00')))
                item_for_direct_purchase['unit_price_before_options'] = Decimal(str(item_for_direct_purchase.get('unit_price_before_options', '0.00')))
                item_for_direct_purchase['unit_price_before_gst'] = Decimal(str(item_for_direct_purchase.get('unit_price_before_gst', '0.00')))
                item_for_direct_purchase['gst_percentage'] = Decimal(str(item_for_direct_purchase.get('gst_percentage', '0.00')))

            except InvalidOperation as e:
                app.logger.error(f"Error converting direct purchase item decimals on GET /purchase_form: {e}", exc_info=True)
                flash("Error processing direct purchase item. Please try again.", "danger")
                session.pop('direct_purchase_item', None) # Clear invalid item
                session.modified = True
                return redirect(url_for('all_products'))

            cart_summary = {
                'cart_items': [item_for_direct_purchase],
                'subtotal_before_gst': item_for_direct_purchase['total_price_before_gst'],
                'total_gst_amount': item_for_direct_purchase['gst_amount'],
                'cgst_amount': item_for_direct_purchase['gst_amount'] / Decimal('2'),
                'sgst_amount': item_for_direct_purchase['gst_amount'] / Decimal('2'),
                'shipping_charge': Decimal('0.00'), 
                'grand_total': Decimal('0.00')    
            }
            if cart_summary['subtotal_before_gst'] > 0 and cart_summary['subtotal_before_gst'] < MAX_SHIPPING_COST_FREE_THRESHOLD:
                cart_summary['shipping_charge'] = DEFAULT_SHIPPING_CHARGE
            cart_summary['grand_total'] = cart_summary['subtotal_before_gst'] + cart_summary['total_gst_amount'] + cart_summary['shipping_charge']

        else: # This branch is for items coming from the regular cart session
            cart_data_from_session = session.get('cart', {})
            if not isinstance(cart_data_from_session, dict):
                app.logger.warning(f"Session cart was not a dictionary on /purchase_form (cart path). Resetting cart for session ID: {session.sid}")
                cart_data_from_session = {}
                session['cart'] = cart_data_from_session 
                session.modified = True

            if not cart_data_from_session:
                flash('Your cart is empty. Please add items to proceed to checkout.', 'info')
                return redirect(url_for('cart'))

            artworks_data = load_artworks_data()
            cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)
            
            try:
                cart_summary['subtotal_before_gst'] = Decimal(str(cart_summary.get('subtotal_before_gst', '0.00')))
                cart_summary['total_gst_amount'] = Decimal(str(cart_summary.get('total_gst_amount', '0.00')))
                cart_summary['cgst_amount'] = Decimal(str(cart_summary.get('cgst_amount', '0.00')))
                cart_summary['sgst_amount'] = Decimal(str(cart_summary.get('sgst_amount', '0.00')))
                cart_summary['shipping_charge'] = Decimal(str(cart_summary.get('shipping_charge', '0.00')))
                cart_summary['grand_total'] = Decimal(str(cart_summary.get('grand_total', '0.00')))
            except InvalidOperation as e:
                app.logger.error(f"Error converting cart_summary decimals in /purchase_form (cart path): {e}", exc_info=True)
                flash("Error processing cart. Please try again.", "danger")
                session.pop('cart', None) 
                session.modified = True
                return redirect(url_for('all_products'))


            if not cart_summary['cart_items']:
                flash('Your cart is empty or all items are out of stock. Please add items to proceed.', 'info')
                return redirect(url_for('all_products'))

        user = current_user
        users_data = load_users_data() 
        user_data_from_db = next((u for u in users_data if u['id'] == str(user.id)), None)

        context = {
            'prefill_name': user_data_from_db.get('name') if user_data_from_db else '',
            'prefill_email': user_data_from_db.get('email') if user_data_from_db else '',
            'prefill_phone': user_data_from_db.get('phone') if user_data_from_db else '',
            'prefill_address': user_data_from_db.get('address') if user_data_from_db else '',
            'prefill_pincode': user_data_from_db.get('pincode') if user_data_from_db else '',
            'cart_summary': cart_summary,
            'cart_json': json.dumps(cart_summary['cart_items'], cls=CustomJsonEncoder)
        }
        return render_template('purchase_form.html', **context)

    elif request.method == 'POST':
        user_id = str(current_user.id)
        
        item_for_direct_purchase = session.pop('direct_purchase_item', None)
        session.modified = True

        if item_for_direct_purchase:
            items_to_process = [item_for_direct_purchase]
            subtotal_before_gst = Decimal(str(item_for_direct_purchase.get('total_price_before_gst', '0.00')))
            total_gst_amount = Decimal(str(item_for_direct_purchase.get('gst_amount', '0.00')))
            shipping_charge = DEFAULT_SHIPPING_CHARGE if (subtotal_before_gst > 0 and subtotal_before_gst < MAX_SHIPPING_COST_FREE_THRESHOLD) else Decimal('0.00')
            total_amount = subtotal_before_gst + total_gst_amount + shipping_charge
        else:
            cart_data_from_session = session.pop('cart', {})
            session.modified = True
            if not cart_data_from_session:
                flash("Your cart is empty, cannot proceed with purchase.", "danger")
                return redirect(url_for('cart'))
            
            artworks_data = load_artworks_data()
            cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)
            items_to_process = cart_summary['cart_items']
            total_amount = Decimal(str(cart_summary.get('grand_total', '0.00')))
            subtotal_before_gst = Decimal(str(cart_summary.get('subtotal_before_gst', '0.00')))
            total_gst_amount = Decimal(str(cart_summary.get('total_gst_amount', '0.00')))
            shipping_charge = Decimal(str(cart_summary.get('shipping_charge', '0.00'))) 

        if not items_to_process:
            flash("No items to purchase. Please add items to your cart.", "danger")
            return redirect(url_for('index'))
        
        customer_name = request.form.get('name', current_user.name)
        customer_email = request.form.get('email', current_user.email)
        customer_phone = request.form.get('phone', current_user.phone)
        customer_address = request.form.get('address', current_user.address)
        customer_pincode = request.form.get('pincode', current_user.pincode)

        users = load_users_data() 
        for i, u_data in enumerate(users):
            if str(u_data['id']) == user_id:
                users[i]['name'] = customer_name
                users[i]['email'] = customer_email
                users[i]['phone'] = customer_phone
                users[i]['address'] = customer_address
                users[i]['pincode'] = customer_pincode
                save_json('users.json', users)
                current_user.name = customer_name
                current_user.email = customer_email
                current_user.phone = customer_phone
                current_user.address = customer_address
                current_user.pincode = customer_pincode
                break

        try:
            new_order_id = str(uuid.uuid4())[:8].upper()
            
            new_order = {
                'order_id': new_order_id,
                'user_id': user_id,
                'user_email': customer_email,
                'customer_name': customer_name,
                'customer_phone': customer_phone,
                'customer_address': customer_address,
                'customer_pincode': customer_pincode,
                'placed_on': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'items': items_to_process, 
                'subtotal_before_gst': subtotal_before_gst,
                'total_gst_amount': total_gst_amount,
                'cgst_amount': total_gst_amount / Decimal('2'),
                'sgst_amount': total_gst_amount / Decimal('2'),
                'shipping_charge': shipping_charge,
                'total_amount': total_amount,
                'status': "Pending Payment", # Initial status before payment screen
                'remark': '',
                'courier': '', # Initialize new fields
                'tracking_number': '', # Initialize new fields
                'invoice_details': {
                    'invoice_status': 'Not Applicable',
                    'is_held_by_admin': False,
                    'invoice_pdf_path': None
                }
            }

            orders = load_orders_data()
            orders.append(new_order)
            save_json('orders.json', orders)

            # --- Stock Deduction ---
            artworks_to_update = load_artworks_data() # Load current stock
            artwork_map = {a['sku']: a for a in artworks_to_update} # Create a map for efficient lookup

            for item in items_to_process:
                sku = item['sku']
                quantity_ordered = item['quantity']
                if sku in artwork_map:
                    original_stock = artwork_map[sku].get('stock', 0)
                    if original_stock >= quantity_ordered:
                        artwork_map[sku]['stock'] = original_stock - quantity_ordered
                    else:
                        app.logger.warning(f"Ordered quantity {quantity_ordered} for SKU {sku} exceeds available stock {original_stock} during final order placement. Stock will go negative.")
                        artwork_map[sku]['stock'] = 0 # Or handle negative stock if business logic allows
            save_json('artworks.json', artworks_to_update) # Save updated stock levels


            flash("Order placed successfully. Please complete the payment.", "success")
            return redirect(url_for('payment_initiate', order_id=new_order_id, amount=float(new_order['total_amount'])))

        except Exception as e:
            app.logger.error(f"An unexpected error occurred during purchase form submission: {e}", exc_info=True)
            flash(f"An unexpected error occurred during your purchase. Please try again. Error: {e}", "danger")
            if not item_for_direct_purchase:
                # If it was a cart purchase, restore cart items to session
                session['cart'] = {item['id']: item for item in items_to_process}
            else:
                # If it was a direct purchase, restore the single item to session
                session['direct_purchase_item'] = items_to_process[0]
            session.modified = True
            return redirect(url_for('purchase_form'))

@app.route('/payment_initiate/<order_id>/<float:amount>')
@login_required
def payment_initiate(order_id, amount):
    """
    Renders the payment initiation page, showing UPI details and QR code.
    """
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order or order.get('user_id') != str(current_user.id):
        flash('Order not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('my_orders'))
    
    # Ensure amount is Decimal for QR URL generation
    amount_decimal = Decimal(str(amount))

    # Generate UPI QR URL
    qr_code_url = generate_upi_qr_url(UPI_ID, BANKING_NAME, amount_decimal, f"Payment for Order {order_id}")

    # Generate QR Code Image as base64 string
    qr = qrcode.make(qr_code_url)
    buffered = io.BytesIO()
    qr.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()

    return render_template('payment_initiate.html',
        order_id=order_id,
        amount=amount_decimal,
        upi_id=UPI_ID,
        banking_name=BANKING_NAME,
        bank_name=BANK_NAME,
        qr_code_url=qr_code_url,
        qr_image=qr_base64
    )

@app.route('/payment_submit/<order_id>', methods=['POST'])
@login_required
def payment_submit(order_id):
    """
    Handles submission of payment screenshot and updates order status.
    """
    orders = load_orders_data()
    order_found = False
    for i, order in enumerate(orders):
        if order.get('order_id') == order_id and order.get('user_id') == str(current_user.id):
            order_found = True
            if 'payment_screenshot' in request.files:
                file = request.files['payment_screenshot']
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['PAYMENT_SCREENSHOTS_FOLDER'], unique_filename)
                    file.save(file_path)
                    orders[i]['payment_screenshot_path'] = f'uploads/payment_screenshots/{unique_filename}'
                    orders[i]['transaction_id'] = request.form.get('transaction_id', '').strip()
                    orders[i]['payment_submitted_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    orders[i]['status'] = 'Payment Submitted - Awaiting Verification' # More precise status
                    save_json('orders.json', orders)
                    flash('Payment details submitted successfully! Your order is now under review.', 'success')

                    # Empty the cart after successful payment submission
                    session.pop('cart', None)
                    session.pop('direct_purchase_item', None) # Clear direct purchase item too
                    session.modified = True

                    return redirect(url_for('thank_you_page', order_id=order_id))
                else:
                    flash('No payment screenshot uploaded.', 'danger')
            else:
                flash('Payment screenshot is required.', 'danger')
            break
    
    if not order_found:
        flash('Order not found or you do not have permission to update it.', 'danger')
    
    # If there was an error, redirect back to payment initiation with flash message
    return redirect(url_for('payment_initiate', order_id=order_id, amount=order.get('total_amount', Decimal('0.00'))))


@app.route('/thank_you/<order_id>')
@login_required
def thank_you_page(order_id):
    """
    Renders a thank you page after successful order placement and payment submission.
    """
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)
    
    if not order or order.get('user_id') != str(current_user.id):
        flash("Thank you page for this order is not accessible.", "danger")
        return redirect(url_for('index'))

    return render_template('thank_you.html', order=order)

@app.route('/my-orders')
@login_required
def my_orders():
    """
    Displays all orders placed by the current logged-in user.
    """
    orders = load_orders_data()
    user_orders = [o for o in orders if o.get('user_id') == str(current_user.id)]
    # Sort orders by placed_on date, newest first
    user_orders.sort(key=lambda x: datetime.strptime(x['placed_on'], "%Y-%m-%d %H:%M:%S"), reverse=True)
    return render_template('my_orders.html', orders=user_orders)

@app.route('/cancel_order/<order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    """
    Allows a user to cancel their own order if it's in a 'Pending Payment' or 'Payment Submitted - Awaiting Verification' state.
    """
    orders = load_orders_data()
    artworks = load_artworks_data() # To update stock if necessary
    
    order_found = False
    for i, order in enumerate(orders):
        if order.get('order_id') == order_id and order.get('user_id') == str(current_user.id):
            order_found = True
            # Only allow cancellation if payment is pending or under review
            if order.get('status') in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
                orders[i]['status'] = 'Cancelled by User'
                orders[i]['remark'] = 'Order cancelled by user.'
                orders[i]['cancelled_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Restore stock for the cancelled items
                artwork_map = {a['sku']: a for a in artworks}
                for item in order.get('items', []):
                    sku = item['sku']
                    quantity_cancelled = item['quantity']
                    if sku in artwork_map:
                        artwork_map[sku]['stock'] = artwork_map[sku].get('stock', 0) + quantity_cancelled
                save_json('artworks.json', artworks) # Save updated stock

                save_json('orders.json', orders)
                flash(f'Order {order_id} has been cancelled successfully. Stock restored.', 'success')
            else:
                flash(f'Order {order_id} cannot be cancelled as its status is "{order.get("status")}".', 'danger')
            break
    
    if not order_found:
        flash('Order not found or you do not have permission to cancel it.', 'danger')
    
    return redirect(url_for('my_orders'))

# --- Admin Routes ---
@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard landing page."""

    filter_status = request.args.get('filter_status')
    search_query = request.args.get('search', '').strip().lower()

    # Load all data
    orders = load_orders_data()
    artworks = load_artworks_data()
    users = load_users_data()

    # Apply search filter
    if search_query:
        orders = [o for o in orders if search_query in o.get('order_id', '').lower() or search_query in o.get('user_id', '').lower()]

    # Apply status filter
    if filter_status:
        orders = [o for o in orders if o.get('status') == filter_status]

    total_orders = len(orders)
    total_artworks = len(artworks)
    total_users = len(users)

    total_revenue = Decimal('0.00')
    for order in orders:
        if order.get('status') in ['Shipped', 'Delivered', 'Payment Confirmed', 'Payment Verified – Preparing Order']:
            total_revenue += Decimal(str(order.get('total_amount', '0.00')))

    low_stock_threshold = 10
    low_stock_artworks = [a for a in artworks if 0 < a.get('stock', 0) <= low_stock_threshold]
    out_of_stock_artworks = [a for a in artworks if a.get('stock', 0) == 0]

    orders_pending_review = [
        o for o in orders 
        if o.get('status') == 'Payment Submitted - Awaiting Verification' or
           (o.get('invoice_details', {}).get('is_held_by_admin') and o.get('status') != 'Delivered')
    ]

    revenue_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
    revenue_values = [12000, 15000, 11000, 18000, 20000, 17000]

    return render_template(
        'admin_panel.html',
        total_orders=total_orders,
        total_artworks=total_artworks,
        total_users=total_users,
        total_revenue=total_revenue,
        low_stock_artworks=low_stock_artworks,
        out_of_stock_artworks=out_of_stock_artworks,
        orders=orders,
        artworks=artworks,
        orders_pending_review=orders_pending_review,
        revenue_labels=revenue_labels,
        revenue_values=revenue_values,
        search_query=search_query
    )


@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/panel')
@admin_login_required
def admin_panel():
    return render_template('admin_panel.html')

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/artworks')
@admin_login_required
def admin_artworks_view():
    try:
        with open('data/artworks.json', 'r') as f:  # ✅ updated path
            artworks = json.load(f)
    except Exception as e:
        print("Error loading artworks:", e)
        artworks = []

    return render_template('admin_artworks_view.html', artworks=artworks)





@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/users')
@admin_required
def admin_users_view():
    users = load_users_data()
    return render_template('admin_users_view.html', users=users)

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/users/toggle_role/<user_id>', methods=['POST'])
@admin_required
def admin_toggle_user_role(user_id):
    users = load_users_data()
    for user_data in users:
        if user_data['id'] == user_id:
            if user_data['role'] == 'user':
                user_data['role'] = 'admin'
                flash(f"User {user_data['name']} is now an Admin.", "success")
            else:
                user_data['role'] = 'user'
                flash(f"User {user_data['name']} is now a Regular User.", "success")
            save_json('users.json', users)
            return jsonify(success=True)
    return jsonify(success=False, message="User not found."), 404

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == str(current_user.id):
        return jsonify(success=False, message="You cannot delete your own admin account."), 400

    users = load_users_data()
    original_len = len(users)
    users = [u for u in users if u['id'] != user_id]
    if len(users) < original_len:
        save_json('users.json', users)
        flash(f'User {user_id} deleted successfully.', 'success')
        return jsonify(success=True)
    else:
        flash(f'User {user_id} not found.', 'danger')
        return jsonify(success=False, message="User not found."), 404

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/orders')
@admin_required
def admin_orders_view():
    orders = load_orders_data()
    
    # Get filter parameters from query string
    filter_status = request.args.get('status')
    filter_invoice_status = request.args.get('invoice_status')
    search_query = request.args.get('search_query', '').strip().lower()

    filtered_orders = []
    for order in orders:
        status_match = (not filter_status) or (order.get('status') == filter_status)
        
        invoice_status_val = order.get('invoice_details', {}).get('invoice_status')
        invoice_status_match = (not filter_invoice_status) or (invoice_status_val == filter_invoice_status)
        
        search_match = (not search_query) or \
                       (search_query in order.get('order_id', '').lower()) or \
                       (search_query in order.get('customer_name', '').lower()) or \
                       (search_query in order.get('user_email', '').lower())

        if status_match and invoice_status_match and search_match:
            filtered_orders.append(order)

    # Sort orders by placed_on, newest first
    filtered_orders.sort(key=lambda x: datetime.strptime(x['placed_on'], "%Y-%m-%d %H:%M:%S"), reverse=True)
    
    return render_template('admin_orders_view.html',
                           orders=filtered_orders,
                           current_filter_status=filter_status,
                           current_filter_invoice_status=filter_invoice_status,
                           current_search_query=search_query)

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/order/update_status/<order_id>', methods=['POST'])
@admin_required
def admin_update_order_status(order_id):
    orders = load_orders_data()
    data = request.get_json()
    new_status = data.get('status') # This is the main status from the modal
    remark = data.get('remark', '').strip()
    courier = data.get('courier', '').strip() # Get courier
    tracking_number = data.get('tracking_number', '').strip() # Get tracking number


    if not new_status:
        # If new_status is not provided, it means this is likely just an remark/courier/tracking update
        # In this case, get the existing status from the order to preserve it.
        order_to_update = next((o for o in orders if o.get('order_id') == order_id), None)
        if order_to_update:
            new_status = order_to_update.get('status') # Use current status if not explicitly updated
        else:
            return jsonify(success=False, message=f'Order {order_id} not found.'), 404


    order_found = False
    for i, order in enumerate(orders):
        if order.get('order_id') == order_id:
            orders[i]['status'] = new_status
            orders[i]['remark'] = remark
            orders[i]['courier'] = courier # Save courier
            orders[i]['tracking_number'] = tracking_number # Save tracking number
            
            # If order is shipped, and invoice is not yet prepared/sent, set status to prepared
            if new_status == 'Shipped' and orders[i].get('invoice_details', {}).get('invoice_status') in ['Not Applicable', None]:
                if 'invoice_details' not in orders[i] or not isinstance(orders[i]['invoice_details'], dict):
                    orders[i]['invoice_details'] = {}
                orders[i]['invoice_details']['invoice_status'] = 'Prepared'
            
            save_json('orders.json', orders)
            flash(f'Status for Order {order_id} updated to "{new_status}".', 'success')
            order_found = True
            return jsonify(success=True, message=f'Status for Order {order_id} updated to "{new_status}".')
    
    if not order_found:
        flash(f'Order {order_id} not found.', 'danger')
    return jsonify(success=False, message=f'Order {order_id} not found.'), 404

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/order/invoice/<order_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_invoice(order_id):
    orders = load_orders_data()
    order = next((o for o in orders if o.get('order_id') == order_id), None)
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders_view'))

    if 'invoice_details' not in order or not isinstance(order['invoice_details'], dict):
        order['invoice_details'] = {}
    
    # Initialize invoice_details with default values if not present
    invoice_det = order['invoice_details']
    invoice_det.setdefault('invoice_number', f"INV-{order_id}-{datetime.now().strftime('%Y%m%d')}")
    invoice_det.setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d"))
    invoice_det.setdefault('billing_address', order.get('customer_address', ''))
    invoice_det.setdefault('gst_rate_applied', DEFAULT_INVOICE_GST_RATE)
    invoice_det.setdefault('business_name', OUR_BUSINESS_NAME)
    invoice_det.setdefault('gst_number', OUR_GSTIN)
    invoice_det.setdefault('pan_number', OUR_PAN)
    invoice_det.setdefault('business_address', OUR_BUSINESS_ADDRESS)

    # Ensure these are initialized as Decimals (from order totals if not explicitly set)
    invoice_det.setdefault('total_gst_amount', order.get('total_gst_amount', Decimal('0.00')))
    invoice_det.setdefault('cgst_amount', order.get('cgst_amount', Decimal('0.00')))
    invoice_det.setdefault('sgst_amount', order.get('sgst_amount', Decimal('0.00')))
    invoice_det.setdefault('shipping_charge', order.get('shipping_charge', Decimal('0.00')))
    invoice_det.setdefault('final_invoice_amount', order.get('total_amount', Decimal('0.00')))
    invoice_det.setdefault('invoice_status', 'Not Applicable' if order.get('status') != 'Shipped' else 'Prepared')
    invoice_det.setdefault('is_held_by_admin', False)
    invoice_det.setdefault('invoice_pdf_path', None)
    invoice_det.setdefault('invoice_email_sent_on', None)


    if request.method == 'POST':
        try:
            invoice_det['business_name'] = request.form['business_name']
            invoice_det['gst_number'] = request.form['gst_number']
            invoice_det['pan_number'] = request.form['pan_number']
            invoice_det['business_address'] = request.form['business_address']

            invoice_det['invoice_number'] = request.form['invoice_number']
            invoice_det['invoice_date'] = datetime.fromisoformat(request.form['invoice_date']).strftime("%Y-%m-%d %H:%M:%S")
            invoice_det['billing_address'] = request.form['billing_address']

            # CRITICAL FIX: Convert these to Decimal BEFORE calculations
            gst_rate_applied = Decimal(request.form['gst_rate'])
            shipping_charge_form = Decimal(request.form['shipping_charge'])

            base_subtotal = order.get('subtotal_before_gst', Decimal('0.00'))
            
            total_gst_amount_recalc = base_subtotal * (gst_rate_applied / Decimal('100'))
            cgst_amount_recalc = total_gst_amount_recalc / Decimal('2')
            sgst_amount_recalc = total_gst_amount_recalc / Decimal('2')
            final_invoice_amount_recalc = base_subtotal + total_gst_amount_recalc + shipping_charge_form

            invoice_det['gst_rate_applied'] = gst_rate_applied
            invoice_det['total_gst_amount'] = total_gst_amount_recalc
            invoice_det['cgst_amount'] = cgst_amount_recalc
            invoice_det['sgst_amount'] = sgst_amount_recalc
            invoice_det['shipping_charge'] = shipping_charge_form
            invoice_det['final_invoice_amount'] = final_invoice_amount_recalc
            
            if invoice_det.get('invoice_status') in ['Prepared', 'Sent']:
                invoice_det['invoice_status'] = 'Edited'
            if invoice_det.get('invoice_status') == 'Edited' and not invoice_det.get('is_held_by_admin'):
                invoice_det['is_held_by_admin'] = True

            save_json('orders.json', orders)
            flash(f'Invoice details for Order {order_id} updated successfully.', 'success')
            return redirect(url_for('admin_orders_view'))

        except Exception as e:
            flash(f'Error updating invoice: {e}', 'danger')
            app.logger.error(f"Error in admin_edit_invoice: {e}", exc_info=True)

    return render_template('admin_edit_invoice.html', order=order)

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/invoice/hold/<order_id>', methods=['POST'])
@admin_required
def admin_hold_invoice(order_id):
    orders = load_orders_data()
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            if 'invoice_details' not in order:
                order['invoice_details'] = {}
            order['invoice_details']['is_held_by_admin'] = True
            order['invoice_details']['invoice_status'] = 'Held'
            save_json('orders.json', orders)
            flash(f'Invoice for Order {order_id} put on HOLD.', 'success')
            order_found = True
            return jsonify(success=True, message=f'Invoice for Order {order_id} put on HOLD.')
    if not order_found:
        flash(f'Order {order_id} not found.', 'danger')
    return jsonify(success=False, message=f'Order {order_id} not found.'), 404


@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/invoice/release/<order_id>', methods=['POST'])
@admin_required
def admin_release_invoice(order_id):
    orders = load_orders_data()
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            if 'invoice_details' not in order:
                order['invoice_details'] = {}
            order['invoice_details']['is_held_by_admin'] = False
            order['invoice_details']['invoice_status'] = 'Prepared' if order.get('status') == 'Shipped' else 'Not Applicable'
            save_json('orders.json', orders)
            flash(f'Invoice for Order {order_id} RELEASED.', 'success')
            order_found = True
            break
    if not order_found:
        flash(f'Order {order_id} not found.', 'danger')
    return jsonify(success=False, message=f'Order {order_id} not found.'), 404

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/invoice/send_email/<order_id>', methods=['POST'])
@admin_required
def admin_send_invoice_email(order_id):
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        return jsonify(success=False, message=f'Order {order_id} not found.'), 404
    
    if order.get('invoice_details', {}).get('is_held_by_admin'):
        return jsonify(success=False, message=f'Invoice for Order {order_id} is on HOLD by admin. Release it first.'), 400

    if order.get('invoice_details', {}).get('invoice_status') == 'Sent':
        # Allow resending an email if needed for debugging or re-delivery
        # return jsonify(success=False, message=f'Invoice for Order {order_id} has already been sent.'), 400
        pass 
    
    # 1. Generate PDF (now this will be a real PDF thanks to ReportLab)
    invoice_pdf_path_relative = generate_invoice_pdf(order_id, order)
    if not invoice_pdf_path_relative:
        return jsonify(success=False, message="Failed to generate invoice PDF."), 500
    
    # Update order with the generated PDF path
    order['invoice_details']['invoice_pdf_path'] = invoice_pdf_path_relative
    save_json('orders.json', orders) # Save with the new PDF path

    # 2. Send email
    recipient_email = order.get('user_email')
    customer_name = order.get('customer_name', 'Valued Customer')
    subject = f"Your Karthika Futures Invoice - Order {order_id}"
    body = f"""Dear {customer_name},

Please find your invoice for Order {order_id} attached.

Thank you for your purchase from Karthika Futures! We appreciate your business.

Order Details:
Order ID: {order_id}
Total Amount: ₹{order.get('total_amount'):.2f}
Status: {order.get('status')}
Placed On: {order.get('placed_on')}

If you have any questions, please reply to this email or contact our support team.

Best Regards,
The Karthika Futures Team
{OUR_BUSINESS_EMAIL}
{OUR_BUSINESS_ADDRESS}
"""
    # Construct the full absolute path for smtplib to read the file
    full_invoice_path = os.path.join(app.root_path, 'static', invoice_pdf_path_relative)
    
    # The attachment_filename is what the user sees, so use .pdf
    attachment_filename_for_email = f"invoice_{order_id}.pdf" 

    success, message = send_email_with_attachment(recipient_email, subject, body, 
                                                  attachment_path=full_invoice_path,
                                                  attachment_filename=attachment_filename_for_email)

    if success:
        order['invoice_details']['invoice_status'] = 'Sent'
        order['invoice_details']['invoice_email_sent_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_json('orders.json', orders)
        flash(f'Invoice email for Order {order_id} sent successfully to {recipient_email}.', 'success')
        return jsonify(success=True, message=f'Invoice email for Order {order_id} sent successfully.')
    else:
        order['invoice_details']['invoice_status'] = 'Email Failed'
        save_json('orders.json', orders)
        flash(f'Failed to send invoice email for Order {order_id}. Error: {message}', 'danger')
        return jsonify(success=False, message=f'Failed to send invoice email for Order {order_id}. Error: {message}'), 500

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/download_invoice/<order_id>')
@admin_required
def download_invoice(order_id):
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders_view'))

    invoice_path_relative = order.get('invoice_details', {}).get('invoice_pdf_path')
    if invoice_path_relative and invoice_path_relative.startswith('uploads/invoices/'):
        # Correctly determine the full path and mimetype based on the stored path
        full_path = os.path.join(app.root_path, 'static', invoice_path_relative)
        mimetype = 'application/pdf' if invoice_path_relative.lower().endswith('.pdf') else 'text/plain'
        download_name = f"invoice_{order_id}.pdf" # Always suggest .pdf for consistency

        if os.path.exists(full_path):
            return send_file(full_path, as_attachment=True, download_name=download_name, mimetype=mimetype)
    
    flash(f'Invoice not found or path invalid for Order {order_id}. Please generate it first from the admin invoice edit page.', 'warning')
    return redirect(url_for('admin_edit_invoice', order_id=order_id))

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/delete_order/<order_id>', methods=['GET'])
@admin_required
def delete_order(order_id):
    orders = load_orders_data()
    original_len = len(orders)
    orders = [order for order in orders if order.get('order_id') != order_id]
    if len(orders) < original_len:
        save_json('orders.json', orders)
        flash(f'Order {order_id} deleted successfully.', 'success')
    else:
        flash(f'Order {order_id} not found.', 'danger')
    return redirect(url_for('admin_orders_view'))

# --- NEW: Route to export orders as CSV ---
@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/export_orders_csv')
@admin_required
def export_orders_csv():
    orders = load_orders_data()

    # Define the CSV column headers
    fieldnames = [
        'Order ID', 'User ID', 'User Email', 'Customer Name', 'Customer Phone',
        'Customer Address', 'Customer Pincode', 'Placed On', 'Status', 'Remark',
        'Courier', 'Tracking Number', # Added courier and tracking number
        'Subtotal Before GST', 'Total GST Amount', 'CGST Amount', 'SGST Amount',
        'Shipping Charge', 'Total Amount', 'Transaction ID', 'Payment Submitted On',
        'Invoice Status', 'Invoice Held by Admin', 'Invoice PDF Path', 'Invoice Email Sent On'
    ]
    
    # Add fields for each item in the order (assuming max 5 items for simplicity, extend as needed)
    for i in range(1, 6): # Up to 5 items per order in the CSV row
        fieldnames.extend([
            f'Item {i} SKU', f'Item {i} Name', f'Item {i} Quantity',
            f'Item {i} Unit Price Before GST', f'Item {i} GST Percentage', f'Item {i} GST Amount',
            f'Item {i} Total Price Before GST', f'Item {i} Total Price'
        ])

    import io
    si = io.StringIO()
    cw = csv.DictWriter(si, fieldnames=fieldnames)
    cw.writeheader()

    for order in orders:
        row = {
            'Order ID': order.get('order_id', ''),
            'User ID': order.get('user_id', ''),
            'User Email': order.get('user_email', ''),
            'Customer Name': order.get('customer_name', ''),
            'Customer Phone': order.get('customer_phone', ''),
            'Customer Address': order.get('customer_address', ''),
            'Customer Pincode': order.get('customer_pincode', ''),
            'Placed On': order.get('placed_on', ''),
            'Status': order.get('status', ''),
            'Remark': order.get('remark', ''),
            'Courier': order.get('courier', ''),  # Added courier
            'Tracking Number': order.get('tracking_number', ''), # Added tracking number
            'Subtotal Before GST': f"{order.get('subtotal_before_gst', Decimal('0.00')):.2f}",
            'Total GST Amount': f"{order.get('total_gst_amount', Decimal('0.00')):.2f}",
            'CGST Amount': f"{order.get('cgst_amount', Decimal('0.00')):.2f}",
            'SGST Amount': f"{order.get('sgst_amount', Decimal('0.00')):.2f}",
            'Shipping Charge': f"{order.get('shipping_charge', Decimal('0.00')):.2f}",
            'Total Amount': f"{order.get('total_amount', Decimal('0.00')):.2f}",
            'Transaction ID': order.get('transaction_id', ''),
            'Payment Submitted On': order.get('payment_submitted_on', ''),
            'Invoice Status': order.get('invoice_details', {}).get('invoice_status', 'N/A'),
            'Invoice Held by Admin': 'Yes' if order.get('invoice_details', {}).get('is_held_by_admin', False) else 'No',
            'Invoice PDF Path': order.get('invoice_details', {}).get('invoice_pdf_path', ''),
            'Invoice Email Sent On': order.get('invoice_details', {}).get('invoice_email_sent_on', '')
        }

        # Populate item-specific fields
        for i, item in enumerate(order.get('items', [])[:5]): # Take up to 5 items
            row[f'Item {i+1} SKU'] = item.get('sku', '')
            row[f'Item {i+1} Name'] = item.get('name', '')
            row[f'Item {i+1} Quantity'] = item.get('quantity', 0)
            row[f'Item {i+1} Unit Price Before GST'] = f"{item.get('unit_price_before_gst', Decimal('0.00')):.2f}"
            row[f'Item {i+1} GST Percentage'] = f"{item.get('gst_percentage', Decimal('0.00')):.2f}"
            row[f'Item {i+1} GST Amount'] = f"{item.get('gst_amount', Decimal('0.00')):.2f}"
            row[f'Item {i+1} Total Price Before GST'] = f"{item.get('total_price_before_gst', Decimal('0.00')):.2f}"
            row[f'Item {i+1} Total Price'] = f"{item.get('total_price', Decimal('0.00')):.2f}"
        
        cw.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=orders_export.csv"
    output.headers["Content-type"] = "text/csv"
    return output


# --- NEW: Route to export artworks as CSV ---
@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/export_artworks_csv')
@admin_required
def export_artworks_csv():
    artworks = load_artworks_data()

    fieldnames = [
        'SKU', 'Name', 'Category', 'Original Price', 'Stock', 'Description',
        'GST Percentage', 'Image Paths', 'Size A4 Price', 'Size A5 Price',
        'Size Letter Price', 'Size Legal Price', 'Frame Wooden Price',
        'Frame Metal Price', 'Frame PVC Price', 'Glass Price', 'Is Featured'
    ]

    import io
    si = io.StringIO()
    cw = csv.DictWriter(si, fieldnames=fieldnames)
    cw.writeheader()

    for artwork in artworks:
        row = {
            'SKU': artwork.get('sku', ''),
            'Name': artwork.get('name', ''),
            'Category': artwork.get('category', ''),
            'Original Price': f"{artwork.get('original_price', Decimal('0.00')):.2f}",
            'Stock': artwork.get('stock', 0),
            'Description': artwork.get('description', ''),
            'GST Percentage': f"{artwork.get('gst_percentage', Decimal('0.00')):.2f}",
            'Image Paths': '; '.join(artwork.get('images', [])), # Join multiple image paths
            'Size A4 Price': f"{artwork.get('size_a4', Decimal('0.00')):.2f}",
            'Size A5 Price': f"{artwork.get('size_a5', Decimal('0.00')):.2f}",
            'Size Letter Price': f"{artwork.get('size_letter', Decimal('0.00')):.2f}",
            'Size Legal Price': f"{artwork.get('size_legal', Decimal('0.00')):.2f}",
            'Frame Wooden Price': f"{artwork.get('frame_wooden', Decimal('0.00')):.2f}",
            'Frame Metal Price': f"{artwork.get('frame_metal', Decimal('0.00')):.2f}",
            'Frame PVC Price': f"{artwork.get('frame_pvc', Decimal('0.00')):.2f}",
            'Glass Price': f"{artwork.get('glass_price', Decimal('0.00')):.2f}",
            'Is Featured': 'Yes' if artwork.get('is_featured', False) else 'No'
        }
        cw.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=artworks_export.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/add_artwork', methods=['GET', 'POST'])
@admin_required
def add_artwork():
    categories = load_categories_data()
    if request.method == 'POST':
        sku = request.form['sku'].strip()
        name = request.form['name'].strip()
        category = request.form['category']
        original_price = Decimal(request.form['original_price'])
        stock = int(request.form['stock'])
        description = request.form.get('description', '').strip()
        gst_percentage = Decimal(request.form.get('gst_percentage', str(DEFAULT_GST_PERCENTAGE)))

        size_a4 = Decimal(request.form.get('size_a4', '0.00'))
        size_a5 = Decimal(request.form.get('size_a5', '0.00'))
        size_letter = Decimal(request.form.get('size_letter', '0.00'))
        size_legal = Decimal(request.form.get('size_legal', '0.00'))
        frame_wooden = Decimal(request.form.get('frame_wooden', '0.00'))
        frame_metal = Decimal(request.form.get('frame_metal', '0.00'))
        frame_pvc = Decimal(request.form.get('frame_pvc', '0.00'))
        glass_price = Decimal(request.form.get('glass_price', '0.00'))

        artworks = load_artworks_data()

        if any(a['sku'] == sku for a in artworks):
            flash('Artwork with this SKU already exists. Please use a unique SKU.', 'danger')
            return render_template('add_artwork.html', categories=categories, form_data=request.form) # Pass request.form
        
        image_filenames = []
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['PRODUCT_IMAGES_FOLDER'], unique_filename)
                    file.save(file_path)
                    image_filenames.append(f'uploads/product_images/{unique_filename}')
        
        if not image_filenames:
            image_filenames.append('/static/images/placeholder.png') # Changed to /static/

        new_artwork = {
            'sku': sku,
            'name': name,
            'category': category,
            'original_price': original_price,
            'stock': stock,
            'description': description,
            'gst_percentage': gst_percentage,
            'images': image_filenames,
            'size_a4': size_a4,
            'size_a5': size_a5,
            'size_letter': size_letter,
            'size_legal': size_legal,
            'frame_wooden': frame_wooden,
            'frame_metal': frame_metal,
            'frame_pvc': frame_pvc,
            'glass_price': glass_price,
            'is_featured': False
        }
        artworks.append(new_artwork)
        save_json('artworks.json', artworks)
        flash(f'Artwork "{name}" added successfully!', 'success')
        return redirect(url_for('admin_artworks_view'))
    return render_template('add_artwork.html', categories=categories, form_data={}) # Pass empty dict for GET

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/edit_artwork/<sku>', methods=['GET', 'POST'])
@admin_required
def edit_artwork(sku):
    artworks = load_artworks_data()
    artwork = next((a for a in artworks if a['sku'] == sku), None)
    if not artwork:
        flash('Artwork not found.', 'danger')
        return redirect(url_for('admin_artworks_view'))

    categories = load_categories_data()

    if request.method == 'POST':
        artwork['name'] = request.form['name'].strip()
        artwork['category'] = request.form['category']
        artwork['original_price'] = Decimal(request.form['original_price'])
        artwork['stock'] = int(request.form['stock'])
        artwork['description'] = request.form.get('description', '').strip()
        artwork['gst_percentage'] = Decimal(request.form.get('gst_percentage', str(DEFAULT_GST_PERCENTAGE)))
        artwork['is_featured'] = 'is_featured' in request.form

        # Ensure that only 'Paintings' and 'photos' category will have custom size/frame/glass options
        if artwork['category'] in ['Paintings', 'photos']:
            artwork['size_a4'] = Decimal(request.form.get('size_a4', '0.00'))
            artwork['size_a5'] = Decimal(request.form.get('size_a5', '0.00'))
            artwork['size_letter'] = Decimal(request.form.get('size_letter', '0.00'))
            artwork['size_legal'] = Decimal(request.form.get('size_legal', '0.00'))
            artwork['frame_wooden'] = Decimal(request.form.get('frame_wooden', '0.00'))
            artwork['frame_metal'] = Decimal(request.form.get('frame_metal', '0.00'))
            artwork['frame_pvc'] = Decimal(request.form.get('frame_pvc', '0.00'))
            artwork['glass_price'] = Decimal(request.form.get('glass_price', '0.00'))
        else:
            # Reset these fields if category changes to non-applicable
            artwork['size_a4'] = Decimal('0.00')
            artwork['size_a5'] = Decimal('0.00')
            artwork['size_letter'] = Decimal('0.00')
            artwork['size_legal'] = Decimal('0.00')
            artwork['frame_wooden'] = Decimal('0.00')
            artwork['frame_metal'] = Decimal('0.00')
            artwork['frame_pvc'] = Decimal('0.00')
            artwork['glass_price'] = Decimal('0.00')

        new_image_filenames = []
        # Process existing images to keep
        images_to_keep_json = request.form.get('images_to_keep')
        if images_to_keep_json:
            try:
                kept_images = json.loads(images_to_keep_json)
                new_image_filenames.extend(kept_images)
            except json.JSONDecodeError:
                app.logger.error("Failed to decode images_to_keep JSON.")

        # Add newly uploaded images
        if 'new_images' in request.files:
            for file in request.files.getlist('new_images'):
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['PRODUCT_IMAGES_FOLDER'], unique_filename)
                    file.save(file_path)
                    new_image_filenames.append(f'uploads/product_images/{unique_filename}')
        
        if not new_image_filenames: # Ensure there's always at least a placeholder
            new_image_filenames.append('/static/images/placeholder.png') 
        
        artwork['images'] = new_image_filenames

        save_json('artworks.json', artworks)
        flash(f'Artwork "{artwork["name"]}" updated successfully!', 'success')
        return redirect(url_for('admin_artworks_view'))
    
    return render_template('edit_artwork.html', artwork=artwork, categories=categories)

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/delete_artwork/<sku>', methods=['GET'])
@admin_required
def delete_artwork(sku):
    artworks = load_artworks_data()
    original_len = len(artworks)
    artworks = [a for a in artworks if a.get('sku') != sku]
    if len(artworks) < original_len:
        save_json('artworks.json', artworks)
        flash(f'Artwork with SKU {sku} deleted successfully.', 'success')
    else:
        flash(f'Artwork with SKU {sku} not found.', 'danger')
    return redirect(url_for('admin_artworks_view'))

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/categories')
@admin_required
def admin_categories_view():
    categories = load_categories_data()  # <-- Ensure it loads the correct file
    return render_template('admin_categories.html', categories=categories)


@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/category/add', methods=['POST'])
@admin_required  # Keep this to ensure only admins can access
def admin_add_category():
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    image_file = request.files.get('image')

    categories = load_categories_data()

    # Check for duplicate category name (case-insensitive)
    if any(c['name'].lower() == name.lower() for c in categories):
        flash('Category with this name already exists.', 'danger')
        return redirect(url_for('admin_categories_view'))

    # Handle image upload
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        file_path = os.path.join(app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
        image_file.save(file_path)
        image_path = f'uploads/category_images/{unique_filename}'
    else:
        image_path = 'images/placeholder.png'  # Relative to static folder

    # Add new category
    new_category = {
        'id': str(uuid.uuid4()),
        'name': name,
        'description': description,
        'image': image_path
    }
    categories.append(new_category)
    save_json('categories.json', categories)

    flash(f'Category "{name}" added successfully!', 'success')
    return redirect(url_for('admin_categories_view'))

def admin_add_category():
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    image_file = request.files.get('image')

    categories = load_categories()
    if any(c['name'].lower() == name.lower() for c in categories):
        flash('Category with this name already exists.', 'danger')
        return redirect(url_for('admin_categories_view'))

    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        file_path = os.path.join(app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
        image_file.save(file_path)
        image_path = f'uploads/category_images/{unique_filename}'
    else:
        image_path = 'images/placeholder.png'

    new_category = {
        'id': str(uuid.uuid4()),
        'name': name,
        'description': description,
        'image': image_path
    }
    categories.append(new_category)
    save_categories(categories)
    flash(f'Category "{name}" added successfully!', 'success')
    return redirect(url_for('admin_categories_view'))

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/category/edit/<category_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_category(category_id):
    categories = load_categories_data()
    category = next((c for c in categories if c['id'] == category_id), None)

    if not category:
        flash('Category not found.', 'danger')
        return redirect(url_for('admin_categories_view'))

    if request.method == 'POST':
        category['name'] = request.form['name'].strip()
        category['description'] = request.form.get('description', '').strip()
        image_file = request.files.get('image')
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            unique_filename = str(uuid.uuid4()) + '_' + filename
            file_path = os.path.join(app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
            image_file.save(file_path)
            category['image'] = f'uploads/category_images/{unique_filename}'
        save_json('categories.json', categories)
        flash('Category updated successfully!', 'success')
        return redirect(url_for('admin_categories_view'))

    return render_template('admin_edit_category.html', category=category)

@app.route('/admin_logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('admin_login'))


# Handle Update Category
@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/update-category/<category_id>', methods=['POST'])
@admin_required
def admin_update_category(category_id):
    categories = load_categories()
    category = next((c for c in categories if c['id'] == category_id), None)
    if not category:
        flash("Category not found.", "danger")
        return redirect(url_for('admin_categories_view'))

    category['name'] = request.form.get('name', category['name']).strip()
    category['description'] = request.form.get('description', category['description']).strip()

    image_file = request.files.get('image')
    if image_file and image_file.filename:
        filename = secure_filename(image_file.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        file_path = os.path.join(app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
        image_file.save(file_path)
        category['image'] = f'uploads/category_images/{unique_filename}'

    save_categories(categories)
    flash("Category updated successfully!", "success")
    return redirect(url_for('admin_categories_view'))

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin/delete-category/<category_id>', methods=['POST'])
@admin_required
def admin_delete_category(category_id):
    categories = load_categories_data()
    updated = [c for c in categories if c['id'] != category_id]

    if len(updated) == len(categories):
        flash("Category not found.", "danger")
        return redirect(url_for('admin_categories_view'))

    save_json('categories.json', updated)
    flash("Category deleted successfully!", "success")
    return redirect(url_for('admin_categories_view'))

@app.route('/admin/update-order', methods=['POST'])
@admin_login_required
def admin_update_order():
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    courier_name = request.form.get('courier_name')
    tracking_id = request.form.get('tracking_id')

    orders = load_orders_data()
    for order in orders:
        if order['order_id'] == order_id:
            order['status'] = new_status
            order['courier_name'] = courier_name
            order['tracking_id'] = tracking_id
            break

    save_json('orders.json', orders)
    flash(f'Order {order_id} updated successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/verify-payment', methods=['POST'])
@admin_required
def admin_verify_payment():
    order_id = request.form.get('order_id')
    orders = load_orders_data()
    for order in orders:
        if order.get('order_id') == order_id:
            order['status'] = 'Payment Verified – Preparing Order'
            save_json('orders.json', orders)
            flash(f"Payment for Order {order_id} marked as verified.", "success")
            break
    else:
        flash("Order not found.", "danger")
    return redirect(url_for('admin_panel'))

# --- User Authentication Routes ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        # If user is already logged in, redirect them based on their original intent
        redirect_endpoint = session.pop('redirect_after_login_endpoint', None)
        next_url_from_arg = request.args.get('next')

        if redirect_endpoint == 'cart':
            return redirect(url_for('cart'))
        elif redirect_endpoint == 'purchase_form':
            # Use next_url_from_arg for the exact path if it was passed (e.g., product detail page)
            return redirect(next_url_from_arg or url_for('purchase_form')) 
        return redirect(next_url_from_arg or url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']
        address = request.form['address']
        pincode = request.form['pincode']
        role = 'user'

        users = load_users_data() 
        if User.find_by_email(email):
            flash('Email already registered. Please login or use a different email.', 'danger')
            return render_template('signup.html', form_data=request.form)

        # --- OTP Logic - Store pending user data and send OTP ---
        otp = str(random.randint(100000, 999999)) # Generate a 6-digit OTP
        otp_expiry = datetime.now() + timedelta(minutes=10) # OTP valid for 10 minutes

        # Temporarily store user data and OTP
        otp_storage[email] = {
            'otp': otp,
            'expiry': otp_expiry,
            'user_data': {
                'id': str(uuid.uuid4()), 
                'email': email,
                'password': generate_password_hash(password), 
                'name': name,
                'phone': phone,
                'address': address,
                'pincode': pincode,
                'role': role
            }
        }

        try:
            subject = "Karthika Futures - Your OTP for Registration"
            body = f"Hi {name},\n\nYour One-Time Password (OTP) for Karthika Futures registration is: {otp}\n\nThis OTP is valid for 10 minutes.\n\nThank you,\nKarthika Futures Team"
            
            # Call the shared email sending function
            email_sent_success, email_message = send_email_with_attachment(email, subject, body)

            if email_sent_success:
                flash(f"An OTP has been sent to {email}. Please verify to complete registration.", 'info')
                session['email_for_otp_verification'] = email # Store email in session for verification route
                session.modified = True
                # Pass 'next' URL to the verify_otp route
                return redirect(url_for('verify_otp', next=request.args.get('next'))) 
            else:
                app.logger.error(f"Failed to send OTP email to {email}: {email_message}")
                flash(f'Failed to send OTP. Please check your email configuration and try again: {email_message}', 'danger')
                return render_template('signup.html', form_data=request.form)
        except Exception as e:
            app.logger.error(f"Error sending OTP email: {e}", exc_info=True)
            flash('An unexpected error occurred while sending OTP. Please try again.', 'danger')
            return render_template('signup.html', form_data=request.form)

    return render_template('signup.html', form_data={})

@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    """
    Handles OTP verification for new user signups or logins via OTP.
    """
    email_for_otp_verification = session.get('email_for_otp_verification')
    next_url = request.args.get('next')  # Optional redirection target

    if not email_for_otp_verification or email_for_otp_verification not in otp_storage:
        flash("No pending OTP verification. Please sign up again.", "danger")
        return redirect(url_for('signup', next=next_url))

    if request.method == 'POST':
        user_otp = request.form['otp'].strip()
        stored_data = otp_storage.get(email_for_otp_verification)

        if stored_data and stored_data['otp'] == user_otp and datetime.now() < stored_data['expiry']:
            # OTP is valid and not expired
            new_user_data = stored_data['user_data']

            users = load_users_data()
            matched_user = next((u for u in users if u['email'] == new_user_data['email']), None)

            if not matched_user:
                # New user, save to users.json
                users.append(new_user_data)
                save_json('users.json', users)
                matched_user = new_user_data

            # ✅ Preserve cart before session cleanup
            preserved_cart = session.get('cart', [])

            # Clean up OTP and temp session values
            otp_storage.pop(email_for_otp_verification, None)
            session.pop('email_for_otp_verification', None)

            # Clear and reset session to prevent leakage but keep cart
            session.clear()
            session['cart'] = preserved_cart  # ✅ Restore cart

            # Log in user
            login_user(User(
                matched_user.get('id', str(uuid.uuid4())),
                matched_user.get('email', ''),
                matched_user.get('password', ''),
                matched_user.get('name', ''),
                matched_user.get('phone', ''),
                matched_user.get('address', ''),
                matched_user.get('pincode', ''),
                matched_user.get('role', 'user')
            ))

            flash("Logged in successfully via OTP!", "success")
            return redirect(next_url or url_for('index'))
        else:
            flash("Invalid or expired OTP. Please try again.", "danger")

    return render_template('verify_otp.html', email=email_for_otp_verification, next_url=next_url)

@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    next_url = request.args.get('next')
    
    if request.method == 'POST':
        email_or_mobile = request.form['email'].strip().lower()
        password = request.form['password'].strip()
        users = load_users_data()

        matched_user = None
        for u in users:
            if u.get('email') == email_or_mobile or u.get('phone') == email_or_mobile:
                matched_user = u
                break

        if not matched_user:
            flash("No user found. Please sign up first.", "danger")
            return redirect(url_for('signup', next=next_url))

        # === CASE A: Password provided ===
        if password:
            if 'password' not in matched_user or not matched_user['password']:
                flash("This account was created using OTP. Please login via OTP.", "warning")
                return redirect(url_for('user_login', next=next_url))

            if check_password_hash(matched_user['password'], password):
                # ✅ FIX: Ensure all 3 args are passed
                email = matched_user.get('email', '')
                pwd = matched_user.get('password', '')
                name = matched_user.get('name') or email.split('@')[0] or 'User'
                login_user(User(
    matched_user.get('id', str(uuid.uuid4())),
    matched_user.get('email', ''),
    matched_user.get('password', ''),
    matched_user.get('name', ''),
    matched_user.get('phone', ''),
    matched_user.get('address', ''),
    matched_user.get('pincode', ''),
    matched_user.get('role', 'user')
))


                flash("Logged in successfully!", "success")
                return redirect(next_url or url_for('index'))
            else:
                flash("Invalid email or password", "danger")
                return redirect(url_for('user_login', next=next_url))

        # === CASE B: No password → Send OTP ===
        else:
            otp = generate_otp()
            expiry = datetime.now() + timedelta(minutes=10)
            otp_storage[email_or_mobile] = {
                'otp': otp,
                'expiry': expiry,
                'user_data': matched_user
            }
            session['email_for_otp_verification'] = email_or_mobile
            send_otp_email(email_or_mobile, otp)
            flash("OTP sent to your email for login", "info")
            return redirect(url_for('verify_otp', next=next_url))

    # Prefill email in form if provided
    prefill_email = request.args.get('email', '')
    return render_template("user_login.html", next_url=next_url, prefill_email=prefill_email)

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    users = load_users_data()
    current_email = current_user.email

    # Find current user
    for user in users:
        if user['email'] == current_email:
            if request.method == 'POST':
                user['name'] = request.form.get('name', user['name'])
                user['phone'] = request.form.get('phone', user['phone'])
                user['address'] = request.form.get('address', user['address'])
                user['pincode'] = request.form.get('pincode', user['pincode'])
                save_json('users.json', users)
                flash("Profile updated successfully.", "success")
                return redirect(url_for('profile'))

            return render_template('profile.html', user_info=user)

    # If user not found
    flash("User not found.", "danger")
    return redirect(url_for('user_login'))


@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email in ADMIN_CREDENTIALS and ADMIN_CREDENTIALS[email] == password:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid credentials.', 'danger')

    return render_template('admin_login.html')


@app.route('/logout')
@login_required
def logout():
    """Logs out the current user."""
    logout_user()
    session.pop('cart', None) # Clear cart on logout for security/privacy
    session.pop('direct_purchase_item', None)
    session.modified = True
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.find_by_email(email)
        if user:
            # Generate a reset token (UUID for simplicity)
            reset_token = str(uuid.uuid4())
            # Store token with expiry (in-memory for simplicity, in production use DB)
            # For now, let's just flash a message to simulate sending.
            
            # In a real app, send email with reset link:
            # reset_link = url_for('reset_password', token=reset_token, _external=True)
            # send_email_with_attachment(user.email, "Password Reset Link", f"Click here to reset: {reset_link}") # Using existing function
            
            flash('If an account with that email exists, a password reset link has been sent.', 'info')
        else:
            flash('If an an account with that email exists, a password reset link has been sent.', 'info') # To prevent email enumeration
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # This is a dummy route as token handling is not implemented with persistence.
    # In a real app, you would verify the token against a database.
    flash('Password reset functionality is under development.', 'warning')
    return redirect(url_for('user_login'))

@app.route('/user_dashboard')
@login_required
def user_dashboard():
    """User dashboard landing page."""
    return render_template('user_dashboard.html')

# --- ONE-TIME ADMIN USER CREATION ON STARTUP (FOR DEBUGGING/INITIAL SETUP) ---
def create_default_admin_if_not_exists():
    users = load_json('users.json')
    # Check if any user with role 'admin' exists
    admin_exists = any(user.get('role') == 'admin' for user in users)

    if not admin_exists:
        default_admin_email = 'admin@karthikafutures.com' # <<< THE ADMIN EMAIL YOU WILL USE
        default_admin_password = 'admin_password_123' # <<< THE ADMIN PASSWORD YOU WILL USE
        
        # Check if an account with this default email already exists (even if not admin)
        if not User.find_by_email(default_admin_email):
            app.logger.info(f"Creating default admin user: {default_admin_email}")
            new_admin = {
                'id': str(uuid.uuid4()),
                'email': default_admin_email,
                'password': generate_password_hash(default_admin_password), # Hashed password
                'name': 'Default Admin',
                'phone': '9999999999',
                'address': 'Karthika Admin Office',
                'pincode': '123456',
                'role': 'admin' # Role must be 'admin'
            }
            users.append(new_admin)
            save_json('users.json', users)
            app.logger.info(f"Default admin '{default_admin_email}' created.")
            print(f"\n--- IMPORTANT: DEFAULT ADMIN CREATED ---")
            print(f"Email: {default_admin_email}")
            print(f"Password: {default_admin_password}")
            print(f"Login at: http://127.0.0.1:5000/admin_login")
            print(f"----------------------------------------\n")
        else:
            app.logger.info(f"Account '{default_admin_email}' already exists, but no admin user was found. Please ensure that account has 'admin' role in users.json or create a new email for default admin.")
            print(f"\n--- WARNING: Default admin email '{default_admin_email}' exists but no admin role found. ---")
            print(f"Please check users.json or change 'default_admin_email' in app.py.")
            print(f"------------------------------------------------------------------\n")
    else:
        app.logger.info("Admin user already exists. Skipping default admin creation.")


@app.context_processor
def inject_globals():
    return {
        'categories': get_all_categories(),
        'our_business_name': 'Karthika Futures',
        'our_business_email': 'support@karthikafutures.com',
        'our_business_address': '123 Divine Street, India',
        'our_gstin': '29ABCDE1234F2Z5',
        'our_pan': 'ABCDE1234F',
        'current_year': datetime.now().year
    }



if __name__ == '__main__':
    create_default_admin_if_not_exists() # CALL THE FUNCTION TO CREATE ADMIN ON STARTUP
    app.run(debug=True)

