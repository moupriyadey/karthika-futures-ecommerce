console.log("✅ main.js script started execution.");

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

/**
 * Adds an item to the cart via AJAX.
 * @param {string} sku - The SKU of the artwork.
 * @param {string} name - The name of the artwork.
 * @param {string} imageUrl - The URL of the artwork image.
 * @param {number} unitPriceBeforeGst - The unit price before GST.
 * @param {number} cgstPercentage - The CGST percentage.
 * @param {number} sgstPercentage - The SGST percentage.
 * @param {number} igstPercentage - The IGST percentage.
 * @param {number} ugstPercentage - The UGST percentage.
 * @param {number} cessPercentage - The CESS percentage. // ADDED
 * @param {number} quantity - The quantity to add.
 * @param {object} selectedOptions - Object of selected options (e.g., { "Size": "A4", "Frame": "Wooden" }).
 */
async function addToCart(sku, name, imageUrl, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, quantity, selectedOptions) { // ADDED cessPercentage
    console.log("addToCart called from main.js:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage }); // ADDED cessPercentage
    try {
        const response = await fetch('/add-to-cart', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                sku: sku,
                name: name,
                imageUrl: imageUrl,
                unit_price_before_gst: unitPriceBeforeGst,
                cgst_percentage: cgstPercentage,
                sgst_percentage: sgstPercentage,
                igst_percentage: igstPercentage,
                ugst_percentage: ugstPercentage,
                cess_percentage: cessPercentage, // ADDED
                quantity: quantity,
                selected_options: selectedOptions
            })
        });
        const data = await response.json();

        if (response.ok && data.success) {
            console.log("Item added to cart successfully:", data);
            if (data.cart_count !== undefined) {
                // Update local storage with the new cart count from the server
                localStorage.setItem('cartCount', data.cart_count);
                
                // --- CRITICAL DEBUGGING LOG ---
                console.log("DEBUG: Type of updateCartCountDisplay before call:", typeof updateCartCountDisplay);
                // --- END CRITICAL DEBUGGING LOG ---

                // Call the correct function to update the display
                updateCartCountDisplay(); 
            }
            // Redirect to cart to show success message there (as per your original logic)
            window.location.href = '/cart'; 
        } else {
            console.error("Failed to add item to cart:", data.message);
            showCustomAlert(data.message || 'Failed to add item to cart.', 'danger');
        }
    } catch (error) {
        console.error('Error adding to cart (fetch failed):', error);
        showCustomAlert('An error occurred. Please try again.', 'danger');
    }
}

/**
 * Handles direct "Buy Now" purchase via AJAX.
 * @param {string} sku - The SKU of the artwork.
 * @param {string} name - The name of the artwork.
 * @param {string} imageUrl - The URL of the artwork image.
 * @param {object} selectedOptions - Object of selected options.
 * @param {number} quantity - The quantity.
 * @param {number} unitPriceBeforeGst - The unit price before GST.
 * @param {number} cgstPercentage - The CGST percentage.
 * @param {number} sgstPercentage - The SGST percentage.
 * @param {number} igstPercentage - The IGST percentage.
 * @param {number} ugstPercentage - The UGST percentage.
 * @param {number} cessPercentage - The CESS percentage. // ADDED
 * @param {number} shippingCharge - The shipping charge for the item.
 */
