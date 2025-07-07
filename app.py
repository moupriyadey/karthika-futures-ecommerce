import os
import json
import csv
import uuid
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
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

# SQLAlchemy Imports
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Numeric, ForeignKey, func 
from sqlalchemy.orm import relationship
from sqlalchemy.exc import IntegrityError 

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
    from reportlab.lib.pagesizes import letter
except ImportError:
    print("ReportLab not installed. PDF generation features will be disabled.")
    SimpleDocTemplate = None

app = Flask(__name__)

from slugify import slugify
app.jinja_env.filters['slugify'] = slugify
# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key_that_should_be_in_env')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit for uploads

# Email Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER', 'smarasada@gmail.com') # REPLACE WITH YOUR EMAIL
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS', 'ujipgkporeybjtoy') # REPLACE WITH YOUR APP PASSWORD

# Business Details (for invoices, etc.)
app.config['OUR_BUSINESS_NAME'] = "Karthika Futures"
app.config['OUR_BUSINESS_ADDRESS'] = "123 Divine Path, Spiritual City, Karnataka - 560001"
app.config['OUR_GSTIN'] = "29ABCDE1234F1Z5" # Example GSTIN
app.config['OUR_PAN'] = "ABCDE1234F" # Example PAN
app.config['DEFAULT_GST_RATE'] = Decimal('18.00') # Default GST rate for products
app.config['DEFAULT_SHIPPING_CHARGE'] = Decimal('100.00') # Default shipping charge

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
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

def send_email(to_email, subject, body, attachment_path=None, attachment_name=None):
    """Sends an email with optional attachment."""
    try:
        msg = MIMEMultipart()
        msg['From'] = app.config['MAIL_USERNAME']
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=attachment_name or os.path.basename(attachment_path))
                msg.attach(attach)

        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as smtp:
            smtp.starttls()
            smtp.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            smtp.send_message(msg)
        print(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        return False

# --- Database Models ---
class User(db.Model, UserMixin):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(120), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True) # Added phone
    password_hash = Column(String(128), nullable=False)
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
    gst_type = Column(String(20), default='intra_state', nullable=False) # 'intra_state', 'inter_state', 'union_territory'

    stock = Column(Integer, default=0, nullable=False)
    category_id = Column(String(36), ForeignKey('category.id'), nullable=False)
    images = Column(Text, nullable=True) # Stored as JSON string of image paths
    is_featured = Column(Boolean, default=False, nullable=False)
    custom_options = Column(Text, nullable=True) # Stored as JSON string { "Size": {"A4": 0, "A3": 500}, "Frame": {"None": 0, "Wooden": 1000} }

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

