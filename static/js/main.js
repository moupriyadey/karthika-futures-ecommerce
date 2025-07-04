console.log("✅ main.js loaded and running");


function showCustomAlert(message, type = 'info') {
    const container = document.getElementById('flash-messages-container') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} flash-message position-fixed top-0 end-0 m-3 shadow`;
    alertDiv.style.zIndex = 9999;
    alertDiv.textContent = message;
    container.appendChild(alertDiv);
    setTimeout(() => alertDiv.remove(), 5000);
}

// Global variable to store CSRF token

// Helper function to get headers including CSRF token
// Helper function to get headers including CSRF token
function getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (window.csrfToken) { // Use the global window.csrfToken
        headers['X-CSRFToken'] = window.csrfToken;
    }
    return headers;
}
/**
 * Handles the "Buy Now" action, directly preparing an order.
 * @param {string} sku - The SKU of the product.
 * @param {string} name - The name of the product.
 * @param {string} imageUrl - The URL of the product image.
 * @param {Object} options - Object containing selected options (size, frame, glass).
 * @param {number} quantity - The selected quantity.
 * @param {number} basePrice - The base price of the product without options.
 * @param {number} gstPercentage - The GST percentage applicable.
 */
async function buyNow(sku, name, imageUrl, options, quantity, basePrice, gstPercentage) {
    const itemToBuyNow = {
        sku: sku,
        name: name,
        imageUrl: imageUrl,
        options: options, // options should already contain size, frame, glass
        quantity: quantity,
        unitPrice: basePrice,
        gstPercentage: gstPercentage
    };

    // Check if isUserLoggedIn is defined and true globally (e.g., set in _base.html)
    if (!window.isUserLoggedIn) {
        sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
        sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form');
        window.location.href = '/user-login?next=' + encodeURIComponent('/purchase_form');
        return;
    }

    try {
        const response = await fetch('/create_direct_order', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(itemToBuyNow)
        });

        const data = await response.json();

        if (response.ok && data.success) {
            showCustomAlert(data.message || 'Direct purchase initiated. Redirecting...', 'success');
            window.location.href = data.redirect_url;
        } else {
            showCustomAlert(data.message || 'Failed to initiate direct purchase.', 'danger');
        }
    } catch (error) {
        console.error('Error in buyNow fetch:', error);
        showCustomAlert('An error occurred during purchase. Please try again.', 'danger');
    }
}

/**
 * Handles adding an item to the cart.
 * @param {string} sku - The SKU of the product.
 * @param {number} quantity - The selected quantity.
 * @param {string|null} size - The selected size option.
 * @param {string|null} frame - The selected frame option.
 * @param {string|null} glass - The selected glass option.
 */
async function addToCart(sku, quantity, size, frame, glass) {
    const itemData = {
        sku: sku,
        quantity: quantity,
        size: size,
        frame: frame,
        glass: glass
    };
    try {
        const response = await fetch('/add-to-cart', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(itemData)
        });
        const data = await response.json();
        if (response.ok && data.success) {
            showCustomAlert(data.message || "Item added to cart!", "success");
            // ✅ Fix: Safely check for data.cart_summary before accessing its properties
            if (data.cart_summary && typeof data.cart_summary.total_items_in_cart !== 'undefined') {
                localStorage.setItem('cartCount', data.cart_summary.total_items_in_cart);
                window.updateCartCountDisplay(); // Call the global function
            } else {
                console.warn("Cart summary or total_items_in_cart not found in response, attempting to fetch cart count.");
                fetchCartCount(); // Fallback: fetch the cart count if not provided in the response
            }
        } else {
            showCustomAlert(data.message || "Failed to add item to cart.", "danger");
        }
    } catch (error) {
        console.error("Error adding to cart:", error);
        showCustomAlert("An error occurred. Please try again.", "danger");
    }
}

// Global update for cart count display (used in _base.html and other pages)
function updateCartCountDisplay() {
    const count = localStorage.getItem('cartCount');
    const badge = document.getElementById('cart-count');

    if (badge) {
        const displayCount = parseInt(count) || 0;
        badge.textContent = displayCount;

        // Force it to show only if count > 0
        if (displayCount > 0) {
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    } else {
        console.warn("🛑 cart-count badge not found in DOM");
    }
}


function updateCartCount() {
    fetch("/get_cart_count")
        .then(res => res.json())
        .then(data => {
            if (data.success && data.cart_count !== undefined) {
                localStorage.setItem('cartCount', data.cart_count);
                updateCartCountDisplay();    // update the badge
            }
        })
        .catch(err => {
            console.error("Error fetching cart count:", err);
        });
}

// Function to fetch cart count from the server (used on page load)
async function fetchCartCount() {
    try {
        const response = await fetch('/get_cart_count');
        const data = await response.json();
        if (data.success) {
            localStorage.setItem('cartCount', data.cart_count);
            updateCartCountDisplay();
        }
    } catch (error) {
        console.error("Error fetching cart count:", error);
    }
}

// All DOM-related interactions should be inside DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    // --- CSRF Token Initialization ---
   console.log("CSRF Token initialized from window:", window.csrfToken);

    // Initial fetch of cart count when the page loads
    fetchCartCount();

    // Ensure window.isUserLoggedIn is set if the user is logged in
    // This variable should be initialized in your HTML template (e.g., _base.html)
    // The line below provides a default if not set in HTML, but setting in HTML is preferred.
    window.isUserLoggedIn = typeof window.isUserLoggedIn !== 'undefined' ? window.isUserLoggedIn : false;


    // --- Event Listeners for Product Card Buttons (all_products.html) ---

    // 1. Add to Cart Buttons
    document.querySelectorAll('.add-to-cart-btn').forEach(button => {
        button.addEventListener('click', async (event) => {
            event.preventDefault(); // Prevent default form submission (if button is part of a form)

            const productCard = button.closest('.product-card'); // Get the parent product card
            const sku = productCard.dataset.sku; // Get SKU from data-sku attribute on product-card
            const quantityInput = productCard.querySelector('.quantity-input');
            const selectedQuantity = parseInt(quantityInput?.value || '1', 10);

            // Get selected options (radio buttons)
            let selectedSize = '';
            let selectedFrame = '';
            let selectedGlass = '';

            const sizeOption = productCard.querySelector(`input[name="size-${sku}"]:checked`);
            if (sizeOption) selectedSize = sizeOption.value;

            const frameOption = productCard.querySelector(`input[name="frame-${sku}"]:checked`);
            if (frameOption) selectedFrame = frameOption.value;

            const glassOption = productCard.querySelector(`input[name="glass-${sku}"]:checked`);
            if (glassOption) selectedGlass = glassOption.value;

            console.log("Preparing to add to cart:", { sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass });

            if (!sku || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity.', 'danger');
                return;
            }

            try {
                await addToCart(sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass);
            } catch (error) {
                console.error("Error in Add to Cart button click:", error);
                showCustomAlert("Failed to add item to cart. Please try again.", 'danger');
            }
        });
    });

    // 2. Buy Now Buttons
    document.querySelectorAll('.buy-now-btn').forEach(button => {
        button.addEventListener('click', async (event) => {
            event.preventDefault(); // Prevent default form submission (if button is part of a form)

            const productCard = button.closest('.product-card'); // Get the parent product card
            const sku = productCard.dataset.sku; // Get SKU from data-sku attribute on product-card
            const quantityInput = productCard.querySelector('.quantity-input');
            const selectedQuantity = parseInt(quantityInput?.value || '1', 10);

            // Collect selected options (radio buttons) for buy now
            let options = {};
            productCard.querySelectorAll('input[type="radio"]:checked').forEach(optionInput => {
                const groupName = optionInput.name.split('-')[0]; // e.g., 'size', 'frame', 'glass'
                options[groupName] = optionInput.value;
            });

            const name = productCard.querySelector('.product-card-title')?.textContent.trim();
            const imageUrl = productCard.querySelector('img')?.src; // Assuming img is direct child or easily found
            // Ensure these data-attributes are correctly set on your .product-card HTML element
            const basePrice = parseFloat(productCard.dataset.basePrice || 0);
            // You need to ensure gstPercentage is available on the product card or from a global source
            // For now, assuming it's part of the `artwork` object rendered in the template,
            // you might need to add it as a data-attribute to the product-card div
            // Example: <div class="product-card" data-sku="..." data-base-price="..." data-gst-percentage="{{ artwork.gst_percentage }}">
            const gstPercentage = parseFloat(productCard.dataset.gstPercentage || 0); // Add data-gst-percentage to your product-card HTML

            console.log("Preparing for Buy Now:", { sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage });

            if (!sku || !name || !imageUrl || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity for direct purchase.', 'danger');
                return;
            }

            try {
                await buyNow(sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage);
            } catch (error) {
                console.error("Error in Buy Now button click:", error);
                showCustomAlert("Failed to process direct purchase. Please try again.", 'danger');
            }
        });
    });


    // --- Modal Event Listeners (for forms within the product details modal) ---
    // Ensure your modal forms and their inputs have the correct IDs/classes as used here

    // Modal Add to Cart Form
    document.querySelectorAll('.modal-add-to-cart-form').forEach(form => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            // Get SKU from modal's hidden input or data attribute
            const sku = form.querySelector('#modalSku')?.value;
            const quantityInput = form.querySelector('.modal-quantity-input') || form.querySelector('input[name="quantity"]');
            const selectedQuantity = parseInt(quantityInput?.value || 1, 10);

            // Get selected options from modal's select elements
            const sizeSelect = form.querySelector('.modal-size-select');
            const frameSelect = form.querySelector('.modal-frame-select');
            const glassSelect = form.querySelector('.modal-glass-select');

            const selectedSize = sizeSelect ? sizeSelect.value : null;
            const selectedFrame = frameSelect ? frameSelect.value : null;
            const selectedGlass = glassSelect ? glassSelect.value : null;

            console.log("Adding from modal to cart:", { sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass });

            if (!sku || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity from the modal.', 'danger');
                return;
            }

            try {
                await addToCart(sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass);
                // Optionally hide the modal after successful add to cart
                const modalElement = form.closest('.modal');
                if (modalElement) {
                    const bootstrapModal = bootstrap.Modal.getInstance(modalElement);
                    if (bootstrapModal) bootstrapModal.hide();
                }
            } catch (error) {
                console.error("Error adding from modal to cart:", error);
                showCustomAlert("Failed to add item from modal to cart. Please try again.", 'danger');
            }
        });
    });

    // Modal Buy Now Form
    document.querySelectorAll('.modal-buy-now-form').forEach(form => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            // Get SKU from modal's hidden input
            const sku = form.querySelector('#modalBuySku')?.value;
            const quantityInput = form.querySelector('.modal-quantity-input') || form.querySelector('input[name="quantity"]');
            const selectedQuantity = parseInt(quantityInput?.value || 1, 10);

            // Collect options from modal select elements
            const options = {
                size: form.querySelector('.modal-size-select')?.value || null,
                frame: form.querySelector('.modal-frame-select')?.value || null,
                glass: form.querySelector('.modal-glass-select')?.value || null
            };

            // Assuming name, imageUrl, price, and GST can be read from elements populated when modal opens
            const name = document.getElementById('modalTitle')?.textContent.trim();
            const imageUrl = document.getElementById('modalImage')?.src;
            // Ensure #modalPrice has data-original-price and data-gst-percentage
            const basePrice = parseFloat(document.getElementById('modalPrice')?.dataset.originalPrice || 0);
            const gstPercentage = parseFloat(document.getElementById('modalPrice')?.dataset.gstPercentage || 0);

            console.log("Preparing for Buy Now from modal:", { sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage });

            if (!sku || !name || !imageUrl || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity for direct purchase from the modal.', 'danger');
                return;
            }

            try {
                await buyNow(sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage);
                // Optionally hide the modal after successful buy now
                const modalElement = form.closest('.modal');
                if (modalElement) {
                    const bootstrapModal = bootstrap.Modal.getInstance(modalElement);
                    if (bootstrapModal) bootstrapModal.hide();
                }
            } catch (error) {
                console.error("Error processing Buy Now from modal:", error);
                showCustomAlert("Failed to process direct purchase from modal. Please try again.", 'danger');
            }
        });
    });

    // --- Existing View Details and Image Click Listeners ---
    // These listeners typically open a modal to view product details.
    // They are separate from the Add to Cart/Buy Now forms themselves.
    document.querySelectorAll('.view-details-btn, .product-image').forEach(element => {
        element.addEventListener('click', (event) => {
            event.preventDefault();
            const card = element.closest('.product-card');
            if (!card) return;

            const sku = card.dataset.sku;
            const name = card.querySelector('.product-card-title')?.textContent.trim(); // Changed from .card-title
            const imageUrl = card.querySelector('img')?.src; // Changed from .product-image
            const description = card.querySelector('.product-description')?.textContent.trim();
            const originalPrice = card.dataset.basePrice; // Changed from .originalPrice
            const category = card.dataset.category; // Ensure this is set on .product-card
            const gstPercentage = card.dataset.gstPercentage; // Ensure this is set on .product-card

            // Populate the modal with details from the clicked card
            document.getElementById('modalImage').src = imageUrl;
            document.getElementById('modalTitle').textContent = name;
            document.getElementById('modalDescription').textContent = description;
            document.getElementById('modalCategory').textContent = `Category: ${category}`;
            document.getElementById('modalPrice').textContent = `Price: ₹${originalPrice}`;
            // Set data attributes on modalPrice for use by modal Buy Now form
            document.getElementById('modalPrice').dataset.originalPrice = originalPrice;
            document.getElementById('modalPrice').dataset.gstPercentage = gstPercentage;

            document.getElementById('modalSku').value = sku; // Set SKU for modal's Add to Cart form
            document.getElementById('modalBuySku').value = sku; // Set SKU for modal's Buy Now form

            // Reset or populate modal's option selectors if necessary
            // These would need to be updated based on specific product's available options
            const modalSizeSelect = document.querySelector('#productModal .modal-size-select');
            const modalFrameSelect = document.querySelector('#productModal .modal-frame-select');
            const modalGlassSelect = document.querySelector('#productModal .modal-glass-select');

            if (modalSizeSelect) modalSizeSelect.value = 'default'; // Or set to first option
            if (modalFrameSelect) modalFrameSelect.value = 'default';
            if (modalGlassSelect) modalGlassSelect.value = 'default';

            // Show the modal
            const productModal = new bootstrap.Modal(document.getElementById('productModal'));
            productModal.show();
        });
    });

    // Close image modal (if you have a separate image pop-up)
    document.getElementById('closeImageModal')?.addEventListener('click', () => {
        document.getElementById('imageModal').style.display = 'none';
    });
});