async function buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge) { // ADDED cessPercentage
    console.log("buyNow called from main.js:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge }); // ADDED cessPercentage
    const itemToBuyNow = {
        sku: sku,
        name: name,
        imageUrl: imageUrl,
        selected_options: selectedOptions,
        quantity: quantity,
        unit_price_before_gst: unitPriceBeforeGst,
        cgst_percentage: cgstPercentage,
        sgst_percentage: sgstPercentage,
        igst_percentage: igstPercentage,
        ugst_percentage: ugstPercentage,
        cess_percentage: cessPercentage, // ADDED
        shipping_charge: shippingCharge
    };

    if (!window.isUserLoggedIn) {
        console.log("User not logged in in main.js, storing item for redirection.");
        sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
        sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form');
        window.location.href = window.userLoginUrl; // Use global login URL
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
            console.log("Direct order initiated successfully:", data);
            window.location.href = data.redirect_url; // Redirect to payment/confirmation
        } else {
            console.error('Direct order initiation failed:', data.message);
            showCustomAlert(data.message || 'Failed to initiate direct purchase.', 'danger');
        }
    } catch (error) {
        console.error('Error initiating direct purchase:', error);
        showCustomAlert('An error occurred during direct purchase setup. Please try again.', 'danger');
    }
}

// Function to update cart count display in the navbar
function updateCartCountDisplay() {
    let cartCount = parseInt(localStorage.getItem('cartCount')) || 0;
    const cartCountBadge = document.getElementById('cart-count');

    if (cartCountBadge) {
        cartCountBadge.textContent = cartCount;
        cartCountBadge.style.display = cartCount > 0 ? 'inline-block' : 'none';
    }

    console.log("main.js: Cart count updated to:", cartCount);
}


// Attach functions to the window object immediately as they are defined
window.showCustomAlert = showCustomAlert;
window.addToCart = addToCart;
window.buyNow = buyNow;
window.updateCartCountDisplay = updateCartCountDisplay;
console.log("main.js: Global functions (addToCart, buyNow, showCustomAlert, updateCartCountDisplay) exposed to window.");


