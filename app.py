import os
from dotenv import load_dotenv
load_dotenv()
import cloudinary
import cloudinary.uploader

import json
import csv
import uuid
import requests
import socket

from datetime import datetime, timedelta # Ensure timedelta is imported here
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename # Added this import
from slugify import slugify

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
from markupsafe import Markup

# SQLAlchemy Imports
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey, func 
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError 

from flask_migrate import Migrate


# Email Sending
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# CSRF protection
from flask_wtf.csrf import CSRFProtect, generate_csrf

# PDF generation
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
    from reportlab.lib.units import inch
    from reportlab.lib.pagesizes import A4 # Changed to A4
    from reportlab.lib.colors import HexColor
    # NEW IMPORTS FOR FONT HANDLING
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError:
    print("ReportLab not installed. PDF generation features will be disabled.")
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    Table = None
    TableStyle = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    TA_RIGHT = None
    TA_CENTER = None
    TA_LEFT = None
    inch = None
    A4 = None
    HexColor = None
    pdfmetrics = None
    TTFont = None


app = Flask(__name__)

app.jinja_env.filters['slugify'] = slugify
# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key_that_should_be_in_env')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit for uploads
import socket

# Detect environment (localhost or production)
hostname = socket.gethostname()
flask_env = os.getenv("FLASK_ENV", "production")

# Use reCAPTCHA keys from environment variables (production only)
app.config['RECAPTCHA_SITE_KEY'] = os.getenv("RECAPTCHA_SITE_KEY")
app.config['RECAPTCHA_SECRET_KEY'] = os.getenv("RECAPTCHA_SECRET_KEY")

# Get DATABASE from environment, fall back to SQLite for local development
# This will now look for 'DATABASE' as set in your Render environment
uri = os.environ.get('DATABASE_URL')


# Render's PostgreSQL URL might use 'postgres://', but SQLAlchemy prefers 'postgresql://'
if uri and uri.startswith('postgres://'):
    uri = uri.replace('postgres://', 'postgresql://', 1)

# Use the 'uri' variable for SQLALCHEMY_DATABASE_URI
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    raise ValueError("DATABASE_URL environment variable is not set. Cannot connect to the database.")
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# Debug print to confirm correct DB URI is being used
print("Database URI in use:", app.config['SQLALCHEMY_DATABASE_URI'])
# In your Flask app setup (e.g., app.py or config.py)

# app.config['SQLALCHEMY_POOL_RECYCLE'] = 300  # Tell app to reconnect every hour
# app.config['SQLALCHEMY_POOL_PRE_PING'] = True # Tell app to 'hello, are you there?' before talking
# Add this line to handle database connection pooling for Render
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 299, # Set to slightly less than Render's default timeout (300s)
}

# Email Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER', 'smarasada@gmail.com') # REPLACE WITH YOUR EMAIL
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS', 'ujipgkporeybjtoy') # REPLACE WITH YOUR APP PASSWORD

cloudinary.config(
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key = os.getenv('CLOUDINARY_API_KEY'),
    api_secret = os.getenv('CLOUDINARY_API_SECRET')
)
# Business Details (for invoices, etc.)
app.config['OUR_BUSINESS_NAME'] = "Karthika Futures"
app.config['OUR_BUSINESS_ADDRESS'] = "Annapoorna Appartment, New Alipur, Kolkata - 53"
app.config['OUR_GSTIN'] = "29ABCDE1234F1Z5" # Example GSTIN
app.config['OUR_PAN'] = "ABCDE1234F" # Example PAN
app.config['DEFAULT_GST_RATE'] = Decimal('18.00') # Default GST rate for products
# app.config['DEFAULT_SHIPPING_CHARGE'] = Decimal('100.00') # This is now deprecated for per-artwork shipping
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


login_manager = LoginManager(app)
login_manager.login_view = 'user_login'
login_manager.login_message_category = 'info'
csrf = CSRFProtect(app)

# --- Helper Functions ---
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def generate_otp(length=6):
    """Generates a random numeric OTP."""
    return ''.join(random.choices(string.digits, k=length))

# NEW: SequenceCounter model for sequential IDs
class SequenceCounter(db.Model):
    id = db.Column(db.String(50), primary_key=True) # e.g., 'order_id_sequence'
    current_value = db.Column(db.BigInteger, nullable=False)

# MODIFIED: Order ID generation function
def generate_order_id():
    counter_name = 'order_id_sequence'
    # Use a transaction for atomic increment to prevent duplicates in concurrent environments
    with db.session.begin_nested(): 
        counter = db.session.query(SequenceCounter).with_for_update().filter_by(id=counter_name).first()
        if not counter:
            # Initialize if it's the first time.
            # Start from 15416760 so the first increment makes it 15416761
            counter = SequenceCounter(id=counter_name, current_value=15416760) 
            db.session.add(counter)
            db.session.flush() # Ensure it's in the session for the update below
        
        counter.current_value += 1
        new_numeric_part = counter.current_value
        # No need to db.session.add(counter) again if it was already fetched/added and modified
        # The flush() above ensures it's tracked.

    # Format the ID as "OD" + padded 8 digits
    return f"OD{new_numeric_part:08d}"
def send_email(to_email, subject, body_plain=None, html_body=None, attachment_path=None, attachment_name=None):
    """Sends an email with optional attachment and supports HTML body."""
    try:
        msg = MIMEMultipart('alternative') # CHANGED THIS LINE
        msg['From'] = current_app.config['MAIL_USERNAME'] # CHANGED THIS LINE
        msg['To'] = to_email
        msg['Subject'] = subject

        if body_plain:
            msg.attach(MIMEText(body_plain, 'plain'))
        if html_body:
            msg.attach(MIMEText(html_body, 'html')) # NEW: Attach HTML part

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=attachment_name or os.path.basename(attachment_path))
                msg.attach(attach)

        # Use current_app.config for SMTP settings
        with smtplib.SMTP(current_app.config['MAIL_SERVER'], current_app.config['MAIL_PORT']) as smtp: # CHANGED THIS LINE
            smtp.starttls()
            smtp.login(current_app.config['MAIL_USERNAME'], current_app.config['MAIL_PASSWORD'])
            smtp.send_message(msg)
        print(f"Email sent successfully to {to_email}") # You can keep this for local testing, or remove it.
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to send email to {to_email}: {e}") # CHANGED THIS LINE
        return False
    
# --- Database Models ---
class User(db.Model, UserMixin):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(120), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True) # Added phone
    password_hash = Column(Text, nullable=False) 
    full_name = Column(String(100), nullable=True) 
    role = Column(String(20), default='customer', nullable=False) # 'customer', 'admin'
    registration_date = Column(DateTime, default=datetime.utcnow)
    email_verified = Column(Boolean, default=False) # Added for OTP verification

    addresses = relationship('Address', backref='user', lazy=True, cascade="all, delete-orphan")
    orders = relationship('Order', backref='customer', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        """Checks if the user has the 'admin' role."""
        return self.role == 'admin'

    def __repr__(self):
        return f"User('{self.email}', '{self.role}')"

class OTP(db.Model):
    id = Column(Integer, primary_key=True)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False)
    otp_code = Column(String(6), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10)) # OTP valid for 10 minutes

    user = relationship('User', backref='otps')

    def is_valid(self):
        return datetime.utcnow() < self.expires_at

class Category(db.Model):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    image = Column(String(255), nullable=True) # Path to category image
    artworks = relationship('Artwork', backref='category', lazy=True)

    def __repr__(self):
        return f"Category('{self.name}')"

class Artwork(db.Model):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sku = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    original_price = Column(Numeric(10, 2), nullable=False) # Price before any options or GST
    
    # New GST fields
    cgst_percentage = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    sgst_percentage = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    igst_percentage = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    ugst_percentage = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    cess_percentage = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False) # NEW: CESS percentage
    gst_type = Column(String(20), default='intra_state', nullable=False) # 'intra_state', 'inter_state', 'union_territory'

    stock = Column(Integer, default=0, nullable=False)
    category_id = Column(String(36), ForeignKey('category.id'), nullable=False)
    images = Column(Text, nullable=True) # Stored as JSON string of image paths
    is_featured = Column(Boolean, default=False, nullable=False)
    custom_options = Column(Text, nullable=True) # Stored as JSON string { "Size": {"A4": 0, "A3": 500}, "Frame": {"None": 0, "Wooden": 1000} }
    shipping_charge = Column(Numeric(10, 2), default=Decimal('0.00'), nullable=False) # NEW: Per-artwork shipping charge

    def get_images_list(self):
        try:
            return json.loads(self.images) if self.images else []
        except json.JSONDecodeError:
            return []

    def set_images_list(self, images_list):
        self.images = json.dumps(images_list)

    def get_custom_options_dict(self):
        try:
            return json.loads(self.custom_options) if self.custom_options else {}
        except json.JSONDecodeError:
            return {}
            
    @property
    def selling_price_incl_gst(self):
        """Calculates the selling price including applicable GST based on gst_type."""
        base_price = self.original_price
        total_gst_rate = Decimal('0.00')
        if self.gst_type == 'intra_state':
            total_gst_rate = self.cgst_percentage + self.sgst_percentage
        elif self.gst_type == 'inter_state':
            total_gst_rate = self.igst_percentage
        elif self.gst_type == 'union_territory':
            total_gst_rate = self.cgst_percentage + self.ugst_percentage
        
        total_gst_rate += self.cess_percentage # Include CESS in total rate for selling price

        return base_price * (1 + total_gst_rate / 100)

    def __repr__(self):
        return f"Artwork('{self.name}', '{self.sku}')"

class Address(db.Model):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False)
    label = Column(String(50), nullable=True) # e.g., "Home", "Work", "Admin Office"
    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address_line1 = Column(String(255), nullable=False)
    address_line2 = Column(String(255), nullable=True)
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    pincode = Column(String(10), nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"Address('{self.full_name}', '{self.city}', '{self.pincode}')"

    # NEW: Method to convert Address object to a dictionary for JSON serialization
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
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

class Order(db.Model):
    # Changed primary key to use the new function generate_order_id
    id = Column(String(10), primary_key=True, default=generate_order_id) # Max 10 chars (OD + 8 digits)
    user_id = Column(String(36), ForeignKey('user.id'), nullable=False)
    order_date = Column(DateTime, default=datetime.utcnow)
    total_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(50), default='Pending Payment', nullable=False) # e.g., Pending Payment, Payment Submitted - Awaiting Verification, Payment Verified – Preparing Order, Shipped, Delivered, Cancelled by User, Cancelled by Admin
    payment_status = Column(String(50), default='pending', nullable=False) # e.g., pending, completed, failed
    shipping_address_id = Column(String(36), ForeignKey('address.id'), nullable=True) # Can be null for direct purchase if address not saved
    shipping_charge = Column(Numeric(10, 2), default=Decimal('0.00'), nullable=False)
    courier = Column(String(100), nullable=True)
    tracking_number = Column(String(100), nullable=True)
    remark = Column(Text, nullable=True) # Admin remarks
    cancellation_reason = Column(Text, nullable=True) # New field for cancellation reason
    payment_screenshot = db.Column(db.String(255), nullable=True)
    email_sent_status = db.Column(db.Boolean, default=False, nullable=False)


    # Invoice details stored as JSON string
    invoice_details = Column(Text, nullable=True) # {business_name, gstin, pan, business_address, invoice_number, invoice_date, billing_address, gst_rate_applied, shipping_charge, final_invoice_amount, invoice_status, is_held_by_admin, cgst_amount, sgst_amount, igst_amount, ugst_amount, cess_amount} # NEW: cess_amount

    items = relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")
    shipping_address = relationship('Address', foreign_keys=[shipping_address_id])

    # Helper to get customer details for display
    @property
    def customer_name(self):
        return self.customer.full_name if self.customer else 'N/A'

    @property
    def customer_email(self):
        return self.customer.email if self.customer else 'N/A'
    
    @property
    def customer_phone(self):
        return self.customer.phone if self.customer else 'N/A'

    def get_shipping_address(self):
        if self.shipping_address:
            return {
                'full_name': self.shipping_address.full_name,
                'phone': self.shipping_address.phone,
                'address_line1': self.shipping_address.address_line1,
                'address_line2': self.shipping_address.address_line2,
                'city': self.shipping_address.city,
                'state': self.shipping_address.state,
                'pincode': self.shipping_address.pincode
            }
        return {}

    def get_invoice_details(self):
        try:
            return json.loads(self.invoice_details) if self.invoice_details else {}
        except json.JSONDecodeError:
            return {}

    def set_invoice_details(self, details_dict):
        self.invoice_details = json.dumps(details_dict)

    def __repr__(self):
        return f"Order('{self.id}', '{self.customer_name}', '{self.total_amount}', '{self.status}')"

class OrderItem(db.Model):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(10), ForeignKey('order.id'), nullable=False) # Changed to String(10) to match Order ID
    artwork_id = Column(String(36), ForeignKey('artwork.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    
    # Store price details at the time of order for historical accuracy
    unit_price_before_gst = Column(Numeric(10, 2), nullable=False) # Price of one unit *including* selected options, *before* GST
    
    # Store applied GST percentages at the time of order
    cgst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    sgst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    igst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    ugst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    cess_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False) # NEW: CESS percentage applied

    selected_options = Column(Text, nullable=True) # e.g., {"Size": "A4", "Frame": "Wooden"}

    artwork = relationship('Artwork')

    @property
    def total_price_before_gst(self):
        return self.unit_price_before_gst * self.quantity

    @property
    def cgst_amount(self):
        return (self.total_price_before_gst * self.cgst_percentage_applied) / 100

    @property
    def sgst_amount(self):
        return (self.total_price_before_gst * self.sgst_percentage_applied) / 100

    @property
    def igst_amount(self):
        return (self.total_price_before_gst * self.igst_percentage_applied) / 100

    @property
    def ugst_amount(self):
        return (self.total_price_before_gst * self.ugst_percentage_applied) / 100

    @property
    def cess_amount(self): # NEW: CESS amount property
        return (self.total_price_before_gst * self.cess_percentage_applied) / 100

    @property
    def total_gst_amount(self):
        return self.cgst_amount + self.sgst_amount + self.igst_amount + self.ugst_amount + self.cess_amount # Include CESS

    @property
    def total_price_incl_gst(self):
        return self.total_price_before_gst + self.total_gst_amount
    
    def get_selected_options_dict(self):
        try:
            return json.loads(self.selected_options) if self.selected_options else {}
        except json.JSONDecodeError:
            return {}

    def __repr__(self):
        return f"OrderItem('{self.artwork.name}', Quantity: {self.quantity}, Total: {self.total_price_incl_gst})"

class ContactMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=False)
    submission_date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<ContactMessage '{self.name} - {self.subject}'>"

