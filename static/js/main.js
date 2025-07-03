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
            showCustomAlert(data.message || 'Item added to cart!', 'success');
            // Update cart count if the function exists
            if (typeof updateCartCountDisplay === 'function') {
                updateCartCountDisplay();
            }
        } else {
            showCustomAlert(data.message || 'Failed to add item to cart.', 'danger');
        }
    } catch (error) {
        console.error('Error adding to cart:', error);
        showCustomAlert('An error occurred. Please try again.', 'danger');
    }
}

// Global update for cart count display (used in _base.html and other pages)
function updateCartCountDisplay() {
    const count = localStorage.getItem('cartCount');
    const badge = document.getElementById('cart-count');
    if (badge) {
        const displayCount = parseInt(count) || 0;
        badge.textContent = displayCount;
        badge.style.display = displayCount > 0 ? 'inline-block' : 'none';
    }
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


    // --- Event Listeners for Product Card Forms (all_products.html) ---

    // 1. Add to Cart Forms
    document.querySelectorAll('.add-to-cart-form').forEach(form => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault(); // Prevent default form submission (page reload)

            const sku = form.dataset.sku || form.querySelector('input[name="sku"]')?.value;
            const quantityInput = form.querySelector('.quantity-input') || form.querySelector('input[name="quantity"]');
            const selectedQuantity = parseInt(quantityInput?.value || 1, 10);

            const sizeSelect = form.querySelector('.size-select');
            const frameSelect = form.querySelector('.frame-select');
            const glassSelect = form.querySelector('.glass-select');

            const selectedSize = sizeSelect ? sizeSelect.value : null;
            const selectedFrame = frameSelect ? frameSelect.value : null;
            const selectedGlass = glassSelect ? glassSelect.value : null;

            console.log("Preparing to add to cart:", { sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass });

            if (!sku || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity.', 'danger');
                return;
            }

            try {
                await addToCart(sku, selectedQuantity, selectedSize, selectedFrame, selectedGlass);
            } catch (error) {
                console.error("Error in Add to Cart form submission:", error);
                showCustomAlert("Failed to add item to cart. Please try again.", 'danger');
            }
        });
    });

    // 2. Buy Now Forms
    document.querySelectorAll('.buy-now-form').forEach(form => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault(); // Prevent default form submission (page reload)

            const sku = form.dataset.sku || form.querySelector('input[name="sku"]')?.value;
            const quantityInput = form.querySelector('.quantity-input') || form.querySelector('input[name="quantity"]');
            const selectedQuantity = parseInt(quantityInput?.value || 1, 10);

            // Collect options from select elements within the form
            const options = {
                size: form.querySelector('.size-select')?.value || null,
                frame: form.querySelector('.frame-select')?.value || null,
                glass: form.querySelector('.glass-select')?.value || null
            };

            const productCard = form.closest('.product-card');
            const name = productCard?.querySelector('.card-title')?.textContent.trim();
            const imageUrl = productCard?.querySelector('.product-image')?.src;
            // Ensure these data-attributes are correctly set on your .product-card HTML element
            const basePrice = parseFloat(productCard?.dataset.originalPrice || 0);
            const gstPercentage = parseFloat(productCard?.dataset.gstPercentage || 0);

            console.log("Preparing for Buy Now:", { sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage });

            if (!sku || !name || !imageUrl || isNaN(selectedQuantity) || selectedQuantity < 1) {
                showCustomAlert('Please select a valid product and quantity for direct purchase.', 'danger');
                return;
            }

            try {
                await buyNow(sku, name, imageUrl, options, selectedQuantity, basePrice, gstPercentage);
            } catch (error) {
                console.error("Error in Buy Now form submission:", error);
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
            const name = card.querySelector('.card-title')?.textContent.trim();
            const imageUrl = card.querySelector('.product-image')?.src;
            const description = card.querySelector('.product-description')?.textContent.trim();
            const originalPrice = card.dataset.originalPrice; // Ensure this is set on .product-card
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