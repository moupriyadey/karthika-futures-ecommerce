import os
import json
import csv
import uuid
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, make_response, send_file
from flask import current_app
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import random
import qrcode
import io
import base64
import string 

# SQLAlchemy Imports
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey, func # Added func
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError # Removed OperationalError as it's not directly used here

# Email Sending
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# CSRF protection
from flask_wtf.csrf import CSRFProtect, generate_csrf

# PDF generation
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    REPORTLAB_AVAILABLE = True
except ImportError:
    print("ReportLab not installed. PDF invoice generation will fall back to text.")
    REPORTLAB_AVAILABLE = False


# --- App Initialization ---
app = Flask(__name__)
app.permanent_session_lifetime = timedelta(minutes=30) # Sessions last for 30 minutes
csrf = CSRFProtect(app)

# --- SQLAlchemy Configuration ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///karthika_futures.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Disable tracking modifications for performance

db = SQLAlchemy(app)

# --- Secret Key ---
# IMPORTANT: In production, use a strong, randomly generated key from an environment variable.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'THIS_IS_A_SUPER_STABLE_STATIC_CSRF_KEY_12345')

# --- Upload Folders ---
# Define paths relative to the static folder for easy serving
UPLOAD_BASE_FOLDER = 'uploads'
app.config['PRODUCT_IMAGES_FOLDER'] = os.path.join('static', UPLOAD_BASE_FOLDER, 'product_images')
app.config['CATEGORY_IMAGES_FOLDER'] = os.path.join('static', UPLOAD_BASE_FOLDER, 'category_images')
app.config['PAYMENT_SCREENSHOTS_FOLDER'] = os.path.join('static', UPLOAD_BASE_FOLDER, 'payment_screenshots')
app.config['INVOICE_PDF_FOLDER'] = os.path.join('static', UPLOAD_BASE_FOLDER, 'invoices')

# Ensure directories exist
os.makedirs(os.path.join(app.root_path, app.config['PRODUCT_IMAGES_FOLDER']), exist_ok=True)
os.makedirs(os.path.join(app.root_path, app.config['CATEGORY_IMAGES_FOLDER']), exist_ok=True)
os.makedirs(os.path.join(app.root_path, app.config['PAYMENT_SCREENSHOTS_FOLDER']), exist_ok=True)
os.makedirs(os.path.join(app.root_path, app.config['INVOICE_PDF_FOLDER']), exist_ok=True)

# --- Email Settings (can override via .env) ---
app.config['SENDER_EMAIL'] = os.environ.get('SENDER_EMAIL', 'your_email@example.com')
app.config['SENDER_PASSWORD'] = os.environ.get('SENDER_PASSWORD', 'your_email_app_password') # Use app password for Gmail
app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', 587))

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
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

# --- Temporary OTP storage (in-memory, volatile) ---
otp_storage = {} # {'email': {'otp': '123456', 'expiry': datetime_object, 'user_data': { ... }}}

# --- Helper Functions ---

# Helper for decimal conversion
def safe_decimal(value, default=Decimal('0.00')):
    """Safely converts a value to Decimal, returns default on error."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default

# Helper for file uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper for generating unique cart item IDs based on SKU and options
def generate_cart_item_id(sku, options):
    """
    Generates a unique ID for a cart item based on SKU and selected options.
    Options should be a dictionary.
    """
    # Ensure options are sorted for consistent ID generation
    sorted_options_string = "-".join(f"{k}-{v}" for k, v in sorted(options.items()))
    # Replace spaces and periods to be URL-friendly
    return f"{sku}-{sorted_options_string}".replace(" ", "_").replace(".", "_").lower()

def calculate_item_price_with_options(artwork, custom_options_selected=None):
    """
    Calculates the final unit price of an artwork based on selected custom options.
    Assumes all options (including what were previously fixed size/frame/glass) are
    now part of the artwork.custom_options JSON.
    """
    unit_price = artwork.original_price # Start with the base price of the artwork

    if custom_options_selected:
        # artwork.get_custom_options() should return a dictionary like {"Group Name": {"Option Label": price}}
        artwork_defined_options = artwork.get_custom_options() 

        for group_name, selected_label in custom_options_selected.items():
            if group_name in artwork_defined_options:
                option_price = artwork_defined_options[group_name].get(selected_label)
                if option_price is not None:
                    try:
                        unit_price += safe_decimal(option_price) 
                    except InvalidOperation:
                        app.logger.warning(f"Invalid price for custom option {group_name}:{selected_label} in artwork {artwork.sku}. Price: {option_price}")
                else:
                    app.logger.warning(f"Selected option '{selected_label}' not found in group '{group_name}' for artwork {artwork.sku}.")
            else:
                app.logger.warning(f"Option group '{group_name}' not defined for artwork {artwork.sku}.")

    return unit_price

def calculate_cart_totals(cart_data_from_session):
    """
    Calculates the totals for the cart, including subtotal, GST, shipping, and grand total.
    Ensures cart items are correctly structured and prices are Decimal.
    """
    if not isinstance(cart_data_from_session, dict):
        current_app.logger.warning(f"Cart data passed to calculate_cart_totals was not dict: {type(cart_data_from_session)}. Returning empty summary.")
        return {
            'cart_items': [],
            'subtotal_before_gst': Decimal('0.00'),
            'total_gst_amount': Decimal('0.00'),
            'shipping_charge': Decimal('0.00'),
            'grand_total': Decimal('0.00'),
            'total_items_in_cart': 0
        }

    subtotal_before_gst = Decimal('0.00')
    total_gst_amount = Decimal('0.00')
    grand_total = Decimal('0.00')
    total_items_in_cart = 0
    cart_items_list = []

    for item_id, item_data in cart_data_from_session.items():
        try:
            item_quantity = int(item_data.get('quantity', 0))
            item_unit_price_before_gst = safe_decimal(item_data.get('unit_price_before_gst', '0.00'))
            item_gst_percentage = safe_decimal(item_data.get('gst_percentage', '0.00'))
            
            item_total_price_before_gst = item_unit_price_before_gst * item_quantity
            item_gst_amount = item_total_price_before_gst * (item_gst_percentage / 100)
            item_total_price = item_total_price_before_gst + item_gst_amount

            subtotal_before_gst += item_total_price_before_gst
            total_gst_amount += item_gst_amount
            grand_total += item_total_price
            total_items_in_cart += item_quantity

            cart_items_list.append({
                'id': item_id,
                'sku': item_data.get('sku'),
                'name': item_data.get('name'),
                'imageUrl': item_data.get('imageUrl'),
                'quantity': item_quantity,
                'unit_price_before_options': safe_decimal(item_data.get('unit_price_before_options', '0.00')),
                'unit_price_before_gst': item_unit_price_before_gst,
                'gst_percentage': item_gst_percentage,
                'gst_amount_per_unit': item_gst_amount / item_quantity if item_quantity > 0 else Decimal('0.00'),
                'total_price_per_unit': item_total_price / item_quantity if item_quantity > 0 else Decimal('0.00'),
                'total_price_before_gst': item_total_price_before_gst,
                'total_gst_amount': item_gst_amount,
                'total_price': item_total_price,
                'options': item_data.get('options', {}) 
            })
        except (TypeError, InvalidOperation, ValueError) as e:
            current_app.logger.error(f"Error processing cart item {item_id}: {e}. Item data: {item_data}", exc_info=True)
            continue 

    shipping_charge = Decimal('0.00')
    if grand_total > 0 and grand_total < current_app.config.get('MAX_SHIPPING_COST_FREE_THRESHOLD', Decimal('500.00')): 
        shipping_charge = DEFAULT_SHIPPING_CHARGE # Use the constant here

    grand_total_with_shipping = grand_total + shipping_charge

    return {
        'cart_items': cart_items_list,
        'subtotal_before_gst': subtotal_before_gst,
        'total_gst_amount': total_gst_amount,
        'shipping_charge': shipping_charge,
        'grand_total': grand_total_with_shipping,
        'total_items_in_cart': total_items_in_cart
    }

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_otp(recipient, otp):
    print(f"[DEBUG] Sending OTP {otp} to {recipient}")
    # Here you can use email or SMS logic

<<<<<<< HEAD

# --- NEW: load_users_data helper function ---

from decimal import Decimal

def enrich_direct_purchase_item(data):
    sku = data.get('sku')
    quantity = int(data.get('quantity', 1))
    options = {k: v for k, v in data.items() if k not in ['sku', 'quantity']}

    artworks = load_artworks_data()
    artwork = next((a for a in artworks if a['sku'] == sku), None)
    if not artwork:
        return None

    base_price = Decimal(str(artwork.get('original_price', 0)))
    gst_percentage = Decimal(str(artwork.get('gst_percentage', 0)))
    extra_price = Decimal('0.00')

    for group, value in options.items():
        try:
            extra_price += Decimal(str(artwork['custom_options'][group][value]))
        except Exception:
            pass  # ignore missing or mismatched options

    unit_price = base_price + extra_price
    total_price_before_gst = unit_price * quantity
    gst_amount = (total_price_before_gst * gst_percentage) / Decimal('100')
    total_price = total_price_before_gst + gst_amount

    return {
        **data,
        'name': artwork.get('name', 'Artwork'),
        'category': artwork.get('category', ''),
        'image': artwork['images'][0] if artwork.get('images') else '',
        'unit_price_before_options': base_price,
        'unit_price_before_gst': unit_price,
        'total_price_before_gst': total_price_before_gst,
        'gst_percentage': gst_percentage,
        'gst_amount': gst_amount,
        'total_price': total_price
    }



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
=======
# UPDATED: Function to generate invoice PDF (using ReportLab)
>>>>>>> a3989ae (SQL v2)
def generate_invoice_pdf(order_id, order_details):
    # Use os.path.join with app.root_path to get absolute path for file operations
    invoice_filename_base = f"invoice_{order_id}"
    invoice_filepath_pdf_abs = os.path.join(app.root_path, app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.pdf")
    invoice_filepath_txt_abs = os.path.join(app.root_path, app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.txt")
    
    # Relative path to be stored in DB and used by url_for
    invoice_pdf_path_relative = os.path.join(os.path.basename(os.path.dirname(app.config['INVOICE_PDF_FOLDER'])), os.path.basename(app.config['INVOICE_PDF_FOLDER']), f"{invoice_filename_base}.pdf")
    invoice_txt_path_relative = os.path.join(os.path.basename(os.path.dirname(app.config['INVOICE_PDF_FOLDER'])), os.path.basename(app.config['INVOICE_PDF_FOLDER']), f"{invoice_filename_base}.txt")


    if REPORTLAB_AVAILABLE: # Check if ReportLab is available
       try:
           doc = SimpleDocTemplate(invoice_filepath_pdf_abs, pagesize=letter)
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
           invoice_number_display = order_details.get_invoice_details().get('invoice_number', 'N/A')
           if not invoice_number_display and order_details.status == 'Shipped': # Auto-generate if not set and shipped
                invoice_number_display = f"INV-{order_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
           story.append(Paragraph(f"<b>Invoice Number:</b> {invoice_number_display}", styles['Normal']))
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
           story.append(Paragraph(f"Name: {order_details.customer_name}", styles['Normal']))
           story.append(Paragraph(f"Email: {order_details.customer_email}", styles['Normal']))
           story.append(Paragraph(f"Phone: {order_details.customer_phone}", styles['Normal']))
           
           shipping_addr = order_details.get_shipping_address()
           story.append(Paragraph(f"Address: {shipping_addr.get('address_line1', 'N/A')}, {shipping_addr.get('city', 'N/A')}, {shipping_addr.get('state', 'N/A')}", styles['Normal']))
           story.append(Paragraph(f"Pincode: {order_details.shipping_pincode}", styles['Normal']))
           story.append(Spacer(1, 0.2*inch))

           # Items Table
           data = [
               ['<b>SKU</b>', '<b>Name</b>', '<b>Qty</b>', '<b>Unit Price</b>', '<b>Total Price</b>']
           ]
           for item in order_details.order_items:
               # Prepare options string for display
               options_str = ""
               if item.selected_options_json:
                   try:
                       options_dict = json.loads(item.selected_options_json)
                       if options_dict:
                           options_str = " (" + ", ".join([f"{k}: {v}" for k, v in options_dict.items()]) + ")"
                   except json.JSONDecodeError:
                       app.logger.error(f"Failed to decode selected_options_json for order item {item.id}")
                       options_str = " (Options Error)"

               data.append([
                   item.sku,
                   item.name + options_str, # Include options in name
                   str(item.quantity),
                   f"₹{item.unit_price_before_gst:.2f}",
                   f"₹{item.total_price:.2f}"
               ])
           
           table = Table(data, colWidths=[1.0*inch, 2.5*inch, 0.5*inch, 1.2*inch, 1.2*inch])
           table.setStyle(TableStyle([
               ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F5F5F5')), # Light grey header
               ('TEXTCOLOR', (0,0), (-1,0), colors.black),
               ('ALIGN', (0,0), (-1,-1), 'LEFT'),
               ('ALIGN', (3,0), (-1,-1), 'RIGHT'), # Align price columns right
               ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
               ('BOTTOMPADDING', (0,0), (-1,0), 12),
               ('BACKGROUND', (0,1), (-1,-1), colors.white), # White background for rows
               ('GRID', (0,0), (-1,-1), 0.5, colors.grey), # Lighter grid lines
               ('BOX', (0,0), (-1,-1), 1, colors.black),
           ]))
           story.append(table)
           story.append(Spacer(1, 0.2*inch))

           # Totals
           story.append(Paragraph(f"<b>Subtotal (Before GST):</b> ₹{order_details.subtotal_before_gst:.2f}", styles['RightAlign']))
           story.append(Paragraph(f"<b>Total GST:</b> ₹{order_details.total_gst_amount:.2f} (CGST: ₹{order_details.cgst_amount:.2f}, SGST: ₹{order_details.sgst_amount:.2f})", styles['RightAlign']))
           story.append(Paragraph(f"<b>Shipping Charge:</b> ₹{order_details.shipping_charge:.2f}", styles['RightAlign']))
           story.append(Paragraph(f"<b>Grand Total:</b> ₹{order_details.total_amount:.2f}", styles['h2']))
           story.append(Spacer(1, 0.5*inch))
           story.append(Paragraph(f"Status: {order_details.status}", styles['Normal']))

           doc.build(story)
           app.logger.info(f"Generated PDF invoice: {invoice_filepath_pdf_abs}")
           return invoice_pdf_path_relative # Return relative path
       except Exception as e:
           app.logger.error(f"Error generating PDF with ReportLab: {e}", exc_info=True)
           # Fallback to text invoice if PDF generation fails
           pass

    # Fallback: Basic text content for the dummy invoice (executed if ReportLab fails or is not enabled)
    invoice_content = f"""
--- INVOICE ---

Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Invoice Number: {order_details.get_invoice_details().get('invoice_number', 'N/A')}
Order ID: {order_id}

Seller:
  Name: {OUR_BUSINESS_NAME}
  GSTIN: {OUR_GSTIN}
  PAN: {OUR_PAN}
  Address: {OUR_BUSINESS_ADDRESS}
  Email: {OUR_BUSINESS_EMAIL}

Customer:
  Name: {order_details.customer_name}
  Phone: {order_details.customer_phone}
  Address: {order_details.get_shipping_address().get('address_line1', 'N/A')}, {order_details.get_shipping_address().get('city', 'N/A')}, {order_details.get_shipping_address().get('state', 'N/A')}
  Pincode: {order_details.shipping_pincode}

