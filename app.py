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
from decimal import Decimal # Import Decimal for precise financial calculations

# Imports for Email Sending
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication # For attaching files

# --- NEW: Flask-WTF and CSRFProtect imports ---
from flask_wtf.csrf import CSRFProtect

# --- Imports for PDF Generation (Conceptual - Requires ReportLab installation in your environment) ---
# Uncomment and install ReportLab (pip install reportlab) in your local/production environment for this to work
# from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
# from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
# from reportlab.lib.enums import TA_RIGHT, TA_CENTER
# from reportlab.lib.units import inch
# from reportlab.lib import colors
# from reportlab.lib.pagesizes import letter


# --- Configuration ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_key_that_should_be_replaced_in_production') # Use FLASK_SECRET_KEY from .env
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['PRODUCT_IMAGES_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'product_images')
app.config['CATEGORY_IMAGES_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'category_images')
app.config['PAYMENT_SCREENSHOTS_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'payment_screenshots')
app.config['INVOICE_PDF_FOLDER'] = os.path.join(app.config['UPLOAD_FOLDER'], 'invoices')

# Email Configuration from environment variables
app.config['SENDER_EMAIL'] = os.environ.get('SENDER_EMAIL')
app.config['SENDER_PASSWORD'] = os.environ.get('SENDER_PASSWORD') # App password for Gmail or actual password for other SMTP
app.config['SMTP_SERVER'] = 'smtp.gmail.com' # For Gmail
app.config['SMTP_PORT'] = 587 # For TLS

# Ensure upload folders exist
os.makedirs(app.config['PRODUCT_IMAGES_FOLDER'], exist_ok=True)
os.makedirs(app.config['CATEGORY_IMAGES_FOLDER'], exist_ok=True)
os.makedirs(app.config['PAYMENT_SCREENSHOTS_FOLDER'], exist_ok=True)
os.makedirs(app.config['INVOICE_PDF_FOLDER'], exist_ok=True)

# --- Constants ---
DEFAULT_SHIPPING_CHARGE = Decimal('50.00') # Use Decimal
MAX_SHIPPING_COST_FREE_THRESHOLD = Decimal('5000.00') # Use Decimal # Orders above this amount get free shipping
DEFAULT_GST_PERCENTAGE = Decimal('18.0') # Use Decimal # Default GST for products if not specified
DEFAULT_INVOICE_GST_RATE = Decimal('18.0') # Use Decimal # Default GST rate applied to invoices

# Our Business Details for Invoices (configurable)
OUR_BUSINESS_NAME = "Karthika Futures"
OUR_GSTIN = "27ABCDE1234F1Z5" # Example GSTIN
OUR_PAN = "ABCDE1234F" # Example PAN
OUR_BUSINESS_ADDRESS = "No. 123, Temple Road, Spiritual City, Karnataka - 560001"
OUR_BUSINESS_EMAIL = "invoices@karthikafutures.com" # Email for sending invoices

# UPI Payment Details
UPI_ID = "smarasada@okaxis"
BANKING_NAME = "SUBHASH S"
BANK_NAME = "PNB"

# --- Login Manager Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'user_login' # Redirect to login page if not authenticated

# --- NEW: Initialize CSRFProtect ---
csrf = CSRFProtect(app)

# NEW: Register a custom Jinja2 filter for floatformat
@app.template_filter('floatformat')
def floatformat_filter(value, places=2):
    """Formats a float/Decimal to a specific number of decimal places."""
    try:
        # Convert to Decimal first for precision, then to float for f-string formatting
        decimal_value = Decimal(str(value))
        return f"{decimal_value:.{places}f}"
    except (ValueError, TypeError, AttributeError): # Added AttributeError for Decimal objects
        # Return original value or a default if conversion fails
        return value # Or return '0.00' as a default string

login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

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
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('user_login'))
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
        # Custom JSONDecoder to handle Decimal if needed later (for now, conversion happens on load)
        # For simplicity, we'll convert to Decimal after loading with normal json.load
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
                artwork[key] = Decimal(str(artwork[key]))
            elif key in artwork and artwork[key] is None: # Ensure None remains None for non-existent prices
                pass
            else: # If key is missing, add it with Decimal('0.00') or None
                if 'price' in key or 'gst' in key: # Default prices to Decimal 0
                    artwork[key] = Decimal('0.00')
                else: # Other values like stock might need integer defaults, but for prices, Decimal 0 is safe
                    pass # Let calling code handle missing non-price defaults

        # Ensure stock is int
        artwork['stock'] = int(artwork.get('stock', 0))
    return artworks

def load_orders_data():
    # Load raw data and convert price-related fields in orders/order_items to Decimal
    orders = load_json('orders.json')
    for order in orders:
        order['total_amount'] = Decimal(str(order.get('total_amount', 0.0)))
        order['subtotal_before_gst'] = Decimal(str(order.get('subtotal_before_gst', 0.0)))
        order['total_gst_amount'] = Decimal(str(order.get('total_gst_amount', 0.0)))
        order['cgst_amount'] = Decimal(str(order.get('cgst_amount', 0.0)))
        order['sgst_amount'] = Decimal(str(order.get('sgst_amount', 0.0)))
        order['shipping_charge'] = Decimal(str(order.get('shipping_charge', 0.0)))
        order['final_invoice_amount'] = Decimal(str(order.get('final_invoice_amount', 0.0))) # For invoice details

        # --- IMPORTANT FIX: Ensure 'items' is always a list ---
        if not isinstance(order.get('items'), list):
            app.logger.warning(f"Order ID {order.get('order_id')} has non-list 'items' type: {type(order.get('items'))}. Setting to empty list.")
            order['items'] = [] # Default to an empty list if missing or not a list
        
        # Now, safely iterate through the items list (which is guaranteed to be a list)
        for item in order['items']:
            for key in ['unit_price_before_options', 'unit_price_before_gst', 'gst_percentage',
                        'gst_amount', 'total_price_before_gst', 'total_price']:
                if key in item and item[key] is not None:
                    item[key] = Decimal(str(item[key]))
                elif key in item and item[key] is None:
                    pass
                else:
                    item[key] = Decimal('0.00') # Default missing item prices to Decimal 0
            item['quantity'] = int(item.get('quantity', 0))
    return orders

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

# --- UPDATED: Function to generate invoice PDF ---
def generate_invoice_pdf(order_id, order_details):
    invoice_filename_base = f"invoice_{order_id}"
    invoice_filepath_pdf = os.path.join(app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.pdf")
    invoice_filepath_txt = os.path.join(app.config['INVOICE_PDF_FOLDER'], f"{invoice_filename_base}.txt")

    # --- Conceptual ReportLab PDF Generation (Uncomment and ensure ReportLab is installed for this to work) ---
    # if False: # Set to True in your local/production environment after installing ReportLab
    #     try:
    #         doc = SimpleDocTemplate(invoice_filepath_pdf, pagesize=letter)
    #         styles = getSampleStyleSheet()
    #         
    #         # Custom style for right-aligned text in tables for amounts
    #         styles.add(ParagraphStyle(name='RightAlign', alignment=TA_RIGHT))
    #         styles.add(ParagraphStyle(name='CenterAlign', alignment=TA_CENTER))
    #         
    #         story = []
    #
    #         # Title
    #         story.append(Paragraph(f"<b>INVOICE</b>", styles['h1']))
    #         story.append(Spacer(1, 0.2*inch))
    #
    #         # Invoice Details
    #         story.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
    #         story.append(Paragraph(f"<b>Invoice Number:</b> {order_details.get('invoice_details', {}).get('invoice_number', 'N/A')}", styles['Normal']))
    #         story.append(Paragraph(f"<b>Order ID:</b> {order_id}", styles['Normal']))
    #         story.append(Spacer(1, 0.2*inch))
    #
    #         # Seller Info
    #         story.append(Paragraph("<b>Seller:</b>", styles['h3']))
    #         story.append(Paragraph(f"Name: {OUR_BUSINESS_NAME}", styles['Normal']))
    #         story.append(Paragraph(f"GSTIN: {OUR_GSTIN}", styles['Normal']))
    #         story.append(Paragraph(f"PAN: {OUR_PAN}", styles['Normal']))
    #         story.append(Paragraph(f"Address: {OUR_BUSINESS_ADDRESS}", styles['Normal']))
    #         story.append(Paragraph(f"Email: {OUR_BUSINESS_EMAIL}", styles['Normal']))
    #         story.append(Spacer(1, 0.2*inch))
    #
    #         # Customer Info
    #         story.append(Paragraph("<b>Customer:</b>", styles['h3']))
    #         story.append(Paragraph(f"Name: {order_details.get('customer_name', 'N/A')}", styles['Normal']))
    #         story.append(Paragraph(f"Email: {order_details.get('user_email', 'N/A')}", styles['Normal']))
    #         story.append(Paragraph(f"Phone: {order_details.get('customer_phone', 'N/A')}", styles['Normal']))
    #         story.append(Paragraph(f"Address: {order_details.get('customer_address', 'N/A')}", styles['Normal']))
    #         story.append(Paragraph(f"Pincode: {order_details.get('customer_pincode', 'N/A')}", styles['Normal']))
    #         story.append(Spacer(1, 0.2*inch))
    #
    #         # Items Table
    #         data = [
    #             ['<b>SKU</b>', '<b>Name</b>', '<b>Qty</b>', '<b>Unit Price</b>', '<b>Total Price</b>']
    #         ]
    #         for item in order_details.get('items', []):
    #             data.append([
    #                 item.get('sku', 'N/A'),
    #                 item.get('name', 'N/A'),
    #                 str(item.get('quantity', 0)),
    #                 f"₹{item.get('unit_price_before_gst', Decimal('0.00')):.2f}",
    #                 f"₹{item.get('total_price', Decimal('0.00')):.2f}"
    #             ])
    #         
    #         table = Table(data, colWidths=[1.0*inch, 2.5*inch, 0.5*inch, 1.2*inch, 1.2*inch])
    #         table.setStyle(TableStyle([
    #             ('BACKGROUND', (0,0), (-1,0), colors.grey),
    #             ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
    #             ('ALIGN', (0,0), (-1,-1), 'LEFT'),
    #             ('ALIGN', (3,0), (-1,-1), 'RIGHT'), # Align price columns right
    #             ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    #             ('BOTTOMPADDING', (0,0), (-1,0), 12),
    #             ('BACKGROUND', (0,1), (-1,-1), colors.beige),
    #             ('GRID', (0,0), (-1,-1), 1, colors.black),
    #             ('BOX', (0,0), (-1,-1), 1, colors.black),
    #         ]))
    #         story.append(table)
    #         story.append(Spacer(1, 0.2*inch))
    #
    #         # Totals
    #         story.append(Paragraph(f"<b>Subtotal (Before GST):</b> ₹{order_details.get('subtotal_before_gst', Decimal('0.00')):.2f}", styles['RightAlign']))
    #         story.append(Paragraph(f"<b>Total GST:</b> ₹{order_details.get('total_gst_amount', Decimal('0.00')):.2f} (CGST: ₹{order_details.get('cgst_amount', Decimal('0.00')):.2f}, SGST: ₹{order_details.get('sgst_amount', Decimal('0.00')):.2f})", styles['RightAlign']))
    #         story.append(Paragraph(f"<b>Shipping Charge:</b> ₹{order_details.get('shipping_charge', Decimal('0.00')):.2f}", styles['RightAlign']))
    #         story.append(Paragraph(f"<b>Grand Total:</b> ₹{order_details.get('total_amount', Decimal('0.00')):.2f}", styles['h2']))
    #         story.append(Spacer(1, 0.5*inch))
    #         story.append(Paragraph(f"Status: {order_details.get('status', 'N/A')}", styles['Normal']))
    #
    #         doc.build(story)
    #         app.logger.info(f"Generated PDF invoice: {invoice_filepath_pdf}")
    #         return f'uploads/invoices/{invoice_filename_base}.pdf'
    #     except Exception as e:
    #         app.logger.error(f"Error generating PDF with ReportLab: {e}", exc_info=True)
    #         # Fallback to text invoice if PDF generation fails
    #         pass
    # --- End of Conceptual ReportLab PDF Generation ---

    # Fallback: Basic text content for the dummy invoice (always executed in this environment)
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
      Email: {order_details.get('user_email', 'N/A')}
      Phone: {order_details.get('customer_phone', 'N/A')}
      Address: {order_details.get('customer_address', 'N/A')}
      Pincode: {order_details.get('customer_pincode', 'N/A')}

    Items:
    {'='*50}
    {'SKU':<10} {'Name':<25} {'Qty':<5} {'Unit Price':<12} {'Total Price':<12}
    {'='*50}
    """
    for item in order_details.get('items', []):
        invoice_content += f"{item.get('sku', 'N/A'):<10} {item.get('name', 'N/A'):<25} {item.get('quantity', 0):<5} {item.get('unit_price_before_gst', Decimal('0.00')):.2f} {item.get('total_price', Decimal('0.00')):.2f}\n"

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
    return f'uploads/invoices/{invoice_filename_base}.pdf' # This will be used with mimetype 'application/pdf'


# --- NEW: Function to send email with attachment ---
def send_email_with_attachment(recipient_email, subject, body, attachment_path=None, attachment_filename=None):
    sender_email = app.config.get('SENDER_EMAIL')
    sender_password = app.config.get('SENDER_PASSWORD')
    smtp_server = app.config.get('SMTP_SERVER')
    smtp_port = app.config.get('SMTP_PORT')

    if not all([sender_email, sender_password, smtp_server, smtp_port]):
        app.logger.error("Email sender configuration missing.")
        return False, "Email server not configured."

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain'))

    if attachment_path and attachment_filename:
        try:
            with open(attachment_path, 'rb') as f:
                attach = MIMEApplication(f.read(), _subtype="pdf") # Treat as PDF despite .txt extension
                attach.add_header('Content-Disposition', 'attachment', filename=attachment_filename)
                msg.attach(attach)
        except Exception as e:
            app.logger.error(f"Failed to attach file {attachment_path}: {e}", exc_info=True)
            return False, "Failed to attach invoice PDF."

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls() # Secure the connection
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True, "Email sent successfully!"
    except Exception as e:
        app.logger.error(f"Failed to send email to {recipient_email}: {e}", exc_info=True)
        return False, f"Failed to send email: {e}"

# --- NEW: Function to generate UPI QR code URL ---
def generate_upi_qr_url(upi_id, payee_name, amount, transaction_note="Payment for artwork"):
    # Using api.qrserver.com for dynamic QR code generation
    # URL format: upi://pay?pa={UPI_ID}&pn={PAYEE_NAME}&am={AMOUNT}&cu=INR&tn={TRANSACTION_NOTE}
    # For QR code, we encode this UPI URI.
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

def calculate_item_price_with_options(artwork, size_option, frame_option, glass_option):
    """Calculates the unit price of an artwork based on selected options (before GST)."""
    # Artwork prices are already Decimal due to load_artworks_data
    unit_price = artwork.get('original_price', Decimal('0.00'))

    # Only apply options if the artwork is a 'Painting'
    if artwork.get('category') == 'Paintings':
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
            # Flash message if quantity was adjusted (for full page load, not AJAX)
            # flash(f"Quantity for '{artwork_info.get('name')}' adjusted to available stock: {stock_available}", 'warning')
        
        # If item quantity becomes 0 due to clamping, or was already 0/negative, mark for removal
        if item_quantity <= 0:
            items_to_remove.append(item_id)
            # Flash messages (for full page load, not AJAX)
            # if stock_available == 0:
            # flash(f"'{artwork_info.get('name')}' is out of stock and removed from cart.", 'danger')
            # else: # If quantity was zero or negative for some reason, remove it
            # flash(f"'{artwork_info.get('name')}' quantity was invalid and removed from cart.", 'danger')
            continue # Skip further processing for this item

        # Recalculate unit price based on selected options and original prices from artworks_data
        unit_price_before_gst = calculate_item_price_with_options(
            artwork_info,
            item_data.get('size'),
            item_data.get('frame'),
            item_data.get('glass') # This should be 'Standard' or 'None'
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
            'image': artwork_info.get('images', ['images/placeholder.png'])[0], # Ensure a default image
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
    
    session['cart'] = current_cart_session # Reassigning the dict effectively sets session.modified = True
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
        'grand_total': grand_total
    }

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
    artwork = get_artwork_by_sku(sku) # Use the helper function, returns Decimal prices
    if artwork:
        # Prices are already Decimal due to get_artwork_by_sku and load_artworks_data
        return render_template('product_detail.html', artwork=artwork,
                               our_business_email=OUR_BUSINESS_EMAIL,
                               our_business_address=OUR_BUSINESS_ADDRESS,
                               current_year=datetime.now().year)
    flash("Product not found.", "danger")
    return redirect(url_for('index'))

@app.route('/add_to_cart', methods=['POST'])
@login_required 
def add_to_cart():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data received"}), 400

        sku = data.get('sku')
        quantity_raw = data.get('quantity')
        size = data.get('size', 'Original')
        frame = data.get('frame', 'None')
        glass = data.get('glass', 'None')

        # Input validation
        if not sku:
            return jsonify({"success": False, "message": "Missing SKU"}), 400

        try:
            quantity = int(quantity_raw)
            if quantity <= 0:
                return jsonify({"success": False, "message": "Quantity must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "message": f"Invalid quantity format: {quantity_raw}"}), 400

        artwork_info = get_artwork_by_sku(sku) # Use the helper function
        if not artwork_info:
            return jsonify({"success": False, "message": f"Artwork with SKU '{sku}' not found."}), 404
        if artwork_info['stock'] < quantity:
            return jsonify({"success": False, "message": f"Only {artwork_info['stock']} units of {artwork_info['name']} are available."}), 400

        # Calculate item price based on options (returns Decimal)
        unit_price_before_gst = calculate_item_price_with_options(artwork_info, size, frame, glass)
        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE) # Already Decimal

        # Construct a unique item ID for the cart, considering options
        item_id = f"{sku}-{size}-{frame}-{glass}"

        cart = session.get('cart', {})
        
        # Ensure cart is a dictionary
        if not isinstance(cart, dict):
            cart = {}
            session['cart'] = cart

        if item_id in cart:
            # If item already in cart, update quantity and re-calculate its total price components
            new_quantity = cart[item_id].get('quantity', 0) + quantity
            if new_quantity > artwork_info['stock']:
                return jsonify(success=False, message=f"Adding {quantity} more would exceed available stock. Only {artwork_info['stock'] - cart[item_id].get('quantity', 0)} more available.", current_quantity=cart[item_id].get('quantity', 0), stock=artwork_info['stock']), 400
            
            # Recalculate based on new quantity
            cart[item_id]['quantity'] = new_quantity
            cart[item_id]['unit_price_before_gst'] = unit_price_before_gst 
            cart[item_id]['total_price_before_gst'] = unit_price_before_gst * new_quantity
            cart[item_id]['gst_percentage'] = gst_percentage
            cart[item_id]['gst_amount'] = (unit_price_before_gst * new_quantity) * (gst_percentage / Decimal('100'))
            cart[item_id]['total_price'] = cart[item_id]['total_price_before_gst'] + cart[item_id]['gst_amount']
            cart[item_id]['stock_available'] = artwork_info['stock'] # Add stock info for JS
        else:
            # Add new item to cart
            if quantity > artwork_info['stock']:
                return jsonify(success=False, message=f"Quantity requested ({quantity}) exceeds available stock ({artwork_info['stock']}).", stock=artwork_info['stock']), 400

            cart[item_id] = {
                'id': item_id,
                'sku': sku,
                'name': artwork_info.get('name'),
                'image': artwork_info.get('images', ['images/placeholder.png'])[0], # Get first image path, with fallback
                'category': artwork_info.get('category'),
                'size': size,
                'frame': frame,
                'glass': glass,
                'quantity': quantity,
                'unit_price_before_gst': unit_price_before_gst, # This is a Decimal
                'gst_percentage': gst_percentage, # This is a Decimal
                'total_price_before_gst': unit_price_before_gst * quantity, # This is a Decimal
                'gst_amount': (unit_price_before_gst * quantity) * (gst_percentage / Decimal('100')), # This is a Decimal
                'total_price': (unit_price_before_gst * quantity) + ((unit_price_before_gst * quantity) * (gst_percentage / Decimal('100'))), # This is a Decimal
                'stock_available': artwork_info['stock'] # Add stock info for JS
            }
        
        session['cart'] = cart
        session.modified = True # Ensure session changes are saved
        # Recalculate global cart totals after adding/updating item
        updated_summary = calculate_cart_totals(session.get('cart', {}), load_artworks_data())

        return jsonify(success=True, message=f"'{artwork_info.get('name')}' added to cart!", cart_count=len(session['cart']), **updated_summary)

    except Exception as e:
        app.logger.error(f"Error adding to cart: {e}", exc_info=True)
        return jsonify(success=False, message=f"An unexpected error occurred while adding to cart: {e}"), 500


@app.route('/update_cart_session', methods=['POST'])
def update_cart_session():
    """
    Endpoint for client-side JS to sync its local cart state with the server session.
    Can also be used to simply fetch the latest server cart state if no 'cart' is provided in payload.
    """
    data = request.get_json()
    client_cart = data.get('cart') # This is the cart object from client-side sessionStorage

    artworks_data = load_artworks_data() # Use the specific loader (returns Decimal prices)

    if client_cart is not None:
        # If client sends a cart, update the server's session cart with it
        # Ensure quantities are valid and prices are consistent with server data
        updated_server_cart = {}
        for item_id, item_data in client_cart.items():
            sku = item_data.get('sku')
            artwork_info = get_artwork_by_sku(sku) # Use the new helper function

            if artwork_info:
                # Re-calculate prices and validate quantity based on server's artwork data
                unit_price_before_gst = calculate_item_price_with_options(
                    artwork_info,
                    item_data.get('size'),
                    item_data.get('frame'),
                    item_data.get('glass')
                ) # This returns Decimal
                gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE) # Already Decimal
                stock_available = artwork_info.get('stock', 0)
                
                quantity = int(item_data.get('quantity', 0))
                if quantity > stock_available:
                    quantity = stock_available # Clamp to available stock
                if quantity <= 0 and stock_available > 0:
                    quantity = 1 # Ensure at least 1 if stock exists, unless genuinely 0
                if stock_available == 0:
                    quantity = 0

                if quantity > 0: # Only add to updated_server_cart if quantity is positive
                    item_total_price_before_gst = unit_price_before_gst * quantity
                    item_gst_amount = item_total_price_before_gst * (gst_percentage / Decimal('100'))
                    item_total_price_with_gst = item_total_price_before_gst + item_gst_amount

                    updated_server_cart[item_id] = {
                        'id': item_id,
                        'sku': sku,
                        'name': artwork_info.get('name'),
                        'image': artwork_info.get('images', ['images/placeholder.png'])[0],
                        'category': item_data.get('category'), # Keep client's category as fallback if not in artwork_info (though it should be)
                        'size': item_data.get('size'),
                        'frame': item_data.get('frame'),
                        'glass': item_data.get('glass'),
                        'quantity': quantity,
                        'unit_price_before_gst': unit_price_before_gst, # Decimal
                        'gst_percentage': gst_percentage, # Decimal
                        'total_price_before_gst': item_total_price_before_gst, # Decimal
                        'gst_amount': item_gst_amount, # Decimal
                        'total_price': item_total_price_with_gst, # Decimal
                        'stock_available': stock_available # Pass available stock
                    }
            else:
                pass # If artwork not found in our database, implicitly remove from cart
        
        session['cart'] = updated_server_cart
        session.modified = True # Crucial for session updates to persist
    else:
        pass # The calculate_cart_totals will automatically work on existing session['cart']

    # Always return the calculated totals based on the server's current session cart
    cart_summary = calculate_cart_totals(session.get('cart', {}), load_artworks_data())
    
    return jsonify(success=True, message="Cart synchronized.", **cart_summary)


@app.route('/cart')
@login_required # This was not in your shared code but is crucial for cart
def cart():
    artworks_data = load_artworks_data() # Use the specific loader
    cart_data_from_session = session.get('cart', {})

    # Ensure cart_data_from_session is a dictionary (for robustness)
    if not isinstance(cart_data_from_session, dict):
        cart_data_from_session = {}
        session['cart'] = cart_data_from_session 
        session.modified = True

    # Recalculate totals and items for display based on the session cart
    # This also handles stock clamping and removing items with zero quantity/stock
    cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)
    
    return render_template('cart.html',
                           cart_summary=cart_summary, # PASS THE ENTIRE DICTIONARY
                           MAX_SHIPPING_COST_FREE_THRESHOLD=MAX_SHIPPING_COST_FREE_THRESHOLD)

@app.route('/update_cart_item_quantity', methods=['POST'])
@login_required 
def update_cart_item_quantity():
    try:
        data = request.get_json()
        item_id = data.get('id') # Using 'id' as per JS
        new_quantity_raw = data.get('quantity') # Using 'quantity' as per JS

        if not item_id or new_quantity_raw is None:
            return jsonify(success=False, message="Invalid request data (item_id or new_quantity missing)."), 400

        current_cart_session = session.get('cart', {})
        
        # Store original quantity for potential rollback in JS if error occurs
        original_quantity = current_cart_session.get(item_id, {}).get('quantity')

        artwork_sku = current_cart_session.get(item_id, {}).get('sku')
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

        if new_quantity_raw < 1: 
            new_quantity = 0 # Force to 0 for removal logic
        else:
            new_quantity = int(new_quantity_raw) # Convert to int

        if new_quantity < 1:
            if item_id in current_cart_session:
                del current_cart_session[item_id]
                session['cart'] = current_cart_session
                session.modified = True
                message = "Item removed from cart."
                item_removed = True
        elif new_quantity > available_stock:
            current_cart_session[item_id]['quantity'] = available_stock
            session['cart'] = current_cart_session
            session.modified = True
            message = f"Only {available_stock} of {artwork_info.get('name')} available. Quantity adjusted."
            if available_stock == 0:
                del current_cart_session[item_id]
                session['cart'] = current_cart_session
                session.modified = True
                item_removed = True
                message = f"No stock for {artwork_info.get('name')}. Item removed."
        else:
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
                response_data['item_removed'] = True
                response_data['message'] = f"Item {artwork_info.get('name')} removed from cart (quantity became 0 or out of stock)."

        return jsonify(response_data), 200

    except Exception as e:
        app.logger.error(f"ERROR: update_cart_item_quantity: {e}", exc_info=True)
        # Return the original quantity to allow JS to revert the UI state
        return jsonify(success=False, message=f"Error updating cart quantity: {e}", current_quantity=original_quantity if original_quantity is not None else 0), 500

@app.route('/remove_from_cart', methods=['POST'])
@login_required 
def remove_from_cart():
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

@app.route('/purchase_form', methods=['GET', 'POST'])
@login_required
def purchase_form():
    if request.method == 'GET':
        item_for_direct_purchase = session.get('direct_purchase_item')

        if item_for_direct_purchase:
            cart_summary = {
                'cart_items': [item_for_direct_purchase],
                'subtotal_before_gst': item_for_direct_purchase['total_price_before_gst'],
                'total_gst_amount': item_for_direct_purchase['gst_amount'],
                'cgst_amount': item_for_direct_purchase['gst_amount'] / Decimal('2'),
                'sgst_amount': item_for_direct_purchase['gst_amount'] / Decimal('2'),
                'shipping_charge': Decimal('0.00'),
                'grand_total': item_for_direct_purchase['total_price']
            }
            if cart_summary['subtotal_before_gst'] > 0 and cart_summary['subtotal_before_gst'] < MAX_SHIPPING_COST_FREE_THRESHOLD:
                cart_summary['shipping_charge'] = DEFAULT_SHIPPING_CHARGE
            cart_summary['grand_total'] = cart_summary['subtotal_before_gst'] + cart_summary['total_gst_amount'] + cart_summary['shipping_charge']

        else:
            cart_data_from_session = session.get('cart', {})
            if not isinstance(cart_data_from_session, dict):
                cart_data_from_session = {}
                session['cart'] = cart_data_from_session 
                session.modified = True

            if not cart_data_from_session:
                flash('Your cart is empty. Please add items to proceed to checkout.', 'info')
                return redirect(url_for('cart'))

            artworks_data = load_artworks_data()
            cart_summary = calculate_cart_totals(cart_data_from_session, artworks_data)

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
            subtotal_before_gst = item_for_direct_purchase['total_price_before_gst']
            total_gst_amount = item_for_direct_purchase['gst_amount']
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
            total_amount = cart_summary['grand_total']
            subtotal_before_gst = cart_summary['subtotal_before_gst']
            total_gst_amount = cart_summary['total_gst_amount']
            shipping_charge = cart_summary['shipping_charge']

        if not items_to_process:
            flash("No items to purchase. Please add items to your cart.", "danger")
            return redirect(url_for('index'))
        
        # Gather shipping details from form
        customer_name = request.form.get('name', current_user.name)
        customer_email = request.form.get('email', current_user.email)
        customer_phone = request.form.get('phone', current_user.phone)
        customer_address = request.form.get('address', current_user.address)
        customer_pincode = request.form.get('pincode', current_user.pincode)

        # Update user's profile with latest shipping info if different
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
                'invoice_details': {
                    'invoice_status': 'Not Applicable',
                    'is_held_by_admin': False,
                    'invoice_pdf_path': None
                }
            }

            orders = load_orders_data()
            orders.append(new_order)
            save_json('orders.json', orders)

            flash("Order placed successfully. Please complete the payment.", "success")
            return redirect(url_for('payment_initiate', order_id=new_order_id, amount=new_order['total_amount']))

        except Exception as e:
            app.logger.error(f"Error processing purchase form: {e}", exc_info=True)
            flash(f"An unexpected error occurred during your purchase. Please try again. Error: {e}", "danger")
            if not item_for_direct_purchase:
                session['cart'] = {item['id']: item for item in items_to_process}
            else:
                session['direct_purchase_item'] = items_to_process[0]
            session.modified = True
            return redirect(url_for('purchase_form'))

@app.route('/create_direct_order', methods=['POST'])
@login_required
def create_direct_order():
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
            return jsonify({"success": False, "message": f"Invalid quantity format: {quantity_raw}"}), 400

        artwork_info = get_artwork_by_sku(sku) # Use the helper function
        if not artwork_info:
            return jsonify({"success": False, "message": f"Artwork with SKU '{sku}' not found."}), 404
        if artwork_info['stock'] < quantity:
            return jsonify({"success": False, "message": f"Only {artwork_info['stock']} units of {artwork_info['name']} are available for direct purchase."}), 400

        unit_price_before_gst = calculate_item_price_with_options(artwork_info, size, frame, glass)
        gst_percentage = artwork_info.get('gst_percentage', DEFAULT_GST_PERCENTAGE)

        item_total_price_before_gst = unit_price_before_gst * quantity
        item_gst_amount = item_total_price_before_gst * (gst_percentage / Decimal('100'))
        final_item_total_price = item_total_price_before_gst + item_gst_amount

        direct_order_item = {
            'sku': sku,
            'name': artwork_info.get('name'),
            'image': artwork_info.get('images', ['images/placeholder.png'])[0],
            'unit_price_before_options': artwork_info['original_price'],
            'unit_price_before_gst': unit_price_before_gst,
            'quantity': quantity,
            'size': size,
            'frame': frame,
            'glass': glass,
            'gst_percentage': gst_percentage,
            'gst_amount': item_gst_amount,
            'total_price_before_gst': item_total_price_before_gst,
            'total_price': final_item_total_price
        }

        session['direct_purchase_item'] = direct_order_item
        session.modified = True
        
        redirect_url = url_for('purchase_form') 

        return jsonify({"success": True, "message": "Direct order initiated.", "redirect_url": redirect_url})

    except Exception as e:
        app.logger.error(f"Error creating direct order: {e}", exc_info=True)
        return jsonify({"success": False, "message": "An unexpected error occurred while processing your direct order."}), 500


# Payment Initiate Page
@app.route('/payment-initiate/<order_id>/<amount>', methods=['GET'])
@login_required
def payment_initiate(order_id, amount):
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        flash('Order not found. Please try again.', 'danger')
        return redirect(url_for('my_orders')) 

    try:
        requested_amount = Decimal(str(amount))
        if abs(order.get('total_amount', Decimal('0.00')) - requested_amount) > Decimal('0.01'):
            flash('Payment amount mismatch. Please try again or contact support.', 'danger')
            return redirect(url_for('my_orders'))
    except Exception as e:
        app.logger.error(f"Error converting amount to Decimal or comparing: {e}", exc_info=True)
        flash('Invalid amount provided. Please try again or contact support.', 'danger')
        return redirect(url_for('my_orders'))

    # Generate UPI QR Code URL
    transaction_note = f"Order {order_id} from {OUR_BUSINESS_NAME}"
    upi_qr_url = generate_upi_qr_url(UPI_ID, BANKING_NAME, requested_amount, transaction_note)

    context = {
        'order_id': order_id,
        'amount': requested_amount,
        'upi_id': UPI_ID,
        'banking_name': BANKING_NAME,
        'bank_name': BANK_NAME, # Added for display
        'upi_qr_url': upi_qr_url # Pass the generated QR URL to template
    }
    return render_template('payment-initiate.html', **context)

# Confirm Payment Details
@app.route('/confirm_payment', methods=['POST'])
@login_required
def confirm_payment():
    order_id = request.form.get('order_id')
    transaction_id = request.form.get('transaction_id')
    screenshot_file = request.files.get('screenshot')

    if not all([order_id, transaction_id]):
        flash('Order ID and Transaction ID are required.', 'danger')
        return redirect(url_for('my_orders')) 

    orders = load_orders_data()
    order_found = False
    screenshot_path = None

    if screenshot_file and screenshot_file.filename != '':
        try:
            os.makedirs(app.config['PAYMENT_SCREENSHOTS_FOLDER'], exist_ok=True)
            
            filename = str(uuid.uuid4()) + os.path.splitext(secure_filename(screenshot_file.filename))[1]
            screenshot_path_full = os.path.join(app.config['PAYMENT_SCREENSHOTS_FOLDER'], filename)
            screenshot_file.save(screenshot_path_full)
            screenshot_path = f'uploads/payment_screenshots/{filename}' 
        except Exception as e:
            app.logger.error(f"ERROR: Failed to save screenshot: {e}", exc_info=True)
            flash('Failed to upload screenshot. Please try again.', 'warning')


    for order in orders:
        if order.get('order_id') == order_id:
            order_found = True
            order['status'] = "Payment Submitted - Awaiting Verification"
            order['transaction_id'] = transaction_id
            if screenshot_path:
                order['payment_screenshot'] = screenshot_path
            order['payment_submitted_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break

    if order_found:
        save_json('orders.json', orders)
        session.pop('cart', None)
        session.pop('direct_purchase_item', None)
        session.modified = True
        flash('Payment details submitted successfully. Your order status will be updated after verification.', 'success')
        response = make_response(redirect(url_for('thank_you_page')))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    else:
        flash('Order not found. Please ensure you are submitting details for a valid order.', 'danger')
        return redirect(url_for('my_orders')) 

@app.route('/thank-you')
def thank_you_page():
    return render_template('thank-you.html')


# --- USER SPECIFIC ROUTES ---
@app.route('/my_orders')
@login_required
def my_orders():
    orders = load_orders_data()
    user_orders = []
    for order in orders:
        order['remark'] = order.get('remark', '') 
        if str(order.get('user_id')) == str(current_user.id):
            user_orders.append(order)
    
    user_orders.sort(key=lambda x: datetime.strptime(x['placed_on'], "%Y-%m-%d %H:%M:%S"), reverse=True)

    return render_template('my_orders.html', orders=user_orders)

@app.route('/cancel-order/<order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    orders = load_orders_data()
    order_found = False
    
    for order_idx, order in enumerate(orders):
        if order.get('order_id') == order_id:
            if str(order.get('user_id')) == str(current_user.id):
                if order.get('status') in ["Pending Payment", "Payment Submitted - Awaiting Verification"]:
                    orders[order_idx]['status'] = "Cancelled by User"
                    if 'invoice_details' not in orders[order_idx]:
                        orders[order_idx]['invoice_details'] = {}
                    orders[order_idx]['invoice_details']['invoice_status'] = 'Cancelled'
                    orders[order_idx]['invoice_details']['is_held_by_admin'] = True 
                    save_json('orders.json', orders)
                    flash(f"Order {order_id} has been cancelled.", "success")
                else:
                    flash(f"Order {order_id} cannot be cancelled at its current status ({order.get('status')}). Please contact support.", "danger")
                order_found = True
                break
            else:
                flash("You do not have permission to cancel this order.", "danger")
                order_found = True
                break
    
    if not order_found:
        flash(f"Order {order_id} not found.", "danger")
    
    return redirect(url_for('my_orders'))

@app.route('/process_checkout_from_cart', methods=['POST']) # Renamed route
@login_required
def process_checkout_from_cart(): # Renamed function
    if not session.get('cart'):
        flash("Your cart is empty!", "warning")
        return redirect(url_for('cart'))
    
    flash("Proceeding to checkout...", "info")
    return jsonify({"success": True, "redirect_url": url_for('purchase_form')})


@app.route('/user-dashboard')
@login_required
def user_dashboard():
    return render_template('user_dashboard.html')

@app.route('/profile')
@login_required
def profile():
    user_info = {
        'name': current_user.name,
        'email': current_user.email,
        'phone': current_user.phone,
        'address': current_user.address,
        'pincode': current_user.pincode,
        'role': current_user.role
    }
    return render_template('profile.html', user_info=user_info)


# --- Admin Routes ---

@app.route('/admin-panel')
@admin_required
def admin_panel():
    orders = load_orders_data()
    artworks = load_artworks_data()
    return render_template('admin_panel.html', orders=orders, artworks=artworks)

@app.route('/admin/artworks')
@admin_required
def admin_artworks_view():
    artworks = load_artworks_data()
    return render_template('admin_artworks_view.html', artworks=artworks)

@app.route('/admin/orders')
@admin_required
def admin_orders_view():
    orders = load_orders_data()
    
    filter_status = request.args.get('status')
    filter_invoice_status = request.args.get('invoice_status')
    search_query = request.args.get('search_query', '').lower()

    filtered_orders = []
    for order in orders:
        match_status = True
        if filter_status and order.get('status') != filter_status:
            match_status = False
        
        match_invoice_status = True
        invoice_det = order.get('invoice_details', {})
        if filter_invoice_status and invoice_det.get('invoice_status') != filter_invoice_status:
            match_invoice_status = False

        match_search = True
        if search_query:
            order_id = order.get('order_id', '').lower()
            customer_name = order.get('customer_name', '').lower()
            customer_email = order.get('user_email', '').lower()
            if not (search_query in order_id or search_query in customer_name or search_query in customer_email):
                match_search = False

        if match_status and match_invoice_status and match_search:
            filtered_orders.append(order)
    
    filtered_orders.sort(key=lambda x: datetime.strptime(x['placed_on'], "%Y-%m-%d %H:%M:%S"), reverse=True)

    return render_template('admin_orders_view.html', 
                           orders=filtered_orders,
                           current_filter_status=filter_status,
                           current_filter_invoice_status=filter_invoice_status,
                           current_search_query=search_query)

@app.route('/admin/order/update', methods=['POST'])
@admin_required
def admin_orders_update():
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    courier = request.form.get('courier')
    tracking_number = request.form.get('tracking_number')

    orders = load_orders_data()
    order_found = False
    for order in orders:
        if order.get('order_id') == order_id:
            order['status'] = new_status
            order['courier'] = courier if new_status == 'Shipped' else None
            order['tracking_number'] = tracking_number if new_status == 'Shipped' else None
            if new_status == 'Shipped' and not order.get('shipped_on'):
                order['shipped_on'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif new_status != 'Shipped':
                order['shipped_on'] = None
            
            if new_status == 'Shipped' and not order.get('invoice_details', {}).get('is_held_by_admin', False):
                if 'invoice_details' not in order:
                    order['invoice_details'] = {}
                order['invoice_details']['invoice_status'] = 'Prepared'
            
            save_json('orders.json', orders)
            flash(f'Order {order_id} status updated to {new_status}.', 'success')
            order_found = True
            break
    if not order_found:
        flash(f'Order {order_id} not found.', 'danger')
    return redirect(url_for('admin_orders_view'))

@app.route('/admin/order/remark', methods=['POST'])
@admin_required
def admin_add_remark():
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        remark_text = data.get('remark')

        orders = load_orders_data()
        order_found = False
        for order in orders:
            if order.get('order_id') == order_id:
                order['remark'] = remark_text
                save_json('orders.json', orders)
                flash(f"Remark for Order {order_id} updated.", "success")
                order_found = True
                return jsonify(success=True, message=f"Remark for Order {order_id} updated.", remark=remark_text)
        if not order_found:
            flash(f"Order {order_id} not found.", "danger")
            return jsonify(success=False, message="Order not found."), 404
    except Exception as e:
        app.logger.error(f"ERROR in admin_add_remark: {e}", exc_info=True)
        flash(f"An error occurred: {e}", "danger")
        return jsonify(success=False, message=f"An error occurred: {e}"), 500


@app.route('/admin/invoice/edit/<order_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_invoice(order_id):
    orders = load_orders_data()
    order = next((o for o in orders if o['order_id'] == order_id), None)

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('admin_orders_view'))

    if 'invoice_details' not in order:
        order['invoice_details'] = {}
    
    invoice_det = order['invoice_details']
    invoice_det.setdefault('business_name', OUR_BUSINESS_NAME)
    invoice_det.setdefault('gst_number', OUR_GSTIN)
    invoice_det.setdefault('pan_number', OUR_PAN)
    invoice_det.setdefault('business_address', OUR_BUSINESS_ADDRESS)
    invoice_det.setdefault('customer_phone_camouflaged', order.get('customer_phone', 'N/A'))
    if invoice_det.get('invoice_number') is None:
        invoice_det['invoice_number'] = str(uuid.uuid4())[:8].upper()
    invoice_det.setdefault('invoice_date', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    invoice_det.setdefault('billing_address', order.get('customer_address', 'N/A'))
    invoice_det.setdefault('gst_rate_applied', DEFAULT_INVOICE_GST_RATE)
    invoice_det.setdefault('total_gst_amount', Decimal('0.00'))
    invoice_det.setdefault('cgst_amount', Decimal('0.00'))
    invoice_det.setdefault('sgst_amount', Decimal('0.00'))
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
        return jsonify(success=False, message=f'Invoice for Order {order_id} has already been sent.'), 400
    
    # 1. Generate PDF (or a placeholder text file for this environment)
    # The generate_invoice_pdf function will now return a path with .pdf extension
    # regardless of whether a real PDF or a dummy .txt is generated.
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
    full_invoice_pdf_path = os.path.join(app.root_path, 'static', invoice_pdf_path_relative)
    
    # The attachment_filename is what the user sees, so use .pdf
    attachment_filename_for_email = f"invoice_{order_id}.pdf" 

    success, message = send_email_with_attachment(recipient_email, subject, body, 
                                                  attachment_path=full_invoice_pdf_path,
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
        # In this environment, it will be a .txt file, but we send it as .pdf
        # If ReportLab is enabled, it would be a true .pdf
        
        # Adjust path to point to .txt if the invoice_pdf_path_relative ends in .pdf but is actually .txt
        actual_file_on_disk_path = os.path.splitext(invoice_path_relative)[0] + '.txt'
        full_path = os.path.join(app.root_path, 'static', actual_file_on_disk_path)

        if os.path.exists(full_path):
            # Send the .txt file, but specify mimetype as PDF and download_name as .pdf
            return send_file(full_path, as_attachment=True, download_name=f"invoice_{order_id}.pdf", mimetype='application/pdf')
    
    flash(f'Invoice PDF not found or path invalid for Order {order_id}. Please generate it first.', 'warning')
    return redirect(url_for('admin_edit_invoice', order_id=order_id))


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
@app.route('/admin/export_orders_csv')
@admin_required
def export_orders_csv():
    orders = load_orders_data()

    # Define the CSV column headers
    fieldnames = [
        'Order ID', 'User ID', 'User Email', 'Customer Name', 'Customer Phone',
        'Customer Address', 'Customer Pincode', 'Placed On', 'Status', 'Remark',
        'Subtotal Before GST', 'Total GST Amount', 'CGST Amount', 'SGST Amount',
        'Shipping Charge', 'Total Amount', 'Transaction ID', 'Payment Submitted On',
        'Invoice Status', 'Invoice Held by Admin', 'Invoice PDF Path', 'Invoice Email Sent On'
    ]
    
    # Add fields for each item in the order (assuming max 5 items for simplicity, extend as needed)
    # A more robust solution might involve one row per order item.
    for i in range(1, 6): # Up to 5 items per order in the CSV row
        fieldnames.extend([
            f'Item {i} SKU', f'Item {i} Name', f'Item {i} Quantity',
            f'Item {i} Unit Price Before GST', f'Item {i} GST Percentage', f'Item {i} GST Amount',
            f'Item {i} Total Price Before GST', f'Item {i} Total Price'
        ])


    # Create a BytesIO object to write CSV data into memory
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
            return render_template('add_artwork.html', categories=categories, artwork=request.form.to_dict())

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
            image_filenames.append('images/placeholder.png')

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
    return render_template('add_artwork.html', categories=categories)

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

        if artwork['category'] == 'Paintings':
            artwork['size_a4'] = Decimal(request.form.get('size_a4', '0.00'))
            artwork['size_a5'] = Decimal(request.form.get('size_a5', '0.00'))
            artwork['size_letter'] = Decimal(request.form.get('size_letter', '0.00'))
            artwork['size_legal'] = Decimal(request.form.get('size_legal', '0.00'))
            artwork['frame_wooden'] = Decimal(request.form.get('frame_wooden', '0.00'))
            artwork['frame_metal'] = Decimal(request.form.get('frame_metal', '0.00'))
            artwork['frame_pvc'] = Decimal(request.form.get('frame_pvc', '0.00'))
            artwork['glass_price'] = Decimal(request.form.get('glass_price', '0.00'))
        else:
            artwork['size_a4'] = Decimal('0.00')
            artwork['size_a5'] = Decimal('0.00')
            artwork['size_letter'] = Decimal('0.00')
            artwork['size_legal'] = Decimal('0.00')
            artwork['frame_wooden'] = Decimal('0.00')
            artwork['frame_metal'] = Decimal('0.00')
            artwork['frame_pvc'] = Decimal('0.00')
            artwork['glass_price'] = Decimal('0.00')

        new_image_filenames = artwork.get('images', [])
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    unique_filename = str(uuid.uuid4()) + '_' + filename
                    file_path = os.path.join(app.config['PRODUCT_IMAGES_FOLDER'], unique_filename)
                    file.save(file_path)
                    new_image_filenames.append(f'uploads/product_images/{unique_filename}')
        artwork['images'] = new_image_filenames
        
        if not artwork['images']:
            artwork['images'] = ['images/placeholder.png']


        save_json('artworks.json', artworks)
        flash(f'Artwork "{artwork["name"]}" updated successfully!', 'success')
        return redirect(url_for('admin_artworks_view'))
    
    return render_template('edit_artwork.html', artwork=artwork, categories=categories)

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


@app.route('/admin/categories')
@admin_required
def admin_categories_view():
    categories = load_categories_data()
    return render_template('admin_categories_view.html', categories=categories)

@app.route('/admin/category/add', methods=['POST'])
@admin_required
def admin_add_category():
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    image_file = request.files.get('image')

    categories = load_categories_data()
    if any(c['name'].lower() == name.lower() for c in categories):
        flash('Category with this name already exists.', 'danger')
        return redirect(url_for('admin_categories_view'))

    image_path = None
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
    save_json('categories.json', categories)
    flash(f'Category "{name}" added successfully!', 'success')
    return redirect(url_for('admin_categories_view'))

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
        flash(f'Category "{category["name"]}" updated successfully!', 'success')
        return redirect(url_for('admin_categories_view'))
    return render_template('admin_edit_category.html', category=category)


@app.route('/admin/category/delete/<category_id>', methods=['POST'])
@admin_required
def admin_delete_category(category_id):
    categories = load_json('categories.json')
    original_len = len(categories)
    categories = [c for c in categories if c.get('id') != category_id]
    if len(categories) < original_len:
        save_json('categories.json', categories)
        flash('Category deleted successfully.', 'success')
    else:
        flash('Category not found.', 'danger')
    return redirect(url_for('admin_categories_view'))

# --- User Authentication Routes ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        redirect_endpoint = session.pop('redirect_after_login_endpoint', None)
        next_url_from_arg = request.args.get('next')

        if redirect_endpoint == 'cart':
            return redirect(url_for('cart'))
        elif redirect_endpoint == 'purchase_form':
            return redirect(next_url_from_arg or url_for('purchase_form'))
        return redirect(next_url_from_arg or url_for('index'))
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']
        address = request.form['address']
        pincode = request.form['pincode']

        users = load_users_data()
        if User.find_by_email(email):
            flash('Email already registered. Please login or use a different email.', 'danger')
            return render_template('signup.html', form_data=request.form)

        hashed_password = generate_password_hash(password)
        new_user = User(id=uuid.uuid4(), email=email, password=hashed_password, name=name, phone=phone, address=address, pincode=pincode, role='user').__dict__
        users.append(new_user)
        save_json('users.json', users)
        flash('Account created successfully! Please log in.', 'success')
        
        redirect_endpoint = session.pop('redirect_after_login_endpoint', None)
        next_url_after_signup = request.args.get('next')

        if redirect_endpoint:
            if redirect_endpoint == 'cart':
                return redirect(url_for('user_login', next=url_for('cart')))
            elif redirect_endpoint == 'purchase_form':
                return redirect(url_for('user_login', next=next_url_after_signup))
            else:
                return redirect(url_for('user_login', next=url_for(redirect_endpoint)))
        
        return redirect(url_for('user_login'))
    
    next_url = request.args.get('next')
    if next_url:
        if 'cart' in next_url:
            session['redirect_after_login_endpoint'] = 'cart'
        elif 'purchase-form' in next_url:
            session['redirect_after_login_endpoint'] = 'purchase_form'
        else:
            session['redirect_after_login_endpoint'] = 'index'
        session.modified = True
    
    return render_template('signup.html', next_url=next_url)

@app.route('/login', methods=['GET', 'POST'])
def user_login():
    if current_user.is_authenticated:
        next_page = request.args.get('next') or session.pop('redirect_after_login_endpoint', None)
        if next_page:
            return redirect(next_page)
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.find_by_email(email)
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            
            next_page = request.args.get('next')
            if not next_page and 'redirect_after_login_endpoint' in session:
                next_endpoint = session.pop('redirect_after_login_endpoint')
                if next_endpoint:
                    try:
                        next_page = url_for(next_endpoint)
                    except Exception as e:
                        app.logger.error(f"Error generating URL for endpoint {next_endpoint}: {e}", exc_info=True)
                        next_page = url_for('index')
            
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')
            return render_template('login.html', form_data=request.form)
    
    next_url = request.args.get('next')
    if next_url:
        if 'cart' in next_url:
            session['redirect_after_login_endpoint'] = 'cart'
        elif 'purchase-form' in next_url:
            session['redirect_after_login_endpoint'] = 'purchase_form'
        else:
            session['redirect_after_login_endpoint'] = 'index'
        session.modified = True
    
    return render_template('login.html', next_url=next_url)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.find_by_email(email)
        if user:
            flash('If an account with that email exists, a password reset link has been sent.', 'info')
            app.logger.info(f"DEBUG: Password reset requested for {email}. (No actual email sent in this dummy setup)")
        else:
            flash('If an account with that email exists, a password reset link has been sent.', 'info')
    
    return render_template('forgot_password.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('cart', None)
    session.modified = True
    flash('You have been logged out.', 'info')
    return redirect(url_for('user_login'))


# --- Admin Login ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin():
        return redirect(url_for('admin_panel'))
    
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.find_by_email(email)
        
        if user and user.is_admin() and check_password_hash(user.password, password):
            login_user(user)
            flash('Logged in as Admin successfully!', 'success')
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid admin credentials.', 'danger')
    return render_template('admin_login.html')

if __name__ == '__main__':
    # Create the 'data' directory if it doesn't exist
    os.makedirs('data', exist_ok=True)
    # Load initial data to ensure JSON files exist with empty arrays if not present
    load_json('users.json')
    load_json('artworks.json')
    load_json('orders.json')
    load_json('categories.json')
    app.run(debug=True)