# Route to handle form submission
@app.route('/contact', methods=['GET', 'POST'])
def contact():
    # This route now serves both the GET and POST requests
    if request.method == 'POST':
        # Get data from the form
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message_content = request.form.get('message')

        # Create a new ContactMessage object and save it to the database
        new_message = ContactMessage(
            name=name,
            email=email,
            subject=subject,
            message=message_content
        )
        try:
            db.session.add(new_message)
            db.session.commit()
            flash('Thank you for your message! We will get back to you shortly.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('There was an issue sending your message. Please try again.', 'danger')
            app.logger.error(f"Error submitting contact form: {e}")

        # Redirect the user back to the contact page
        return redirect(url_for('contact'))

    # Your original logic to render the template goes here for GET requests
    # Make sure you have these variables defined in your app's context or configuration.
    our_business_address = app.config.get('OUR_BUSINESS_ADDRESS', 'Annapoorna Appartment, New Alipur, Kolkata - 53')
    our_business_email = app.config.get('MAIL_USERNAME', 'covcorres@gmail.com')
    return render_template('contact.html', our_business_address=our_business_address, our_business_email=our_business_email)

from functools import wraps
from flask import abort

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # In a real app, you would check if the user is an admin.
        # For this example, we'll assume a user with a specific ID is an admin.
        # You should replace this with your actual admin logic.
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated_function
# Route for the admin to view messages
# This route is protected so only admins can access it
@app.route('/admin/contact_messages')
@login_required
@admin_required
def admin_contact_messages():
    all_messages = ContactMessage.query.order_by(ContactMessage.submission_date.desc()).all()
    return render_template('admin_contact_messages.html', messages=all_messages)

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    # Fix for LegacyAPIWarning
    return db.session.get(User, user_id)

@app.template_filter('strftime')
def format_datetime(value, format="%Y-%m-%d %H:%M:%S"):
    """Format a datetime object to a string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime(format)
    return str(value) # Or raise an error if you only expect datetime objects



# --- Context Processors ---
@app.context_processor
def inject_global_data():
    """Injects data available globally to all templates."""
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    return {
        'current_year': datetime.now().year,
        'our_business_name': app.config['OUR_BUSINESS_NAME'],
        'our_business_address': app.config['OUR_BUSINESS_ADDRESS'],
        'our_gstin': app.config['OUR_GSTIN'],
        'our_pan': app.config['OUR_PAN'],
        'default_gst_rate': app.config['DEFAULT_GST_RATE'],
        'cart_count': cart_count,
        'now': datetime.utcnow, # For use in templates (e.g., invoice date)
        'timedelta': timedelta # Make timedelta available in Jinja2 context
    }

# --- Custom Jinja2 Filters ---
@app.template_filter('currency')
def currency_filter(value):
    """Formats a number as Indian Rupee currency."""
    try:
        return f"₹{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError):
        return "₹0.00"

@app.template_filter('percent')
def percent_filter(value):
    """Formats a number as a percentage."""
    try:
        return f"{Decimal(value):.2f}%"
    except (InvalidOperation, TypeError):
        return "0.00%"

@app.template_filter('slugify')
def slugify_filter(s):
    """Converts a string to a URL-friendly slug."""
    return slugify(s)

# --- Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin(): # Changed to call is_admin()
            flash('Admin access required.', 'danger')
            return redirect(url_for('user_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Routes ---

# NEW: Route to get cart count for real-time update
@app.route('/get_cart_count')
def get_cart_count():
    cart_data = session.get('cart', {})
    total_quantity = sum(item['quantity'] for item in cart_data.values())
    return jsonify(success=True, cart_count=total_quantity)

# NEW: Helper function to calculate item total including options and GST
# Helper function to calculate item total including options and GST
def calculate_item_total(artwork, selected_options, quantity):
    """
    Calculates the total price and GST components for a single artwork item,
    considering custom options and quantity.
    Returns a dictionary of detailed calculation results.
    """
    base_price = artwork.original_price

    # Add option prices if applicable
    options_data = artwork.get_custom_options_dict()
    for option_group, option_value in selected_options.items():
        if option_group in options_data and option_value in options_data[option_group]:
            base_price += Decimal(str(options_data[option_group][option_value]))

    unit_price_before_gst = base_price

    # Use artwork's specific GST percentages
    cgst_percentage = artwork.cgst_percentage
    sgst_percentage = artwork.sgst_percentage
    igst_percentage = artwork.igst_percentage
    ugst_percentage = artwork.ugst_percentage
    cess_percentage = artwork.cess_percentage # NEW: Get CESS percentage

    total_price_before_gst_for_item = unit_price_before_gst * quantity

    cgst_amount = (total_price_before_gst_for_item * cgst_percentage) / 100
    sgst_amount = (total_price_before_gst_for_item * sgst_percentage) / 100
    igst_amount = (total_price_before_gst_for_item * igst_percentage) / 100
    ugst_amount = (total_price_before_gst_for_item * ugst_percentage) / 100
    cess_amount = (total_price_before_gst_for_item * cess_percentage) / 100 # NEW: CESS amount

    total_gst_amount_for_item = cgst_amount + sgst_amount + igst_amount + ugst_amount + cess_amount # Include CESS
    total_price_incl_gst = total_price_before_gst_for_item + total_gst_amount_for_item

    return {
        'unit_price_before_gst': unit_price_before_gst,
        'cgst_percentage_applied': cgst_percentage,
        'sgst_percentage_applied': sgst_percentage,
        'igst_percentage_applied': igst_percentage,
        'ugst_percentage_applied': ugst_percentage,
        'cess_percentage_applied': cess_percentage, # NEW: Pass CESS percentage
        'total_price_incl_gst': total_price_incl_gst,
        'cgst_amount': cgst_amount,
        'sgst_amount': sgst_amount,
        'igst_amount': igst_amount,
        'ugst_amount': ugst_amount,
        'cess_amount': cess_amount, # NEW: Pass CESS amount
        'total_price_before_gst': total_price_before_gst_for_item
    }

# Assuming you have a get_cart_items_details() function somewhere,
# NEW: Helper function to get detailed cart items for display and calculation
from decimal import Decimal, InvalidOperation # Ensure InvalidOperation is imported

def get_cart_items_details():
    """
    Retrieves detailed information for items in the session cart or direct purchase session.
    Prioritizes direct_purchase_cart if it exists.
    Returns (detailed_cart_items, subtotal_before_gst, total_cgst_amount,
              total_sgst_amount, total_igst_amount, total_ugst_amount,
              total_gst_amount, grand_total, total_shipping_charge)
    """
    detailed_cart_items = []
    subtotal_before_gst = Decimal('0.00')
    total_cgst_amount = Decimal('0.00')
    total_sgst_amount = Decimal('0.00')
    total_igst_amount = Decimal('0.00')
    total_ugst_amount = Decimal('0.00')
    total_cess_amount = Decimal('0.00') # NEW: Total CESS amount
    total_gst_amount = Decimal('0.00')
    grand_total = Decimal('0.00')
    total_shipping_charge = Decimal('0.00') # Initialize total shipping charge

    items_source = {}
    if 'direct_purchase_cart' in session and session['direct_purchase_cart']:
        for key, value in session['direct_purchase_cart'].items():
            items_source[key] = value
    else:
        items_source = session.get('cart', {}).copy()

    for item_key, item_data in items_source.items():
        sku = item_data['sku']
        quantity = item_data['quantity']
        selected_options = item_data.get('selected_options', item_data.get('options', {}))

        artwork = Artwork.query.filter_by(sku=sku).first()
        if artwork:
            results_from_calculation = calculate_item_total(artwork, selected_options, quantity)

            unit_price_before_gst = results_from_calculation['unit_price_before_gst']
            cgst_percentage_applied = results_from_calculation['cgst_percentage_applied']
            sgst_percentage_applied = results_from_calculation['sgst_percentage_applied']
            igst_percentage_applied = results_from_calculation['igst_percentage_applied']
            ugst_percentage_applied = results_from_calculation['ugst_percentage_applied']
            cess_percentage_applied = results_from_calculation['cess_percentage_applied'] # NEW
            total_price_incl_gst = results_from_calculation['total_price_incl_gst']
            cgst_amount = results_from_calculation['cgst_amount']
            sgst_amount = results_from_calculation['sgst_amount']
            igst_amount = results_from_calculation['igst_amount']
            ugst_amount = results_from_calculation['ugst_amount']
            cess_amount = results_from_calculation['cess_amount'] # NEW
            total_price_before_gst_for_item = results_from_calculation['total_price_before_gst']

            detailed_cart_items.append({
                'item_key': item_key,
                'artwork': artwork, # Full artwork object
                'quantity': quantity,
                'unit_price_before_gst': unit_price_before_gst,
                'cgst_percentage': cgst_percentage_applied, # CHANGED
                'sgst_percentage': sgst_percentage_applied, # CHANGED
                'igst_percentage': igst_percentage_applied, # CHANGED
                'ugst_percentage': ugst_percentage_applied, # CHANGED
                'cess_percentage': cess_percentage_applied, # NEW
                'total_price_incl_gst': total_price_incl_gst,
                'cgst_amount': cgst_amount,
                'sgst_amount': sgst_amount,
                'igst_amount': igst_amount,
                'ugst_amount': ugst_amount,
                'cess_amount': cess_amount, # NEW
                'selected_options': selected_options,
                'image_url': artwork.get_images_list()[0] if artwork.get_images_list() else 'images/placeholder.png'
            })
            subtotal_before_gst += total_price_before_gst_for_item # CHANGED
            total_cgst_amount += cgst_amount
            total_sgst_amount += sgst_amount
            total_igst_amount += igst_amount
            total_ugst_amount += ugst_amount
            total_cess_amount += cess_amount # NEW
            total_gst_amount += (cgst_amount + sgst_amount + igst_amount + ugst_amount + cess_amount) # Include CESS
            grand_total += total_price_incl_gst
            
            item_shipping_charge = Decimal(str(item_data.get('shipping_charge', artwork.shipping_charge)))
            total_shipping_charge += item_shipping_charge * quantity
        else:
            flash(f"Artwork with SKU {sku} not found and removed from your cart.", "warning")
            if item_key in session.get('cart', {}):
                del session['cart'][item_key]
            session.modified = True
            
    grand_total += total_shipping_charge

    return (detailed_cart_items, subtotal_before_gst, total_cgst_amount,
            total_sgst_amount, total_igst_amount, total_ugst_amount, total_cess_amount, # NEW: Return total_cess_amount
            total_gst_amount, grand_total, total_shipping_charge)

# NEW: Route to add item to cart (AJAX endpoint)
@app.route('/add-to-cart', methods=['POST'])
@csrf.exempt # Exempt CSRF for AJAX, handled by X-CSRFToken header
def add_to_cart():
    data = request.get_json()
    sku = data.get('sku')
    quantity = int(data.get('quantity', 1))
    selected_options = data.get('options', {}) # Dictionary of selected options

    if not sku or quantity < 1:
        return jsonify(success=False, message='Invalid product or quantity.'), 400

    artwork = Artwork.query.filter_by(sku=sku).first()
    if not artwork:
        return jsonify(success=False, message='Artwork not found.'), 404
    
    if artwork.stock < quantity:
        return jsonify(success=False, message=f'Only {artwork.stock} units of {artwork.name} are available.'), 400

    # Calculate item price including options and GST
    calculated_results = calculate_item_total(artwork, selected_options, quantity)
    
    unit_price_before_gst = calculated_results['unit_price_before_gst']
    cgst_percentage = calculated_results['cgst_percentage_applied']
    sgst_percentage = calculated_results['sgst_percentage_applied']
    igst_percentage = calculated_results['igst_percentage_applied']
    ugst_percentage = calculated_results['ugst_percentage_applied']
    cess_percentage = calculated_results['cess_percentage_applied']

    cart = session.get('cart', {})
    
    # Create a unique key for the cart item based on SKU and selected options
    # This ensures different options for the same SKU are treated as separate cart items
    options_key = json.dumps(selected_options, sort_keys=True)
    item_key = f"{sku}_{options_key}"

    if item_key in cart:
        # If item with same options already in cart, update quantity
        cart[item_key]['quantity'] += quantity
    else:
        # Add new item to cart
        cart[item_key] = {
            'sku': sku,
            'name': artwork.name,
            'imageUrl': artwork.get_images_list()[0] if artwork.get_images_list() else 'images/placeholder.png',
            'quantity': quantity,
            'unitPriceBeforeGst': str(unit_price_before_gst), # Store as string for Decimal
            'cgstPercentage': str(cgst_percentage), # Store as string for Decimal
            'sgstPercentage': str(sgst_percentage),
            'igstPercentage': str(igst_percentage),
            'ugstPercentage': str(ugst_percentage),
            'cessPercentage': str(cess_percentage), # NEW: Store cessPercentage
            'options': selected_options
        }
    
    session['cart'] = cart
    session.modified = True # Important to mark session as modified

    total_quantity_in_cart = sum(item['quantity'] for item in session['cart'].values())
    
    cart_url = url_for('cart') # Get the URL for the cart page
    message_content = f"{quantity} x {artwork.name} added to cart! <a href='{cart_url}' class='alert-link' style='color: inherit; text-decoration: underline; margin-left: 10px;'>Go to Cart</a>"
    flash(Markup(message_content), 'success') # Wrap the message in Markup

    return jsonify(success=True, message='Item added to cart!', cart_count=total_quantity_in_cart)

# NEW: Route to remove item from cart (AJAX endpoint)
@app.route('/remove-from-cart', methods=['POST'])
@csrf.exempt # Exempt CSRF for AJAX, handled by X-CSRFToken header
def remove_from_cart():
    data = request.get_json()
    item_key = data.get('item_key')

    cart = session.get('cart', {})
    if item_key in cart:
        del cart[item_key]
        session['cart'] = cart
        session.modified = True
        total_quantity_in_cart = sum(item['quantity'] for item in session['cart'].values())
        flash('Item removed from cart.', 'info')
        return jsonify(success=True, message='Item removed from cart.', cart_count=total_quantity_in_cart)
    return jsonify(success=False, message='Item not found in cart.'), 404

# MODIFIED: Cart route to display detailed cart items
@app.route('/cart')
def cart():
    detailed_cart_items, subtotal_before_gst, total_cgst_amount, \
    total_sgst_amount, total_igst_amount, total_ugst_amount, total_cess_amount, \
    total_gst_amount, grand_total, total_shipping_charge = get_cart_items_details() # Changed variable name
    
    return render_template('cart.html', 
                           cart_items=detailed_cart_items,
                           subtotal_before_gst=subtotal_before_gst,
                           total_cgst_amount=total_cgst_amount,
                           total_sgst_amount=total_sgst_amount,
                           total_igst_amount=total_igst_amount,
                           total_ugst_amount=total_ugst_amount,
                           total_cess_amount=total_cess_amount, # NEW
                           total_gst_amount=total_gst_amount,
                           grand_total=grand_total,
                           shipping_charge=total_shipping_charge) # Pass the calculated total_shipping_charge

# NEW: Route to create a direct order from "Buy Now"
@app.route('/create_direct_order', methods=['POST'])
@csrf.exempt # Exempt CSRF for AJAX, handled by X-CSRFToken header
def create_direct_order():
    data = request.get_json()
    # Expect data to contain a 'cart' object, even if it's just one item
    # The 'cart' object here is actually the itemToBuyNow from main.js
    item_to_buy_now = data 

    if not item_to_buy_now:
        return jsonify(success=False, message='No items provided for direct purchase.'), 400

    # Convert numeric values to strings before storing in session to ensure consistency
    # with how cart items are stored (which are initially from form data/DB, not JS floats)
    if 'unitPriceBeforeGst' in item_to_buy_now:
        item_to_buy_now['unitPriceBeforeGst'] = str(item_to_buy_now['unitPriceBeforeGst'])
    if 'cgstPercentage' in item_to_buy_now: # Changed from gstPercentage
        item_to_buy_now['cgstPercentage'] = str(item_to_buy_now['cgstPercentage'])
    if 'sgstPercentage' in item_to_buy_now:
        item_to_buy_now['sgstPercentage'] = str(item_to_buy_now['sgstPercentage'])
    if 'igstPercentage' in item_to_buy_now:
        item_to_buy_now['igstPercentage'] = str(item_to_buy_now['igstPercentage'])
    if 'ugstPercentage' in item_to_buy_now:
        item_to_buy_now['ugstPercentage'] = str(item_to_buy_now['ugstPercentage'])
    if 'cessPercentage' in item_to_buy_now: # NEW
        item_to_buy_now['cessPercentage'] = str(item_to_buy_now['cessPercentage'])

    # NEW: Store shipping_charge in item_to_buy_now if present
    if 'shippingCharge' in item_to_buy_now:
        item_to_buy_now['shippingCharge'] = str(item_to_buy_now['shippingCharge'])

    # Store the direct purchase item in session for later retrieval after login/signup
    # Store as a list of one item to mimic cart structure for purchase_form
    session['direct_purchase_cart'] = {'temp_item_key': item_to_buy_now} 
    session.modified = True

    if current_user.is_authenticated:
        # If logged in, proceed to purchase form directly
        return jsonify(success=True, message='Proceeding to checkout.', redirect_url=url_for('purchase_form'))
    else:
        # If not logged in, redirect to login page, which will then redirect to purchase_form
        # Store the intended destination for after login
        session['redirect_after_auth'] = url_for('purchase_form') 
        session.modified = True
        return jsonify(success=True, message='Please log in or sign up to complete your purchase.', redirect_url=url_for('user_login', next=url_for('purchase_form')))

# MODIFIED: Purchase form to handle both cart checkout and direct purchase
# In app.py, locate your purchase_form route and update it.

@app.route('/purchase-form', methods=['GET', 'POST'])
@login_required
def purchase_form():
    user_addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc(), Address.id.asc()).all()
    
    prefill_address = None
    if user_addresses:
        for addr in user_addresses:
            if addr.is_default:
                prefill_address = addr
                break
        if not prefill_address:
            prefill_address = user_addresses[0]

    prefill_address_dict = prefill_address.to_dict() if prefill_address else None
    selected_address = prefill_address

    items_to_process = []
    subtotal_before_gst = Decimal('0.00')
    total_cgst_amount = Decimal('0.00')
    total_sgst_amount = Decimal('0.00')
    total_igst_amount = Decimal('0.00')
    total_ugst_amount = Decimal('0.00')
    total_cess_amount = Decimal('0.00')
    total_gst = Decimal('0.00')
    shipping_charge = Decimal('0.00')
    final_total_amount = Decimal('0.00')
    shipping_address_obj = None

    if request.method == 'POST':
        (items_to_process, subtotal_before_gst, total_cgst_amount, 
         total_sgst_amount, total_igst_amount, total_ugst_amount, total_cess_amount,
         total_gst, final_total_amount, shipping_charge) = get_cart_items_details()

        if not items_to_process:
            flash("No items to purchase.", "danger")
            return redirect(url_for('cart'))

        action_type = request.form.get('action_type')

        if action_type == 'add_new_address':
            selected_address_id = request.form.get('selected_address_id') or request.form.get('shipping_address')
            full_name = request.form.get('full_name')
            phone = request.form.get('phone')
            address_line1 = request.form.get('address_line1')
            address_line2 = request.form.get('address_line2')
            city = request.form.get('city')
            state = request.form.get('state')
            pincode = request.form.get('pincode')
            save_address = request.form.get('save_address') == 'on'
            set_as_default = request.form.get('set_as_default') == 'on'

            if not all([full_name, phone, address_line1, city, state, pincode]):
                flash('Please fill in all required fields for the new address.', 'danger')
                return render_template('purchase_form.html',
                                       items_to_process=items_to_process,
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_gst=total_gst,
                                       shipping_charge=shipping_charge,
                                       final_total_amount=final_total_amount,
                                       user_addresses=user_addresses,
                                       prefill_address=prefill_address_dict,
                                       form_data=request.form.to_dict(),
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_cess_amount=total_cess_amount,
                                       has_addresses=bool(user_addresses),
                                       current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email},
                                       config=app.config)

            new_address = Address(
                user_id=current_user.id,
                full_name=full_name,
                phone=phone,
                address_line1=address_line1,
                address_line2=address_line2,
                city=city,
                state=state,
                pincode=pincode,
                is_default=set_as_default
            )
            db.session.add(new_address)
            db.session.commit()
            session['pre_selected_address_id'] = new_address.id
            flash('New address added successfully! Please select it below before placing the order.', 'info')
            return redirect(url_for('purchase_form'))

        elif action_type == 'place_order':
            selected_address_id = request.form.get('selected_address_id') or request.form.get('shipping_address')
            
            if not selected_address_id:
                flash('Please select a shipping address.', 'danger')
                return render_template('purchase_form.html',
                                       items_to_process=items_to_process, 
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_gst=total_gst,
                                       shipping_charge=shipping_charge,
                                       final_total_amount=final_total_amount,
                                       user_addresses=user_addresses,
                                       prefill_address=prefill_address_dict,
                                       form_data=request.form.to_dict(),
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_cess_amount=total_cess_amount,
                                       has_addresses=bool(user_addresses),
                                       current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email},
                                       config=app.config)

            # --- reCAPTCHA Verification Start ---
            recaptcha_secret = app.config['RECAPTCHA_SECRET_KEY']
            recaptcha_response = request.form.get('g-recaptcha-response')

            if not recaptcha_response:
                flash("reCAPTCHA validation failed. Please try again.", "danger")
                return render_template('purchase_form.html',
                                       items_to_process=items_to_process, 
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_gst=total_gst,
                                       shipping_charge=shipping_charge,
                                       final_total_amount=final_total_amount,
                                       user_addresses=user_addresses,
                                       prefill_address=prefill_address_dict,
                                       form_data=request.form.to_dict(),
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_cess_amount=total_cess_amount,
                                       has_addresses=bool(user_addresses),
                                       current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email},
                                       config=app.config)

            recaptcha_data = {
                'secret': recaptcha_secret,
                'response': recaptcha_response
            }
            recaptcha_verification = requests.post('https://www.google.com/recaptcha/api/siteverify', data=recaptcha_data)
            recaptcha_result = recaptcha_verification.json()
            print("=== reCAPTCHA Debug ===")
            print("Response JSON:", recaptcha_result)

            if not recaptcha_result.get('success'):
                flash("reCAPTCHA verification failed. Please check the box.", "danger")
                return render_template('purchase_form.html',
                                       items_to_process=items_to_process, 
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_gst=total_gst,
                                       shipping_charge=shipping_charge,
                                       final_total_amount=final_total_amount,
                                       user_addresses=user_addresses,
                                       prefill_address=prefill_address_dict,
                                       form_data=request.form.to_dict(),
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_cess_amount=total_cess_amount,
                                       has_addresses=bool(user_addresses),
                                       current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email},
                                       config=app.config)
            # --- reCAPTCHA Verification End ---

            shipping_address_obj = db.session.get(Address, selected_address_id)
            if not shipping_address_obj or shipping_address_obj.user_id != current_user.id:
                flash("Invalid address selection.", "danger")
                return render_template('purchase_form.html',
                                       items_to_process=items_to_process, 
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_gst=total_gst,
                                       shipping_charge=shipping_charge,
                                       final_total_amount=final_total_amount,
                                       user_addresses=user_addresses,
                                       prefill_address=prefill_address_dict,
                                       form_data=request.form.to_dict(),
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_cess_amount=total_cess_amount,
                                       has_addresses=bool(user_addresses),
                                       current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email},
                                       config=app.config)

            try:
                new_order = Order(
                    id=generate_order_id(),
                    user_id=current_user.id,
                    total_amount=final_total_amount,
                    status='Pending Payment',
                    payment_status='pending',
                    shipping_address_id=shipping_address_obj.id,
                    shipping_charge=shipping_charge
                )
                db.session.add(new_order)
                db.session.flush()

                for item in items_to_process:
                    order_item = OrderItem(
                        order_id=new_order.id,
                        artwork_id=item['artwork'].id,
                        quantity=item['quantity'],
                        unit_price_before_gst=item['unit_price_before_gst'],
                        cgst_percentage_applied=item['cgst_percentage'],
                        sgst_percentage_applied=item['sgst_percentage'],
                        igst_percentage_applied=item['igst_percentage'],
                        ugst_percentage_applied=item['ugst_percentage'],
                        cess_percentage_applied=item['cess_percentage'],
                        selected_options=json.dumps(item['selected_options'])
                    )
                    db.session.add(order_item)

                    artwork = db.session.get(Artwork, item['artwork'].id)
                    if artwork:
                        artwork.stock -= item.get('quantity', 0)
                        if artwork.stock < 0:
                            artwork.stock = 0

                db.session.commit()
                session.pop('cart', None)
                session.pop('direct_purchase_cart', None)
                session.modified = True

                try:
                    msg = Message(
                        subject=f"Your Order #{new_order.id} Confirmation - Karthika Futures",
                        recipients=[current_user.email]
                    )
                    msg.body = f"Dear {current_user.full_name},\n\nThank you for your order #{new_order.id}.\n\nPlease find your invoice attached.\n\nKarthika Futures Team"

                    pdf_buffer = generate_invoice_pdf_buffer(new_order)
                    if pdf_buffer:
                        msg.attach(
                            filename=f"invoice_{new_order.id}.pdf",
                            content_type="application/pdf",
                            data=pdf_buffer.read()
                        )
                    mail.send(msg)
                except Exception as e:
                    print(f"Error sending email: {e}")

                flash('Order placed successfully! Please proceed to payment.', 'success')
                return redirect(url_for('payment_initiate', order_id=new_order.id, amount=new_order.total_amount))

            except IntegrityError:
                db.session.rollback()
                flash('An error occurred while creating your order. Please try again.', 'danger')
            except Exception as e:
                db.session.rollback()
                flash(f'An unexpected error occurred: {e}', 'danger')
    
    (items_to_process, subtotal_before_gst, total_cgst_amount, 
     total_sgst_amount, total_igst_amount, total_ugst_amount, total_cess_amount,
     total_gst, final_total_amount, shipping_charge) = get_cart_items_details()

    if not items_to_process:
        flash("No items to purchase.", "danger")
        return redirect(url_for('cart'))

    pre_selected_id = session.pop('pre_selected_address_id', None)
    if pre_selected_id:
        selected_address = db.session.get(Address, pre_selected_id)

    form_data = request.form.to_dict() if request.method == 'POST' else {}

    return render_template('purchase_form.html',
                           items_to_process=items_to_process,
                           subtotal_before_gst=subtotal_before_gst,
                           total_gst=total_gst,
                           shipping_charge=shipping_charge,
                           final_total_amount=final_total_amount,
                           user_addresses=user_addresses,
                           selected_address=selected_address,
                           prefill_address=prefill_address_dict,
                           form_data=form_data,
                           total_cgst_amount=total_cgst_amount,
                           total_sgst_amount=total_sgst_amount,
                           total_igst_amount=total_igst_amount,
                           total_ugst_amount=total_ugst_amount,
                           total_cess_amount=total_cess_amount,
                           new_address_added=bool(pre_selected_id),
                           has_addresses=bool(user_addresses),
                           config=app.config,
                           current_user_data={'full_name': current_user.full_name, 'phone': current_user.phone, 'email': current_user.email}
)


@app.route('/set-default-address/<uuid:address_id>', methods=['POST'])
@login_required
def set_default_address(address_id):
    address_to_set = Address.query.filter_by(id=address_id, user_id=current_user.id).first()

    if not address_to_set:
        flash("Address not found or does not belong to you.", "danger")
        return redirect(url_for('my_addresses'))

    try:
        # Unset the old default address for the user
        current_default = Address.query.filter_by(user_id=current_user.id, is_default=True).first()
        if current_default:
            current_default.is_default = False
        
        # Set the new default address
        address_to_set.is_default = True
        db.session.commit()
        
        flash("Default address has been updated successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while setting the default address: {e}", "danger")

    return redirect(url_for('my_addresses'))
# MODIFIED: Signup route to include OTP verification and next_url capture
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Store the 'next' URL if provided in the query parameters (e.g., from @login_required)
    next_url = request.args.get('next')
    if next_url:
        session['redirect_after_auth'] = next_url
    # If no 'next' param, try to use referrer, but avoid redirecting back to auth pages
    elif request.referrer and request.referrer != request.url:
        # Check if referrer is not from an authentication page to avoid redirection loops
        if not any(auth_path in request.referrer for auth_path in ['/user-login', '/signup', '/verify_otp', '/forgot-password', '/verify_reset_otp', '/reset_password']):
            session['redirect_after_auth'] = request.referrer
    
    form_data = {}
    if request.method == 'POST':
        email = request.form.get('email')
        phone = request.form.get('phone')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        full_name = request.form.get('full_name')

        form_data = {'email': email, 'phone': phone, 'full_name': full_name}

        if not email or not password or not confirm_password:
            flash('Please fill in all required fields.', 'danger')
            return render_template('signup.html', form_data=form_data)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html', form_data=form_data)

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('signup.html', form_data=form_data)

        existing_user_email = User.query.filter_by(email=email).first()
        if existing_user_email:
            if existing_user_email.email_verified:
                flash('An account with this email already exists. Please log in.', 'warning')
            else:
                # Resend OTP if email not verified
                otp_code = generate_otp()
                new_otp = OTP(user_id=existing_user_email.id, otp_code=otp_code)
                db.session.add(new_otp)
                db.session.commit()
                send_email(existing_user_email.email, 'Karthika Futures - Verify Your Email', f'Your OTP for email verification is: {otp_code}. It is valid for 10 minutes.')
                session['otp_user_id'] = existing_user_email.id
                flash('An account with this email exists but is not verified. A new OTP has been sent to your email.', 'info')
                return redirect(url_for('verify_otp'))
            return render_template('signup.html', form_data=form_data)
        
        # Check if phone number already exists
        if phone:
            existing_user_phone = User.query.filter_by(phone=phone).first()
            if existing_user_phone:
                flash('An account with this phone number already exists. Please log in or use a different phone number.', 'warning')
                return render_template('signup.html', form_data=form_data)

        # Create user but mark as unverified
        new_user = User(email=email, phone=phone, full_name=full_name, email_verified=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # Generate and send OTP
        otp_code = generate_otp()
        otp_entry = OTP(user_id=new_user.id, otp_code=otp_code)
        db.session.add(otp_entry)
        db.session.commit()

        send_email(new_user.email, 'Karthika Futures - Verify Your Email', f'Your OTP for email verification is: {otp_code}. It is valid for 10 minutes.')
        
        session['otp_user_id'] = new_user.id # Store user ID in session for OTP verification
        
        session['prefill_login_phone'] = new_user.phone # Store phone for login prefill

        flash('A One-Time Password (OTP) has been sent to your email. Please verify to complete registration.', 'success')
        return redirect(url_for('verify_otp'))

    return render_template('signup.html', form_data=form_data)

# NEW: Helper function to handle post-authentication redirection
def _handle_post_auth_redirect():
    # Prioritize direct purchase flow (from 'Buy Now' button)
    if 'direct_purchase_cart' in session and session['direct_purchase_cart']:
        # Clear the direct purchase cart from session once handled
        session.pop('direct_purchase_cart', None)
        # Ensure 'itemToBuyNow' is cleared if it was set by older logic
        session.pop('itemToBuyNow', None) 
        flash('Login successful! Redirecting to complete your purchase.', 'success')
        return redirect(url_for('purchase_form'))
    
    # Then check for a general 'next' URL (from @login_required or referrer)
    redirect_to_url = session.pop('redirect_after_auth', None)
    if redirect_to_url:
        flash('Login successful! You are now logged in.', 'success')
        return redirect(redirect_to_url)
    
    # Fallback to homepage if no specific URL was stored
    flash('Login successful! You are now logged in.', 'success')
    return redirect(url_for('index'))


@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('otp_user_id')
    if not user_id:
        flash('No pending verification. Please sign up or try forgot password again.', 'danger')
        return redirect(url_for('signup'))

    # Fix for LegacyAPIWarning
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found for verification.', 'danger')
        return redirect(url_for('signup'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        
        # Find the latest valid OTP for this user
        latest_otp = OTP.query.filter_by(user_id=user.id).order_by(OTP.created_at.desc()).first()

        if latest_otp and latest_otp.otp_code == otp_entered and latest_otp.is_valid():
            user.email_verified = True
            db.session.delete(latest_otp)  # Delete used OTP
            db.session.commit()
            session.pop('otp_user_id', None)

            login_user(user)  # ✅ Automatically log the user in after OTP verified

            # Use the new helper function for redirection
            return _handle_post_auth_redirect()

        else:
            flash('Invalid or expired OTP. Please try again.', 'danger')

    return render_template('verify_otp.html', user_email=user.email)

# NEW: Resend OTP route
@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    user_id = session.get('otp_user_id')
    if not user_id:
        return jsonify(success=False, message='No user session found for OTP resend.'), 400

    # Fix for LegacyAPIWarning
    user = db.session.get(User, user_id)
    if not user:
        return jsonify(success=False, message='User not found.'), 404

    # Generate a new OTP
    otp_code = generate_otp()
    new_otp = OTP(user_id=user.id, otp_code=otp_code)
    db.session.add(new_otp)
    db.session.commit()

    if send_email(user.email, 'Karthika Futures - Your New OTP', f'Your new OTP for verification is: {otp_code}. It is valid for 10 minutes.'):
        return jsonify(success=True, message='New OTP sent to your email.')
    else:
        return jsonify(success=False, message='Failed to send OTP. Please try again later.'), 500

# MODIFIED: User Login route to check email verification
@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Store the 'next' URL if provided in the query parameters (e.g., from @login_required)
    next_url = request.args.get('next')
    if next_url:
        session['redirect_after_auth'] = next_url
    # If no 'next' param, try to use referrer, but avoid redirecting back to auth pages
    elif request.referrer and request.referrer != request.url:
        # Check if referrer is not from an authentication page to avoid redirection loops
        if not any(auth_path in request.referrer for auth_path in ['/user-login', '/signup', '/verify_otp', '/forgot-password', '/verify_reset_otp', '/reset_password']):
            session['redirect_after_auth'] = request.referrer
    
    # Retrieve prefill data from session (will be removed after being read once)
    prefill_phone = session.pop('prefill_login_phone', None)
    prefill_email = session.pop('prefill_login_email', None)

    form_data = {} # Initialize form_data for GET requests or failed POSTs

    if request.method == 'POST':
        # Accept either email or phone for login
        login_identifier = request.form.get('login_identifier')
        password = request.form.get('password')
        form_data = {'login_identifier': login_identifier} # Pass back entered identifier on failure

        # Query for user by either email OR phone number
        user = User.query.filter((User.email == login_identifier) | (User.phone == login_identifier)).first()

        if user and user.check_password(password):
            if not user.email_verified:
                # If email not verified, send OTP and redirect to verify_otp
                otp_code = generate_otp()
                new_otp = OTP(user_id=user.id, otp_code=otp_code)
                db.session.add(new_otp)
                db.session.commit()
                send_email(user.email, 'Karthika Futures - Verify Your Email', f'Your OTP for email verification is: {otp_code}. It is valid for 10 minutes.')
                session['otp_user_id'] = user.id
                flash('Your email is not verified. An OTP has been sent to your email to verify your account.', 'warning')
                return redirect(url_for('verify_otp'))
            
            login_user(user)
            # Use the new helper function for redirection
            return _handle_post_auth_redirect()
        else:
            flash('Invalid login ID or password.', 'danger')

    # Pass prefill data AND form_data to the template for GET requests or failed POST requests
    return render_template('login.html', form_data=form_data, prefill_phone=prefill_phone, prefill_email=prefill_email)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    
    # Clear cartCount from session (if stored)
    session.pop('cartCount', None)
    
    # Clear other session data like 'itemToBuyNow' if needed
    session.pop('itemToBuyNow', None)
    session.pop('redirect_after_login_endpoint', None)
    session.pop('redirect_after_auth', None) # Clear the new redirect key
    session.pop('direct_purchase_cart', None) # Clear direct purchase cart on logout
    
    session.clear()  # Optional: Clears entire session
    
    flash("You’ve been logged out.", "info")
    response = redirect(url_for('index'))
    
    # Optional: Clear cartCount from browser's localStorage via response cookie
    response.set_cookie('cartCount', '', expires=0)  # Helps JS if you sync it with cookies
    return response


# MODIFIED: Forgot Password route to use OTP
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form_data = {}
    if request.method == 'POST':
        email = request.form.get('email')
        form_data = {'email': email}
        user = User.query.filter_by(email=email).first()

        if user:
            otp_code = generate_otp()
            # Invalidate any previous OTPs for this user for password reset
            OTP.query.filter_by(user_id=user.id).delete()
            db.session.commit()

            new_otp = OTP(user_id=user.id, otp_code=otp_code)
            db.session.add(new_otp)
            db.session.commit()

            send_email(user.email, 'Karthika Futures - Password Reset OTP', f'Your OTP for password reset is: {otp_code}. It is valid for 10 minutes.')
            session['otp_user_id'] = user.id # Store user ID for OTP verification
            flash('A One-Time Password (OTP) has been sent to your email to reset your password.', 'success')
            return redirect(url_for('verify_reset_otp'))
        else:
            flash('No account found with that email address.', 'danger')
    
    return render_template('forgot_password.html', form_data=form_data)

# NEW: Route to verify OTP for password reset
@app.route('/verify_reset_otp', methods=['GET', 'POST'])
def verify_reset_otp():
    user_id = session.get('otp_user_id')
    if not user_id:
        flash('No pending password reset. Please request a new reset.', 'danger')
        return redirect(url_for('forgot_password'))

    # Fix for LegacyAPIWarning
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found for password reset.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        
        latest_otp = OTP.query.filter_by(user_id=user.id).order_by(OTP.created_at.desc()).first()

        if latest_otp and latest_otp.otp_code == otp_entered and latest_otp.is_valid():
            user.email_verified = True
            db.session.delete(latest_otp) # Delete used OTP
            db.session.commit()
            # IMPORTANT FIX: Set the user_id in the correct session key for reset_password
            session['reset_user_id'] = user.id
            session.pop('otp_user_id', None) # Clear the temporary OTP user ID
            flash('OTP verified! You can now set your new password.', 'success')
            return redirect(url_for('reset_password'))
        else:
            flash('Invalid or expired OTP. Please try again.', 'danger')
    
    return render_template('verify_reset_otp.html', user_email=user.email)

# NEW: Route to set new password after OTP verification
@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    user_id = session.get('reset_user_id')
    if not user_id:
        flash('Unauthorized access. Please verify OTP first.', 'danger')
        return redirect(url_for('forgot_password'))

    # Fix for LegacyAPIWarning
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found for password reset.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('confirm_new_password')

        if not new_password or not confirm_new_password:
            flash('Please enter and confirm your new password.', 'danger')
            return render_template('reset_password.html')

        if new_password != confirm_new_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html')

        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('reset_password.html')

        user.set_password(new_password)
        db.session.commit()
        session.pop('reset_user_id', None) # Clear reset user ID
        flash('Your password has been reset successfully! Please log in with your new password.', 'success')
        return redirect(url_for('user_login'))

    return render_template('reset_password.html')

@app.route('/category/<category_slug>')
def category_page(category_slug):
    # This is a placeholder function to fix the BuildError.
    # Replace this with your actual logic later.
    # For now, let's assume you have a 'category_page.html' template.
    return render_template('category_page.html', category_slug=category_slug)
# app.py (Modified Excerpt)

@app.route('/')
def index():
    # Fetch categories for the new horizontal layout
    categories = Category.query.order_by(Category.name).all() 
    # Find a representative artwork image for each category
    for category in categories:
        first_artwork = Artwork.query.filter_by(category_id=category.id).first()
        if first_artwork:
            images_list = first_artwork.get_images_list()
            if images_list:
                category.main_artwork_image = images_list[0]
            else:
                category.main_artwork_image = url_for('static', filename='images/placeholder.png')
        else:
            category.main_artwork_image = url_for('static', filename='images/placeholder.png')
    # Fetch featured artworks (we'll keep this separate for now)
    featured_artworks = Artwork.query.filter_by(is_featured=True).limit(6).all()
    
    # Logic for continuous carousel loop (keeping it for now, though we'll use a different section)
    featured_artworks_for_carousel = [] 
    if featured_artworks:
        num_duplicates = 3
        if len(featured_artworks) < num_duplicates:
            num_duplicates = len(featured_artworks)
        items_to_duplicate = featured_artworks[:num_duplicates]
        featured_artworks_for_carousel = featured_artworks + items_to_duplicate
    else:
        featured_artworks_for_carousel = []
    # --- END NEW LOGIC ---

    testimonials = [
        {
            'name': 'Radha Devi',
            'feedback': 'The artwork is truly divine and brings immense peace to my home. Highly recommend Karthika Futures!',
            'rating': 5,
            'image': 'images/testimonial1.jpg',
            'product_sku': '89898'
        },
        {
            'name': 'Krishna Murthy',
            'feedback': 'Exceptional quality and prompt delivery. Each piece tells a story. A blessed experience!',
            'rating': 5,
            'image': 'images/testimonial2.jpg',
            'product_sku': '232323'
        },
        {
            'name': 'Priya Sharma',
            'feedback': 'Beautiful collection! The details are intricate and the colors vibrant. My meditation space feels complete.',
            'rating': 4,
            'image': 'images/testimonial3.jpg',
            'product_sku': '656565'
        },
    ]

    # Pass the new 'featured_artworks_for_carousel' list to your template
    return render_template(
        'index.html',
        categories=categories,  # This is the new line
        featured_artworks=featured_artworks_for_carousel, 
        testimonials=testimonials)

# MODIFIED: all_products route to pass categorized artworks
@app.route('/all-products')
def all_products():
    search_query = request.args.get('search', '')
    
    # Fetch all categories
    categories = Category.query.all()
    
    # Dictionary to hold artworks grouped by category
    categorized_artworks = {}

    for category in categories:
        if search_query:
            # Filter artworks within each category by search query
            artworks_in_category = Artwork.query.filter(
                Artwork.category_id == category.id,
                (Artwork.name.ilike(f'%{search_query}%')) |
                (Artwork.description.ilike(f'%{search_query}%')) |
                (Artwork.sku.ilike(f'%{search_query}%'))
            ).all()
        else:
            # Get all artworks for the category
            artworks_in_category = Artwork.query.filter_by(category_id=category.id).all()
        
        if artworks_in_category: # Only add category if it has artworks
            categorized_artworks[category.name] = artworks_in_category

    return render_template('all_products.html', 
                           categorized_artworks=categorized_artworks, 
                           search_query=search_query)

@app.route('/product/<string:sku>')
def product_detail(sku):
    artwork = Artwork.query.filter_by(sku=sku).first_or_404()
    
    # Convert Artwork object to a JSON-serializable dictionary
    artwork_data = {
        'id': artwork.id,
        'sku': artwork.sku,
        'name': artwork.name,
        'description': artwork.description,
        'original_price': float(artwork.original_price), # Convert Decimal to float
        'cgst_percentage': float(artwork.cgst_percentage),
        'sgst_percentage': float(artwork.sgst_percentage),
        'igst_percentage': float(artwork.igst_percentage),
        'ugst_percentage': float(artwork.ugst_percentage),
        'cess_percentage': float(artwork.cess_percentage), # NEW
        'gst_type': artwork.gst_type,
        'stock': artwork.stock,
        'is_featured': artwork.is_featured,
        'shipping_charge': float(artwork.shipping_charge), # Convert Decimal to float
        'image_url': artwork.get_images_list()[0] if artwork.get_images_list() else 'images/placeholder.png',
        'custom_options': artwork.get_custom_options_dict()
    }
    # Ensure Decimal values are converted to float or string for JSON serialization
    # For custom_options, ensure any Decimal values within are also converted if present
    # (though get_custom_options_dict should ideally handle this by storing floats/ints)
    
    return render_template('product_detail.html', artwork=artwork, artwork_data=artwork_data)




@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/order_summary/<order_id>') # This line defines the web address
@login_required # This means only logged-in users can see this page
def order_summary(order_id):
    # --- START OF CHANGES ---
    print(f"DEBUG: Entering order_summary for order_id: {order_id}")
    print(f"DEBUG: Current user ID: {current_user.id}")

    # 1. Find the order in the database
    #    Changed from .first_or_404() to .first() for more direct control and debugging
    #    and added explicit handling if order is None.
    if hasattr(current_user, 'is_admin') and current_user.is_admin:
        order = Order.query.filter_by(id=order_id).first()
    else:
        order = Order.query.filter_by(id=order_id, user_id=current_user.id).first()


    if not order:
        print(f"DEBUG: Order NOT found for ID={order_id} and user ID={current_user.id}.")
        flash('Order not found or you are not authorized to view it.', 'danger')
        return redirect(url_for('user_orders')) # Redirect to a safe page if order isn't found
    
    # If order is found, print its status
    print(f"DEBUG: Order found: ID={order.id}, email_sent_status: {order.email_sent_status}")

    # --- END OF CHANGES ---

    # 2. Check if the email has already been sent for this order
    #    If 'email_sent_status' is False, send the email
    if not order.email_sent_status:
        try:
            # Prepare the email subject
            subject = f"Order Confirmation - Your Order #{order.id} with {current_app.config.get('OUR_BUSINESS_NAME', 'Karthika Futures')}"

            # Get the recipient's email (usually the logged-in user's email)
            recipient_email = current_user.email 

            # 3. Create the HTML content for the email
            #    We use the new template you just created: 'email/order_confirmation.html'
            email_html_body = render_template('email/order_confirmation.html', order=order)

            # 4. Send the email using your updated send_email function
            if send_email(to_email=recipient_email, subject=subject, html_body=email_html_body):
                # If email sent successfully, update the order status in the database
                order.email_sent_status = True
                db.session.commit() # Save the change to the database

              # Hinding email confirmation by #. can acrivate if # removed <<<   flash('Order confirmation email sent successfully!', 'success')
            else:
                # If sending failed, show a message
                flash('Failed to send order confirmation email. Please contact support.', 'danger')
        except Exception as e:
            # If any other error occurs during email sending
            flash(f'An error occurred while sending email: {e}', 'danger')
            current_app.logger.error(f"Error sending order confirmation email for Order ID {order.id}: {e}")
    else: # Added for more explicit logging when email is already sent
        print(f"DEBUG: Email already sent for Order ID: {order.id}")


    # 5. Finally, show the order summary page to the user
    return render_template('order_summary.html', order=order)
@app.route('/payment_initiate/<order_id>/<amount>')
@login_required
def payment_initiate(order_id, amount):
    # Fix for LegacyAPIWarning
    order = db.session.get(Order, order_id)
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('user_orders'))

    if order.user_id != current_user.id:
        flash('You are not authorized to make payment for this order.', 'danger')
        return redirect(url_for('user_orders'))

    if order.status != 'Pending Payment':
        flash('This order is not pending payment or has already been processed.', 'warning')
        return redirect(url_for('order_summary', order_id=order.id))

    # Dummy UPI details for demonstration
    upi_id = "smarasada@okaxis" # Replace with your actual UPI ID
    banking_name = "Subhash S" # Replace with your banking name
    

    return render_template('payment_initiate.html', 
                       order=order, # <--- Pass the 'order' object here
                       amount=Decimal(amount), 
                       our_upi_id=upi_id, # Changed variable name to match template
                       our_banking_name=banking_name) # Changed variable name to match template
                       # Removed bank_name as it's not displayed in the template

@app.route('/payment_submit/<order_id>', methods=['POST'])
@login_required
def payment_submit(order_id):
    MAX_SCREENSHOT_SIZE = 1.5 * 1024 * 1024  # 1.5 MB

    order = db.session.get(Order, order_id)
    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('user_orders'))

    if order.user_id != current_user.id:
        flash('You are not authorized to submit payment for this order.', 'danger')
        return redirect(url_for('user_orders'))

    if order.status != 'Pending Payment':
        flash('This order is not pending payment or has already been processed.', 'warning')
        return redirect(url_for('order_summary', order_id=order.id))

    payment_screenshot = request.files.get('payment_screenshot')

    if not payment_screenshot:
        flash('Payment screenshot is required to confirm payment.', 'danger')
        return redirect(url_for('payment_initiate', order_id=order.id, amount=order.total_amount))

    if not allowed_file(payment_screenshot.filename):
        flash('Invalid file type for screenshot. Please upload an image.', 'warning')
        return redirect(url_for('payment_initiate', order_id=order.id, amount=order.total_amount))

    # Check file size before saving
    payment_screenshot.seek(0, os.SEEK_END)
    file_size = payment_screenshot.tell()
    payment_screenshot.seek(0)  # reset pointer

    if file_size > MAX_SCREENSHOT_SIZE:
        flash('Screenshot too large. Please upload an image smaller than 1.5 MB.', 'danger')
        return redirect(url_for('payment_initiate', order_id=order.id, amount=order.total_amount))

    # Upload file to Cloudinary and update order
    try:
        cloudinary_result = cloudinary.uploader.upload(payment_screenshot, folder="payment_screenshots")
        if cloudinary_result:
            order.payment_screenshot = cloudinary_result['secure_url']
            order.status = 'Payment Submitted - Awaiting Verification'
            order.payment_status = 'submitted'
            db.session.commit()
            flash('Success! Your order has been placed.', 'success')
            return redirect(url_for('order_summary', order_id=order.id))
        else:
            flash('Failed to upload payment screenshot to Cloudinary. Please try again.', 'danger')
            return redirect(url_for('payment_initiate', order_id=order.id, amount=order.total_amount))
    except Exception as e:
        app.logger.error(f"Cloudinary upload failed for payment screenshot: {e}")
        flash('An error occurred during file upload. Please try again.', 'danger')
        return redirect(url_for('payment_initiate', order_id=order.id, amount=order.total_amount))# NEW: Route for the Thank You page
# CHANGED: <int:order_id> to <string:order_id>
@app.route('/thank-you/<string:order_id>') 
@login_required # If only logged-in users can view their orders
def thank_you_page(order_id):
    # Fetch the order using filter_by because the ID is a string
    order = Order.query.filter_by(id=order_id).first_or_404()
    
    # Optional: Add security check to ensure user can only view their own order
    if order.user_id != current_user.id:
        flash("You do not have permission to view this order.", "danger")
        return redirect(url_for('user_orders')) # or 'index'
    

    # Insert here to clear cart session
    session['cart'] = {}
    session.modified = True
    
    return render_template('thank_you.html', order=order)


# --- Admin Routes ---
@app.route('/admin-login', methods=['GET', 'POST'])
@csrf.exempt # Exempt CSRF for this route as it's a simple login form
def admin_login():
    if current_user.is_authenticated and current_user.is_admin():
        return redirect(url_for('admin_dashboard'))

    form_data = {}
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        form_data = {'email': email}

        user = User.query.filter_by(email=email, role='admin').first()
        if user and user.check_password(password):
            login_user(user)
            flash('Admin logged in successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html', form_data=form_data)

@app.route('/admin-dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_artworks = Artwork.query.count()
    total_orders = Order.query.count()
    pending_orders_count = Order.query.filter(Order.status.in_(['Pending Payment', 'Payment Submitted - Awaiting Verification'])).count()

    # Revenue calculation (simplified for dashboard)
    # This sums up total_amount of completed orders
    total_revenue_query = db.session.query(func.sum(Order.total_amount)).filter_by(payment_status='completed').scalar()
    total_revenue = total_revenue_query if total_revenue_query is not None else Decimal('0.00')

    # Orders pending admin review (e.g., payment verification, held invoices)
    orders_pending_review = Order.query.filter(
        (Order.status == 'Payment Submitted - Awaiting Verification') |
        (Order.invoice_details.like('%"is_held_by_admin": true%')) # Check JSON string for held invoices
    ).order_by(Order.order_date.desc()).all()

    # All orders with search and filter
    search_query = request.args.get('search', '')
    filter_status = request.args.get('filter_status', '')
    
    orders_query = Order.query.order_by(Order.order_date.desc())

    if search_query:
        orders_query = orders_query.join(User).filter(
            (Order.id.ilike(f'%{search_query}%')) |
            (User.full_name.ilike(f'%{search_query}%')) | # Corrected variable name
            (User.email.ilike(f'%{search_query}%'))
        )
    if filter_status:
        orders_query = orders_query.filter_by(status=filter_status)
    
    orders = orders_query.all()

    # Low stock and out of stock artworks
    low_stock_artworks = Artwork.query.filter(Artwork.stock > 0, Artwork.stock <= 10).all()
    out_of_stock_artworks = Artwork.query.filter_by(stock=0).all()

    # Monthly Revenue for Chart (Last 6 months)
    revenue_labels = []
    revenue_values = []
    for i in range(6, 0, -1):
        month_start = (datetime.utcnow() - timedelta(days=30*i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=30)).replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1) # End of month
        
        monthly_revenue = db.session.query(func.sum(Order.total_amount)).filter(
            Order.order_date >= month_start,
            Order.order_date < month_end,
            Order.payment_status == 'completed'
        ).scalar()
        
        revenue_labels.append(month_start.strftime('%b %Y'))
        revenue_values.append(float(monthly_revenue) if monthly_revenue is not None else 0.0)

    return render_template('admin_dashboard.html',
                           total_users=total_users,
                           total_artworks=total_artworks,
                           total_orders=total_orders,
                           pending_orders=pending_orders_count, # Renamed for clarity
                           total_revenue=total_revenue,
                           orders_pending_review=orders_pending_review,
                           orders=orders,
                           search_query=search_query,
                           filter_status=filter_status,
                           low_stock_artworks=low_stock_artworks,
                           out_of_stock_artworks=out_of_stock_artworks,
                           revenue_labels=revenue_labels,
                           revenue_values=revenue_values)

@app.route('/admin/verify-payment', methods=['POST'])
@login_required
@admin_required
@csrf.exempt # Handled by X-CSRFToken header
def admin_verify_payment():
    order_id = request.form.get('order_id')
    # Fix for LegacyAPIWarning
    order = db.session.get(Order, order_id)
    if order:
        order.status = 'Payment Verified – Preparing Order'
        order.payment_status = 'completed' # Ensure payment status is also completed
        db.session.commit()
        flash(f'Payment for Order ID {order_id} verified successfully!', 'success')
        return jsonify(success=True, message='Payment verified.')
    return jsonify(success=False, message='Order not found.'), 404

@app.route('/admin/order/update_status/<order_id>', methods=['POST'])
@login_required
@admin_required
@csrf.exempt # Handled by X-CSRFToken header
def admin_update_order_status(order_id): # Added order_id to arguments
    try:
        data = request.get_json()
        # order_id is now correctly passed as a path parameter, no need to get from data
        # Fix for LegacyAPIWarning
        order = db.session.get(Order, order_id)
        if not order:
            return jsonify(success=False, message='Order not found.'), 404

        new_status = data.get('status')
        remark = data.get('remark')
        courier = data.get('courier')
        tracking_number = data.get('tracking_number')
        cancellation_reason = data.get('cancellation_reason') # New: capture cancellation reason

        if new_status:
            order.status = new_status
            order.remark = remark
            order.courier = courier
            order.tracking_number = tracking_number
            order.cancellation_reason = cancellation_reason # Save cancellation reason

            # Update payment status based on order status for consistency
            if 'Cancelled' in new_status:
                order.payment_status = 'cancelled'
            elif new_status == 'Delivered':
                order.payment_status = 'completed' # Assuming payment was completed before delivery
            # Other statuses like 'Shipped', 'Preparing Order' can keep payment_status as 'completed'
            # if it was already marked as such after initial verification.

            db.session.commit()
            flash(f'Order {order_id} status updated to {new_status}.', 'success')
            return jsonify(success=True, message='Order status updated.')
        return jsonify(success=False, message='Invalid status provided.'), 400
    except Exception as e:
        db.session.rollback() # Rollback in case of error
        print(f"Error updating order status for {order_id}: {e}")
        return jsonify(success=False, message='An internal server error occurred.'), 500



@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/delete-user/<user_id>', methods=['POST']) # Corrected from @app.Route
@login_required
@admin_required
def admin_delete_user(user_id):
    # Fix for LegacyAPIWarning
    user = db.session.get(User, user_id)
    if user:
        if user.is_admin(): # Changed to call is_admin()
            flash('Cannot delete an admin user directly.', 'danger')
            return redirect(url_for('admin_users'))
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.email} deleted successfully.', 'success')
    else:
        flash('User not found.', 'danger')
    return redirect(url_for('admin_users'))

@app.route('/admin/order/<order_id>')
@login_required
@admin_required
def admin_order_details(order_id):
    order = Order.query.filter_by(id=order_id).first_or_404()
    return render_template('admin_order_details.html', order=order)


@app.route('/admin/categories')
@login_required
@admin_required
def admin_categories():
    categories = Category.query.all()
    return render_template('admin_categories.html', categories=categories)

@app.route('/admin/add-category', methods=['POST'])
@login_required
@admin_required
def admin_add_category():
    name = request.form.get('category_name')
    if name:
        existing_category = Category.query.filter_by(name=name).first()
        if existing_category:
            flash(f'Category "{name}" already exists.', 'warning')
        else:
            new_category = Category(name=name)
            db.session.add(new_category)
            db.session.commit()
            flash(f'Category "{name}" added successfully!', 'success')
    else:
        flash('Category name cannot be empty.', 'danger')
    return redirect(url_for('admin_categories'))

@app.route('/admin/edit-category/<category_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_category(category_id):
    category = Category.query.get_or_404(category_id)
    if request.method == 'POST':
        new_name = request.form.get('name')
        description = request.form.get('description')
        
        if new_name and new_name != category.name:
            existing_category = Category.query.filter_by(name=new_name).first()
            if existing_category and existing_category.id != category.id:
                flash(f'Category name "{new_name}" already exists.', 'danger')
                return render_template('admin_edit_category.html', category=category)
            category.name = new_name
        
        category.description = description

        # Handle image upload
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = str(uuid.uuid4()) + '_' + filename
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                # Delete old image if exists
                if category.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(category.image))):
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(category.image)))
                category.image = 'uploads/' + unique_filename
            elif file and not allowed_file(file.filename):
                flash('Invalid image file type.', 'danger')
                return render_template('admin_edit_category.html', category=category)

        db.session.commit()
        flash('Category updated successfully!', 'success')
        return redirect(url_for('admin_categories'))
    return render_template('admin_edit_category.html', category=category)

@app.route('/delete-selected-orders', methods=['POST'])
@login_required

def delete_selected_orders():
    selected_ids = request.form.getlist('selected_orders[]')  # Use the [] version here too
    if not selected_ids:
        flash("No orders selected for deletion.", "warning")
        return redirect(url_for('admin_orders_view'))

    for order_id in selected_ids:
        order = Order.query.filter_by(id=order_id).first()
        if order:
            db.session.delete(order)
    db.session.commit()
    flash(f"{len(selected_ids)} order(s) deleted successfully.", "success")
    return redirect(url_for('admin_orders_view'))


@app.route('/admin/delete-category/<category_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_category(category_id):
    # Fix for LegacyAPIWarning
    category = db.session.get(Category, category_id)
    if category:
        # Check if there are artworks associated with this category
        if category.artworks:
            flash(f'Cannot delete category "{category.name}" because it has associated artworks. Please reassign or delete artworks first.', 'danger')
            return redirect(url_for('admin_categories'))
        
        # Delete category image if exists
        if category.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(category.image))):
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(category.image)))

        db.session.delete(category)
        db.session.commit()
        flash(f'Category "{category.name}" deleted successfully.', 'success')
    else:
        flash('Category not found.', 'danger')
    return redirect(url_for('admin_categories'))

@app.route('/admin/artworks')
@login_required
@admin_required
def admin_artworks():
    artworks = Artwork.query.all()

    # ADD THE DEBUGGING CODE HERE
    for artwork in artworks:
        print(f"Artwork SKU: {artwork.sku}, Images: {artwork.images}, List: {artwork.get_images_list()}")
    
    return render_template('admin_artworks.html', artworks=artworks)
    

@app.route('/admin/add-artwork', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_artwork():
    categories = Category.query.all()
    form_data = {} # Initialize form_data for GET requests
    if request.method == 'POST':
        sku = request.form.get('sku')
        name = request.form.get('name')
        description = request.form.get('description')
        # Use .get() with a default value to prevent NoneType errors
        original_price = request.form.get('original_price', '0.00')
        
        # New GST fields - provide default '0.00' if not present
        cgst_percentage = request.form.get('cgst_percentage', '0.00')
        sgst_percentage = request.form.get('sgst_percentage', '0.00')
        igst_percentage = request.form.get('igst_percentage', '0.00')
        ugst_percentage = request.form.get('ugst_percentage', '0.00')
        cess_percentage = request.form.get('cess_percentage', '0.00') # NEW
        gst_type = request.form.get('gst_type')

        stock = request.form.get('stock', '0') # Default to '0' for stock
        category_id = request.form.get('category_id')
        is_featured = 'is_featured' in request.form # Checkbox
        custom_options_json = request.form.get('custom_options') # JSON string from JS
        shipping_charge = request.form.get('shipping_charge', '0.00') # NEW: Default to '0.00'
        shipping_slab_size = int(request.form.get('shipping_slab_size', 3))

        # Populate form_data for re-rendering on error
        form_data = {
            'sku': sku, 'name': name, 'description': description,
            'original_price': original_price, 'cgst_percentage': cgst_percentage,
            'sgst_percentage': sgst_percentage, 'igst_percentage': igst_percentage,
            'ugst_percentage': ugst_percentage, 'cess_percentage': cess_percentage, # NEW
            'gst_type': gst_type,
            'stock': stock, 'category_id': category_id, 'is_featured': is_featured,
            'shipping_charge': shipping_charge
        }
        if custom_options_json:
            try:
                form_data['custom_option_groups'] = json.loads(custom_options_json)
            except json.JSONDecodeError:
                form_data['custom_option_groups'] = {} # Invalid JSON, treat as empty

        if not all([sku, name, category_id, gst_type]): # Removed original_price and stock from this check
            flash('Please fill in all required fields (SKU, Name, Category, GST Type).', 'danger')
            return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)

        try:
            original_price = Decimal(original_price)
            cgst_percentage = Decimal(cgst_percentage)
            sgst_percentage = Decimal(sgst_percentage)
            igst_percentage = Decimal(igst_percentage)
            ugst_percentage = Decimal(ugst_percentage)
            cess_percentage = Decimal(cess_percentage) # NEW
            stock = int(stock)
            shipping_charge = Decimal(shipping_charge) # NEW: Convert to Decimal
        except (ValueError, InvalidOperation):
            flash('Invalid numeric value for price, GST percentage, stock quantity, or shipping charge.', 'danger')
            return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)

        existing_artwork = Artwork.query.filter_by(sku=sku).first()
        if existing_artwork:
            flash(f'Artwork with SKU "{sku}" already exists.', 'danger')
            return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)

        image_paths = []
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and allowed_file(file.filename):
                    # Upload to Cloudinary and get the public URL
                    upload_result = cloudinary.uploader.upload(file)
                    image_paths.append(upload_result['secure_url'])
                elif file.filename != '': # If file is present but not allowed
                    flash(f'Invalid file type for image: {file.filename}.', 'danger')
                    return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)
       
        new_artwork = Artwork(
            sku=sku,
            name=name,
            description=description,
            original_price=original_price,
            cgst_percentage=cgst_percentage,
            sgst_percentage=sgst_percentage,
            igst_percentage=igst_percentage,
            ugst_percentage=ugst_percentage,
            cess_percentage=cess_percentage, # NEW
            gst_type=gst_type,
            stock=stock,
            category_id=category_id,
            is_featured=is_featured,
            shipping_charge=shipping_charge # NEW: Assign shipping charge
        )
        new_artwork.set_images_list(image_paths) # Store image paths as JSON
        
        # Store custom options as JSON
        if custom_options_json:
            try:
                # Validate if it's valid JSON before saving
                json.loads(custom_options_json)
                new_artwork.custom_options = custom_options_json
            except json.JSONDecodeError:
                flash('Invalid format for custom options JSON.', 'danger')
                return render_template('admin_add_artwork.html', categories=categories, form_data=form_data)

        db.session.add(new_artwork)
        db.session.commit()
        flash('Artwork added successfully!', 'success')
        return redirect(url_for('admin_artworks'))

    return render_template('admin_add_artwork.html', categories=categories, form_data=form_data) # Always pass form_data

@app.route('/admin/edit-artwork/<artwork_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_artwork(artwork_id):
    artwork = Artwork.query.get_or_404(artwork_id)
    categories = Category.query.all()

    if request.method == 'POST':
        # Retrieve form data
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        is_featured = 'is_featured' in request.form
        # Use .get() with a default value to prevent NoneType errors
        original_price = request.form.get('original_price', '0.00')
        
        # New GST fields - provide default '0.00' if not present
        cgst_percentage = request.form.get('cgst_percentage', '0.00')
        sgst_percentage = request.form.get('sgst_percentage', '0.00')
        igst_percentage = request.form.get('igst_percentage', '0.00')
        ugst_percentage = request.form.get('ugst_percentage', '0.00')
        cess_percentage = request.form.get('cess_percentage', '0.00') # NEW
        stock = request.form.get('stock', '0') # Default to '0' for stock
        description = request.form.get('description')
        shipping_charge = request.form.get('shipping_charge', '0.00') # NEW: Default to '0.00'
        gst_type = request.form.get('gst_type') # NEW

        # Get images to keep (hidden inputs from frontend)
        images_to_keep = request.form.getlist('images_to_keep')
        
        # Get custom options JSON string
        custom_options_json_str = request.form.get('custom_options_json') # This name needs to match frontend

        # Update artwork object
        artwork.name = name
        artwork.category_id = category_id
        artwork.is_featured = is_featured
        artwork.description = description
        artwork.gst_type = gst_type # NEW

        try:
            artwork.original_price = Decimal(original_price)
            artwork.cgst_percentage = Decimal(cgst_percentage)
            artwork.sgst_percentage = Decimal(sgst_percentage)
            artwork.igst_percentage = Decimal(igst_percentage)
            artwork.ugst_percentage = Decimal(ugst_percentage)
            artwork.cess_percentage = Decimal(cess_percentage) # NEW
            artwork.stock = int(stock)
            artwork.shipping_charge = Decimal(shipping_charge) # NEW: Assign shipping charge
        except (ValueError, InvalidOperation):
            flash('Invalid numeric value for price, GST percentage, stock quantity, or shipping charge.', 'danger')
            # Pass form data back to template to re-populate
            form_data = request.form.to_dict()
            form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else {} # Ensure it's a dict
            return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

        # Handle new image uploads
        new_image_paths = []
        if 'new_images' in request.files:
            for file in request.files.getlist('new_images'):
                if file and allowed_file(file.filename):
                    # Upload to Cloudinary and get the public URL
                    upload_result = cloudinary.uploader.upload(file)
                    new_image_paths.append(upload_result['secure_url'])
                elif file.filename != '': # If file is present but not allowed
                    flash(f'Invalid file type for new image: {file.filename}.', 'danger')
                    form_data = request.form.to_dict()
                    form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else {} # Ensure it's a dict
                    return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

        # Combine old images to keep and new images
        final_image_list = images_to_keep + new_image_paths
        artwork.set_images_list(final_image_list)


        # Update custom options
        if custom_options_json_str:
            try:
                # Validate and save
                json.loads(custom_options_json_str)
                artwork.custom_options = custom_options_json_str
            except json.JSONDecodeError:
                flash('Invalid format for custom options JSON.', 'danger')
                form_data = request.form.to_dict()
                form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else {} # Ensure it's a dict
                return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)
        else:
            artwork.custom_options = None # Clear if no options are submitted

        db.session.commit()
        flash('Artwork updated successfully!', 'success')
        return redirect(url_for('admin_artworks'))

    # For GET request, prepare form_data from existing artwork
    form_data = {
        'name': artwork.name,
        'category_id': artwork.category_id,
        'is_featured': artwork.is_featured,
        'original_price': artwork.original_price,
        'cgst_percentage': artwork.cgst_percentage,
        'sgst_percentage': artwork.sgst_percentage,
        'igst_percentage': artwork.igst_percentage,
        'ugst_percentage': artwork.ugst_percentage,
        'cess_percentage': artwork.cess_percentage, # NEW
        'gst_type': artwork.gst_type,
        'stock': artwork.stock,
        'description': artwork.description,
        'shipping_charge': artwork.shipping_charge, # NEW: Pass shipping charge
        # Pass the dictionary directly, it will be converted to JSON string by tojson in template
        'custom_option_groups': artwork.get_custom_options_dict() 
    }
    # No need to convert custom_option_groups dict to a list of dicts here.
    # The JS in admin_edit_artwork.html expects the raw dictionary from get_custom_options_dict()
    # and handles its own formatting for display.

    return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

# In app.py
from flask import flash, redirect, url_for
from sqlalchemy.exc import IntegrityError  # Import IntegrityError


import os
from flask import current_app
# deletes physical file also
@app.route('/admin/artwork/delete/<string:artwork_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_artwork(artwork_id):
    try:
        artwork = db.session.get(Artwork, artwork_id)
        if not artwork:
            flash('Artwork not found.', 'danger')
            return redirect(url_for('admin_artworks'))

        # Check for associated orders before attempting deletion
        has_orders = OrderItem.query.filter_by(artwork_id=artwork.id).first()
        if has_orders:
            flash("Cannot delete artwork: It is linked to existing orders. Please handle the orders first.", 'danger')
            return redirect(url_for('admin_artworks'))

        # Get the path to the uploads folder
        uploads_dir = os.path.join(current_app.root_path, 'static', 'uploads')
        
        # Split the artwork.images string into individual filenames
        image_filenames = artwork.images.split(',') if artwork.images else []

        # Delete each image file
        for filename in image_filenames:
            image_path = os.path.join(uploads_dir, filename)
            if os.path.exists(image_path):
                os.remove(image_path)
                print(f"Deleted image file: {image_path}")
        
        # Delete the artwork record from the database
        db.session.delete(artwork)
        db.session.commit()
        
        flash(f'Artwork "{artwork.name}" and its images have been deleted successfully.', 'success')
        return redirect(url_for('admin_artworks'))

    except IntegrityError as e:
        db.session.rollback()
        flash(f"Deletion failed due to a database constraint. Error: {str(e)}", 'danger')
        return redirect(url_for('admin_artworks'))
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting artwork: {e}")
        flash('An unexpected error occurred while deleting the artwork.', 'danger')
        return redirect(url_for('admin_artworks'))    

@app.route('/admin/edit-invoice/<order_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_invoice(order_id):
    order = Order.query.get_or_404(order_id)
    
    if request.method == 'POST':
        # Collect all invoice details from the form
        invoice_details = {
            'business_name': request.form.get('business_name'),
            'gst_number': request.form.get('gst_number'),
            'pan_number': request.form.get('pan_number'),
            'business_address': request.form.get('business_address'),
            'invoice_number': request.form.get('invoice_number'),
            'invoice_date': request.form.get('invoice_date'),
            'billing_address': request.form.get('billing_address'), # This field is not in the HTML, but kept for completeness if you add it
            # Convert Decimal types to string before storing in JSON
            'gst_rate_applied': str(Decimal(request.form.get('gst_rate', '0.00'))), 
            'shipping_charge': str(Decimal(request.form.get('shipping_charge', '0.00'))), 
            'final_invoice_amount': str(Decimal(request.form.get('total_amount', '0.00'))), 
            'invoice_status': request.form.get('invoice_status', 'Generated'), # Default if not explicitly set
            'is_held_by_admin': 'is_held_by_admin' in request.form, # Checkbox
            'cgst_amount': str(Decimal(request.form.get('cgst_amount', '0.00'))), 
            'sgst_amount': str(Decimal(request.form.get('sgst_amount', '0.00'))),
            'igst_amount': str(Decimal(request.form.get('igst_amount', '0.00'))),
            'ugst_amount': str(Decimal(request.form.get('ugst_amount', '0.00'))),
            'cess_amount': str(Decimal(request.form.get('cess_amount', '0.00'))) # NEW
        }
        
        order.set_invoice_details(invoice_details)
        # Ensure that when updating order.shipping_charge and order.total_amount,
        # they are converted back to Decimal from the string in invoice_details
        order.shipping_charge = Decimal(invoice_details['shipping_charge']) 
        order.total_amount = Decimal(invoice_details['final_invoice_amount']) 
        db.session.commit()
        flash('Invoice details updated successfully!', 'success')
        return redirect(url_for('admin_dashboard')) # Or admin_orders_view if you create one
    
    # For GET request, parse invoice_details and convert date strings back to datetime objects
    invoice_data = order.get_invoice_details()
    if 'invoice_date' in invoice_data and invoice_data['invoice_date']:
        try:
            invoice_data['invoice_date'] = datetime.strptime(invoice_data['invoice_date'], '%Y-%m-%d')
        except ValueError:
            invoice_data['invoice_date'] = None # Handle potential format issues
    if 'due_date' in invoice_data and invoice_data['due_date']:
        try:
            invoice_data['due_date'] = datetime.strptime(invoice_data['due_date'], '%Y-%m-%d')
        except ValueError:
            invoice_data['due_date'] = None # Handle potential format issues

    return render_template('admin_edit_invoice.html', order=order, invoice_data=invoice_data)


# Helper function to generate the flowables for a single invoice copy
def _get_single_invoice_flowables(order, invoice_data_safe, styles, font_name, font_name_bold):
    story_elements = []

    # Header
    story_elements.append(Paragraph(invoice_data_safe['business_name'], styles['h1']))
    story_elements.append(Paragraph(invoice_data_safe['business_address'], styles['Normal']))
    story_elements.append(Paragraph(f"GSTIN: {invoice_data_safe['gst_number']} | PAN: {invoice_data_safe['pan_number']}", styles['Normal']))
    story_elements.append(Spacer(1, 0.05 * inch)) # Reduced space

    # Invoice Title and Details
    story_elements.append(Paragraph("TAX INVOICE", styles['h2']))
    
    # Use a two-column table for Invoice No and Date for better alignment
    invoice_header_data = [
        [Paragraph(f"<b>Invoice No:</b> {invoice_data_safe['invoice_number']}", styles['BoldBodyText']),
         Paragraph(f"<b>Invoice Date:</b> {invoice_data_safe['invoice_date_dt'].strftime('%d-%m-%Y')}", styles['RightAlign'])]
    ]
    invoice_header_table = Table(invoice_header_data, colWidths=[3.25*inch, 3.25*inch]) # Still using 3.25*inch for each, but total width is 6.5 inch
    invoice_header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story_elements.append(invoice_header_table)
    story_elements.append(Spacer(1, 0.05 * inch)) # Reduced space

    # Billing Address
    story_elements.append(Paragraph("<b>Bill To:</b>", styles['BoldBodyText']))
    # Split the consolidated address into lines for better formatting
    billing_address_lines = invoice_data_safe['billing_address'].split(', ')
    # Filter out empty strings that might result from missing address parts
    billing_address_paragraphs = [Paragraph(line, styles['Normal']) for line in filter(None, billing_address_lines)]
    story_elements.extend(billing_address_paragraphs)
    story_elements.append(Spacer(1, 0.05 * inch)) # Reduced space

    # Order Items Table
    data = [
        [
            Paragraph('SKU', styles['BoldBodyText']),
            Paragraph('Artwork Name', styles['BoldBodyText']),
            Paragraph('Options', styles['BoldBodyText']),
            Paragraph('Unit Price (Excl. GST)', styles['BoldBodyText']),
            Paragraph('Qty', styles['BoldBodyText']),
            Paragraph('Taxable Value', styles['BoldBodyText']), # NEW
            Paragraph('CGST', styles['BoldBodyText']),
            Paragraph('SGST', styles['BoldBodyText']),
            Paragraph('IGST', styles['BoldBodyText']),
            Paragraph('UGST', styles['BoldBodyText']),
            Paragraph('CESS', styles['BoldBodyText']), # NEW
            Paragraph('Total (Incl. GST)', styles['BoldBodyText'])
        ]
    ]
    
    total_cgst_items = Decimal('0.00')
    total_sgst_items = Decimal('0.00')
    total_igst_items = Decimal('0.00')
    total_ugst_items = Decimal('0.00')
    total_cess_items = Decimal('0.00') # NEW
    for item in order.items:
        options_str = ", ".join([f"{k}: {v}" for k, v in item.get_selected_options_dict().items()])
        
        # Ensure Decimal values are converted to string for display in PDF
        unit_price_excl_gst_display = f"₹{item.unit_price_before_gst:,.2f}"
        taxable_value_display = f"₹{item.total_price_before_gst:,.2f}" # NEW
        
        # Conditional display for GST components
        cgst_display = f"₹{item.cgst_amount:,.2f} ({item.cgst_percentage_applied}%)" if item.cgst_amount > Decimal('0.00') else ""
        sgst_display = f"₹{item.sgst_amount:,.2f} ({item.sgst_percentage_applied}%)" if item.sgst_amount > Decimal('0.00') else ""
        igst_display = f"₹{item.igst_amount:,.2f} ({item.igst_percentage_applied}%)" if item.igst_amount > Decimal('0.00') else ""
        ugst_display = f"₹{item.ugst_amount:,.2f} ({item.ugst_percentage_applied}%)" if item.ugst_amount > Decimal('0.00') else ""
        cess_display = f"₹{item.cess_amount:,.2f} ({item.cess_percentage_applied}%)" if item.cess_amount > Decimal('0.00') else "" # NEW
        
        total_incl_gst_display = f"₹{item.total_price_incl_gst:,.2f}"

        data.append([
            Paragraph(item.artwork.sku, styles['TableCell']),
            Paragraph(item.artwork.name, styles['TableCellLeft']),
            Paragraph(options_str, styles['TableCellLeft']),
            Paragraph(unit_price_excl_gst_display, styles['TableCellRight']),
            Paragraph(str(item.quantity), styles['TableCell']),
            Paragraph(taxable_value_display, styles['TableCellRight']), # NEW
            Paragraph(cgst_display, styles['TableCellRight']),
            Paragraph(sgst_display, styles['TableCellRight']),
            Paragraph(igst_display, styles['TableCellRight']),
            Paragraph(ugst_display, styles['TableCellRight']),
            Paragraph(cess_display, styles['TableCellRight']), # NEW
            Paragraph(total_incl_gst_display, styles['TableCellRight'])
        ])
        total_cgst_items += item.cgst_amount
        total_sgst_items += item.sgst_amount
        total_igst_items += item.igst_amount
        total_ugst_items += item.ugst_amount
        total_cess_items += item.cess_amount # NEW

    # Adjusted colWidths to better fit content and distribute space for 12 columns
    # Total width is A4[0] - 2*0.3 inches (margins) = 7.67 inches. Let's make it 7.5 inches for easier division.
    col_widths = [
        0.5*inch, # SKU
        1.0*inch, # Artwork Name
        0.9*inch, # Options
        0.8*inch, # Unit Price (Excl. GST)
        0.3*inch, # Qty
        0.8*inch, # Taxable Value (NEW)
        0.6*inch, # CGST
        0.6*inch, # SGST
        0.6*inch, # IGST
        0.6*inch, # UGST
        0.5*inch, # CESS (NEW)
        0.8*inch  # Total (Incl. GST)
    ]
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#FFBF00')), # Golden Saffron header
        ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#FFFFFF')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'), # Align artwork name left
        ('ALIGN', (2, 0), (2, -1), 'LEFT'), # Align options left
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'), # Align unit price right
        ('ALIGN', (4, 0), (4, -1), 'CENTER'), # Align quantity center
        ('ALIGN', (5, 0), (-1, -1), 'RIGHT'), # Align Taxable Value, GST and total amounts right
        ('FONTNAME', (0, 0), (-1, 0), font_name_bold), # Use registered bold font
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4), # Reduced padding
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#FAF9F6')), # Light background for rows
        ('GRID', (0, 0), (-1, -1), 0.25, HexColor('#E5E7EB')), # Lighter grid lines
        ('BOX', (0, 0), (-1, -1), 0.25, HexColor('#E5E7EB')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 2), # Further reduced padding
        ('RIGHTPADDING', (0,0), (-1,-1), 2), # Further reduced padding
        ('TOPPADDING', (0,0), (-1,-1), 2), # Further reduced padding
        ('BOTTOMPADDING', (0,0), (-1,-1), 2), # Further reduced padding
    ]))
    story_elements.append(table)
    story_elements.append(Spacer(1, 0.05 * inch)) # Reduced space

    # Summary Table
    summary_data = []
    summary_data.append([Paragraph('Subtotal (Excl. GST):', styles['RightAlign']), Paragraph(f"₹{order.total_amount - order.shipping_charge - total_cgst_items - total_sgst_items - total_igst_items - total_ugst_items - total_cess_items:,.2f}", styles['RightAlign'])]) # Adjusted calculation
    if total_cgst_items > Decimal('0.00'):
        summary_data.append([Paragraph('CGST:', styles['RightAlign']), Paragraph(f"₹{total_cgst_items:,.2f}", styles['RightAlign'])])
    if total_sgst_items > Decimal('0.00'):
        summary_data.append([Paragraph('SGST:', styles['RightAlign']), Paragraph(f"₹{total_sgst_items:,.2f}", styles['RightAlign'])])
    if total_igst_items > Decimal('0.00'):
        summary_data.append([Paragraph('IGST:', styles['RightAlign']), Paragraph(f"₹{total_igst_items:,.2f}", styles['RightAlign'])])
    if total_ugst_items > Decimal('0.00'):
        summary_data.append([Paragraph('UGST:', styles['RightAlign']), Paragraph(f"₹{total_ugst_items:,.2f}", styles['RightAlign'])])
    if total_cess_items > Decimal('0.00'): # NEW: Conditional CESS display
        summary_data.append([Paragraph('CESS:', styles['RightAlign']), Paragraph(f"₹{total_cess_items:,.2f}", styles['RightAlign'])])
    
    summary_data.append([Paragraph('Shipping Charge:', styles['RightAlign']), Paragraph(f"₹{order.shipping_charge:,.2f}", styles['RightAlign'])])
    summary_data.append([Paragraph('<b>Grand Total (Incl. GST):</b>', styles['BoldBodyText']), Paragraph(f"<b>₹{order.total_amount:,.2f}</b>", styles['BoldBodyText'])])
    
    summary_table = Table(summary_data, colWidths=[5*inch, 2.5*inch]) # Adjusted total width to 7.5 inches
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), font_name_bold), # Bold for Grand Total
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2), # Reduced padding
        ('GRID', (0, 0), (-1, -1), 0.25, HexColor('#E5E7EB')),
        ('BOX', (0, 0), (-1, -1), 0.25, HexColor('#E5E7EB')),
    ]))
    story_elements.append(summary_table)
    story_elements.append(Spacer(1, 0.1 * inch)) # Reduced space

    # WhatsApp Message
    story_elements.append(Paragraph("Please WhatsApp to +919123700057 for easy returns and refund.", styles['Normal']))
    story_elements.append(Spacer(1, 0.1 * inch)) # Reduced space

    # Authorized Signatory and Office Seal Block
    story_elements.append(Spacer(1, 0.2 * inch)) # Add some space before the signature block

    signature_data = [
        [Paragraph("<b>For Karthika Futures</b>", styles['RightAlign'])],
        [Spacer(1, 0.5 * inch)], # Space for signature
        [Paragraph("_________________________", styles['RightAlign'])], # Corrected line
        [Paragraph("<b>Authorized Signatory</b>", styles['RightAlign'])],
        [Spacer(1, 0.1 * inch)], # Space between signatory and seal area
        [Paragraph(f"Date: {datetime.now().strftime('%d-%m-%Y')}", styles['RightAlign'])], # Date for ink seal
        [Paragraph("(Office Seal)", styles['RightAlign'])] # Placeholder for office seal
    ]

    signature_table = Table(signature_data, colWidths=[7.5*inch]) # Table spans full content width
    signature_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('ALIGN', (0,2), (0,2), 'RIGHT'),
        ('ALIGN', (0,3), (0,3), 'RIGHT'),
        ('ALIGN', (0,5), (0,5), 'RIGHT'),
        ('ALIGN', (0,6), (0,6), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story_elements.append(signature_table)

    story_elements.append(Spacer(1, 0.1 * inch)) # Space before footer

    # Footer
    story_elements.append(Paragraph("Thank you for your purchase and devotion!", styles['Normal']))
    story_elements.append(Paragraph(f"Invoice Status: <b>{invoice_data_safe['invoice_status']}</b>", styles['BoldBodyText']))
    story_elements.append(Spacer(1, 0.05 * inch)) # Reduced space
    story_elements.append(Paragraph(f"Contact: {order.customer_phone if order.customer_phone else 'N/A'} | {order.customer_email if order.customer_email else 'N/A'}", styles['Footer']))

    return story_elements


@app.route('/generate_invoice_pdf/<order_id>')
@login_required
@admin_required
def generate_invoice_pdf(order_id):
    if SimpleDocTemplate is None:
        flash('PDF generation library (ReportLab) is not installed.', 'danger')
        return redirect(url_for('admin_edit_invoice', order_id=order_id))

    order = Order.query.get_or_404(order_id)
    invoice_data = order.get_invoice_details()

    # Ensure all necessary invoice_data fields are present, provide defaults if not
    invoice_data_safe = {
        'business_name': invoice_data.get('business_name') or app.config['OUR_BUSINESS_NAME'],
        'gst_number': invoice_data.get('gst_number') or app.config['OUR_GSTIN'],
        'pan_number': invoice_data.get('pan_number') or app.config['OUR_PAN'],
        'business_address': invoice_data.get('business_address') or app.config['OUR_BUSINESS_ADDRESS'],
        'invoice_number': invoice_data.get('invoice_number') or order.id,
        'invoice_date': invoice_data.get('invoice_date') or datetime.utcnow().strftime('%Y-%m-%d'),
        'billing_address': invoice_data.get('billing_address') or ', '.join(filter(None, [order.customer_name, order.customer_phone, order.get_shipping_address().get('address_line1'), order.get_shipping_address().get('address_line2'), order.get_shipping_address().get('city'), order.get_shipping_address().get('state'), order.get_shipping_address().get('pincode')])), # Consolidated
        'gst_rate_applied': Decimal(invoice_data.get('gst_rate_applied', '0.00')), 
        'shipping_charge': Decimal(invoice_data.get('shipping_charge', '0.00')), 
        'final_invoice_amount': Decimal(invoice_data.get('final_invoice_amount', '0.00')), 
        'invoice_status': invoice_data.get('invoice_status', 'Generated'),
        'cgst_amount': Decimal(invoice_data.get('cgst_amount', '0.00')), 
        'sgst_amount': Decimal(invoice_data.get('sgst_amount', '0.00')),
        'igst_amount': Decimal(invoice_data.get('igst_amount', '0.00')),
        'ugst_amount': Decimal(invoice_data.get('ugst_amount', '0.00')),
        'cess_amount': Decimal(invoice_data.get('cess_amount', '0.00')), # NEW
    }

    # Convert date string to datetime object for formatting in PDF
    if isinstance(invoice_data_safe['invoice_date'], str):
        try:
            invoice_data_safe['invoice_date_dt'] = datetime.strptime(invoice_data_safe['invoice_date'], '%Y-%m-%d')
        except ValueError:
            invoice_data_safe['invoice_date_dt'] = datetime.utcnow() # Fallback
    else:
        invoice_data_safe['invoice_date_dt'] = invoice_data_safe['invoice_date']


    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, # Set page size to A4
                            leftMargin=0.3*inch, rightMargin=0.3*inch, # Reduced margins
                            topMargin=0.3*inch, bottomMargin=0.3*inch) # Reduced margins
    
    # NEW: Register a Unicode font that supports the Rupee symbol
    # You need to ensure 'DejaVuSans.ttf' and 'DejaVuSans-Bold.ttf' are available in your project's root directory
    # You can download DejaVuSans.ttf from: https://dejavu-fonts.github.io/
    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
        font_name = 'DejaVuSans'
        font_name_bold = 'DejaVuSans-Bold'
    except Exception as e:
        print(f"Could not register DejaVuSans font: {e}. Falling back to default.")
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'

    # Get a fresh stylesheet
    styles = getSampleStyleSheet() 
    
    # Modify the base 'Normal' style first and ensure bulletText is a string
    styles['Normal'].fontName = font_name
    styles['Normal'].fontSize = 8
    styles['Normal'].leading = 9
    styles['Normal'].alignment = TA_LEFT
    styles['Normal'].spaceAfter = 1
    styles['Normal'].bulletText = '' # Crucial: Ensure this is a string

    # Now define other styles, inheriting from the modified 'Normal'
    # and explicitly setting bulletText to an empty string.
    # We must use styles.add() for new styles, and modify existing ones directly.
    # Ensure 'parent' argument is used correctly for inheritance.
    
    # Re-define or modify styles to ensure bulletText is always a string
    styles['h1'].fontName = font_name_bold
    styles['h1'].fontSize = 14
    styles['h1'].leading = 16
    styles['h1'].alignment = TA_CENTER
    styles['h1'].spaceAfter = 3
    styles['h1'].bulletText = '' # Explicitly set

    styles['h2'].fontName = font_name_bold
    styles['h2'].fontSize = 12
    styles['h2'].leading = 14
    styles['h2'].alignment = TA_LEFT
    styles['h2'].spaceAfter = 4
    styles['h2'].bulletText = '' # Explicitly set

    # Add new styles or modify existing ones, always setting bulletText
    # If a style already exists in getSampleStyleSheet, modify it directly.
    # If it's a new custom style, use styles.add()
    
    # Check if 'RightAlign' exists, if not, add it. Then modify.
    if 'RightAlign' not in styles:
        styles.add(ParagraphStyle(name='RightAlign', parent=styles['Normal']))
    styles['RightAlign'].alignment = TA_RIGHT
    styles['RightAlign'].fontName = font_name
    styles['RightAlign'].bulletText = ''

    if 'BoldBodyText' not in styles:
        styles.add(ParagraphStyle(name='BoldBodyText', parent=styles['Normal']))
    styles['BoldBodyText'].fontName = font_name_bold
    styles['BoldBodyText'].spaceAfter = 1
    styles['BoldBodyText'].bulletText = ''

    if 'Footer' not in styles:
        styles.add(ParagraphStyle(name='Footer', parent=styles['Normal']))
    styles['Footer'].fontSize = 6
    styles['Footer'].leading = 7
    styles['Footer'].alignment = TA_CENTER
    styles['Footer'].spaceBefore = 5
    styles['Footer'].fontName = font_name
    styles['Footer'].bulletText = ''

    if 'TableCell' not in styles:
        styles.add(ParagraphStyle(name='TableCell', parent=styles['Normal']))
    styles['TableCell'].alignment = TA_CENTER
    styles['TableCell'].fontName = font_name
    styles['TableCell'].fontSize = 7
    styles['TableCell'].leading = 8
    styles['TableCell'].bulletText = ''

    if 'TableCellLeft' not in styles:
        styles.add(ParagraphStyle(name='TableCellLeft', parent=styles['Normal']))
    styles['TableCellLeft'].alignment = TA_LEFT
    styles['TableCellLeft'].fontName = font_name
    styles['TableCellLeft'].fontSize = 7
    styles['TableCellLeft'].leading = 8
    styles['TableCellLeft'].bulletText = ''

    if 'TableCellRight' not in styles:
        styles.add(ParagraphStyle(name='TableCellRight', parent=styles['Normal']))
    styles['TableCellRight'].alignment = TA_RIGHT
    styles['TableCellRight'].fontName = font_name
    styles['TableCellRight'].fontSize = 7
    styles['TableCellRight'].leading = 8
    styles['TableCellRight'].bulletText = ''


    full_story = []

    # Generate the first invoice copy
    invoice_copy_1_story = _get_single_invoice_flowables(order, invoice_data_safe, styles, font_name, font_name_bold)
    full_story.extend(invoice_copy_1_story)

    # Add a spacer to push the second copy down.
    # A4 height is 11.69 inches. We need to push the second copy roughly to the middle.
    # The exact value might need fine-tuning based on content.
    # It's a bit of a hack for SimpleDocTemplate to get two distinct sections on one page.
    full_story.append(Spacer(1, 0.5 * inch)) # Adjust this value if needed for exact positioning

    # Generate the second invoice copy (identical to the first)
    invoice_copy_2_story = _get_single_invoice_flowables(order, invoice_data_safe, styles, font_name, font_name_bold)
    full_story.extend(invoice_copy_2_story)

    doc.build(full_story)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f"invoice_{order.id}.pdf", mimetype='application/pdf')

def generate_invoice_pdf_buffer(order):
    if SimpleDocTemplate is None:
        return None

    invoice_data = order.get_invoice_details()

    invoice_data_safe = {
        'business_name': invoice_data.get('business_name') or app.config['OUR_BUSINESS_NAME'],
        'gst_number': invoice_data.get('gst_number') or app.config['OUR_GSTIN'],
        'pan_number': invoice_data.get('pan_number') or app.config['OUR_PAN'],
        'business_address': invoice_data.get('business_address') or app.config['OUR_BUSINESS_ADDRESS'],
        'invoice_number': invoice_data.get('invoice_number') or order.id,
        'invoice_date': invoice_data.get('invoice_date') or datetime.utcnow().strftime('%Y-%m-%d'),
        'billing_address': invoice_data.get('billing_address') or ', '.join(filter(None, [
            order.customer_name, order.customer_phone,
            order.get_shipping_address().get('address_line1'),
            order.get_shipping_address().get('address_line2'),
            order.get_shipping_address().get('city'),
            order.get_shipping_address().get('state'),
            order.get_shipping_address().get('pincode')
        ])),
        'gst_rate_applied': Decimal(invoice_data.get('gst_rate_applied', '0.00')), 
        'shipping_charge': Decimal(invoice_data.get('shipping_charge', '0.00')), 
        'final_invoice_amount': Decimal(invoice_data.get('final_invoice_amount', '0.00')), 
        'invoice_status': invoice_data.get('invoice_status', 'Generated'),
        'cgst_amount': Decimal(invoice_data.get('cgst_amount', '0.00')), 
        'sgst_amount': Decimal(invoice_data.get('sgst_amount', '0.00')),
        'igst_amount': Decimal(invoice_data.get('igst_amount', '0.00')),
        'ugst_amount': Decimal(invoice_data.get('ugst_amount', '0.00')),
        'cess_amount': Decimal(invoice_data.get('cess_amount', '0.00')),
    }

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=0.3*inch, rightMargin=0.3*inch,
                            topMargin=0.3*inch, bottomMargin=0.3*inch)

    # Register fonts (same as your original code)
    try:
        pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
        pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
        font_name = 'DejaVuSans'
        font_name_bold = 'DejaVuSans-Bold'
    except Exception as e:
        font_name = 'Helvetica'
        font_name_bold = 'Helvetica-Bold'

    styles = getSampleStyleSheet()
    styles['Normal'].fontName = font_name
    styles['Normal'].fontSize = 8
    styles['Normal'].leading = 9
    styles['Normal'].alignment = TA_LEFT
    styles['Normal'].spaceAfter = 1
    styles['Normal'].bulletText = ''

    # Update styles like before (h1, h2, etc.) — skip retyping here for now

    story = []
    story += _get_single_invoice_flowables(order, invoice_data_safe, styles, font_name, font_name_bold)
    story.append(Spacer(1, 0.5 * inch))
    story += _get_single_invoice_flowables(order, invoice_data_safe, styles, font_name, font_name_bold)

    doc.build(story)
    buffer.seek(0)
    return buffer



# --- User Profile & Orders ---
@app.route('/user-profile')
@login_required
def user_profile():
    user_addresses = current_user.addresses
    return render_template('user_profile.html', user_addresses=user_addresses)

@app.route('/add-address-form', methods=['GET'])
@login_required
def add_address_form():
    return render_template('add_address_form.html')


@app.route('/add-address', methods=['POST'])
@login_required
def add_address():
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    address_line1 = request.form.get('address_line1')
    address_line2 = request.form.get('address_line2')
    city = request.form.get('city')
    state = request.form.get('state')
    pincode = request.form.get('pincode')
    is_default = 'is_default' in request.form

    if not all([full_name, phone, address_line1, city, state, pincode]):
        flash('Please fill in all required address fields.', 'danger')
        return redirect(url_for('purchase_form')) # Corrected redirect for validation failure

    if is_default:
        # Unset previous default address
        for addr in current_user.addresses:
            if addr.is_default:
                addr.is_default = False

    new_address = Address(
        user_id=current_user.id,
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
    return redirect(url_for('purchase_form')) # Corrected redirect for success


@app.route('/my-addresses')
@login_required
def my_addresses():
    addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc(), Address.id.asc()).all()
    return render_template('my_addresses.html', addresses=addresses)


@app.route('/admin/screenshots')
@login_required
@admin_required
def view_uploaded_screenshots():
    orders = Order.query.filter(Order.payment_screenshot.isnot(None)).order_by(Order.order_date.desc()).all()
    missing_files = []

    for order in orders:
        path = os.path.join('static', order.payment_screenshot)
        if not os.path.exists(path):
            missing_files.append(order.order_id)

    return render_template('admin_screenshots.html', orders=orders, missing_files=missing_files)

@app.route('/edit-address/<address_id>', methods=['GET', 'POST'])
@login_required
def edit_address(address_id):
    # Fetch address belonging to current user only
    address = Address.query.filter_by(id=address_id, user_id=current_user.id).first_or_404()

    if request.method == 'POST':
        address.label = request.form.get('label', '')
        address.full_name = request.form.get('full_name', '')
        address.phone = request.form.get('phone', '')
        address.address_line1 = request.form.get('address_line1', '')
        address.address_line2 = request.form.get('address_line2', '')
        address.pincode = request.form.get('pincode', '')
        address.city = request.form.get('city', '')
        address.state = request.form.get('state', '')
        address.is_default = 'is_default' in request.form

        # If user set this as default, unset all others
        if address.is_default:
            other_addresses = Address.query.filter(Address.user_id == current_user.id, Address.id != address.id)
            for addr in other_addresses:
                addr.is_default = False

        db.session.commit()
        flash("Address updated successfully!", "success")
        return redirect(url_for('my_addresses'))  # Or wherever you show the list of addresses

    return render_template("edit_address.html", address=address)



@app.route('/delete-address/<address_id>', methods=['GET', 'POST'])
@login_required
def delete_address(address_id):
    if request.method == 'GET':
        flash('Invalid request method for deleting address.', 'warning')
        return redirect(url_for('user_profile'))

    address = db.session.get(Address, address_id)
    if not address:
        flash('Address not found.', 'danger')
        return redirect(url_for('user_profile'))

    if address.user_id != current_user.id:
        flash('You are not authorized to delete this address.', 'danger')
        return redirect(url_for('user_profile'))

    if address.is_default and len(current_user.addresses) > 1:
        flash('Cannot delete default address if other addresses exist. Please set another address as default first.', 'danger')
        return redirect(url_for('user_profile'))

    if db.session.query(Order).filter_by(shipping_address_id=address_id).count() > 0:
        flash('Cannot delete address: it is linked to existing orders.', 'danger')
        return redirect(url_for('user_profile'))

    db.session.delete(address)
    db.session.commit()
    flash('Address deleted successfully!', 'success')
    return redirect(url_for('user_profile'))


@app.route('/user-orders')
@login_required
def user_orders():
    if current_user.is_admin():
        orders = Order.query.order_by(Order.order_date.desc()).all()
    else:
        orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    return render_template('user_orders.html', orders=orders)


import os
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/user/order/<order_id>/edit_screenshot', methods=['POST'])
@login_required
@csrf.exempt  # If you're using AJAX or ensure CSRF token included
def edit_payment_screenshot(order_id):
    # Allow admin to edit any order, user can edit only their own
    if current_user.is_admin():
        order = Order.query.filter_by(id=order_id).first()
    else:
        order = Order.query.filter_by(id=order_id, user_id=current_user.id).first()

    if not order:
        print(f"DEBUG: Order NOT found for ID={order_id}.")
        flash('Order not found or you are not authorized to view it.', 'danger')
        return redirect(url_for('user_orders'))

    if 'screenshot' not in request.files:
        flash("No screenshot uploaded.", "warning")
        return redirect(url_for('user_orders'))

    file = request.files['screenshot']
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{order.id}_screenshot.{file.filename.rsplit('.', 1)[1].lower()}")
        filepath = os.path.join('static', 'payment_screenshots', filename)

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # Delete old screenshot if exists
        if order.payment_screenshot:
            try:
                old_screenshot_path = os.path.join('static', order.payment_screenshot)
                if os.path.exists(old_screenshot_path):
                    os.remove(old_screenshot_path)
            except Exception as e:
                print(f"Warning: Could not delete old screenshot: {e}")

        file.save(filepath)
        order.payment_screenshot = f'payment_screenshots/{filename}'
        db.session.commit()

        flash("Screenshot uploaded successfully.", "success")
    else:
        flash("Choose an image first & then Upload Screenshot. Only PNG, JPG, JPEG allowed.", "danger")

    return redirect(url_for('user_orders'))


from flask import jsonify, request

@app.route('/delete-order/<order_id>', methods=['POST', 'DELETE'])
@login_required
def delete_order(order_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    order = db.session.get(Order, order_id)
    if not order:
        if is_ajax:
            return jsonify(success=False, message='Order not found.'), 404
        flash('Order not found.', 'danger')
        return redirect(url_for('user_orders'))

    if not current_user.is_admin() and order.status not in ['Pending Payment', 'Payment Failed', 'Cancelled by User', 'Cancelled by Admin']:
        if is_ajax:
            return jsonify(success=False, message='You are not allowed to delete this order.'), 403
        flash('This order cannot be deleted.', 'danger')
        return redirect(url_for('user_orders'))

    try:
        for item in order.items:
            artwork = db.session.get(Artwork, item.artwork_id)
            if artwork:
                artwork.stock += item.quantity

        db.session.delete(order)
        db.session.commit()
        if is_ajax:
            return jsonify(success=True, message='Order deleted successfully.')
        flash('Order deleted successfully.', 'success')

    except Exception as e:
        db.session.rollback()
        if is_ajax:
            return jsonify(success=False, message=f'Error deleting order: {e}'), 500
        flash(f'Error deleting order: {e}', 'danger')

    return redirect(url_for('admin_orders_view' if current_user.is_admin() else 'user_orders'))


# --- Initialize DB and Migrate Data on First Run ---
with app.app_context():
    db.create_all()

    # Create default admin user if not exists
    default_admin_email = os.environ.get('DEFAULT_ADMIN_EMAIL', 'admin@karthikafutures.com')
    default_admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'adminpass') # Change this in production!

    admin_user_exists = User.query.filter_by(email=default_admin_email).first()
    if not admin_user_exists:
        initial_admin = User(
            email=default_admin_email,
            full_name="Karthika Futures Admin",
            role='admin',
            email_verified=True # Admin email is pre-verified
        )
        initial_admin.set_password(default_admin_password)
        db.session.add(initial_admin)
        db.session.commit()

        # Create a default address for the admin user
        initial_admin_address = Address(
            user_id=initial_admin.id,
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
        print(f"Login at: http://127.0.0.1:5000/admin-login")
        print(f"----------------------------------------\n")
    else:
        # Check if existing user with default admin email is actually an admin
        if not admin_user_exists.is_admin(): # Changed to call is_admin()
            print(f"\n--- WARNING: Account '{default_admin_email}' exists but is not admin. ---")
            print(f"Please manually change role to 'admin' for user {default_admin_email} in the database if needed.")
            print(f"------------------------------------------------------------------\n")
        else:
            print("Admin user already exists. Skipping default admin creation.")

    # NEW: Initialize order_id_sequence if it doesn't exist
    order_sequence_exists = db.session.get(SequenceCounter, 'order_id_sequence')
    if not order_sequence_exists:
        initial_sequence = SequenceCounter(id='order_id_sequence', current_value=15416760)
        db.session.add(initial_sequence)
        db.session.commit()
        print("Initialized 'order_id_sequence' to 15416760.")
    
    # NEW: Check for CESS column in Artwork and OrderItem models
    # This is a simple check. For production, use Flask-Migrate.
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    artwork_columns = [col['name'] for col in inspector.get_columns('artwork')]
    order_item_columns = [col['name'] for col in inspector.get_columns('order_item')]

    if 'cess_percentage' not in artwork_columns or \
       'cess_percentage_applied' not in order_item_columns or \
       'cess_amount' not in order_item_columns:
        # Removed the print statement for this warning
        pass # Keep this for schema check, but no print output

@app.route("/check-db")
def check_db():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "Not Set")
    return f"Database URI in use: {uri}"

@app.route("/version")
def version():
    return "Karthika Futures | Build: 2025-07-28 10:45 AM"

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True)