Items:
{'='*50}
{'SKU':<10} {'Name':<25} {'Qty':<5} {'Unit Price':<12} {'Total Price':<12}
{'='*50}
"""
    for item in order_details.order_items:
        options_str = ""
        if item.selected_options_json:
            try:
                options_dict = json.loads(item.selected_options_json)
                if options_dict:
                    options_str = " (" + ", ".join([f"{k}: {v}" for k, v in options_dict.items()]) + ")"
            except json.JSONDecodeError:
                options_str = " (Options Error)"

        unit_price_formatted = f"{item.unit_price_before_gst:.2f}"
        total_price_formatted = f"{item.total_price:.2f}"
        invoice_content += f"{item.sku:<10} {item.name + options_str:<25} {item.quantity:<5} {unit_price_formatted:<12} {total_price_formatted:<12}\n"

    invoice_content += f"""
{'='*50}
Subtotal (Before GST): {order_details.subtotal_before_gst:.2f}
Total GST: {order_details.total_gst_amount:.2f} (CGST: {order_details.cgst_amount:.2f}, SGST: {order_details.sgst_amount:.2f})
Shipping Charge: {order_details.shipping_charge:.2f}
Grand Total: {order_details.total_amount:.2f}

Status: {order_details.status}

--- End of Invoice ---
"""

    with open(invoice_filepath_txt_abs, 'w') as f:
        f.write(invoice_content)
    
    return invoice_txt_path_relative # Return relative path

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
            # Ensure attachment_path is an absolute path for file operations
            full_attachment_path = os.path.join(app.root_path, 'static', attachment_path)
            _maintype, _subtype = ('application', 'pdf') if attachment_path.lower().endswith('.pdf') else ('text', 'plain')
            with open(full_attachment_path, 'rb') as f:
                attach = MIMEApplication(f.read(), _maintype=_maintype, _subtype=_subtype) 
                attach.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
                msg.attach(attach)
        except FileNotFoundError:
            app.logger.error(f"Attachment file not found at {full_attachment_path}")
            return False, f"Attachment file not found at {full_attachment_path}"
        except Exception as e:
            app.logger.error(f"Failed to attach file {full_attachment_path}: {e}", exc_info=True)
            return False, f"Failed to attach invoice: {e}"

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
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

def generate_upi_qr_url(upi_id, payee_name, amount, transaction_note="Payment for artwork"):
    upi_uri = f"upi://pay?pa={upi_id}&pn={payee_name.replace(' ', '%20')}&am={amount:.2f}&cu=INR&tn={transaction_note.replace(' ', '%20')}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={upi_uri}"
    return qr_url

# Helper to parse custom options from form data for repopulation
def parse_custom_options_from_form(form):
    custom_option_groups = []
    group_indices = sorted(list(set([k.split('_')[3] for k in form if k.startswith('option_group_name_')])))

    for group_index in group_indices:
        group_name = form.get(f'option_group_name_{group_index}', '').strip()
        if group_name:
            options_list = []
            option_indices = sorted(list(set([k.split('_')[4] for k in form if k.startswith(f'option_label_{group_index}_')])))
            for option_index in option_indices:
                option_label = form.get(f'option_label_{group_index}_{option_index}', '').strip()
                option_price = form.get(f'option_price_{group_index}_{option_index}', '0.00')
                if option_label:
                    options_list.append({'label': option_label, 'price': safe_decimal(option_price)})
            custom_option_groups.append({'group_name': group_name, 'options': options_list})
    return custom_option_groups

# --- SQLAlchemy Models ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    role = Column(String(20), default='user') # 'user', 'admin'
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    addresses = relationship('Address', backref='user', lazy=True, cascade="all, delete-orphan")
    orders = relationship(
        'Order', 
        backref='user_obj', 
        lazy=True, 
        cascade="all, delete-orphan",
        primaryjoin="User.id == Order.user_id" 
    )
    reviews = relationship('Review', backref='user', lazy=True, cascade="all, delete-orphan")
    stock_notifications = relationship('StockNotification', backref='user_for_notification', lazy=True, cascade="all, delete-orphan") 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

    def get_id(self):
        return str(self.id)

    @staticmethod
    def find_by_email_or_phone(identifier):
        user = User.query.filter_by(email=identifier).first()
        if not user:
            user = User.query.filter_by(phone=identifier).first()
        return user

    def __repr__(self):
        return f"<User {self.email}>"

class Address(db.Model):
    __tablename__ = 'addresses'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), ForeignKey('users.id'), nullable=False)
    label = Column(String(100), nullable=False) # e.g., "Home", "Work"
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    pincode = Column(String(10), nullable=False)
    is_default = Column(Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'full_name': self.full_name,
            'phone': self.phone,
            'address_line1': self.address_line1,
            'address_line2': self.address_line2,
            'city': self.city,
            'state': self.state,
            'pincode': self.pincode,
            'is_default': self.is_default
        }

    def __repr__(self):
        return f"<Address {self.label} for User {self.user_id}>"

class Category(db.Model):
    __tablename__ = 'categories'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    image_path = Column(String(255), nullable=True) # Path to category image

    # Changed backref name to avoid conflict with Artwork.category
    # The relationship is defined on Artwork side, backref is 'category_obj'
    # This relationship is here for completeness, but the backref 'artworks_in_category'
    # is actually defined on the Artwork model's relationship to Category.
    # This line is technically not needed here if the Artwork defines the relationship,
    # but it doesn't hurt. The key is the backref name on Artwork's relationship.
    # artworks_in_category = relationship('Artwork', backref='category_obj', lazy=True) # This is the correct backref name

    def __repr__(self):
        return f"<Category {self.name}>"

class Artwork(db.Model):
    __tablename__ = 'artworks'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    category_id = Column(String(50), ForeignKey('categories.id'), nullable=False)
    original_price = Column(Numeric(10, 2), nullable=False)
    gst_percentage = Column(Numeric(5, 2), nullable=False, default=DEFAULT_GST_PERCENTAGE)
    stock = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    images = Column(Text, nullable=True) # Stores JSON string of image paths
    is_featured = Column(Boolean, default=False)
    
    # All options now handled by custom_options JSON
    custom_options = Column(Text, nullable=True) # Stores JSON string of custom options: {"Group Name": {"Option Label": price}}

    # Define relationship from Artwork to Category with a unique backref name
    # The backref 'category_obj' is used on the Artwork model to access the Category object
    category = relationship('Category', backref='artworks_in_category', lazy=True) # Changed backref name to avoid conflict

    reviews = relationship('Review', backref='artwork', lazy=True, cascade="all, delete-orphan")
    wishlist_items = relationship('Wishlist', backref='artwork', lazy=True, cascade="all, delete-orphan")
    stock_notifications = relationship('StockNotification', backref='artwork', lazy=True, cascade="all, delete-orphan")

    def get_images_list(self):
        if self.images:
            try:
                return json.loads(self.images)
            except json.JSONDecodeError:
                app.logger.error(f"Error decoding images JSON for SKU {self.sku}: {self.images}")
                return []
        return []

    def get_custom_options(self):
        if self.custom_options:
            try:
                return json.loads(self.custom_options)
            except json.JSONDecodeError:
                app.logger.error(f"Error decoding custom_options JSON for SKU {self.sku}: {self.custom_options}")
                return {}
        return {}

    def __repr__(self):
        return f"<Artwork {self.sku} - {self.name}>"

class Review(db.Model):
    __tablename__ = 'reviews'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    artwork_id = Column(String(50), ForeignKey('artworks.id'), nullable=False)
    user_id = Column(String(50), ForeignKey('users.id'), nullable=False)
    rating = Column(Integer, nullable=False) # 1 to 5 stars
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Review {self.id} for Artwork {self.artwork_id} by User {self.user_id}>"

class Wishlist(db.Model):
    __tablename__ = 'wishlist'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), ForeignKey('users.id'), nullable=False)
    artwork_id = Column(String(50), ForeignKey('artworks.id'), nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow)

    # Ensure unique combination of user and artwork in wishlist
    __table_args__ = (db.UniqueConstraint('user_id', 'artwork_id', name='_user_artwork_uc'),)

    def __repr__(self):
        return f"<Wishlist {self.id} for User {self.user_id} Artwork {self.artwork_id}>"

class Order(db.Model):
    __tablename__ = 'orders'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), ForeignKey('users.id'), nullable=False) # User who placed the order
    order_date = Column(DateTime, default=datetime.utcnow)
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(120), nullable=False)
    customer_phone = Column(String(20), nullable=False)
    shipping_address_json = Column(Text, nullable=False) # Stores JSON string of address details
    shipping_pincode = Column(String(10), nullable=False)
    subtotal_before_gst = Column(Numeric(10, 2), nullable=False)
    total_gst_amount = Column(Numeric(10, 2), nullable=False)
    cgst_amount = Column(Numeric(10, 2), nullable=False)
    sgst_amount = Column(Numeric(10, 2), nullable=False)
    shipping_charge = Column(Numeric(10, 2), nullable=False)
    total_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(50), nullable=False, default='Pending Payment') # e.g., Pending Payment, Payment Submitted, Payment Confirmed, Shipped, Delivered, Cancelled
    transaction_id = Column(String(100), nullable=True) # UPI UTR
    payment_screenshot_path = Column(String(255), nullable=True)
    payment_submitted_on = Column(DateTime, nullable=True)
    remark = Column(Text, nullable=True)
    courier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    invoice_details_json = Column(Text, nullable=True) # Stores JSON string of invoice details

    # --- NEW CANCELLATION FIELDS ---
    cancellation_reason = Column(Text, nullable=True)
    cancellation_timestamp = Column(DateTime, nullable=True)
    cancelled_by_user_id = Column(String(50), ForeignKey('users.id'), nullable=True) # User who cancelled
    cancelled_by_admin_id = Column(String(50), ForeignKey('users.id'), nullable=True) # Admin who cancelled

    # Relationships for cancellation tracking
    user_who_cancelled = relationship('User', foreign_keys=[cancelled_by_user_id], backref='cancelled_orders_by_user', lazy=True)
    admin_who_cancelled = relationship('User', foreign_keys=[cancelled_by_admin_id], backref='cancelled_orders_by_admin', lazy=True)

    order_items = relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

    def get_shipping_address(self):
        return json.loads(self.shipping_address_json) if self.shipping_address_json else {}

    def get_invoice_details(self):
        return json.loads(self.invoice_details_json) if self.invoice_details_json else {}

    def __repr__(self):
        return f"<Order {self.id} by User {self.user_id}>"

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(50), ForeignKey('orders.id'), nullable=False)
    artwork_id = Column(String(50), ForeignKey('artworks.id'), nullable=False)
    sku = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    image_path = Column(String(255), nullable=True) # Storing the image path at time of order
    quantity = Column(Integer, nullable=False)
    unit_price_before_options = Column(Numeric(10, 2), nullable=False) # Base price of artwork before any options
    unit_price_before_gst = Column(Numeric(10, 2), nullable=False) # Price per unit after options, before GST
    gst_percentage = Column(Numeric(5, 2), nullable=False)
    gst_amount = Column(Numeric(10, 2), nullable=False) # Total GST for this item (quantity * unit_gst_amount)
    total_price_before_gst = Column(Numeric(10, 2), nullable=False) # Total for this item (quantity * unit_price_before_gst)
    total_price = Column(Numeric(10, 2), nullable=False) # Total for this item (quantity * unit_price_after_gst)
    selected_options_json = Column(Text, nullable=True) # Stores JSON string of selected custom options

    def get_selected_options(self):
        return json.loads(self.selected_options_json) if self.selected_options_json else {}

    def __repr__(self):
        return f"<OrderItem {self.id} for Order {self.order_id} - {self.name}>"

class StockNotification(db.Model):
    __tablename__ = 'stock_notifications'
    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(50), ForeignKey('users.id'), nullable=True) # Made nullable as per discussion
    email = Column(String(120), nullable=False) # Can be for non-logged in users
    artwork_id = Column(String(50), ForeignKey('artworks.id'), nullable=False)
    notified_at = Column(DateTime, nullable=True) # Timestamp when notification was sent
    requested_at = Column(DateTime, default=datetime.utcnow) # When request was made
    is_active = Column(Boolean, default=True) # Set to False once notified or removed

    __table_args__ = (db.UniqueConstraint('email', 'artwork_id', name='_email_artwork_notification_uc'),) # Unique by email and artwork

    def __repr__(self):
        return f"<StockNotification {self.id} User {self.user_id if self.user_id else self.email} Artwork {self.artwork_id}>"


# --- Context Processors ---
@app.context_processor
def inject_global_data():
    cart_summary = calculate_cart_totals(session.get('cart', {}))
    
    testimonials = [
        {
            'name': 'Radha Devi',
            'image': url_for('static', filename='uploads/testimonial_radha.jpg'),
            'rating': 5,
            'feedback': 'The Krishna painting I received is absolutely divine. It brings so much peace to my home. Highly recommend!',
            'product_sku': 'KP001'
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
    
    for t in testimonials:
        # Construct full path to check existence
        # The URL from url_for('static', filename='...') will be like '/static/uploads/testimonial_radha.jpg'
        # We need to remove '/static/' to get the path relative to the static folder.
        relative_path_from_static = t['image'][len('/static/'):]
        full_image_path = os.path.join(app.root_path, 'static', relative_path_from_static)

        if not os.path.exists(full_image_path):
            t['image'] = url_for('static', filename='images/user-placeholder.png') # Fallback to placeholder

    return dict(
        categories=Category.query.all(), # Fetch categories here
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
        now=datetime.now,
        cart_count=cart_summary['total_items_in_cart'], # Pass cart count
        is_user_logged_in=str(current_user.is_authenticated).lower() # For JS to check login status
    )

# Jinja2 filter for JavaScript string escaping
@app.template_filter('js_string')
def js_string_filter(s):
    """Escape a string for use in JavaScript."""
    return json.dumps(str(s))[1:-1].replace("'", "\\'")

# NEW: Register a custom Jinja2 filter for floatformat
@app.template_filter('floatformat')
def floatformat_filter(value, places=2):
    """
    Formats a float/Decimal to a specific number of decimal places.
    Handles non-numeric inputs gracefully by returning '0.00' or original value.
    """
    try:
        decimal_value = Decimal(str(value)) 
        return f"{decimal_value:.{places}f}"
    except (ValueError, TypeError, AttributeError, InvalidOperation): 
        app.logger.warning(f"floatformat_filter received invalid value '{value}' (type: {type(value)}). Returning '0.00'.")
        return f"{Decimal('0.00'):.{places}f}" 

# ✅ Inject csrf_token into all templates (IMPORTANT!)
@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

# --- Login Manager Callbacks ---
@login_manager.unauthorized_handler
def unauthorized():
    flash('Please log in to access this page.', 'info')
    return redirect(url_for('user_login'))

# --- Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('user_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

@app.route('/')
def index():
    featured_artworks = Artwork.query.filter_by(is_featured=True).limit(6).all()
    
    # Logic for artworks by category on index page (similar to your provided code)
    artworks_by_category = defaultdict(list)
    # Fetch all artworks to categorize them
    all_artworks = Artwork.query.all()
    for art in all_artworks:
        category_name = art.category.name if art.category else 'Uncategorized' # Use .category here
        # Limit to 6 artworks per category for display on index
        if len(artworks_by_category[category_name]) < 6:
            artworks_by_category[category_name].append(art)
    
    # Sort categories, e.g., 'Paintings' first, then others alphabetically
    ordered_categories = sorted(artworks_by_category.keys(), key=lambda x: (0, x) if x == 'Paintings' else (1, x))
    artworks_by_category_dict = {cat: artworks_by_category[cat] for cat in ordered_categories} 

    return render_template('index.html', featured_artworks=featured_artworks, artworks_by_category=artworks_by_category_dict)

@app.route('/all_products') # Changed from /all-products to /all_products for consistency
def all_products():
    search_query = request.args.get('search', '').strip()
    selected_category_id = request.args.get('category_id', '') # Filter by category ID

    artworks_query = Artwork.query.order_by(Artwork.name)

    if search_query:
        artworks_query = artworks_query.filter(
            (Artwork.name.ilike(f'%{search_query}%')) |
            (Artwork.description.ilike(f'%{search_query}%')) |
            (Artwork.sku.ilike(f'%{search_query}%'))
        )
    if selected_category_id:
        artworks_query = artworks_query.filter_by(category_id=selected_category_id)
    
    artworks = artworks_query.all()
    categories = Category.query.order_by(Category.name).all() # Fetch all categories for filter dropdown

    return render_template('all_products.html', 
                           artworks=artworks, 
                           search_query=search_query, 
                           selected_category_id=selected_category_id,
                           categories=categories # Pass categories to template
                          )

@app.route('/category/<category_id>')
def products_by_category(category_id):
    category = Category.query.get_or_404(category_id)
    artworks = Artwork.query.filter_by(category_id=category.id).order_by(Artwork.name).all()
    return render_template('products_by_category.html', category=category, artworks=artworks)

@app.route('/product/<sku>')
def product_detail(sku):
    artwork = Artwork.query.filter_by(sku=sku).first_or_404()
    return render_template('product_detail.html', artwork=artwork)

@app.route('/user_register', methods=['GET', 'POST'])
def user_register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()
        name = request.form['name'].strip()
        phone = request.form['phone'].strip()
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('register.html', form_data=request.form)
        if User.query.filter_by(phone=phone).first():
            flash('Phone number already registered.', 'danger')
            return render_template('register.html', form_data=request.form)

        new_user = User(email=email, name=name, phone=phone)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('user_login'))
    return render_template('register.html', form_data={})

@app.route('/user_logout')
@login_required
def user_logout():
    logout_user()
    session.pop('cart', None) # Clear cart on logout for security/privacy
    session.pop('direct_purchase_item', None)
    session.modified = True
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def user_profile():
    return render_template('profile.html')

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.name = request.form['name'].strip()
        current_user.phone = request.form['phone'].strip()
        db.session.commit()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('user_profile'))
    return render_template('edit_profile.html')

@app.route('/profile/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if not current_user.check_password(old_password):
            flash('Incorrect old password.', 'danger')
        elif new_password != confirm_password:
            flash('New password and confirmation do not match.', 'danger')
        elif len(new_password) < 6: # Example: minimum password length
            flash('New password must be at least 6 characters long.', 'danger')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('user_profile'))
    return render_template('change_password.html')

@app.route('/addresses')
@login_required
def manage_addresses():
    addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc(), Address.label).all()
    return render_template('manage_addresses.html', addresses=addresses)

@app.route('/addresses/add', methods=['GET', 'POST'])
@login_required
def add_address():
    if request.method == 'POST':
        label = request.form['label'].strip()
        full_name = request.form['full_name'].strip()
        phone = request.form['phone'].strip()
        address_line1 = request.form['address_line1'].strip()
        address_line2 = request.form.get('address_line2', '').strip()
        city = request.form['city'].strip()
        state = request.form['state'].strip()
        pincode = request.form['pincode'].strip()
        is_default = 'is_default' in request.form

        # If new address is set as default, unset others
        if is_default:
            Address.query.filter_by(user_id=current_user.id, is_default=True).update({'is_default': False})

        new_address = Address(
            user_id=current_user.id,
            label=label,
            full_name=full_name,
            phone=phone,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            pincode=pincode,
            is_default=is_default
        )
        db.session.add(new_address)
        db.session.commit()
        flash('Address added successfully!', 'success')
        return redirect(url_for('manage_addresses'))
    return render_template('add_edit_address.html', address=None)

@app.route('/addresses/edit/<address_id>', methods=['GET', 'POST'])
@login_required
def edit_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash('You do not have permission to edit this address.', 'danger')
        return redirect(url_for('manage_addresses'))

    if request.method == 'POST':
        address.label = request.form['label'].strip()
        address.full_name = request.form['full_name'].strip()
        address.phone = request.form['phone'].strip()
        address.address_line1 = request.form['address_line1'].strip()
        address.address_line2 = request.form.get('address_line2', '').strip()
        address.city = request.form['city'].strip()
        address.state = request.form['state'].strip()
        address.pincode = request.form['pincode'].strip()
        is_default = 'is_default' in request.form

        if is_default:
            # If this address is set as default, unset others
            Address.query.filter_by(user_id=current_user.id, is_default=True).update({'is_default': False})
            address.is_default = True # Set this one as default
        else:
            # If this address is explicitly unset as default, ensure at least one remains default
            # This logic might need refinement if you want to force one default at all times
            address.is_default = False
            # Consider adding logic to set another address as default if this was the only one and is_default is unchecked

        db.session.commit()
        flash('Address updated successfully!', 'success')
        return redirect(url_for('manage_addresses'))
    return render_template('add_edit_address.html', address=address)

@app.route('/addresses/delete/<address_id>', methods=['POST'])
@login_required
def delete_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash('You do not have permission to delete this address.', 'danger')
        return redirect(url_for('manage_addresses'))
    
    if address.is_default:
        flash('Cannot delete default address. Please set another address as default first.', 'danger')
        return redirect(url_for('manage_addresses'))

    db.session.delete(address)
    db.session.commit()
    flash('Address deleted successfully!', 'success')
    return redirect(url_for('manage_addresses'))


# --- Cart Routes ---

# This is the /add-to-cart route that your frontend is calling via AJAX
@csrf.exempt
@app.route('/add-to-cart', methods=['POST']) 
def add_to_cart():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "message": "Invalid or missing JSON"}), 400

        sku = data.get('sku')
        quantity_raw = data.get('quantity')
        
        selected_options = data.get('options', {}) 

        if not sku:
            return jsonify({"success": False, "message": "Missing SKU"}), 400

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                return jsonify({"success": False, "message": "Quantity must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": "Invalid quantity format"}), 400

        artwork_info = Artwork.query.filter_by(sku=sku).first()
        if not artwork_info:
            return jsonify({"success": False, "message": f"Artwork with SKU '{sku}' not found."}), 404

        stock = artwork_info.stock
        
        item_id = generate_cart_item_id(sku, selected_options) 

        cart = session.get('cart', {})
        if not isinstance(cart, dict):
            cart = {}
            session['cart'] = cart
            session.modified = True

        unit_price_before_gst = calculate_item_price_with_options(artwork_info, selected_options)
        gst_percentage = artwork_info.gst_percentage
        gst_decimal = gst_percentage / Decimal('100')
        gst_amount_per_unit = unit_price_before_gst * gst_decimal
        total_price_per_unit = unit_price_before_gst + gst_amount_per_unit

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
            cart[item_id]['total_price_before_gst'] = unit_price_before_gst * new_qty
            cart[item_id]['total_gst_amount'] = gst_amount_per_unit * new_qty
            cart[item_id]['total_price'] = total_price_per_unit * new_qty
        else:
            if quantity > stock:
                return jsonify({"success": False, "message": f"Requested {quantity}, only {stock} available."}), 400

            cart[item_id] = {
                'id': item_id,
                'sku': sku,
                'name': artwork_info.name,
                'imageUrl': artwork_info.get_images_list()[0] if artwork_info.get_images_list() else 'images/placeholder.png', 
                'options': selected_options, 
                'quantity': quantity,
                'unit_price_before_options': artwork_info.original_price, 
                'unit_price_before_gst': unit_price_before_gst, 
                'gst_percentage': gst_percentage,
                'gst_amount_per_unit': gst_amount_per_unit, 
                'total_price_per_unit': total_price_per_unit, 
                'total_price_before_gst': unit_price_before_gst * quantity, 
                'total_gst_amount': gst_amount_per_unit * quantity, 
                'total_price': total_price_per_unit * quantity, 
                'stock_available': stock 
            }

        session['cart'] = cart
        session.modified = True

        updated_summary = calculate_cart_totals(session['cart']) 

        return jsonify({
            "success": True,
            "message": f"'{artwork_info.name}' added to cart!",
            "cart_count": updated_summary['total_items_in_cart'], 
            "cart_subtotal": updated_summary['subtotal_before_gst'] 
        })

    except Exception as e:
        app.logger.error(f"Cart error: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Unexpected error: {str(e)}"}), 500

@app.route('/cart')
@login_required
def cart():
    cart_data_from_session = session.get('cart', {})

    if not isinstance(cart_data_from_session, dict):
        app.logger.warning(f"Session cart was not a dictionary on /cart. Resetting cart for session ID: {session.sid}")
        cart_data_from_session = {}
        session['cart'] = cart_data_from_session 
        session.modified = True

    cart_summary = calculate_cart_totals(cart_data_from_session)
    
    session['cart'] = {item['id']: item for item in cart_summary['cart_items']}
    session.modified = True

    return render_template('cart.html',
                           cart_summary=cart_summary,
                           MAX_SHIPPING_COST_FREE_THRESHOLD=MAX_SHIPPING_COST_FREE_THRESHOLD)

@app.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    try:
        data = request.get_json()
        item_id = data.get('item_id')

        cart = session.get('cart', {})
        if not isinstance(cart, dict):
            current_app.logger.warning(f"Cart was not dict: {type(cart)}. Resetting to empty.")
            cart = {}
            session['cart'] = cart
            session.modified = True
            return jsonify({"success": False, "message": "Cart was corrupted and reset."}), 400

        if item_id in cart:
            del cart[item_id]
            session['cart'] = cart
            session.modified = True
            
            cart_summary = calculate_cart_totals(cart) 
            return jsonify({
                "success": True, 
                "message": "Item removed from cart.", 
                "cart_summary": cart_summary
            })
        else:
            return jsonify({"success": False, "message": "Item not found in cart."}), 404

    except Exception as e:
        app.logger.error(f"Error in remove_from_cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Server error while removing item."}), 500

@app.route('/update_cart_quantity', methods=['POST'])
def update_cart_quantity():
    data = request.get_json()
    item_id = data.get('item_id')
    quantity = data.get('quantity')

    if not item_id or quantity is None:
        return jsonify(success=False, message='Missing item ID or quantity.'), 400

    try:
        quantity = int(quantity)
        if quantity < 1:
            return jsonify(success=False, message='Quantity must be at least 1.'), 400
    except ValueError:
        return jsonify(success=False, message='Invalid quantity format.'), 400

    cart = session.get('cart', {})
    if not isinstance(cart, dict):
        app.logger.warning(f"Cart was not dict: {type(cart)}. Resetting to empty.")
        cart = {}
        session['cart'] = cart
        session.modified = True
        return jsonify({"success": False, "message": "Cart was corrupted and reset."}), 400

    if item_id not in cart:
        return jsonify(success=False, message='Item not found in cart.'), 404

    item = cart[item_id]
    artwork = Artwork.query.filter_by(sku=item['sku']).first()

    if not artwork:
        return jsonify(success=False, message='Associated product not found.'), 404
    if artwork.stock < quantity:
        return jsonify(success=False, message=f'Not enough stock for {item["name"]}. Available: {artwork.stock}'), 400

    item['quantity'] = quantity
    item['total_price_before_gst'] = safe_decimal(item['unit_price_before_gst']) * quantity
    item['total_gst_amount'] = safe_decimal(item['gst_amount_per_unit']) * quantity
    item['total_price'] = safe_decimal(item['total_price_per_unit']) * quantity

    session['cart'] = cart
    session.modified = True

    cart_summary = calculate_cart_totals(cart) 
    return jsonify(success=True, message='Cart updated successfully.',
                   cart_summary=cart_summary,
                   updated_item_total=item['total_price'])

@app.route('/get_cart_summary', methods=['GET'])
def get_cart_summary():
    try:
        cart = session.get('cart', {})
        total_items_quantity = sum(int(item.get('quantity', 0)) for item in cart.values())

        return jsonify({
            'success': True,
            'total_items_quantity': total_items_quantity
        }), 200
    except Exception as e:
        app.logger.error(f"Error in get_cart_summary: {e}", exc_info=True)
<<<<<<< HEAD
        return jsonify({'success': False, 'message': 'Failed to retrieve cart summary due0 to a server error.'}), 500

# --- NEW: Endpoint to process checkout from cart page ---
=======
        return jsonify({'success': False, 'message': 'Failed to retrieve cart summary due to a server error.'}), 500

>>>>>>> a3989ae (SQL v2)
@app.route('/process_checkout_from_cart', methods=['POST'])
@login_required
def process_checkout_from_cart():
    cart_data_from_session = session.get('cart', {})
    if not cart_data_from_session:
        flash("Your cart is empty. Please add items to proceed to checkout.", "danger")
        return redirect(url_for('cart'))

    cart_summary = calculate_cart_totals(cart_data_from_session)

    if not cart_summary['cart_items']:
        flash("Your cart is empty or all items are out of stock. Please add items to proceed.", "danger")
        return redirect(url_for('all_products'))
    
    session['checkout_cart'] = session.get('cart', {})
    session.modified = True

    return redirect(url_for('purchase_form'))

@app.route('/create_direct_order', methods=['POST'])
def create_direct_order():
    data = request.get_json()
    sku = data.get('sku')
    name = data.get('name')
    image_url = data.get('imageUrl')
    gst_percentage = safe_decimal(data.get('gstPercentage'))
    quantity = int(data.get('quantity'))
    selected_options = data.get('options', {}) 

    if quantity <= 0:
        return jsonify(success=False, message='Quantity must be at least 1.'), 400

    artwork = Artwork.query.filter_by(sku=sku).first()
    if not artwork:
        return jsonify(success=False, message='Product not found.'), 404
    if artwork.stock < quantity:
        return jsonify(success=False, message=f'Not enough stock for {name}. Available: {artwork.stock}'), 400

    unit_price_before_gst = calculate_item_price_with_options(artwork, selected_options)

    gst_amount_per_unit = unit_price_before_gst * (gst_percentage / 100)
    total_price_per_unit = unit_price_before_gst + gst_amount_per_unit

    item_for_direct_purchase = {
        'id': generate_cart_item_id(sku, selected_options), 
        'sku': sku,
        'name': name,
        'imageUrl': image_url,
        'quantity': quantity,
        'unit_price_before_options': artwork.original_price, 
        'unit_price_before_gst': unit_price_before_gst, 
        'gst_percentage': gst_percentage,
        'gst_amount_per_unit': gst_amount_per_unit,
        'total_price_per_unit': total_price_per_unit,
        'total_price_before_gst': unit_price_before_gst * quantity,
        'total_gst_amount': gst_amount_per_unit * quantity,
        'total_price': total_price_per_unit * quantity,
        'options': selected_options 
    }

    session['direct_purchase_item'] = item_for_direct_purchase
    session.modified = True

    return jsonify(success=True, message='Proceeding to purchase.', redirect_url=url_for('purchase_form'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_summary = calculate_cart_totals(session.get('cart', {}))
    
    if not cart_summary['cart_items'] and not session.get('direct_purchase_item'):
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('all_products'))

    user_addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc()).all()
    
    items_to_checkout = []
    if 'direct_purchase_item' in session and session['direct_purchase_item']:
        items_to_checkout.append(session['direct_purchase_item'])
    else:
        items_to_checkout = cart_summary['cart_items']

    if request.method == 'POST':
        selected_address_index = request.form.get('shipping_address')
        if selected_address_index is None:
            flash('Please select a shipping address.', 'danger')
            return render_template('checkout.html', cart_summary=cart_summary, user_addresses=user_addresses, items_to_checkout=items_to_checkout)

        try:
            selected_address_index = int(selected_address_index)
            shipping_address_data = user_addresses[selected_address_index].to_dict()
        except (ValueError, IndexError):
            flash('Invalid shipping address selected.', 'danger')
            return render_template('checkout.html', cart_summary=cart_summary, user_addresses=user_addresses, items_to_checkout=items_to_checkout)

        new_order = Order(
            user_id=current_user.id,
            customer_name=shipping_address_data['full_name'],
            customer_email=current_user.email,
            customer_phone=shipping_address_data['phone'],
            shipping_address_json=json.dumps(shipping_address_data),
            shipping_pincode=shipping_address_data['pincode'],
            subtotal_before_gst=cart_summary['subtotal_before_gst'],
            total_gst_amount=cart_summary['total_gst_amount'],
            cgst_amount=cart_summary['total_gst_amount'] / 2, 
            sgst_amount=cart_summary['total_gst_amount'] / 2, 
            shipping_charge=cart_summary['shipping_charge'],
            total_amount=cart_summary['grand_total'],
            status='Pending Payment' 
        )
        db.session.add(new_order)
        db.session.flush() 

        for item_data in items_to_checkout:
            artwork_obj = Artwork.query.filter_by(sku=item_data['sku']).first()
            if not artwork_obj:
                flash(f"Error: Product {item_data['name']} not found.", 'danger')
                db.session.rollback() 
                return redirect(url_for('cart')) 

            order_item = OrderItem(
                order_id=new_order.id,
                artwork_id=artwork_obj.id,
                sku=item_data['sku'],
                name=item_data['name'],
                quantity=item_data['quantity'],
                unit_price_before_options=item_data['unit_price_before_options'],
                unit_price_before_gst=item_data['unit_price_before_gst'],
                gst_percentage=item_data['gst_percentage'],
                gst_amount=item_data['gst_amount_per_unit'] * item_data['quantity'],
                total_price_before_gst=item_data['total_price_before_gst'],
                total_price=item_data['total_price'],
                selected_options_json=json.dumps(item_data.get('options', {})) 
            )
            db.session.add(order_item)
            
            artwork = Artwork.query.filter_by(sku=item_data['sku']).first()
            if artwork:
                artwork.stock -= item_data['quantity']
                db.session.add(artwork)

        db.session.commit()

        if 'direct_purchase_item' in session:
            session.pop('direct_purchase_item', None)
        else:
            session.pop('cart', None)
        session.modified = True

        flash('Order placed successfully! Please complete your payment.', 'success')
        return redirect(url_for('payment_initiate', order_id=new_order.id, amount=new_order.total_amount))

    return render_template('checkout.html', cart_summary=cart_summary, user_addresses=user_addresses, items_to_checkout=items_to_checkout)

@app.route('/purchase_form')
@login_required
def purchase_form():
    item_for_direct_purchase = session.get('direct_purchase_item')
    if not item_for_direct_purchase:
        # If direct purchase item is not set, check for checkout_cart (from cart checkout)
        cart_data_from_session = session.get('checkout_cart', {})
        if not cart_data_from_session:
            flash('No item selected for direct purchase or cart is empty.', 'warning')
            return redirect(url_for('all_products'))
        
        # Calculate summary for the entire cart
        cart_summary = calculate_cart_totals(cart_data_from_session)
        items_to_display = cart_summary['cart_items']

    else:
        # Recalculate totals for the single item to ensure accuracy
        temp_cart = {item_for_direct_purchase['id']: item_for_direct_purchase}
        cart_summary = calculate_cart_totals(temp_cart)
        items_to_display = cart_summary['cart_items'] # This will contain just the one direct item

    user_addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc()).all()
    
    # Prefill with user's default address or first saved address
    prefill_name = current_user.name
    prefill_email = current_user.email
    prefill_phone = current_user.phone
    prefill_address_line1 = ""
    prefill_pincode = ""
    prefill_city = ""
    prefill_state = ""
    
    if user_addresses:
        default_address = next((addr for addr in user_addresses if addr.is_default), user_addresses[0])
        prefill_name = default_address.full_name
        prefill_phone = default_address.phone
        prefill_address_line1 = default_address.address_line1
        prefill_pincode = default_address.pincode
        prefill_city = default_address.city
        prefill_state = default_address.state
    
    form_data = {
        'name': prefill_name,
        'email': prefill_email,
        'phone': prefill_phone,
        'address_line1': prefill_address_line1,
        'pincode': prefill_pincode,
        'city': prefill_city,
        'state': prefill_state
    }

    return render_template('purchase_form.html', 
                           form_data=form_data,
                           cart_summary=cart_summary,
                           items_to_display=items_to_display, # Pass the items to display
                           user_addresses=user_addresses)


@app.route('/payment_initiate/<order_id>/<float:amount>')
@login_required
def payment_initiate(order_id, amount):
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        flash('Order not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('my_orders'))
    
    if order.status not in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
        flash(f'Payment for Order {order_id} has already been processed or is not pending.', 'info')
        return redirect(url_for('my_orders'))

    amount_decimal = Decimal(str(amount))

    qr_code_url = generate_upi_qr_url(UPI_ID, BANKING_NAME, amount_decimal, f"Payment for Order {order_id}")

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
<<<<<<< HEAD
    """
    Handles submission of payment screenshot and updates order status.
    """
    orders = load_orders_data()
    order_index = -1
    for i, order in enumerate(orders):
        if order.get('order_id') == order_id and order.get('user_id') == str(current_user.id):
            order_index = i
            break

    if order_index == -1:
        flash('Order not found or you do not have permission to update it.', 'danger')
        return redirect(url_for('my_orders'))

    order = orders[order_index]

    transaction_id = request.form.get('transaction_id', '').strip()

    # --- UTR Validation ---
    if not transaction_id:
        flash('Transaction ID (UTR) is required.', 'danger')
        # Redirect back to the payment page with the correct order details
        return redirect(url_for('payment_initiate', order_id=order_id, amount=order.get('total_amount', Decimal('0.00'))))

    if not (transaction_id.isdigit() and len(transaction_id) == 12):
        flash('Please enter a valid 12-digit UTR number.', 'danger')
        return redirect(url_for('payment_initiate', order_id=order_id, amount=order.get('total_amount', Decimal('0.00'))))
    # --- End UTR Validation ---

    # Process screenshot if provided (now optional)
    screenshot_path = None
    if 'payment_screenshot' in request.files:
        file = request.files['payment_screenshot']
        if file and file.filename:
            filename = secure_filename(file.filename)
            unique_filename = str(uuid.uuid4()) + '_' + filename
            file_path = os.path.join(app.config['PAYMENT_SCREENSHOTS_FOLDER'], unique_filename)
            file.save(file_path)
            screenshot_path = f'uploads/payment_screenshots/{unique_filename}'
        # Else: if no file or empty filename, screenshot_path remains None (optional)

    # Update order details
    orders[order_index]['transaction_id'] = transaction_id
    if screenshot_path: # Only update path if a screenshot was actually uploaded
        orders[order_index]['payment_screenshot_path'] = screenshot_path

    orders[order_index]['payment_submitted_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    orders[order_index]['status'] = 'Payment Submitted - Awaiting Verification' # More precise status
    save_json('orders.json', orders)

    # Empty the cart after successful payment submission
    session.pop('cart', None)
    session.pop('direct_purchase_item', None) # Clear direct purchase item too
    session.modified = True

    flash('Payment details submitted successfully! Your order is now under review.', 'success')
    return redirect(url_for('thank_you_page', order_id=order_id))
=======
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        flash('Order not found or you do not have permission to submit payment for it.', 'danger')
        return redirect(url_for('my_orders'))

    if order.status not in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
        flash(f'Payment for Order {order_id} has already been processed or is not pending.', 'info')
        return redirect(url_for('my_orders'))

    transaction_id = request.form.get('transaction_id', '').strip()
    payment_screenshot = request.files.get('payment_screenshot')

    if not transaction_id and not payment_screenshot:
        flash('Please provide a UPI Transaction ID or upload a payment screenshot.', 'danger')
        return redirect(url_for('payment_initiate', order_id=order_id, amount=order.total_amount))
>>>>>>> a3989ae (SQL v2)

    order.transaction_id = transaction_id
    order.payment_submitted_on = datetime.utcnow()
    order.status = 'Payment Submitted - Awaiting Verification'

    if payment_screenshot and allowed_file(payment_screenshot.filename):
        filename = secure_filename(payment_screenshot.filename)
        unique_filename = str(uuid.uuid4()) + '_' + filename
        # Use full path for saving, but store relative path in DB
        filepath = os.path.join(app.root_path, app.config['PAYMENT_SCREENSHOTS_FOLDER'], unique_filename)
        payment_screenshot.save(filepath)
        order.payment_screenshot_path = os.path.join(os.path.basename(os.path.dirname(app.config['PAYMENT_SCREENSHOTS_FOLDER'])), os.path.basename(app.config['PAYMENT_SCREENSHOTS_FOLDER']), unique_filename) # Store relative path
    else:
        flash('Invalid payment screenshot file type. Allowed: png, jpg, jpeg, gif.', 'warning')

    db.session.commit()
    flash('Payment details submitted successfully. Your order is awaiting verification.', 'success')
    return redirect(url_for('thank_you_page', order_id=order_id))

@app.route('/thank_you_page/<order_id>')
@login_required
def thank_you_page(order_id):
    order = Order.query.get(order_id)
    if not order or order.user_id != current_user.id:
        flash('Order not found or you do not have permission to view it.', 'danger')
        return redirect(url_for('my_orders'))
    return render_template('thank_you.html', order=order)

@app.route('/my_orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    return render_template('my_orders.html', orders=orders)

@app.route('/cancel_order/<order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    order = Order.query.get(order_id)
    
    if not order or order.user_id != current_user.id:
        if request.is_json:
            return jsonify(success=False, message='Order not found or you do not have permission to cancel it.'), 403
        flash('Order not found or you do not have permission to cancel it.', 'danger')
        return redirect(url_for('my_orders'))

    if order.status in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
        order.status = 'Cancelled by User'
        order.remark = 'Order cancelled by user.' 
        order.cancellation_reason = 'Cancelled by customer via My Orders page.' 
        order.cancellation_timestamp = datetime.utcnow()
        order.cancelled_by_user_id = current_user.id 
        order.cancelled_by_admin_id = None 
        
        for item in order.order_items:
            artwork = Artwork.query.get(item.artwork_id)
            if artwork:
                artwork.stock += item.quantity
                db.session.add(artwork)
        
        db.session.add(order)
        db.session.commit()

        admin_email = app.config.get('SENDER_EMAIL')
        if admin_email:
            subject = f"Order Cancellation Alert: Order {order_id} Cancelled by User"
            body = f"""Dear Admin,