document.addEventListener('DOMContentLoaded', () => {
    console.log("main.js: DOMContentLoaded fired.");
    // Initial update of cart count when DOM is ready
    updateCartCountDisplay();

    // Event listeners for modal interactions (if modals are used on the page)
    const productModalElement = document.getElementById('productModal');

    if (productModalElement) {
        console.log("main.js: Product modal element found. Attaching modal listeners.");
        // Function to update modal price and options dynamically
        function updateModalPrice() {
            const modalOriginalPrice = parseFloat(document.getElementById('modalOriginalPrice').value);
            const modalCgstPercentage = parseFloat(document.getElementById('modalCgstPercentage').value);
            const modalSgstPercentage = parseFloat(document.getElementById('modalSgstPercentage').value);
            const modalIgstPercentage = parseFloat(document.getElementById('modalIgstPercentage').value);
            const modalUgstPercentage = parseFloat(document.getElementById('modalUgstPercentage').value);
            const modalCessPercentage = parseFloat(document.getElementById('modalCessPercentage').value); // ADDED: Get cess percentage
            const modalGstType = document.getElementById('modalGstType').value;
            const modalShippingCharge = parseFloat(document.getElementById('modalShippingCharge').value);
            
            const modalQuantityInput = document.getElementById('modalQuantity');
            const modalCalculatedPriceSpan = document.getElementById('modalCalculatedPrice');
            const modalStockSpan = document.getElementById('modalStock');

            let currentBasePrice = modalOriginalPrice;
            const quantity = parseInt(modalQuantityInput.value);
            const selectedOptions = {};

            productModalElement.querySelectorAll('.modal-option-select').forEach(selectElement => {
                const groupName = selectElement.dataset.groupName;
                const selectedValue = selectElement.value;

                if (selectedValue && selectedValue !== 'default') {
                    const parts = selectedValue.split('|');
                    const optionLabel = parts[0];
                    const optionPrice = parseFloat(parts[1]);
                    currentBasePrice += optionPrice;
                    selectedOptions[groupName] = optionLabel;
                }
            });

            const totalBeforeGst = currentBasePrice * quantity;
            
            let totalGstRate = 0;
            if (modalGstType === 'intra_state') {
                totalGstRate = modalCgstPercentage + modalSgstPercentage;
            } else if (modalGstType === 'inter_state') {
                totalGstRate = modalIgstPercentage;
            } else if (modalGstType === 'union_territory') {
                totalGstRate = modalCgstPercentage + modalUgstPercentage;
            }
            totalGstRate += modalCessPercentage; // ADDED: Include cess in total GST rate for display calculation

            const gstAmount = (totalBeforeGst * totalGstRate) / 100;
            let finalPrice = totalBeforeGst + gstAmount;

            finalPrice += modalShippingCharge;

            modalCalculatedPriceSpan.textContent = finalPrice.toFixed(2);

            const currentStock = parseInt(modalStockSpan.dataset.initialStock);
            if (currentStock === 0 || quantity > currentStock) {
                document.getElementById('modalAddToCartBtn').disabled = true;
                document.getElementById('modalBuyNowBtn').disabled = true;
                if (currentStock === 0) {
                    modalStockSpan.textContent = "Out of Stock";
                } else {
                    modalStockSpan.textContent = `Only ${currentStock} units available`;
                }
            } else {
                document.getElementById('modalAddToCartBtn').disabled = false;
                document.getElementById('modalBuyNowBtn').disabled = false;
                modalStockSpan.textContent = `${currentStock}`;
            }

            return {
                name: document.getElementById('modalArtworkName').value,
                imageUrl: document.getElementById('modalArtworkImageUrl').value,
                selectedOptions: selectedOptions,
                quantity: quantity,
                unitPriceBeforeGst: currentBasePrice,
                cgstPercentage: modalCgstPercentage,
                sgstPercentage: modalSgstPercentage,
                igstPercentage: modalIgstPercentage,
                ugstPercentage: modalUgstPercentage,
                cessPercentage: modalCessPercentage, // ADDED: Return cessPercentage
                shippingCharge: modalShippingCharge
            };
        }

        document.getElementById('modalQuantity')?.addEventListener('input', updateModalPrice);
        productModalElement.querySelectorAll('.modal-option-select').forEach(select => {
            select.addEventListener('change', updateModalPrice);
        });

        productModalElement.addEventListener('show.bs.modal', function (event) {
            console.log("main.js: Product modal show event triggered.");
            const button = event.relatedTarget;
            const artworkData = JSON.parse(button.dataset.artwork);

            document.getElementById('modalArtworkName').value = artworkData.name;
            document.getElementById('modalSku').value = artworkData.sku;
            document.getElementById('modalOriginalPrice').value = artworkData.original_price;
            document.getElementById('modalCgstPercentage').value = artworkData.cgst_percentage;
            document.getElementById('modalSgstPercentage').value = artworkData.sgst_percentage;
            document.getElementById('modalIgstPercentage').value = artworkData.igst_percentage;
            document.getElementById('modalUgstPercentage').value = artworkData.ugst_percentage;
            document.getElementById('modalCessPercentage').value = artworkData.cess_percentage; // ADDED: Populate cess_percentage
            document.getElementById('modalGstType').value = artworkData.gst_type;
            document.getElementById('modalShippingCharge').value = artworkData.shipping_charge;
            
            document.getElementById('modalArtworkImageUrl').value = artworkData.image_url;
            document.getElementById('modalProductImage').src = artworkData.image_url;
            document.getElementById('modalStock').textContent = artworkData.stock;
            document.getElementById('modalStock').dataset.initialStock = artworkData.stock;

            document.getElementById('modalQuantity').value = 1;

            const modalCustomOptionsContainer = document.getElementById('modalCustomOptionsContainer');
            modalCustomOptionsContainer.innerHTML = '';

            if (artworkData.custom_options) {
                for (const groupName in artworkData.custom_options) {
                    if (artworkData.custom_options.hasOwnProperty(groupName)) {
                        const options = artworkData.custom_options[groupName];
                        const div = document.createElement('div');
                        div.className = 'mb-3';
                        div.innerHTML = `
                            <label for="modal-option-${groupName}" class="form-label fw-bold">${groupName}:</label>
                            <select class="form-select modal-option-select" id="modal-option-${groupName}" data-group-name="${groupName}">
                                <option value="default" disabled selected>Select ${groupName}</option>
                                ${Object.entries(options).map(([label, price]) => `<option value="${label}|${price}">${label} (+₹${price.toFixed(2)})</option>`).join('')}
                            </select>
                        `;
                        modalCustomOptionsContainer.appendChild(div);
                    }
                }
                modalCustomOptionsContainer.querySelectorAll('.modal-option-select').forEach(select => {
                    select.addEventListener('change', updateModalPrice);
                });
            }

            updateModalPrice();
        });

        document.getElementById('modalAddToCartBtn')?.addEventListener('click', async function() {
            const sku = document.getElementById('modalSku').value;
            const { name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage } = updateModalPrice(); // ADDED: Destructure cessPercentage

            if (!sku || !name || !imageUrl || isNaN(quantity) || quantity < 1) {
                showCustomAlert('Please select a valid product and quantity from the modal.', 'danger');
                return;
            }

            try {
                await window.addToCart(sku, name, imageUrl, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, quantity, selectedOptions); // ADDED: Pass cessPercentage
                const modalElement = this.closest('.modal');
                if (modalElement) {
                    const bootstrapModal = bootstrap.Modal.getInstance(modalElement);
                    if (bootstrapModal) bootstrapModal.hide();
                }
            } catch (error) {
                console.error("Error adding from modal to cart:", error);
                showCustomAlert("Failed to add item from modal to cart. Please try again.", 'danger');
            }
        });

        document.getElementById('modalBuyNowBtn')?.addEventListener('click', async function() {
            const sku = document.getElementById('modalSku').value;
            const { name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge } = updateModalPrice(); // ADDED: Destructure cessPercentage

            if (!sku || !name || !imageUrl || isNaN(quantity) || quantity < 1) {
                showCustomAlert('Please select a valid product and quantity for direct purchase from the modal.', 'danger');
                return;
            }

            try {
                await window.buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge); // ADDED: Pass cessPercentage
                const modalElement = this.closest('.modal');
                if (modalElement) {
                    const bootstrapModal = bootstrap.Modal.getInstance(modalElement);
                    if (bootstrapModal) bootstrapModal.hide();
                }
            } catch (error) {
                console.error("Error processing Buy Now from modal:", error);
                showCustomAlert("Failed to process direct purchase from modal. Please try again.", 'danger');
            }
        });
    }

    // Logic to handle redirection after login for "Buy Now"
    const itemToBuyNow = sessionStorage.getItem('itemToBuyNow');
    const redirectEndpoint = sessionStorage.getItem('redirect_after_login_endpoint');

    if (itemToBuyNow && redirectEndpoint === 'purchase_form' && window.isUserLoggedIn) {
        console.log("main.js: Resuming Buy Now flow after login.");
        sessionStorage.removeItem('itemToBuyNow');
        sessionStorage.removeItem('redirect_after_login_endpoint');

        try {
            const parsedItem = JSON.parse(itemToBuyNow);
            // Re-initiate the buyNow AJAX call with the stored item data
            window.buyNow(
                parsedItem.sku, 
                parsedItem.name, 
                parsedItem.imageUrl, 
                parsedItem.selected_options, 
                parsedItem.quantity, 
                parsedItem.unit_price_before_gst, 
                parsedItem.cgst_percentage, 
                parsedItem.sgst_percentage, 
                parsedItem.igst_percentage, 
                parsedItem.ugst_percentage, 
                parsedItem.cess_percentage, // ADDED: Pass cess_percentage
                parsedItem.shipping_charge
            );
        } catch (e) {
            console.error("Failed to parse itemToBuyNow from session storage:", e);
            showCustomAlert("There was an issue resuming your purchase. Please try again.", 'danger');
        }
    }
});