class Order(db.Model):
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
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

    # Invoice details stored as JSON string
    invoice_details = Column(Text, nullable=True) # {business_name, gstin, pan, business_address, invoice_number, invoice_date, billing_address, gst_rate_applied, shipping_charge, final_invoice_amount, invoice_status, is_held_by_admin, cgst_amount, sgst_amount, igst_amount, ugst_amount}

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
    order_id = Column(String(36), ForeignKey('order.id'), nullable=False)
    artwork_id = Column(String(36), ForeignKey('artwork.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    
    # Store price details at the time of order for historical accuracy
    unit_price_before_gst = Column(Numeric(10, 2), nullable=False) # Price of one unit *including* selected options, *before* GST
    
    # Store applied GST percentages at the time of order
    cgst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    sgst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    igst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)
    ugst_percentage_applied = Column(Numeric(5, 2), default=Decimal('0.00'), nullable=False)

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
    def total_gst_amount(self):
        return self.cgst_amount + self.sgst_amount + self.igst_amount + self.ugst_amount

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

# --- Flask-Login User Loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

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
        'now': datetime.utcnow # For use in templates (e.g., invoice date)
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
def calculate_item_total(artwork, selected_options, quantity):
    """
    Calculates the total price for an item, including base price,
    option prices, and GST components.
    Returns (unit_price_before_gst, cgst_percentage, sgst_percentage, 
             igst_percentage, ugst_percentage, total_price_incl_gst,
             cgst_amount, sgst_amount, igst_amount, ugst_amount)
    """
    base_price = artwork.original_price
    
    # Calculate price based on selected options
    options_price_additions = Decimal('0.00')
    artwork_options = artwork.get_custom_options_dict()

    for group_name, option_label in selected_options.items():
        if group_name in artwork_options and option_label in artwork_options[group_name]:
            options_price_additions += Decimal(str(artwork_options[group_name][option_label]))
    
    unit_price_before_gst = base_price + options_price_additions
    total_before_gst = unit_price_before_gst * quantity

    cgst_percentage = artwork.cgst_percentage
    sgst_percentage = artwork.sgst_percentage
    igst_percentage = artwork.igst_percentage
    ugst_percentage = artwork.ugst_percentage

    cgst_amount = (total_before_gst * cgst_percentage) / 100
    sgst_amount = (total_before_gst * sgst_percentage) / 100
    igst_amount = (total_before_gst * igst_percentage) / 100
    ugst_amount = (total_before_gst * ugst_percentage) / 100

    total_gst_amount = cgst_amount + sgst_amount + igst_amount + ugst_amount
    total_price_incl_gst = total_before_gst + total_gst_amount
    
    return (unit_price_before_gst, cgst_percentage, sgst_percentage, 
            igst_percentage, ugst_percentage, total_price_incl_gst,
            cgst_amount, sgst_amount, igst_amount, ugst_amount)

# NEW: Helper function to get detailed cart items for display and calculation
def get_cart_items_details():
    """
    Retrieves detailed information for items in the session cart.
    Returns (detailed_cart_items, subtotal_before_gst, total_cgst_amount, 
             total_sgst_amount, total_igst_amount, total_ugst_amount,
             total_gst_amount, grand_total, shipping_charge)
    """
    detailed_cart_items = []
    subtotal_before_gst = Decimal('0.00')
    total_cgst_amount = Decimal('0.00')
    total_sgst_amount = Decimal('0.00')
    total_igst_amount = Decimal('0.00')
    total_ugst_amount = Decimal('0.00')
    total_gst_amount = Decimal('0.00')
    grand_total = Decimal('0.00')
    shipping_charge = app.config['DEFAULT_SHIPPING_CHARGE'] # Get default shipping charge

    # Iterate over a copy of the cart to allow modification during iteration
    cart_copy = session.get('cart', {}).copy() 
    for item_key, item_data in cart_copy.items():
        sku = item_data['sku']
        quantity = item_data['quantity']
        selected_options = item_data.get('options', {})

        artwork = Artwork.query.filter_by(sku=sku).first()
        if artwork:
            # Re-calculate prices to ensure accuracy, especially if artwork data changed
            (unit_price_before_gst, cgst_percentage, sgst_percentage, 
             igst_percentage, ugst_percentage, total_price_incl_gst,
             cgst_amount, sgst_amount, igst_amount, ugst_amount) = \
                calculate_item_total(artwork, selected_options, quantity)

            detailed_cart_items.append({
                'item_key': item_key,
                'artwork': artwork, # Full artwork object
                'quantity': quantity,
                'unit_price_before_gst': unit_price_before_gst,
                'cgst_percentage': cgst_percentage,
                'sgst_percentage': sgst_percentage,
                'igst_percentage': igst_percentage,
                'ugst_percentage': ugst_percentage,
                'total_price_incl_gst': total_price_incl_gst,
                'cgst_amount': cgst_amount,
                'sgst_amount': sgst_amount,
                'igst_amount': igst_amount,
                'ugst_amount': ugst_amount,
                'selected_options': selected_options,
                'image_url': artwork.get_images_list()[0] if artwork.get_images_list() else 'images/placeholder.png'
            })
            subtotal_before_gst += unit_price_before_gst * quantity
            total_cgst_amount += cgst_amount
            total_sgst_amount += sgst_amount
            total_igst_amount += igst_amount
            total_ugst_amount += ugst_amount
            total_gst_amount += (cgst_amount + sgst_amount + igst_amount + ugst_amount)
            grand_total += total_price_incl_gst
        else:
            # If artwork not found, remove from cart and flash message
            flash(f"Artwork with SKU {sku} not found and removed from your cart.", "warning")
            # Remove from the original session cart, not the copy
            if item_key in session['cart']:
                del session['cart'][item_key]
            session.modified = True # Mark session as modified
            
    # Add shipping charge to grand total
    grand_total += shipping_charge

    return (detailed_cart_items, subtotal_before_gst, total_cgst_amount, 
            total_sgst_amount, total_igst_amount, total_ugst_amount,
            total_gst_amount, grand_total, shipping_charge)


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
    (unit_price_before_gst, cgst_percentage, sgst_percentage, 
     igst_percentage, ugst_percentage, _, _, _, _, _) = \
        calculate_item_total(artwork, selected_options, quantity)

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
            'options': selected_options
        }
    
    session['cart'] = cart
    session.modified = True # Important to mark session as modified

    total_quantity_in_cart = sum(item['quantity'] for item in session['cart'].values())
    flash(f"{quantity} x {artwork.name} added to cart!", 'success')
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
    total_sgst_amount, total_igst_amount, total_ugst_amount, \
    total_gst_amount, grand_total, shipping_charge = get_cart_items_details()
    
    return render_template('cart.html', 
                           cart_items=detailed_cart_items,
                           subtotal_before_gst=subtotal_before_gst,
                           total_cgst_amount=total_cgst_amount,
                           total_sgst_amount=total_sgst_amount,
                           total_igst_amount=total_igst_amount,
                           total_ugst_amount=total_ugst_amount,
                           total_gst_amount=total_gst_amount,
                           grand_total=grand_total,
                           shipping_charge=shipping_charge)

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

    # Store the direct purchase item in session for later retrieval after login/signup
    # Store as a list of one item to mimic cart structure for purchase_form
    session['direct_purchase_cart'] = {'temp_item_key': item_to_buy_now} 
    session.modified = True

    if current_user.is_authenticated:
        # If logged in, proceed to purchase form directly
        return jsonify(success=True, message='Proceeding to checkout.', redirect_url=url_for('purchase_form'))
    else:
        # If not logged in, redirect to login page, which will then redirect to purchase_form
        return jsonify(success=True, message='Please log in or sign up to complete your purchase.', redirect_url=url_for('user_login', next='purchase_form'))