Order ID: {order_id} has been cancelled by the user.

Customer Name: {order.customer_name}
Customer Email: {order.customer_email}
Cancellation Date: {order.cancellation_timestamp.strftime('%Y-%m-%d %H:%M:%S')}
Cancellation Reason: {order.cancellation_reason}
Order Status: {order.status}

Please review the order details in the admin panel.

Regards,
Your Website Notification System
"""
            success, msg = send_email_with_attachment(admin_email, subject, body)
            if not success:
                app.logger.error(f"Failed to send admin cancellation email for order {order_id}: {msg}")

        if request.is_json:
            return jsonify(success=True, message=f'Order {order_id} has been cancelled successfully. Stock restored.'), 200
        flash(f'Order {order_id} has been cancelled successfully. Stock restored.', 'success')
        return redirect(url_for('my_orders'))
    else:
        if request.is_json:
            return jsonify(success=False, message=f'Order {order_id} cannot be cancelled as its status is "{order.status}".'), 400
        flash(f'Order {order_id} cannot be cancelled as its status is "{order.status}".', 'danger')
        return redirect(url_for('my_orders'))


@app.route('/download_invoice/<order_id>')
@login_required
def download_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id and not current_user.is_admin():
        flash('You do not have permission to download this invoice.', 'danger')
        return redirect(url_for('my_orders'))

    invoice_details = order.get_invoice_details()
    invoice_pdf_path = invoice_details.get('invoice_pdf_path')

    if invoice_pdf_path:
        # Ensure path is relative to static folder
        full_path = os.path.join(app.root_path, 'static', invoice_pdf_path)
        if os.path.exists(full_path):
            # Use os.path.dirname and os.path.basename for send_file
            return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))
        else:
            flash('Invoice file not found on server.', 'danger')
    else:
        flash('Invoice not yet generated for this order.', 'info')
    return redirect(url_for('my_orders')) # or admin_orders_view if admin


# --- Admin Routes ---
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin_dashboard'))
        flash('You are already logged in as a regular user. Please log out to access admin login.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()
        
        user = User.query.filter_by(email=email).first()

        if user and user.is_admin() and user.check_password(password):
            login_user(user)
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    filter_status = request.args.get('filter_status')
    search_query = request.args.get('search', '').strip().lower()

    orders_query = Order.query

    if search_query:
        orders_query = orders_query.filter(
            (Order.id.ilike(f'%{search_query}%')) |
            (Order.customer_name.ilike(f'%{search_query}%')) |
            (Order.customer_email.ilike(f'%{search_query}%'))
        )
    if filter_status:
        orders_query = orders_query.filter_by(status=filter_status)
    
    orders = orders_query.order_by(Order.order_date.desc()).all()

    total_orders = Order.query.count()
    total_revenue = db.session.query(func.sum(Order.total_amount)).scalar() or 0
    total_artworks = Artwork.query.count()
    total_users = User.query.count()

    # Monthly Revenue for Chart
    revenue_data = db.session.query(
        func.strftime('%Y-%m', Order.order_date),
        func.sum(Order.total_amount)
    ).filter(Order.status == 'Delivered').group_by(func.strftime('%Y-%m', Order.order_date)).order_by(func.strftime('%Y-%m', Order.order_date)).all()

    revenue_labels = [row[0] for row in revenue_data] if revenue_data else []
    revenue_values = [float(row[1]) for row in revenue_data] if revenue_data else []


    # Low Stock / Out of Stock Artworks
    low_stock_artworks = Artwork.query.filter(Artwork.stock <= 10, Artwork.stock > 0).all()
    out_of_stock_artworks = Artwork.query.filter_by(stock=0).all()

    # Orders Pending Review (e.g., Payment Submitted - Awaiting Verification or Held Invoices)
    orders_pending_review = Order.query.filter(
        (Order.status == 'Payment Submitted - Awaiting Verification') |
        (Order.invoice_details_json.like('%"is_held_by_admin": true%')) 
    ).order_by(Order.order_date.desc()).all()


    return render_template('admin_dashboard.html',
                           total_orders=total_orders,
                           total_revenue=total_revenue,
                           total_artworks=total_artworks,
                           total_users=total_users,
                           revenue_labels=revenue_labels,
                           revenue_values=revenue_values,
                           low_stock_artworks=low_stock_artworks,
                           out_of_stock_artworks=out_of_stock_artworks,
                           orders_pending_review=orders_pending_review,
                           orders=orders, 
                           search_query=search_query,
                           filter_status=filter_status)

@app.route('/admin/users')
@admin_required
def admin_users_view():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users_view.html', users=users)

@app.route('/admin/users/edit/<user_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.name = request.form['name'].strip()
        user.email = request.form['email'].strip()
        user.phone = request.form['phone'].strip()
        user.role = request.form['role'].strip()
        
        # Handle password change if provided
        new_password = request.form.get('password', '').strip()
        if new_password:
            user.set_password(new_password)

        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin_users_view'))
    return render_template('admin_edit_user.html', user=user)

@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own admin account.', 'danger')
        return redirect(url_for('admin_users_view'))
    
    db.session.delete(user)
    db.session.commit()
    flash('User deleted successfully!', 'success')
    return redirect(url_for('admin_users_view'))

@app.route('/admin/categories')
@admin_required
def admin_categories_view():
    categories = Category.query.order_by(Category.name).all()
    return render_template('admin_categories_view.html', categories=categories)

@app.route('/admin/categories/add', methods=['GET', 'POST'])
@admin_required
def add_category():
    categories = Category.query.all() # For dropdown in template
    form_data = {} # For repopulating form on error

    if request.method == 'POST':
        name = request.form['name'].strip()
        description = request.form.get('description', '').strip()
        
        if Category.query.filter_by(name=name).first():
            flash('Category with this name already exists.', 'danger')
            form_data = request.form.to_dict()
            return render_template('admin_add_edit_category.html', category=None, form_data=form_data, categories=categories)

        new_category = Category(name=name, description=description)

        # Handle image upload for category
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = str(uuid.uuid4()) + '_' + filename
                # Use full path for saving, but store relative path in DB
                filepath = os.path.join(app.root_path, app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
                file.save(filepath)
                new_category.image_path = os.path.join(os.path.basename(os.path.dirname(app.config['CATEGORY_IMAGES_FOLDER'])), os.path.basename(app.config['CATEGORY_IMAGES_FOLDER']), unique_filename) # Store relative path
            else:
                flash('Invalid image file for category. Allowed: png, jpg, jpeg, gif.', 'warning')
                form_data = request.form.to_dict()
                return render_template('admin_add_edit_category.html', category=None, form_data=form_data, categories=categories)
        else:
             new_category.image_path = 'images/placeholder.png' # Default placeholder if no image uploaded
        
        db.session.add(new_category)
        db.session.commit()
        flash('Category added successfully!', 'success')
        return redirect(url_for('admin_categories_view'))
    return render_template('admin_add_edit_category.html', category=None, form_data={}, categories=categories)

@app.route('/admin/categories/edit/<category_id>', methods=['GET', 'POST'])
@admin_required
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    categories = Category.query.all() # For dropdown in template

    if request.method == 'POST':
        new_name = request.form['name'].strip()
        if new_name != category.name and Category.query.filter_by(name=new_name).first():
            flash('Category with this name already exists.', 'danger')
            return render_template('admin_add_edit_category.html', category=category, form_data=request.form.to_dict(), categories=categories)

        category.name = new_name
        category.description = request.form.get('description', '').strip()

        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                # Delete old image if it exists and is not the placeholder
                if category.image_path and 'placeholder.png' not in category.image_path:
                    old_image_full_path = os.path.join(app.root_path, 'static', category.image_path)
                    if os.path.exists(old_image_full_path):
                        os.remove(old_image_full_path)
                
                filename = secure_filename(file.filename)
                unique_filename = str(uuid.uuid4()) + '_' + filename
                filepath = os.path.join(app.root_path, app.config['CATEGORY_IMAGES_FOLDER'], unique_filename)
                file.save(filepath)
                category.image_path = os.path.join(os.path.basename(os.path.dirname(app.config['CATEGORY_IMAGES_FOLDER'])), os.path.basename(app.config['CATEGORY_IMAGES_FOLDER']), unique_filename)
            else:
                flash('Invalid image file for category. Allowed: png, jpg, jpeg, gif.', 'warning')
                return render_template('admin_add_edit_category.html', category=category, form_data=request.form.to_dict(), categories=categories)
        
        db.session.commit()
        flash('Category updated successfully!', 'success')
        return redirect(url_for('admin_categories_view'))
    return render_template('admin_add_edit_category.html', category=category, form_data=category.__dict__, categories=categories) 

@app.route('/admin/categories/delete/<category_id>', methods=['POST'])
@admin_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)
    
    # Check if any artworks are linked to this category
    if category.artworks_in_category: # Use the new backref name
        return jsonify(success=False, message=f'Cannot delete category "{category.name}" because it has {len(category.artworks_in_category)} linked artworks. Please reassign or delete artworks first.'), 400

    # Delete associated image file if it exists and is not the placeholder
    if category.image_path and 'placeholder.png' not in category.image_path:
        full_path = os.path.join(app.root_path, 'static', category.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)

    db.session.delete(category)
    db.session.commit()
    return jsonify(success=True, message='Category deleted successfully!')


@app.route('/admin/artworks')
@admin_required
def admin_artworks_view():
    search_query = request.args.get('search_query', '').strip()
    selected_category_id = request.args.get('category_id', '')

    artworks_query = Artwork.query.order_by(Artwork.name)

    if search_query:
        artworks_query = artworks_query.filter(
            (Artwork.name.ilike(f'%{search_query}%')) |
            (Artwork.description.ilike(f'%{search_query}%')) |
            (Artwork.sku.ilike(f'%{search_query}%'))
        )
    if selected_category_id:
        artworks_query = artworks_query.filter_by(category_id=selected_category_id)
    
    artworks = artworks_query.all()
    categories = Category.query.order_by(Category.name).all()

    return render_template('admin_artworks_view.html', 
                           artworks=artworks, 
                           categories=categories, 
                           search_query=search_query, 
                           selected_category_id=selected_category_id)

@csrf.exempt
@app.route('/admin/add_artwork', methods=['GET', 'POST']) # Your existing route path
@admin_required
def add_artwork():
    categories = Category.query.all()
    form_data = {} 

    if request.method == 'POST':
        try:
            sku = request.form['sku'].strip()
            name = request.form['name'].strip()
            
            category_id = request.form.get('category_id') 

            if not category_id:
                flash('Category is required.', 'danger')
                form_data = request.form.to_dict() 
                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                return render_template('admin_add_artwork.html', form_data=form_data, categories=categories)
            
            category = Category.query.get(category_id)
            if not category:
                flash('Invalid category selected.', 'danger')
                form_data = request.form.to_dict()
                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                return render_template('admin_add_artwork.html', form_data=form_data, categories=categories)

            if Artwork.query.filter_by(sku=sku).first():
                flash('Artwork with this SKU already exists. Please use a unique SKU.', 'danger')
                form_data = request.form.to_dict()
                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)

            original_price = safe_decimal(request.form['original_price'])
            gst_percentage = safe_decimal(request.form.get('gst_percentage', str(DEFAULT_GST_PERCENTAGE)))
            stock = int(request.form['stock'])
            description = request.form.get('description', '').strip()
            is_featured = 'is_featured' in request.form

            custom_options_dict = {}
            group_indices = sorted(list(set([k.split('_')[3] for k in request.form if k.startswith('option_group_name_')])))

            for group_index in group_indices:
                group_name = request.form.get(f'option_group_name_{group_index}', '').strip()
                if group_name:
                    custom_options_dict[group_name] = {}
                    option_indices = sorted(list(set([k.split('_')[4] for k in request.form if k.startswith(f'option_label_{group_index}_')])))
                    for option_index in option_indices:
                        option_label = request.form.get(f'option_label_{group_index}_{option_index}', '').strip()
                        option_price = request.form.get(f'option_price_{group_index}_{option_index}')
                        if option_label and option_price is not None:
                            try:
                                custom_options_dict[group_name][option_label] = safe_decimal(option_price)
                            except InvalidOperation:
                                flash(f'Invalid price for option "{option_label}" in group "{group_name}".', 'danger')
                                form_data = request.form.to_dict()
                                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                                return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)
            custom_options_json = json.dumps(custom_options_dict) if custom_options_dict else None

            new_artwork = Artwork(
                sku=sku,
                name=name,
                category_id=category_id,
                original_price=original_price,
                gst_percentage=gst_percentage,
                stock=stock,
                description=description,
                is_featured=is_featured,
                custom_options=custom_options_json
            )

            uploaded_image_paths = []
            if 'images' in request.files:
                for file in request.files.getlist('images'):
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        unique_filename = str(uuid.uuid4()) + '_' + filename
                        file_path = os.path.join(app.root_path, app.config['PRODUCT_IMAGES_FOLDER'], unique_filename)
                        file.save(file_path)
                        uploaded_image_paths.append(os.path.join(os.path.basename(os.path.dirname(app.config['PRODUCT_IMAGES_FOLDER'])), os.path.basename(app.config['PRODUCT_IMAGES_FOLDER']), unique_filename))
            
            if not uploaded_image_paths: 
                uploaded_image_paths.append('images/placeholder.png')

            new_artwork.images = json.dumps(uploaded_image_paths)
            
            db.session.add(new_artwork)
            db.session.commit()

            flash(f'Artwork "{name}" added successfully!', 'success')
            return redirect(url_for('admin_artworks_view'))

        except (ValueError, InvalidOperation) as e:
            flash(f'Invalid input for numeric fields: {e}', 'danger')
            form_data = request.form.to_dict()
            form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
        except Exception as e:
            app.logger.error(f"Error adding artwork: {e}", exc_info=True)
            flash(f'An unexpected error occurred: {e}', 'danger')
        
    return render_template('admin_add_artwork.html', form_data=form_data, categories=categories)


@csrf.exempt
@app.route('/admin/edit_artwork/<sku>', methods=['GET', 'POST'])
@admin_required
def edit_artwork(sku):
    artwork = Artwork.query.filter_by(sku=sku).first_or_404()
    categories = Category.query.order_by(Category.name).all()

    if request.method == 'POST':
        try:
            artwork.name = request.form['name'].strip()
            category_id = request.form.get('category_id') 
            artwork.original_price = safe_decimal(request.form['original_price'])
            artwork.gst_percentage = safe_decimal(request.form.get('gst_percentage', str(DEFAULT_GST_PERCENTAGE)))
            artwork.stock = int(request.form['stock'])
            artwork.description = request.form.get('description', '').strip()
            artwork.is_featured = 'is_featured' in request.form

            if not category_id:
                flash('Category is required.', 'danger')
                form_data = {k: v for k, v in request.form.items()}
                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

            category = Category.query.get(category_id)
            if not category:
                flash('Invalid category selected.', 'danger')
                form_data = {k: v for k, v in request.form.items()}
                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)
            artwork.category_id = category_id

            custom_options_dict = {}
            group_indices = sorted(list(set([k.split('_')[3] for k in request.form if k.startswith('option_group_name_')])))

            for group_index in group_indices:
                group_name = request.form.get(f'option_group_name_{group_index}', '').strip()
                if group_name:
                    custom_options_dict[group_name] = {}
                    option_indices = sorted(list(set([k.split('_')[4] for k in request.form if k.startswith(f'option_label_{group_index}_')])))
                    for option_index in option_indices:
                        option_label = request.form.get(f'option_label_{group_index}_{option_index}', '').strip()
                        option_price = request.form.get(f'option_price_{group_index}_{option_index}')
                        if option_label and option_price is not None:
                            try:
                                custom_options_dict[group_name][option_label] = safe_decimal(option_price)
                            except InvalidOperation:
                                flash(f'Invalid price for option "{option_label}" in group "{group_name}".', 'danger')
                                form_data = {k: v for k, v in request.form.items()}
                                form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
                                return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)
            artwork.custom_options = json.dumps(custom_options_dict) if custom_options_dict else None

            images_to_keep = request.form.getlist('images_to_keep')
            new_uploaded_image_paths = []
            if 'new_images' in request.files:
                for file in request.files.getlist('new_images'):
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        unique_filename = str(uuid.uuid4()) + '_' + filename
                        file_path = os.path.join(app.root_path, app.config['PRODUCT_IMAGES_FOLDER'], unique_filename)
                        file.save(file_path)
                        new_uploaded_image_paths.append(os.path.join(os.path.basename(os.path.dirname(app.config['PRODUCT_IMAGES_FOLDER'])), os.path.basename(app.config['PRODUCT_IMAGES_FOLDER']), unique_filename))
            
            final_image_paths = images_to_keep + new_uploaded_image_paths
            if not final_image_paths:
                final_image_paths.append('images/placeholder.png') 

            artwork.images = json.dumps(final_image_paths)

            db.session.commit()
            flash(f'Artwork "{artwork.name}" updated successfully!', 'success')
            return redirect(url_for('admin_artworks_view'))

        except (ValueError, InvalidOperation) as e:
            flash(f'Invalid input for numeric fields: {e}', 'danger')
            form_data = {k: v for k, v in request.form.items()}
            form_data['custom_option_groups'] = parse_custom_options_from_form(request.form)
        except Exception as e:
            app.logger.error(f"Error editing artwork: {e}", exc_info=True)
            flash(f'An unexpected error occurred: {e}', 'danger')

    form_data = {
        'sku': artwork.sku,
        'name': artwork.name,
        'category_id': artwork.category_id,
        'original_price': artwork.original_price,
        'gst_percentage': artwork.gst_percentage,
        'stock': artwork.stock,
        'description': artwork.description,
        'is_featured': artwork.is_featured,
    }
    form_data['custom_option_groups'] = []
    artwork_custom_options = artwork.get_custom_options()
    for group_name, options in artwork_custom_options.items():
        option_list = []
        for label, price in options.items():
            option_list.append({'label': label, 'price': price})
        form_data['custom_option_groups'].append({'group_name': group_name, 'options': option_list})

    return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)


@csrf.exempt
@app.route('/admin/delete_artwork/<sku>', methods=['POST'])
@admin_required
def delete_artwork(sku):
    artwork = Artwork.query.filter_by(sku=sku).first()
    if not artwork:
        return jsonify(success=False, message='Artwork not found.'), 404
    
    if artwork.order_items:
        return jsonify(success=False, message=f'Cannot delete artwork "{artwork.name}" (SKU: {artwork.sku}) because it is part of existing orders. Please cancel/manage orders first.'), 400

    for image_path_relative in artwork.get_images_list():
        full_path = os.path.join(app.root_path, 'static', image_path_relative)
        if os.path.exists(full_path) and 'placeholder.png' not in image_path_relative: 
            try:
                os.remove(full_path)
            except OSError as e:
                app.logger.error(f"Error deleting image file {full_path}: {e}")

    db.session.delete(artwork)
    db.session.commit()
    return jsonify(success=True, message=f'Artwork "{artwork.name}" (SKU: {artwork.sku}) deleted successfully.')


@app.route('/admin/orders')
@admin_required
def admin_orders_view():
    search_query = request.args.get('search_query', '').strip()
    current_filter_status = request.args.get('status', '')
    current_filter_invoice_status = request.args.get('invoice_status', '')

    orders_query = Order.query.order_by(Order.order_date.desc())

    if search_query:
        orders_query = orders_query.filter(
            (Order.id.ilike(f'%{search_query}%')) |
            (Order.customer_name.ilike(f'%{search_query}%')) |
            (Order.customer_email.ilike(f'%{search_query}%'))
        )
    if current_filter_status:
        orders_query = orders_query.filter_by(status=current_filter_status)
    
    if current_filter_invoice_status:
        if current_filter_invoice_status == 'Held':
            orders_query = orders_query.filter(Order.invoice_details_json.like('%"is_held_by_admin": true%'))
        else:
            orders_query = orders_query.filter(Order.invoice_details_json.like(f'%\"invoice_status\": \"{current_filter_invoice_status}\"%'))


    orders = orders_query.all()
    return render_template('admin_orders_view.html', 
                           orders=orders, 
                           current_search_query=search_query, 
                           current_filter_status=current_filter_status,
                           current_filter_invoice_status=current_filter_invoice_status)


@csrf.exempt
@app.route('/admin/order/update_status/<order_id>', methods=['POST'])
@admin_required
def admin_update_order_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify(success=False, message=f'Order {order_id} not found.'), 404

    data = request.get_json()
    new_status = data.get('status', order.status)
    remark = data.get('remark', '').strip()
    courier = data.get('courier', '').strip()
    tracking_number = data.get('tracking_number', '').strip()
    cancellation_reason_admin = data.get('cancellation_reason', '').strip()

    if new_status == 'Cancelled by Admin':
        if order.status not in ["Cancelled by User", "Cancelled by Admin"]:
            order.cancellation_reason = cancellation_reason_admin if cancellation_reason_admin else 'Cancelled by admin.'
            order.cancellation_timestamp = datetime.utcnow()
            order.cancelled_by_admin_id = current_user.id 
            order.cancelled_by_user_id = None 

            for item in order.order_items:
                artwork = Artwork.query.get(item.artwork_id)
                if artwork:
                    artwork.stock += item.quantity
                    db.session.add(artwork)
    elif order.status in ["Cancelled by User", "Cancelled by Admin"] and new_status not in ["Cancelled by User", "Cancelled by Admin"]:
        order.cancellation_reason = None
        order.cancellation_timestamp = None
        order.cancelled_by_admin_id = None
        order.cancelled_by_user_id = None

    order.status = new_status
    order.remark = remark
    order.courier = courier
    order.tracking_number = tracking_number
    
    invoice_details = order.get_invoice_details()
    if new_status == 'Shipped' and invoice_details.get('invoice_status') in ['Not Applicable', None]:
        invoice_details['invoice_status'] = 'Prepared'
    order.invoice_details_json = json.dumps(invoice_details)

    db.session.add(order)
    db.session.commit()
    flash(f'Status for Order {order_id} updated to "{new_status}".', 'success')
    return jsonify(success=True, message=f'Status for Order {order_id} updated to "{new_status}".')

@app.route('/admin/order/delete/<order_id>', methods=['POST'])
@admin_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    # Restore stock for items in the order before deleting
    for item in order.order_items:
        artwork = Artwork.query.get(item.artwork_id)
        if artwork:
            artwork.stock += item.quantity
            db.session.add(artwork) # Mark artwork for update

    db.session.delete(order)
    db.session.commit()
    return jsonify(success=True, message=f'Order {order_id} and its items deleted successfully. Stock restored.')


@app.route('/admin/verify-payment', methods=['POST'])
@admin_required
def admin_verify_payment():
    order_id = request.form.get('order_id')
    order = Order.query.get(order_id)

    if not order:
        return jsonify(success=False, message='Order not found.'), 404

    if order.status == 'Payment Submitted - Awaiting Verification':
        order.status = 'Payment Verified – Preparing Order'
        order.remark = (order.remark or '') + '\nPayment verified by admin.'
        db.session.commit()
        flash(f'Payment for Order {order_id} verified. Status updated to "Payment Verified – Preparing Order".', 'success')
        return jsonify(success=True, message='Payment verified successfully.')
    else:
        flash(f'Order {order_id} is not in "Payment Submitted - Awaiting Verification" status.', 'danger')
        return jsonify(success=False, message='Order status not suitable for verification.'), 400

@app.route('/admin/edit_invoice/<order_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    invoice_details = order.get_invoice_details()

    # Set defaults if not present
    invoice_details.setdefault('invoice_number', f"INV-{order_id}-{datetime.now().strftime('%Y%m%d')}")
    invoice_details.setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d"))
    invoice_details.setdefault('billing_address', order.get_shipping_address().get('address_line1', ''))
    invoice_details.setdefault('gst_rate_applied', DEFAULT_INVOICE_GST_RATE)
    invoice_details.setdefault('business_name', OUR_BUSINESS_NAME)
    invoice_details.setdefault('gst_number', OUR_GSTIN)
    invoice_details.setdefault('pan_number', OUR_PAN)
    invoice_details.setdefault('business_address', OUR_BUSINESS_ADDRESS)
    invoice_details.setdefault('total_gst_amount', order.total_gst_amount)
    invoice_details.setdefault('cgst_amount', order.cgst_amount)
    invoice_details.setdefault('sgst_amount', order.sgst_amount)
    invoice_details.setdefault('shipping_charge', order.shipping_charge)
    invoice_details.setdefault('final_invoice_amount', order.total_amount)
    invoice_details.setdefault('invoice_status', 'Not Applicable' if order.status != 'Shipped' else 'Prepared')
    invoice_details.setdefault('is_held_by_admin', False)
    invoice_details.setdefault('invoice_pdf_path', None)
    invoice_details.setdefault('invoice_email_sent_on', None)


    if request.method == 'POST':
        try:
            invoice_details['business_name'] = request.form['business_name']
            invoice_details['gst_number'] = request.form['gst_number']
            invoice_details['pan_number'] = request.form['pan_number']
            invoice_details['business_address'] = request.form['business_address']

            invoice_details['invoice_number'] = request.form['invoice_number']
            invoice_details['invoice_date'] = datetime.fromisoformat(request.form['invoice_date']).strftime("%Y-%m-%d %H:%M:%S")
            invoice_details['billing_address'] = request.form['billing_address']

            gst_rate_applied = safe_decimal(request.form['gst_rate'])
            shipping_charge_form = safe_decimal(request.form['shipping_charge'])

            base_subtotal = order.subtotal_before_gst # Use order's original subtotal
            
            total_gst_amount_recalc = base_subtotal * (gst_rate_applied / Decimal('100'))
            cgst_amount_recalc = total_gst_amount_recalc / Decimal('2')
            sgst_amount_recalc = total_gst_amount_recalc / Decimal('2')
            final_invoice_amount_recalc = base_subtotal + total_gst_amount_recalc + shipping_charge_form

            invoice_details['gst_rate_applied'] = gst_rate_applied
            invoice_details['total_gst_amount'] = total_gst_amount_recalc
            invoice_details['cgst_amount'] = cgst_amount_recalc
            invoice_details['sgst_amount'] = sgst_amount_recalc
            invoice_details['shipping_charge'] = shipping_charge_form
            invoice_details['final_invoice_amount'] = final_invoice_amount_recalc
            
            if invoice_details.get('invoice_status') in ['Prepared', 'Sent']:
                invoice_details['invoice_status'] = 'Edited'
            if invoice_details.get('invoice_status') == 'Edited' and not invoice_details.get('is_held_by_admin'):
                invoice_details['is_held_by_admin'] = True

            order.invoice_details_json = json.dumps(invoice_details) 
            db.session.add(order)
            db.session.commit()
            flash(f'Invoice details for Order {order_id} updated successfully.', 'success')
            return redirect(url_for('admin_orders_view'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating invoice: {e}', 'danger')
            app.logger.error(f"Error in admin_edit_invoice: {e}", exc_info=True)

    return render_template('admin_edit_invoice.html', order=order, invoice_details=invoice_details)


@csrf.exempt
@app.route('/admin/invoice/hold/<order_id>', methods=['POST'])
@admin_required
def admin_hold_invoice(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify(success=False, message=f'Order {order_id} not found.'), 404
    
    invoice_details = order.get_invoice_details()
    invoice_details['is_held_by_admin'] = True
    invoice_details['invoice_status'] = 'Held'
    order.invoice_details_json = json.dumps(invoice_details)
    
    db.session.add(order)
    db.session.commit()
    flash(f'Invoice for Order {order_id} put on HOLD.', 'success')
    return jsonify(success=True, message=f'Invoice for Order {order_id} put on HOLD.')


@csrf.exempt
@app.route('/admin/invoice/release/<order_id>', methods=['POST'])
@admin_required
def admin_release_invoice(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify(success=False, message=f'Order {order_id} not found.'), 404
    
    invoice_details = order.get_invoice_details()
    invoice_details['is_held_by_admin'] = False
    invoice_details['invoice_status'] = 'Prepared' if order.status == 'Shipped' else 'Not Applicable'
    order.invoice_details_json = json.dumps(invoice_details)
    
    db.session.add(order)
    db.session.commit()
    flash(f'Invoice for Order {order_id} RELEASED.', 'success')
    return jsonify(success=True, message=f'Invoice for Order {order_id} RELEASED.')

@csrf.exempt
@app.route('/admin/invoice/send_email/<order_id>', methods=['POST'])
@admin_required
def admin_send_invoice_email(order_id):
    order = Order.query.get(order_id)

    if not order:
        return jsonify(success=False, message=f'Order {order_id} not found.'), 404
    
    invoice_details = order.get_invoice_details()
    if invoice_details.get('is_held_by_admin'):
        return jsonify(success=False, message=f'Invoice for Order {order_id} is on HOLD by admin. Release it first.'), 400

    # 1. Generate PDF
    invoice_pdf_path_relative = generate_invoice_pdf(order_id, order)
    if not invoice_pdf_path_relative:
        return jsonify(success=False, message="Failed to generate invoice PDF."), 500
    
    invoice_details['invoice_pdf_path'] = invoice_pdf_path_relative
    order.invoice_details_json = json.dumps(invoice_details) 

    db.session.add(order)
    db.session.commit()

    # 2. Send email
    recipient_email = order.customer_email
    customer_name = order.customer_name
    subject = f"Your Karthika Futures Invoice - Order {order_id}"
    body = f"""Dear {customer_name},

