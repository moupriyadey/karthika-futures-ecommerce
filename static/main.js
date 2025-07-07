console.log("✅ main.js loaded and running");

/**
 * Displays a custom animated alert message with a gradient border and a "Go To Cart" button.
 * @param {string} message - The message to display.
 * @param {string} type - The type of alert (e.g., 'success', 'danger', 'info').
 * @param {boolean} showCartLink - Whether to show the "Go To Cart" link.
 */
function showCustomAlert(message, type = 'info', showCartLink = false) {
    const container = document.getElementById('flash-messages-container') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.className = `custom-alert alert-${type}`; // Use custom-alert class
    alertDiv.style.zIndex = 9999;

    let contentHtml = `<div class="custom-alert-message">${message}</div>`;
    if (showCartLink) {
        contentHtml += `<a href="/cart" class="btn btn-primary mt-3">Go To Cart</a>`; // Added mt-3 for spacing
    }
    alertDiv.innerHTML = contentHtml;
    
    container.appendChild(alertDiv);

    // Remove the alert after 5 seconds
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Helper function to get headers including CSRF token
function getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (window.csrfToken) {
        headers['X-CSRFToken'] = window.csrfToken;
    }
    return headers;
}

// Function to update the cart count display in the navbar
window.updateCartCountDisplay = function() {
    const cartBadge = document.getElementById('cart-total-quantity');
    if (cartBadge) {
        const cartCount = localStorage.getItem('cartCount') || '0';
        cartBadge.textContent = cartCount;
        cartBadge.style.display = parseInt(cartCount) > 0 ? 'inline-block' : 'none';
    }
};

// Function to fetch cart count from the server (used on page load)
async function fetchCartCount() {
    console.log("Fetching cart count from server...");
    try {
        const response = await fetch('/get_cart_count');
        // Check if the response is JSON before parsing
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            const data = await response.json();
            if (data.success) {
                console.log("Fetched cart count from server:", data.cart_count);
                localStorage.setItem('cartCount', data.cart_count); // Use data.cart_count as per backend
                window.updateCartCountDisplay();
            } else {
                console.error("Failed to fetch cart count from server:", data.message);
            }
        } else {
            const text = await response.text();
            console.error("Server response was not JSON:", text);
            showCustomAlert("Error: Server did not return expected data for cart count. Please ensure /get_cart_count returns JSON.", "danger");
        }
    } catch (error) {
        console.error("Error fetching cart count from server:", error);
    }
}

/**
 * Handles the "Buy Now" action, directly preparing an order.
 * This function is now primarily called from the product modal in all_products.html
 * @param {string} sku - The SKU of the product.
 * @param {string} name - The name of the product.
 * @param {string} imageUrl - The URL of the product image.
 * @param {Object} options - Object containing selected options (e.g., { "Size": "A4", "Frame": "Wooden" }).
 * @param {number} quantity - The selected quantity.
 * @param {number} unitPriceBeforeGst - The unit price of the product including options, before GST.
 * @param {number} gstPercentage - The GST percentage applicable.
 */
async function buyNow(sku, name, imageUrl, options, quantity, unitPriceBeforeGst, gstPercentage) {
    const itemToBuyNow = {
        sku: sku,
        name: name,
        imageUrl: imageUrl,
        quantity: quantity,
        unitPriceBeforeGst: unitPriceBeforeGst, // This is the price with options, before GST
        gstPercentage: gstPercentage,
        options: options // Pass all collected options
    };

    if (!window.isUserLoggedIn) {
        sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
        sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form');
        window.location.href = '/user-login'; // Redirect to user_login, it will handle 'next' param
        return;
    }

    try {
        // The backend /create_direct_order expects a 'cart' object containing the item
        const response = await fetch('/create_direct_order', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ cart: { 'temp_item': itemToBuyNow } }) // Wrap in 'cart' object
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
 * This function is now primarily called from the product modal in all_products.html
 * @param {string} sku - The SKU of the product.
 * @param {string} name - The name of the product.
 * @param {string} imageUrl - The URL of the product image.
 * @param {number} basePrice - The original_price of the artwork (before any options).
 * @param {number} gstPercentage - The GST percentage applicable.
 * @param {number} quantity - The selected quantity.
 * @param {Object} options - Object containing selected options (e.g., { "Size": "A4", "Frame": "Wooden" }).
 */
async function addToCart(sku, name, imageUrl, basePrice, gstPercentage, quantity, options) {
    const itemData = {
        sku: sku,
        name: name, // Pass name
        imageUrl: imageUrl, // Pass imageUrl
        basePrice: basePrice, // Pass original_price
        gstPercentage: gstPercentage, // Pass gst_percentage
        quantity: quantity,
        options: options // Pass all collected options
    };
    console.log("Attempting to add to cart:", itemData);
    try {
        const response = await fetch('/add-to-cart', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(itemData)
        });
        const data = await response.json();
        console.log("Add to cart response:", data);

        if (response.ok && data.success) {
            showCustomAlert(data.message || "Item added to cart!", "success", true); // Show "Go To Cart" link
            if (data.cart_count !== undefined) {
                console.log("Updating cart count from response:", data.cart_count);
                localStorage.setItem('cartCount', data.cart_count);
                window.updateCartCountDisplay(); // Update the badge immediately
            } else {
                console.warn("total_quantity not found in response, attempting to fetch cart count as fallback.");
                fetchCartCount(); // Fallback: fetch the cart count if not provided in the response
            }
        } else {
            console.error("Failed to add item to cart:", data.message);
            showCustomAlert(data.message || "Failed to add item to cart.", "danger");
        }
    } catch (error) {
        console.error("Error adding to cart (fetch failed):", error);
        showCustomAlert("An error occurred. Please try again.", "danger");
    }
}


// All DOM-related interactions should be inside DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    // --- CSRF Token Initialization ---
    console.log("CSRF Token initialized from window:", window.csrfToken);

    // Initial fetch of cart count when the page loads
    fetchCartCount();

    // Ensure window.isUserLoggedIn is set if the user is logged in
    window.isUserLoggedIn = typeof window.isUserLoggedIn !== 'undefined' ? window.isUserLoggedIn : false;

    // --- Global functions for cart/buy now actions ---
    // Make these functions globally accessible if they are called from other scripts (like all_products.html)
    window.buyNow = buyNow;
    window.addToCart = addToCart;

    // No longer need to attach listeners to product cards here, as all_products.html handles them directly
    // within its extra_js block for the modal interactions.
});