# MODIFIED: Purchase form to handle both cart checkout and direct purchase
@app.route('/purchase_form', methods=['GET', 'POST'])
@login_required
def purchase_form():
    # Check if there's a direct purchase request in session
    direct_purchase_item_data = session.pop('direct_purchase_cart', None) # Pop to clear it after use

    if direct_purchase_item_data:
        # If direct purchase, use its item
        # The structure is {'temp_item_key': actual_item_data}
        item_data = next(iter(direct_purchase_item_data.values())) # Get the actual item data
        
        # Temporarily put direct purchase item(s) into cart session for get_cart_items_details to process
        # This mimics the structure expected by get_cart_items_details
        session['cart'] = {'temp_item_key': item_data} 
        session.modified = True
        flash("Proceeding with your direct purchase.", "info")
    elif not session.get('cart'):
        flash('Your cart is empty. Please add items to proceed.', 'warning')
        return redirect(url_for('all_products'))

    detailed_cart_items, subtotal_before_gst, total_cgst_amount, \
    total_sgst_amount, total_igst_amount, total_ugst_amount, \
    total_gst_amount, grand_total, shipping_charge = get_cart_items_details()

    user_addresses = current_user.addresses
    default_address = next((addr for addr in user_addresses if addr.is_default), None)

    # Initialize form_data for GET requests or when re-rendering with errors
    form_data = {}
    if request.method == 'GET':
        if default_address:
            form_data = {
                'full_name': default_address.full_name,
                'phone': default_address.phone,
                'address_line1': default_address.address_line1,
                'address_line2': default_address.address_line2,
                'city': default_address.city,
                'state': default_address.state,
                'pincode': default_address.pincode,
                'is_default': default_address.is_default
            }
        else:
            # If no default address, initialize with empty strings
            form_data = {
                'full_name': '', 'phone': '', 'address_line1': '', 'address_line2': '',
                'city': '', 'state': '', 'pincode': '', 'is_default': False
            }
    elif request.method == 'POST':
        # If POST request, and there are validation errors, form_data will be populated
        # by the error handling block. If no errors, it proceeds to order creation.
        # This ensures form_data is available if the template is re-rendered due to validation.
        form_data = request.form.to_dict()
        form_data['is_default'] = request.form.get('set_as_default') == 'on' # Manually set checkbox state

    if request.method == 'POST':
        selected_address_id = request.form.get('shipping_address')
        new_address_data = {}

        if selected_address_id == 'new':
            new_address_data = {
                'full_name': request.form.get('full_name'),
                'phone': request.form.get('phone'),
                'address_line1': request.form.get('address_line1'),
                'address_line2': request.form.get('address_line2'),
                'city': request.form.get('city'),
                'state': request.form.get('state'),
                'pincode': request.form.get('pincode'),
                'is_default': request.form.get('set_as_default') == 'on'
            }
            # Basic validation for new address
            if not all(new_address_data.get(field) for field in ['full_name', 'phone', 'address_line1', 'city', 'state', 'pincode']):
                flash('Please fill in all required fields for the new address.', 'danger')
                return render_template('purchase_form.html',
                                       cart_items=detailed_cart_items,
                                       subtotal_before_gst=subtotal_before_gst,
                                       total_cgst_amount=total_cgst_amount,
                                       total_sgst_amount=total_sgst_amount,
                                       total_igst_amount=total_igst_amount,
                                       total_ugst_amount=total_ugst_amount,
                                       total_gst_amount=total_gst_amount,
                                       grand_total=grand_total,
                                       shipping_charge=shipping_charge,
                                       user_addresses=user_addresses,
                                       selected_address_id='new',
                                       form_data=new_address_data, # Pass new_address_data as form_data
                                       default_address=default_address) # Pass default_address for existing addresses radio
            
            # Create and save new address
            new_address = Address(
                user_id=current_user.id,
                full_name=new_address_data['full_name'],
                phone=new_address_data['phone'],
                address_line1=new_address_data['address_line1'],
                address_line2=new_address_data['address_line2'],
                city=new_address_data['city'],
                state=new_address_data['state'],
                pincode=new_address_data['pincode'],
                is_default=new_address_data['is_default']
            )
            if new_address.is_default:
                # Unset previous default address
                for addr in user_addresses:
                    if addr.is_default:
                        addr.is_default = False
            db.session.add(new_address)
            db.session.commit()
            selected_address_id = new_address.id
            flash('New address added successfully!', 'success')
            user_addresses = current_user.addresses # Refresh addresses

        shipping_address_obj = Address.query.get(selected_address_id)
        if not shipping_address_obj:
            flash('Invalid shipping address selected.', 'danger')
            return redirect(url_for('purchase_form'))

        try:
            # Create the order
            new_order = Order(
                user_id=current_user.id,
                total_amount=grand_total,
                status='Pending Payment',
                payment_status='pending',
                shipping_address_id=shipping_address_obj.id,
                shipping_charge=shipping_charge # Use the calculated shipping charge
            )
            db.session.add(new_order)
            db.session.flush() # To get new_order.id before commit

            # Add order items
            for item in detailed_cart_items:
                order_item = OrderItem(
                    order_id=new_order.id,
                    artwork_id=item['artwork'].id,
                    quantity=item['quantity'],
                    unit_price_before_gst=item['unit_price_before_gst'],
                    cgst_percentage_applied=item['cgst_percentage'],
                    sgst_percentage_applied=item['sgst_percentage'],
                    igst_percentage_applied=item['igst_percentage'],
                    ugst_percentage_applied=item['ugst_percentage'],
                    selected_options=json.dumps(item['selected_options']) # Store options as JSON string
                )
                db.session.add(order_item)
                # Deduct stock
                artwork = Artwork.query.get(item['artwork'].id)
                if artwork:
                    artwork.stock -= item['quantity']
                    if artwork.stock < 0:
                        artwork.stock = 0 # Prevent negative stock
                
            db.session.commit()

            # Clear cart after successful order creation
            session.pop('cart', None)
            session.modified = True
            flash('Order placed successfully! Please proceed to payment.', 'success')
            return redirect(url_for('order_summary', order_id=new_order.id))

        except IntegrityError:
            db.session.rollback()
            flash('An error occurred while creating your order. Please try again.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'An unexpected error occurred: {e}', 'danger')

    return render_template('purchase_form.html',
                           cart_items=detailed_cart_items,
                           subtotal_before_gst=subtotal_before_gst,
                           total_cgst_amount=total_cgst_amount,
                           total_sgst_amount=total_sgst_amount,
                           total_igst_amount=total_igst_amount,
                           total_ugst_amount=total_ugst_amount,
                           total_gst_amount=total_gst_amount,
                           grand_total=grand_total,
                           shipping_charge=shipping_charge,
                           user_addresses=user_addresses,
                           default_address=default_address,
                           selected_address_id=default_address.id if default_address else None,
                           form_data=form_data) # Ensure form_data is always passed
                           
# MODIFIED: Signup route to include OTP verification
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

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
        flash('A One-Time Password (OTP) has been sent to your email. Please verify to complete registration.', 'success')
        return redirect(url_for('verify_otp'))

    return render_template('signup.html', form_data=form_data)

# NEW: OTP Verification Route
@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    user_id = session.get('otp_user_id')
    if not user_id:
        flash('No pending verification. Please sign up or try forgot password again.', 'danger')
        return redirect(url_for('signup'))

    user = User.query.get(user_id)
    if not user:
        flash('User not found for verification.', 'danger')
        return redirect(url_for('signup'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        
        # Find the latest valid OTP for this user
        latest_otp = OTP.query.filter_by(user_id=user.id).order_by(OTP.created_at.desc()).first()

        if latest_otp and latest_otp.otp_code == otp_entered and latest_otp.is_valid():
            user.email_verified = True
            db.session.delete(latest_otp) # Delete used OTP
            db.session.commit()
            session.pop('otp_user_id', None) # Clear OTP user ID from session

            # If user was trying to access a 'next' page after login, redirect them
            redirect_after_login = session.pop('redirect_after_login_endpoint', None)
            item_to_buy_now = session.pop('itemToBuyNow', None)

            if redirect_after_login == 'purchase_form' and item_to_buy_now:
                # If it was a direct purchase, put the item back into a temporary session cart
                # The purchase_form route will handle picking this up
                session['direct_purchase_cart'] = {'temp_item': item_to_buy_now}
                session.modified = True
                flash('Email verified! Redirecting to complete your purchase.', 'success')
                return redirect(url_for('purchase_form'))
            elif redirect_after_login:
                flash('Email verified! You are now logged in.', 'success')
                return redirect(url_for(redirect_after_login))
            
            flash('Email verified! You can now log in.', 'success')
            return redirect(url_for('user_login'))
        else:
            flash('Invalid or expired OTP. Please try again.', 'danger')
    
    return render_template('verify_otp.html', user_email=user.email)

# NEW: Resend OTP route
@app.route('/resend_otp', methods=['POST'])
def resend_otp():
    user_id = session.get('otp_user_id')
    if not user_id:
        return jsonify(success=False, message='No user session found for OTP resend.'), 400

    user = User.query.get(user_id)
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

    form_data = {}
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        form_data = {'email': email}

        user = User.query.filter_by(email=email).first()

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
            flash('Logged in successfully!', 'success')

            next_page = request.args.get('next')
            # Handle redirect after login for direct purchase
            item_to_buy_now = session.pop('itemToBuyNow', None)
            redirect_after_login_endpoint = session.pop('redirect_after_login_endpoint', None)

            if redirect_after_login_endpoint == 'purchase_form' and item_to_buy_now:
                session['direct_purchase_cart'] = {'temp_item': item_to_buy_now}
                session.modified = True
                return redirect(url_for('purchase_form'))
            
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html', form_data=form_data)

@app.route('/user-logout')
@login_required
def user_logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

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

    user = User.query.get(user_id)
    if not user:
        flash('User not found for password reset.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        otp_entered = request.form.get('otp')
        
        latest_otp = OTP.query.filter_by(user_id=user.id).order_by(OTP.created_at.desc()).first()

        if latest_otp and latest_otp.otp_code == otp_entered and latest_otp.is_valid():
            session['reset_user_id'] = user.id # Store user ID to allow password change
            session.pop('otp_user_id', None) # Clear OTP user ID
            db.session.delete(latest_otp) # Delete used OTP
            db.session.commit()
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

    user = User.query.get(user_id)
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


@app.route('/')
def index():
    featured_artworks = Artwork.query.filter_by(is_featured=True).limit(6).all()
    # Placeholder for testimonials, replace with actual data from DB if available
    testimonials = [
        {'name': 'Radha Devi', 'feedback': 'The artwork is truly divine and brings immense peace to my home. Highly recommend Karthika Futures!', 'rating': 5, 'image': 'images/testimonial1.jpg', 'product_sku': 'ART001'},
        {'name': 'Krishna Murthy', 'feedback': 'Exceptional quality and prompt delivery. Each piece tells a story. A blessed experience!', 'rating': 5, 'image': 'images/testimonial2.jpg', 'product_sku': 'ART003'},
        {'name': 'Priya Sharma', 'feedback': 'Beautiful collection! The details are intricate and the colors vibrant. My meditation space feels complete.', 'rating': 4, 'image': 'images/testimonial3.jpg', 'product_sku': 'ART002'},
    ]
    # Ensure image paths are correct for static folder
    for t in testimonials:
        if not t['image'].startswith('static/'):
            t['image'] = 'static/' + t['image']

    return render_template('index.html', featured_artworks=featured_artworks, testimonials=testimonials)

# MODIFIED: all_products route to pass custom_options data
@app.route('/all-products')
def all_products():
    search_query = request.args.get('search', '')
    if search_query:
        artworks = Artwork.query.filter(
            (Artwork.name.ilike(f'%{search_query}%')) |
            (Artwork.description.ilike(f'%{search_query}%')) |
            (Artwork.sku.ilike(f'%{search_query}%'))
        ).all()
    else:
        artworks = Artwork.query.all()
    return render_template('all_products.html', artworks=artworks, search_query=search_query)

@app.route('/product/<string:sku>')
def product_detail(sku):
    artwork = Artwork.query.filter_by(sku=sku).first_or_404()
    return render_template('product_detail.html', artwork=artwork)

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/order-summary/<order_id>')
@login_required
def order_summary(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id and not current_user.is_admin(): # Changed to call is_admin()
        flash('You are not authorized to view this order.', 'danger')
        return redirect(url_for('user_orders'))
    return render_template('order_summary.html', order=order)

@app.route('/payment_initiate/<order_id>/<amount>')
@login_required
def payment_initiate(order_id, amount):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash('You are not authorized to make payment for this order.', 'danger')
        return redirect(url_for('user_orders'))

    if order.status != 'Pending Payment':
        flash('This order is not pending payment or has already been processed.', 'warning')
        return redirect(url_for('order_summary', order_id=order.id))

    # In a real application, you would integrate with a payment gateway here (e.g., Razorpay, Stripe)
    # For now, we'll simulate a successful payment.
    flash(f"Initiating payment for Order ID: {order_id} with amount ₹{amount}. (Simulated)", 'info')
    # Redirect to a simulated payment success/failure page or directly to a backend route that updates payment status
    return redirect(url_for('payment_callback', order_id=order_id, status='success'))

@app.route('/payment_callback/<order_id>/<status>')
def payment_callback(order_id, status):
    order = Order.query.get_or_404(order_id)
    if status == 'success':
        order.payment_status = 'completed'
        order.status = 'Payment Submitted - Awaiting Verification' # Admin needs to verify
        flash('Payment successful! Your order is awaiting admin verification.', 'success')
    else:
        order.payment_status = 'failed'
        order.status = 'Payment Failed'
        flash('Payment failed. Please try again.', 'danger')
    db.session.commit()
    return redirect(url_for('order_summary', order_id=order.id))


# --- Admin Routes ---
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin(): # Changed to call is_admin()
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
            (User.full_name.ilike(f'%{search_query}%')) | # Changed to full_name
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
    order = Order.query.get(order_id)
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
def admin_update_order_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify(success=False, message='Order not found.'), 404

    data = request.get_json()
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

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/delete-user/<user_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get(user_id)
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

@app.route('/admin/delete-category/<category_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_category(category_id):
    category = Category.query.get(category_id)
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
    return render_template('admin_artworks.html', artworks=artworks)

@app.route('/admin/add-artwork', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_artwork():
    categories = Category.query.all()
    if request.method == 'POST':
        sku = request.form.get('sku')
        name = request.form.get('name')
        description = request.form.get('description')
        original_price = request.form.get('original_price')
        
        # New GST fields
        cgst_percentage = request.form.get('cgst_percentage')
        sgst_percentage = request.form.get('sgst_percentage')
        igst_percentage = request.form.get('igst_percentage')
        ugst_percentage = request.form.get('ugst_percentage')
        gst_type = request.form.get('gst_type')

        stock = request.form.get('stock')
        category_id = request.form.get('category_id')
        is_featured = 'is_featured' in request.form # Checkbox
        custom_options_json = request.form.get('custom_options') # JSON string from JS

        if not all([sku, name, original_price, stock, category_id, gst_type]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('admin_add_artwork.html', categories=categories)

        try:
            original_price = Decimal(original_price)
            cgst_percentage = Decimal(cgst_percentage)
            sgst_percentage = Decimal(sgst_percentage)
            igst_percentage = Decimal(igst_percentage)
            ugst_percentage = Decimal(ugst_percentage)
            stock = int(stock)
        except (ValueError, InvalidOperation):
            flash('Invalid price, GST percentage, or stock quantity.', 'danger')
            return render_template('admin_add_artwork.html', categories=categories)

        existing_artwork = Artwork.query.filter_by(sku=sku).first()
        if existing_artwork:
            flash(f'Artwork with SKU "{sku}" already exists.', 'danger')
            return render_template('admin_add_artwork.html', categories=categories)

        image_paths = []
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    image_paths.append('uploads/' + unique_filename)
                elif file.filename != '': # If file is present but not allowed
                    flash(f'Invalid file type for image: {file.filename}.', 'danger')
                    return render_template('admin_add_artwork.html', categories=categories)

        new_artwork = Artwork(
            sku=sku,
            name=name,
            description=description,
            original_price=original_price,
            cgst_percentage=cgst_percentage,
            sgst_percentage=sgst_percentage,
            igst_percentage=igst_percentage,
            ugst_percentage=ugst_percentage,
            gst_type=gst_type,
            stock=stock,
            category_id=category_id,
            is_featured=is_featured
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
                return render_template('admin_add_artwork.html', categories=categories)

        db.session.add(new_artwork)
        db.session.commit()
        flash('Artwork added successfully!', 'success')
        return redirect(url_for('admin_artworks'))

    return render_template('admin_add_artwork.html', categories=categories)

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
        original_price = request.form.get('original_price')
        
        # New GST fields
        cgst_percentage = request.form.get('cgst_percentage')
        sgst_percentage = request.form.get('sgst_percentage')
        igst_percentage = request.form.get('igst_percentage')
        ugst_percentage = request.form.get('ugst_percentage')
        gst_type = request.form.get('gst_type')

        stock = request.form.get('stock')
        description = request.form.get('description')
        
        # Get images to keep (hidden inputs from frontend)
        images_to_keep = request.form.getlist('images_to_keep')
        
        # Get custom options JSON string
        custom_options_json_str = request.form.get('custom_options_json') # This name needs to match frontend

        # Update artwork object
        artwork.name = name
        artwork.category_id = category_id
        artwork.is_featured = is_featured
        artwork.description = description
        artwork.gst_type = gst_type

        try:
            artwork.original_price = Decimal(original_price)
            artwork.cgst_percentage = Decimal(cgst_percentage)
            artwork.sgst_percentage = Decimal(sgst_percentage)
            artwork.igst_percentage = Decimal(igst_percentage)
            artwork.ugst_percentage = Decimal(ugst_percentage)
            artwork.stock = int(stock)
        except (ValueError, InvalidOperation):
            flash('Invalid price, GST percentage, or stock quantity.', 'danger')
            # Pass form data back to template to re-populate
            form_data = request.form.to_dict()
            form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else []
            return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

        # Handle new image uploads
        new_image_paths = []
        if 'new_images' in request.files:
            for file in request.files.getlist('new_images'):
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    new_image_paths.append('uploads/' + unique_filename)
                elif file.filename != '': # If file is present but not allowed
                    flash(f'Invalid file type for new image: {file.filename}.', 'danger')
                    form_data = request.form.to_dict()
                    form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else []
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
                form_data['custom_option_groups'] = json.loads(custom_options_json_str) if custom_options_json_str else []
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
        'gst_type': artwork.gst_type,
        'stock': artwork.stock,
        'description': artwork.description,
        # Pass the dictionary directly, it will be converted to JSON string by tojson in template
        'custom_option_groups': artwork.get_custom_options_dict() 
    }
    # No need to convert custom_option_groups dict to a list of dicts here.
    # The JS in admin_edit_artwork.html expects the raw dictionary from get_custom_options_dict()
    # and handles its own formatting for display.

    return render_template('admin_edit_artwork.html', artwork=artwork, categories=categories, form_data=form_data)

@app.route('/admin/delete-artwork/<artwork_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_artwork(artwork_id):
    artwork = Artwork.query.get(artwork_id)
    if artwork:
        # Delete associated images from uploads folder
        for img_path in artwork.get_images_list():
            full_path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(img_path))
            if os.path.exists(full_path):
                os.remove(full_path)
        
        db.session.delete(artwork)
        db.session.commit()
        flash(f'Artwork "{artwork.name}" deleted successfully.', 'success')
    else:
        flash('Artwork not found.', 'danger')
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
            'billing_address': request.form.get('billing_address'),
            'gst_rate_applied': Decimal(request.form.get('gst_rate')),
            'shipping_charge': Decimal(request.form.get('shipping_charge')),
            'final_invoice_amount': Decimal(request.form.get('final_invoice_amount')),
            'invoice_status': request.form.get('invoice_status', 'Generated'), # Default if not explicitly set
            'is_held_by_admin': 'is_held_by_admin' in request.form, # Checkbox
            'cgst_amount': Decimal(request.form.get('cgst_amount', '0.00')),
            'sgst_amount': Decimal(request.form.get('sgst_amount', '0.00')),
            'igst_amount': Decimal(request.form.get('igst_amount', '0.00')),
            'ugst_amount': Decimal(request.form.get('ugst_amount', '0.00'))
        }
        
        order.set_invoice_details(invoice_details)
        order.shipping_charge = invoice_details['shipping_charge'] # Update order's shipping charge too
        order.total_amount = invoice_details['final_invoice_amount'] # Update order's total amount
        db.session.commit()
        flash('Invoice details updated successfully!', 'success')
        return redirect(url_for('admin_dashboard')) # Or admin_orders_view if you create one
    
    # For GET request, pass current invoice details to the template
    return render_template('admin_edit_invoice.html', order=order)

# --- User Profile & Orders ---
@app.route('/user-profile')
@login_required
def user_profile():
    user_addresses = current_user.addresses
    return render_template('user_profile.html', user_addresses=user_addresses)

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
        return redirect(url_for('user_profile'))

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
    return redirect(url_for('user_profile'))

@app.route('/edit-address/<address_id>', methods=['GET', 'POST'])
@login_required
def edit_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash('You are not authorized to edit this address.', 'danger')
        return redirect(url_for('user_profile'))

    if request.method == 'POST':
        address.full_name = request.form.get('full_name')
        address.phone = request.form.get('phone')
        address.address_line1 = request.form.get('address_line1')
        address.address_line2 = request.form.get('address_line2')
        address.city = request.form.get('city')
        address.state = request.form.get('state')
        address.pincode = request.form.get('pincode')
        is_default = 'is_default' in request.form

        if not all([address.full_name, address.phone, address.address_line1, address.city, address.state, address.pincode]):
            flash('Please fill in all required address fields.', 'danger')
            return render_template('edit_address.html', address=address)

        if is_default:
            # Unset previous default address
            for addr in current_user.addresses:
                if addr.is_default and addr.id != address.id:
                    addr.is_default = False
        address.is_default = is_default

        db.session.commit()
        flash('Address updated successfully!', 'success')
        return redirect(url_for('user_profile'))
    return render_template('edit_address.html', address=address)

@app.route('/delete-address/<address_id>', methods=['POST'])
@login_required
def delete_address(address_id):
    address = Address.query.get_or_404(address_id)
    if address.user_id != current_user.id:
        flash('You are not authorized to delete this address.', 'danger')
        return redirect(url_for('user_profile'))
    
    if address.is_default and len(current_user.addresses) > 1:
        flash('Cannot delete default address if other addresses exist. Please set another address as default first.', 'danger')
        return redirect(url_for('user_profile'))

    db.session.delete(address)
    db.session.commit()
    flash('Address deleted successfully!', 'success')
    return redirect(url_for('user_profile'))

@app.route('/user-orders')
@login_required
def user_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    return render_template('user_orders.html', orders=orders)

@app.route('/delete-order/<order_id>', methods=['POST'])
@login_required
def delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    # Only allow user to delete their own pending/failed orders, or admin to delete any
    if order.user_id != current_user.id and not current_user.is_admin(): # Changed to call is_admin()
        flash('You are not authorized to delete this order.', 'danger')
        return redirect(url_for('user_orders'))
    
    # Prevent deletion of completed/shipped/delivered orders by users
    if not current_user.is_admin() and order.status not in ['Pending Payment', 'Payment Failed', 'Cancelled by User', 'Cancelled by Admin']: # Changed to call is_admin()
        flash('This order cannot be deleted.', 'danger')
        return redirect(url_for('user_orders'))

    try:
        # Restore stock for items in the order before deleting
        for item in order.items:
            artwork = Artwork.query.get(item.artwork_id)
            if artwork:
                artwork.stock += item.quantity
        
        db.session.delete(order)
        db.session.commit()
        flash(f'Order {order_id} deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting order: {e}', 'danger')

    if current_user.is_admin(): # Changed to call is_admin()
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('user_orders'))


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


# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True)