Please find your invoice for Order {order_id} attached.

Thank you for your purchase from Karthika Futures! We appreciate your business.

Order Details:
Order ID: {order_id}
Total Amount: ₹{order.total_amount:.2f}
Status: {order.status}
Placed On: {order.order_date.strftime("%Y-%m-%d %H:%M:%S")}

If you have any questions, please reply to this email or contact our support team.

Best Regards,
The Karthika Futures Team
{OUR_BUSINESS_EMAIL}
{OUR_BUSINESS_ADDRESS}
"""
    full_invoice_path = os.path.join(app.root_path, 'static', invoice_pdf_path_relative)
    attachment_filename_for_email = f"invoice_{order_id}.pdf" 

    success, message = send_email_with_attachment(recipient_email, subject, body, 
                                                  attachment_path=full_invoice_path,
                                                  attachment_filename=attachment_filename_for_email)

    if success:
        invoice_details['invoice_status'] = 'Sent'
        invoice_details['invoice_email_sent_on'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        order.invoice_details_json = json.dumps(invoice_details)
        db.session.add(order)
        db.session.commit()
        flash(f'Invoice email for Order {order_id} sent successfully to {recipient_email}.', 'success')
        return jsonify(success=True, message=f'Invoice email for Order {order_id} sent successfully.')
    else:
        invoice_details['invoice_status'] = 'Email Failed'
        order.invoice_details_json = json.dumps(invoice_details)
        db.session.add(order)
        db.session.commit()
        flash(f'Failed to send invoice email for Order {order_id}. Error: {message}', 'danger')
        return jsonify(success=False, message=f'Failed to send invoice email for Order {order_id}. Error: {message}'), 500

@csrf.exempt
@app.route('/admin/download_invoice/<order_id>')
@admin_required
def admin_download_invoice(order_id): # Renamed to avoid conflict with user's download_invoice
    order = Order.query.get(order_id)

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders_view'))

    invoice_path_relative = order.get_invoice_details().get('invoice_pdf_path')
    if invoice_path_relative and invoice_path_relative.startswith('uploads/invoices/'):
        full_path = os.path.join(app.root_path, 'static', invoice_path_relative)
        mimetype = 'application/pdf' if invoice_path_relative.lower().endswith('.pdf') else 'text/plain'
        download_name = f"invoice_{order_id}.pdf" # Always suggest PDF name

        if os.path.exists(full_path):
            return send_file(full_path, as_attachment=True, download_name=download_name, mimetype=mimetype)
    
    flash(f'Invoice not found or path invalid for Order {order_id}. Please generate it first from the admin invoice edit page.', 'warning')
    return redirect(url_for('admin_edit_invoice', order_id=order_id))


@csrf.exempt
@app.route('/admin/export_orders_csv')
@admin_required
def export_orders_csv():
    orders = Order.query.all()

    fieldnames = [
        'Order ID', 'User ID', 'User Email', 'Customer Name', 'Customer Phone',
        'Shipping Address', 'Shipping Pincode', 'Order Date', 'Status', 'Remark',
        'Courier', 'Tracking Number',
        'Subtotal Before GST', 'Total GST Amount', 'CGST Amount', 'SGST Amount',
        'Shipping Charge', 'Total Amount', 'Transaction ID', 'Payment Submitted On',
        'Invoice Status', 'Invoice Held by Admin', 'Invoice PDF Path', 'Invoice Email Sent On',
        'Cancellation Reason', 'Cancellation Timestamp', 'Cancelled By User ID', 'Cancelled By Admin ID' 
    ]
    
    max_items = max((len(o.order_items) for o in orders), default=0)
    for i in range(1, max_items + 1):
        fieldnames.extend([
            f'Item {i} SKU', f'Item {i} Name', f'Item {i} Quantity',
            f'Item {i} Unit Price Before Options', f'Item {i} Unit Price Before GST',
            f'Item {i} GST Percentage', f'Item {i} GST Amount',
            f'Item {i} Total Price Before GST', f'Item {i} Total Price',
            f'Item {i} Selected Options'
        ])

    si = io.StringIO()
    cw = csv.DictWriter(si, fieldnames=fieldnames)
    cw.writeheader()

    for order in orders:
        row = {
            'Order ID': order.id,
            'User ID': order.user_id,
            'User Email': order.customer_email,
            'Customer Name': order.customer_name,
            'Customer Phone': order.customer_phone,
            'Shipping Address': order.shipping_address_json,
            'Shipping Pincode': order.shipping_pincode,
            'Order Date': order.order_date.strftime("%Y-%m-%d %H:%M:%S") if order.order_date else '',
            'Status': order.status,
            'Remark': order.remark,
            'Courier': order.courier,
            'Tracking Number': order.tracking_number,
            'Subtotal Before GST': f"{order.subtotal_before_gst:.2f}",
            'Total GST Amount': f"{order.total_gst_amount:.2f}",
            'CGST Amount': f"{order.cgst_amount:.2f}",
            'SGST Amount': f"{order.sgst_amount:.2f}",
            'Shipping Charge': f"{order.shipping_charge:.2f}",
            'Total Amount': f"{order.total_amount:.2f}",
            'Transaction ID': order.transaction_id or '',
            'Payment Submitted On': order.payment_submitted_on.strftime("%Y-%m-%d %H:%M:%S") if order.payment_submitted_on else '',
            'Invoice Status': order.get_invoice_details().get('invoice_status', 'N/A'),
            'Invoice Held by Admin': 'Yes' if order.get_invoice_details().get('is_held_by_admin', False) else 'No',
            'Invoice PDF Path': order.get_invoice_details().get('invoice_pdf_path', ''),
            'Invoice Email Sent On': order.get_invoice_details().get('invoice_email_sent_on', '') or '',
            'Cancellation Reason': order.cancellation_reason or '', 
            'Cancellation Timestamp': order.cancellation_timestamp.strftime("%Y-%m-%d %H:%M:%S") if order.cancellation_timestamp else '', 
            'Cancelled By User ID': order.cancelled_by_user_id or '', 
            'Cancelled By Admin ID': order.cancelled_by_admin_id or '' 
        }

        for i, item in enumerate(order.order_items):
            row[f'Item {i+1} SKU'] = item.sku
            row[f'Item {i+1} Name'] = item.name
            row[f'Item {i+1} Quantity'] = item.quantity
            row[f'Item {i+1} Unit Price Before Options'] = f"{item.unit_price_before_options:.2f}"
            row[f'Item {i+1} Unit Price Before GST'] = f"{item.unit_price_before_gst:.2f}"
            row[f'Item {i+1} GST Percentage'] = f"{item.gst_percentage:.2f}"
            row[f'Item {i+1} GST Amount'] = f"{item.gst_amount:.2f}"
            row[f'Item {i+1} Total Price Before GST'] = f"{item.total_price_before_gst:.2f}"
            row[f'Item {i+1} Total Price'] = f"{item.total_price:.2f}"
            row[f'Item {i+1} Selected Options'] = item.selected_options_json or '{}'
        
        cw.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=orders_export.csv"
    output.headers["Content-type"] = "text/csv"
    return output


@csrf.exempt
@app.route('/admin/export_artworks_csv')
@admin_required
def export_artworks_csv():
    artworks = Artwork.query.all()

    fieldnames = [
        'SKU', 'Name', 'Category', 'Original Price', 'Stock', 'Description',
        'GST Percentage', 'Image Paths', 'Is Featured', 
        'Custom Options' 
    ]

    si = io.StringIO()
    cw = csv.DictWriter(si, fieldnames=fieldnames)
    cw.writeheader()

    for artwork in artworks:
        custom_options_str = artwork.custom_options or '{}'

        row = {
            'SKU': artwork.sku,
            'Name': artwork.name,
            'Category': artwork.category.name if artwork.category else 'N/A', 
            'Original Price': f"{artwork.original_price:.2f}",
            'Stock': artwork.stock,
            'Description': artwork.description,
            'GST Percentage': f"{artwork.gst_percentage:.2f}",
            'Image Paths': '; '.join(artwork.get_images_list()),
            'Is Featured': 'Yes' if artwork.is_featured else 'No',
            'Custom Options': custom_options_str 
        }
        cw.writerow(row)

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=artworks_export.csv"
    output.headers["Content-type"] = "text/csv"
    return output


# --- User Authentication Routes (OTP and Password based) ---

# This route handles both password-based and OTP-based login
@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

    if current_user.is_authenticated:
        if current_user.is_admin():
            return redirect(url_for('admin_dashboard'))
        return redirect(next_url)

    if request.method == 'POST':
        identifier = request.form['identifier'].strip().lower() # Can be email or phone
        password = request.form.get('password', '').strip() # Optional for OTP login

        user = User.find_by_email_or_phone(identifier)

        if not user:
            flash("No user found with that email or phone number. Please sign up.", "danger")
            return render_template('user_login.html', next_url=next_url, prefill_identifier=identifier)

        # If password is provided, attempt password login
        if password:
            if user.check_password(password):
                login_user(user)
                user.last_login_at = datetime.utcnow()
                db.session.add(user)
                db.session.commit()
                flash("Logged in successfully!", "success")
                return redirect(next_url)
            else:
                flash("Invalid password. If you registered with OTP, please use OTP login.", "danger")
                return render_template('user_login.html', next_url=next_url, prefill_identifier=identifier)
        else: # No password provided, proceed with OTP logic
            otp = generate_otp()
            expiry = datetime.utcnow() + timedelta(minutes=5) # OTP valid for 5 minutes
            
            # Store data for OTP verification
            otp_storage[identifier] = {
                'otp': otp,
                'expiry': expiry,
                'user_id': user.id # Store user ID for direct lookup after verification
            }
            session['identifier_for_otp_verification'] = identifier # Store identifier in session
            session.modified = True

            subject = "Karthika Futures - Your OTP for Login"
            body = f"Hi {user.name},\n\nYour One-Time Password (OTP) for Karthika Futures login is: {otp}\n\nThis OTP is valid for 5 minutes.\n\nThank you,\nKarthika Futures Team"
            
            email_sent_success, email_message = send_email_with_attachment(user.email, subject, body)

            if email_sent_success:
                flash("OTP sent to your registered email for login. Please check your inbox.", "info")
                return redirect(url_for('verify_otp', next=next_url))
            else:
                app.logger.error(f"Failed to send OTP email for login to {user.email}: {email_message}")
                flash(f'Failed to send OTP. Please check your email configuration and try again: {email_message}', 'danger')
                return render_template('user_login.html', next_url=next_url, prefill_identifier=identifier)

    prefill_identifier = request.args.get('identifier', '')
    return render_template("user_login.html", next_url=next_url, prefill_identifier=prefill_identifier)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password'].strip()
        confirm_password = request.form['confirm_password'].strip()
        phone = request.form['phone'].strip()
        address_line1 = request.form['address_line1'].strip()
        address_line2 = request.form.get('address_line2', '').strip()
        city = request.form['city'].strip()
        state = request.form['state'].strip()
        pincode = request.form['pincode'].strip()

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html', form_data=request.form)

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login or use a different email.', 'danger')
            return render_template('signup.html', form_data=request.form)
        if User.query.filter_by(phone=phone).first():
            flash('Phone number already registered. Please login or use a different phone number.', 'danger')
            return render_template('signup.html', form_data=request.form)

        # Store user data for later creation after OTP verification
        otp = generate_otp()
        otp_expiry = datetime.utcnow() + timedelta(minutes=5)
        otp_storage[email] = {
            'otp': otp,
            'expiry': otp_expiry,
            'user_data': {
                'email': email,
                'password_hash': generate_password_hash(password),
                'name': name,
                'phone': phone,
                'address_line1': address_line1,
                'address_line2': address_line2,
                'city': city,
                'state': state,
                'pincode': pincode,
                'role': 'user'
            }
        }
        session['identifier_for_otp_verification'] = email # Use email as identifier for signup OTP

        try:
            subject = "Karthika Futures - Your OTP for Registration"
            body = f"Hi {name},\n\nYour One-Time Password (OTP) for Karthika Futures registration is: {otp}\n\nThis OTP is valid for 5 minutes.\n\nThank you,\nKarthika Futures Team"
            
            email_sent_success, email_message = send_email_with_attachment(email, subject, body)

            if email_sent_success:
                flash(f"An OTP has been sent to {email}. Please verify to complete registration.", 'info')
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


@csrf.exempt
@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    identifier_for_otp_verification = session.get('identifier_for_otp_verification')
    next_url = request.args.get('next')

    if not identifier_for_otp_verification or identifier_for_otp_verification not in otp_storage:
        flash("No pending OTP verification. Please try logging in or signing up again.", "danger")
        return redirect(url_for('user_login', next=next_url))

    if request.method == 'POST':
        user_otp = request.form['otp'].strip()
        stored_data = otp_storage.get(identifier_for_otp_verification)

        if stored_data and stored_data['otp'] == user_otp and datetime.utcnow() < stored_data['expiry']:
            # OTP is valid
            
            # Check if it's a new user registration or an existing user login
            if 'user_data' in stored_data: # This is a new user registration flow
                new_user_data_for_db = stored_data['user_data']
                user = User(
                    email=new_user_data_for_db['email'],
                    password_hash=new_user_data_for_db['password_hash'],
                    name=new_user_data_for_db['name'],
                    phone=new_user_data_for_db['phone'],
                    role=new_user_data_for_db['role'],
                    created_at=datetime.utcnow(),
                    last_login_at=datetime.utcnow()
                )
                db.session.add(user)
                db.session.flush() # Get user.id before committing for address

                initial_address = Address(
                    user_id=user.id,
                    label="Primary",
                    full_name=new_user_data_for_db['name'],
                    phone=new_user_data_for_db['phone'],
                    address_line1=new_user_data_for_db['address_line1'],
                    address_line2=new_user_data_for_db['address_line2'],
                    city=new_user_data_for_db['city'],
                    state=new_user_data_for_db['state'],
                    pincode=new_user_data_for_db['pincode'],
                    is_default=True
                )
                db.session.add(initial_address)
                db.session.commit()
                flash("Account created and logged in successfully!", "success")
            elif 'user_id' in stored_data: # This is an existing user login flow
                user = User.query.get(stored_data['user_id'])
                if user:
                    user.last_login_at = datetime.utcnow()
                    db.session.add(user)
                    db.session.commit()
                    flash("Logged in successfully via OTP!", "success")
                else:
                    flash("User not found for OTP verification. Please try again.", "danger")
                    return redirect(url_for('user_login', next=next_url))
            else:
                flash("Invalid OTP state. Please try logging in or signing up again.", "danger")
                return redirect(url_for('user_login', next=next_url))

            otp_storage.pop(identifier_for_otp_verification, None)
            session.pop('identifier_for_otp_verification', None)

            # Clear session and re-login to ensure clean state
            # Preserve cart if it was there before login/signup
            temp_cart = session.pop('cart', {})
            temp_direct_purchase_item = session.pop('direct_purchase_item', None)
            session.clear()
            session.permanent = True # Keep session permanent if desired
            session['cart'] = temp_cart
            if temp_direct_purchase_item:
                session['direct_purchase_item'] = temp_direct_purchase_item
            session.modified = True

            login_user(user) # Log in the user

            return redirect(next_url or url_for('index'))
        else:
            flash("Invalid or expired OTP. Please try again.", "danger")

    return render_template('verify_otp.html', identifier=identifier_for_otp_verification, next_url=next_url)


<<<<<<< HEAD
@app.route('/user-login', methods=['GET', 'POST'])  # Corrected route name
def user_login():
    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

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

            # ✅ Backup cart before login
            saved_cart = session.get('cart', {})
            if not isinstance(saved_cart, dict):
                saved_cart = {}

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

            session.permanent = False  # Non-permanent session

            # ✅ Restore cart after login
            session['cart'] = saved_cart

            # 🔁 Restore Buy Now session if present (JS must send this to backend)
            # 🔁 Restore Buy Now session if present
            if 'direct_purchase_item' in session:
                next_url = url_for('purchase_form')

        
            flash("Logged in successfully!", "success")
            return redirect(next_url)
        else:
            # === CASE B: No password → Send OTP ===
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

    # Prefill email if available
    prefill_email = request.args.get('email', '')
    return render_template("user_login.html", next_url=next_url, prefill_email=prefill_email)


@app.route('/set_direct_purchase_item', methods=['POST'])
@csrf.exempt
def set_direct_purchase_item():
    try:
        raw_item = request.get_json()
        enriched = enrich_direct_purchase_item(raw_item)
        if not enriched:
            return jsonify(success=False, message="Invalid artwork or options."), 400
        session['direct_purchase_item'] = enriched
        session.modified = True
        return jsonify(success=True, redirect_url='/purchase-form')
    except Exception as e:
        app.logger.error(f"Error in /set_direct_purchase_item: {e}", exc_info=True)
        return jsonify(success=False, message="Error saving Buy Now item."), 500



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

import uuid

@app.route('/my-addresses')
@login_required
def my_addresses():
    user_email = current_user.email
    users = load_users_data()
    user = next((u for u in users if u["email"] == user_email), None)
    address_list = user.get('addresses', []) if user else []
    return render_template("my_addresses.html", addresses=address_list)

@app.route('/add-address', methods=['GET', 'POST'])
@login_required
def add_address():
    if request.method == 'POST':
        data = request.form
        new_address = {
            "id": str(uuid.uuid4())[:8],
            "label": data.get('label'),
            "full_name": data.get('full_name'),
            "phone": data.get('phone'),
            "address": data.get('address'),
            "pincode": data.get('pincode')
        }
        users = load_users_data()
        for u in users:
            if u['email'] == current_user.email:
                if 'addresses' not in u:
                    u['addresses'] = []
                u['addresses'].append(new_address)
                break
        save_json('users.json', users)
        flash("✅ Address added successfully!", "success")
        return redirect(url_for('my_addresses'))

    return render_template("add_address.html")

@app.route('/delete-address/<addr_id>', methods=['POST'])
@login_required
def delete_address(addr_id):
    users = load_users_data()
    for u in users:
        if u['email'] == current_user.email:
            u['addresses'] = [a for a in u.get('addresses', []) if a['id'] != addr_id]
            break
    save_json('users.json', users)
    flash("🗑️ Address deleted.", "info")
    return redirect(url_for('my_addresses'))


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

=======
>>>>>>> a3989ae (SQL v2)
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            # In a real app, generate a secure, time-limited token and store it in DB
            # For this example, we'll simulate sending a reset link (no actual token storage)
            reset_token = str(uuid.uuid4()) # Dummy token
            
            reset_link = url_for('reset_password', token=reset_token, _external=True)
            subject = "Karthika Futures - Password Reset Request"
            body = f"Hi {user.name},\n\nYou have requested a password reset for your Karthika Futures account.\n\nClick on the following link to reset your password:\n{reset_link}\n\nThis link will expire in [e.g., 1 hour]. If you did not request this, please ignore this email.\n\nThank you,\nThe Karthika Futures Team"
            
            email_sent_success, email_message = send_email_with_attachment(user.email, subject, body)
            
            if email_sent_success:
                flash('If an account with that email exists, a password reset link has been sent.', 'info')
            else:
                app.logger.error(f"Failed to send password reset email to {user.email}: {email_message}")
                flash('An error occurred while sending the password reset email. Please try again.', 'danger')
        else:
            flash('If an account with that email exists, a password reset link has been sent.', 'info') 
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # This is a placeholder. In a real application:
    # 1. Look up the token in your database (e.g., PasswordResetTokens.query.filter_by(token=token, used=False, expiry > now).first()).
    # 2. If valid, allow the user to set a new password for the associated user.
    # 3. Invalidate the token (set used=True).
    # 4. If not valid/expired, flash error.
    flash('Password reset functionality is under development. This is a placeholder link.', 'warning')
    return redirect(url_for('user_login'))

@app.route('/user_dashboard')
@login_required
def user_dashboard():
    return render_template('user_dashboard.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/notify_me', methods=['POST'])
def notify_me():
    email = request.form.get('email')
    sku = request.form.get('sku')
    
    if not email or not sku:
        return jsonify(success=False, message="Email and SKU are required."), 400

    artwork = Artwork.query.filter_by(sku=sku).first()
    if not artwork:
        return jsonify(success=False, message="Artwork not found."), 404

    # Check if this notification already exists to prevent duplicates
    # Check for both active and inactive notifications to avoid re-adding
    existing_notification = StockNotification.query.filter_by(email=email, artwork_id=artwork.id).first()
    if existing_notification:
        if existing_notification.is_active:
            return jsonify(success=True, message="You are already subscribed for notifications for this item."), 200
        else: # If inactive, reactivate it
            existing_notification.is_active = True
            existing_notification.notified_at = None # Reset notified_at
            existing_notification.requested_at = datetime.utcnow() # Update request time
            db.session.commit()
            return jsonify(success=True, message="Your notification request has been reactivated!"), 200

    new_notification = StockNotification(
        email=email,
        artwork_id=artwork.id,
        requested_at=datetime.utcnow(),
        user_id=current_user.id if current_user.is_authenticated else None # Link to user if logged in
    )
    db.session.add(new_notification)
    db.session.commit()
    
    return jsonify(success=True, message="You will be notified when the item is back in stock!"), 200

# --- ONE-TIME DATA MIGRATION AND ADMIN USER CREATION ---
def initialize_database_and_migrate_data():
    with app.app_context():
        db.create_all() # Create all tables if they don't exist

        # --- Migrate Categories ---
        if Category.query.count() == 0 and os.path.exists('data/categories.json'):
            print("Migrating categories from JSON to DB...")
            try:
                with open('data/categories.json', 'r') as f:
                    old_categories = json.load(f)
                for cat_data in old_categories:
                    new_category = Category(
                        id=cat_data.get('id', str(uuid.uuid4())),
                        name=cat_data['name'],
                        description=cat_data.get('description', ''),
                        image_path=cat_data.get('image', '')
                    )
                    db.session.add(new_category)
                db.session.commit()
                print(f"Migrated {len(old_categories)} categories.")
            except Exception as e:
                db.session.rollback()
                print(f"Error migrating categories: {e}")

        # --- Migrate Artworks ---
        if Artwork.query.count() == 0 and os.path.exists('data/artworks.json'):
            print("Migrating artworks from JSON to DB...")
            try:
                with open('data/artworks.json', 'r') as f:
                    old_artworks = json.load(f)
                for art_data in old_artworks:
                    category = Category.query.filter_by(name=art_data.get('category')).first()
                    category_id = category.id if category else None
                    
                    if not category_id:
                        print(f"Warning: Artwork '{art_data.get('name')}' has unknown category '{art_data.get('category')}', skipping.")
                        continue

                    new_artwork = Artwork(
                        id=art_data.get('id', str(uuid.uuid4())),
                        sku=art_data['sku'],
                        name=art_data['name'],
                        category_id=category_id,
                        original_price=safe_decimal(art_data.get('original_price')),
                        stock=int(art_data.get('stock', 0)),
                        description=art_data.get('description', ''),
                        gst_percentage=safe_decimal(art_data.get('gst_percentage', DEFAULT_GST_PERCENTAGE)),
                        is_featured=art_data.get('is_featured', False),
                        images=json.dumps(art_data.get('images', [])),
                        custom_options=json.dumps(art_data.get('custom_options', {}))
                    )
                    db.session.add(new_artwork)
                db.session.commit()
                print(f"Migrated {len(old_artworks)} artworks.")
            except Exception as e:
                db.session.rollback()
                print(f"Error migrating artworks: {e}")

        # --- Migrate Users and their Addresses ---
        if User.query.count() == 0 and os.path.exists('data/users.json'):
            print("Migrating users and addresses from JSON to DB...")
            try:
                with open('data/users.json', 'r') as f:
                    old_users = json.load(f)
                for user_data in old_users:
                    new_user = User(
                        id=user_data.get('id', str(uuid.uuid4())),
                        email=user_data['email'],
                        password_hash=user_data['password'], 
                        name=user_data.get('name', ''),
                        phone=user_data.get('phone', ''),
                        role=user_data.get('role', 'user'),
                        created_at=datetime.utcnow(), 
                        last_login_at=datetime.utcnow() 
                    )
                    db.session.add(new_user)
                    db.session.flush() 

                    if user_data.get('address') and user_data.get('pincode'):
                        new_address = Address(
                            user_id=new_user.id,
                            label="Primary (Migrated)",
                            full_name=user_data.get('name', ''),
                            phone=user_data.get('phone', ''),
                            address_line1=user_data['address'],
                            address_line2="",
                            city="Unknown", 
                            state="Unknown", 
                            pincode=user_data['pincode'],
                            is_default=True
                        )
                        db.session.add(new_address)
                    
                    for addr_data in user_data.get('addresses', []):
                        if addr_data.get('address') == user_data.get('address') and addr_data.get('pincode') == user_data.get('pincode'):
                            continue 
                        
                        new_additional_address = Address(
                            user_id=new_user.id,
                            id=addr_data.get('id', str(uuid.uuid4())),
                            label=addr_data.get('label', 'Migrated Address'),
                            full_name=addr_data.get('full_name', user_data.get('name', '')),
                            phone=addr_data.get('phone', user_data.get('phone', '')),
                            address_line1=addr_data.get('address', ''),
                            address_line2=addr_data.get('address_line2', ''), 
                            city=addr_data.get('city', 'Unknown'),
                            state=addr_data.get('state', 'Unknown'),
                            pincode=addr_data.get('pincode', ''),
                            is_default=addr_data.get('is_default', False)
                        )
                        db.session.add(new_additional_address)

                db.session.commit()
                print(f"Migrated {len(old_users)} users and their addresses.")
            except Exception as e:
                db.session.rollback()
                print(f"Error migrating users and addresses: {e}")

        # --- Migrate Orders and OrderItems ---
        if Order.query.count() == 0 and os.path.exists('data/orders.json'):
            print("Migrating orders and order items from JSON to DB...")
            try:
                with open('data/orders.json', 'r') as f:
                    old_orders = json.load(f)
                for order_data in old_orders:
                    user = User.query.get(order_data.get('user_id'))
                    if not user:
                        print(f"Warning: Order {order_data.get('order_id')} has unknown user_id {order_data.get('user_id')}, skipping.")
                        continue
                    
                    order_date_obj = datetime.strptime(order_data['placed_on'], "%Y-%m-%d %H:%M:%S") if 'placed_on' in order_data else datetime.utcnow()
                    
                    payment_submitted_on_obj = None
                    if order_data.get('payment_submitted_on'):
                        try:
                            payment_submitted_on_obj = datetime.strptime(order_data['payment_submitted_on'], "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pass 

                    new_order = Order(
                        id=order_data.get('order_id', str(uuid.uuid4())),
                        user_id=user.id,
                        order_date=order_date_obj,
                        customer_name=order_data.get('customer_name', ''),
                        customer_email=order_data.get('user_email', ''),
                        customer_phone=order_data.get('customer_phone', ''),
                        shipping_address_json=json.dumps({
                            'label': 'Migrated',
                            'full_name': order_data.get('customer_name', ''),
                            'phone': order_data.get('customer_phone', ''),
                            'address_line1': order_data.get('customer_address', ''),
                            'address_line2': '',
                            'city': 'Unknown',
                            'state': 'Unknown',
                            'pincode': order_data.get('customer_pincode', '')
                        }),
                        shipping_pincode=order_data.get('customer_pincode', ''),
                        subtotal_before_gst=safe_decimal(order_data.get('subtotal_before_gst')),
                        total_gst_amount=safe_decimal(order_data.get('total_gst_amount')),
                        cgst_amount=safe_decimal(order_data.get('cgst_amount')),
                        sgst_amount=safe_decimal(order_data.get('sgst_amount')),
                        shipping_charge=safe_decimal(order_data.get('shipping_charge')),
                        total_amount=safe_decimal(order_data.get('total_amount')),
                        status=order_data.get('status', 'Pending Payment'),
                        transaction_id=order_data.get('transaction_id', ''),
                        payment_screenshot_path=order_data.get('payment_screenshot_path', ''),
                        payment_submitted_on=payment_submitted_on_obj,
                        remark=order_data.get('remark', ''),
                        courier=order_data.get('courier', ''),
                        tracking_number=order_data.get('tracking_number', ''),
                        invoice_details_json=json.dumps(order_data.get('invoice_details', {}))
                    )
                    db.session.add(new_order)
                    db.session.flush() 

                    for item_data in order_data.get('items', []):
                        artwork = Artwork.query.filter_by(sku=item_data.get('sku')).first()
                        if not artwork:
                            print(f"Warning: Order {order_data.get('order_id')} item {item_data.get('sku')} not found in artworks, skipping.")
                            continue

                        migrated_options = {
                            k: v for k, v in item_data.items()
                            if k not in [
                                'id', 'sku', 'name', 'image', 'category', 'quantity',
                                'unit_price_before_gst', 'total_price_before_gst', 'gst_percentage',
                                'gst_amount', 'total_price', 'stock_available', 'unit_price_before_options',
                                'size', 'frame', 'glass' 
                            ]
                        }

                        new_order_item = OrderItem(
                            order_id=new_order.id,
                            artwork_id=artwork.id,
                            sku=item_data.get('sku', ''),
                            name=item_data.get('name', ''),
                            image_path=item_data.get('image', ''),
                            quantity=int(item_data.get('quantity', 0)),
                            unit_price_before_options=safe_decimal(item_data.get('unit_price_before_options', item_data.get('original_price', '0.00'))), 
                            unit_price_before_gst=safe_decimal(item_data.get('unit_price_before_gst')),
                            gst_percentage=safe_decimal(item_data.get('gst_percentage')),
                            gst_amount=safe_decimal(item_data.get('gst_amount')),
                            total_price_before_gst=safe_decimal(item_data.get('total_price_before_gst')),
                            total_price=safe_decimal(item_data.get('total_price')),
                            selected_options_json=json.dumps(migrated_options) 
                        )
                        db.session.add(new_order_item)
                db.session.commit()
                print(f"Migrated {len(old_orders)} orders and their items.")
            except Exception as e:
                db.session.rollback()
                print(f"Error migrating orders: {e}")

        # --- Create Default Admin User (if no admin exists) ---
        if not User.query.filter_by(role='admin').first():
            default_admin_email = 'admin@karthikafutures.com'
            default_admin_password = 'admin_password_123'
            
            existing_user = User.query.filter_by(email=default_admin_email).first()
            if not existing_user:
                print(f"Creating default admin user: {default_admin_email}")
                new_admin = User(
                    email=default_admin_email,
                    password_hash=generate_password_hash(default_admin_password),
                    name='Default Admin',
                    phone='9999999999',
                    role='admin',
                    created_at=datetime.utcnow(),
                    last_login_at=datetime.utcnow()
                )
                db.session.add(new_admin)
                db.session.flush() 
                
                initial_admin_address = Address(
                    user_id=new_admin.id,
                    label="Admin Office",
                    full_name="Karthika Futures Admin",
                    phone="9999999999",
                    address_line1="Admin Office, 123 Main St",
                    address_line2="",
                    city="Spiritual City",
                    state="Karnataka",
                    pincode="560001",
                    is_default=True
                )
                db.session.add(initial_admin_address)
                db.session.commit()
                print(f"Default admin '{default_admin_email}' created.")
                print(f"\n--- IMPORTANT: DEFAULT ADMIN CREATED ---")
                print(f"Email: {default_admin_email}")
                print(f"Password: {default_admin_password}")
                print(f"Login at: http://127.0.0.1:5000/admin_login")
                print(f"----------------------------------------\n")
            else:
                print(f"\n--- WARNING: Account '{default_admin_email}' exists but is not admin. ---")
                print(f"Please manually change role to 'admin' for user {default_admin_email} in the database if needed.")
                print(f"------------------------------------------------------------------\n")
        else:
<<<<<<< HEAD
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







# -------------------- FIXED CART SESSION ROUTES --------------------
@csrf.exempt  # 💥 disables CSRF for this route
@app.route('/update_cart_item_quantity', methods=['POST'])
def update_cart_item_quantity():
    data = request.get_json()
    if not data or 'item_id' not in data or 'quantity' not in data:
        return jsonify({'error': 'Missing item_id or quantity'}), 400

    cart = session.get('cart', {})
    item_id = data['item_id']
    quantity = int(data['quantity'])

    if item_id in cart:
        cart[item_id]['quantity'] = quantity

        # Recalculate totals
        unit_price = Decimal(str(cart[item_id]['unit_price_before_gst']))
        gst_percent = Decimal(str(cart[item_id]['gst_percentage'])) / 100
        cart[item_id]['total_price_before_gst'] = float(unit_price * quantity)
        cart[item_id]['gst_amount'] = float((unit_price * quantity) * gst_percent)
        cart[item_id]['total_price'] = cart[item_id]['total_price_before_gst'] + cart[item_id]['gst_amount']

        session['cart'] = cart
        session.modified = True
        return jsonify({'message': 'Cart updated successfully'}), 200
    else:
        return jsonify({'error': 'Item not found in cart'}), 404

@app.route('/remove_from_cart', methods=['POST'])
# @csrf.exempt # Keep this if you're handling CSRF manually or disabling it for this route
def remove_from_cart():
    try:
        data = request.get_json()
        # ✅ FIX: Use 'id' from frontend, which is the unique cart item ID
        item_to_remove_id = data.get('id')

        cart = session.get('cart', {})

        if not isinstance(cart, dict):
            app.logger.warning(f"Cart was not dict: {type(cart)}. Resetting to empty.")
            cart = {}
            session['cart'] = cart
            session.modified = True
            return jsonify({"success": False, "message": "Cart was corrupted and reset."}), 400

        if item_to_remove_id in cart:
            del cart[item_to_remove_id]
            session['cart'] = cart
            session.modified = True

            # ✅ FIX: Recalculate and return the updated cart summary
            artworks_data = load_artworks_data() # Assuming this function is available
            updated_cart_summary = calculate_cart_totals(cart, artworks_data) # Assuming this function is available

            return jsonify({
                "success": True,
                "message": "Item removed from cart.",
                "id": item_to_remove_id, # Return ID for frontend to remove element
                "cart_summary": updated_cart_summary
            })
        else:
            # Return 404 if item not found, consistent with the error message
            return jsonify({"success": False, "message": "Item not found in cart."}), 404

    except Exception as e:
        app.logger.error(f"Error in remove_from_cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": "Server error while removing item."}), 500

# You also need to ensure your `update_cart_item_quantity` route
# (which isn't shown but is called from cart.html)
# also returns the full `cart_summary` in its successful response.
# It should look similar to the `remove_from_cart` success response:
# return jsonify({
#     "success": True,
#     "message": "Cart updated successfully.",
#     "updated_item": updated_item_details, # if applicable
#     "cart_summary": updated_cart_summary
# })


@app.route('/get_cart_count')
def get_cart_count():
    cart = session.get('cart', {})

    # Ensure cart is a dict. If not, reset it to empty dict.
    if not isinstance(cart, dict):
        current_app.logger.warning(f"Cart was not dict: {type(cart)}. Resetting to empty.")
        cart = {}
        session['cart'] = cart
        session.modified = True

    total_items_in_cart = sum(item.get('quantity', 0) for item in cart.values())

    return jsonify({
        'success': True,                  # ✅ add this line
        'cart_count': total_items_in_cart
    })

=======
            print("Admin user already exists. Skipping default admin creation.")
>>>>>>> a3989ae (SQL v2)


# --- Initialize DB and Migrate Data on First Run ---
with app.app_context():
    initialize_database_and_migrate_data()

if __name__ == '__main__':
    app.run(debug=True)

