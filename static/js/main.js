console.log("✅ main.js loaded and running");

<<<<<<< HEAD

function showCustomAlert(message, type = 'info') {
=======
/**
 * Displays a custom animated alert message with a gradient border and a "Go To Cart" button.
 * @param {string} message - The message to display.
 * @param {string} type - The type of alert (e.g., 'success', 'danger', 'info').
 * @param {boolean} showCartLink - Whether to show the "Go To Cart" link.
 */
function showCustomAlert(message, type = 'info', showCartLink = false) {
>>>>>>> a3989ae (SQL v2)
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
    if (window.csrfToken) { // Use the global window.csrfToken
        headers['X-CSRFToken'] = window.csrfToken;
    }
    return headers;
}

/**
 * Calculates and displays the price for a given product card based on selected options and quantity.
 * @param {HTMLElement} productCard - The product card DOM element.
 * @returns {Object} An object containing calculated prices and selected options.
 */
function calculateAndDisplayPrice(productCard) {
    const basePrice = parseFloat(productCard.dataset.basePrice || 0);
    const gstPercentage = parseFloat(productCard.dataset.gstPercentage || 0);
    const category = productCard.dataset.category;
    const quantity = parseInt(productCard.querySelector('.quantity-input')?.value || '1', 10);

    let currentUnitPriceBeforeGst = basePrice;
    let selectedOptions = {};

    // Handle hardcoded options for 'Paintings' and 'photos'
    if (category === 'Paintings' || category === 'photos') {
        const sizeOption = productCard.querySelector(`input[name^="size-"]:checked`);
        if (sizeOption) {
            currentUnitPriceBeforeGst += parseFloat(sizeOption.dataset.additionalPrice || 0);
            selectedOptions.size = sizeOption.value;
        } else {
            selectedOptions.size = 'Original'; // Default if no size selected
        }

        const frameOption = productCard.querySelector(`input[name^="frame-"]:checked`);
        if (frameOption) {
            currentUnitPriceBeforeGst += parseFloat(frameOption.dataset.additionalPrice || 0);
            selectedOptions.frame = frameOption.value;
        } else {
            selectedOptions.frame = 'None'; // Default if no frame selected
        }

        const glassOption = productCard.querySelector(`input[name^="glass-"]:checked`);
        if (glassOption) {
            currentUnitPriceBeforeGst += parseFloat(glassOption.dataset.additionalPrice || 0);
            selectedOptions.glass = glassOption.value;
        } else {
            selectedOptions.glass = 'None'; // Default if no glass selected
        }
    }

    // Handle dynamic custom options
    const customOptionGroups = productCard.querySelectorAll('.option-group');
    customOptionGroups.forEach(groupDiv => {
        const groupName = groupDiv.dataset.optionGroup;
        const selectedOption = groupDiv.querySelector(`input[name^="${groupName}-"]:checked`);
        if (selectedOption) {
            currentUnitPriceBeforeGst += parseFloat(selectedOption.dataset.additionalPrice || 0);
            selectedOptions[groupName] = selectedOption.value;
        }
    });

    const totalBeforeGst = currentUnitPriceBeforeGst * quantity;
    const gstAmount = (totalBeforeGst * gstPercentage) / 100;
    const finalTotal = totalBeforeGst + gstAmount;

    // Update the displayed price on the card
    const finalPriceSpan = productCard.querySelector('.final-price');
    if (finalPriceSpan) {
        finalPriceSpan.textContent = finalTotal.toFixed(2);
    }

    return {
        unitPriceBeforeGst: currentUnitPriceBeforeGst,
        totalPriceBeforeGst: totalBeforeGst,
        gstAmount: gstAmount,
        finalTotal: finalTotal,
        selectedOptions: selectedOptions,
        quantity: quantity,
        sku: productCard.dataset.sku,
        name: productCard.querySelector('.product-card-title')?.textContent.trim(),
        imageUrl: productCard.querySelector('img')?.src,
        gstPercentage: gstPercentage // Pass GST percentage for buyNow/addToCart
    };
}


/**
 * Handles the "Buy Now" action, directly preparing an order.
 * @param {string} sku - The SKU of the product.
 * @param {string} name - The name of the product.
 * @param {string} imageUrl - The URL of the product image.
 * @param {Object} options - Object containing selected options (size, frame, glass, or dynamic).
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
        size: options.size || 'Original', // Ensure size is always present
        frame: options.frame || 'None',   // Ensure frame is always present
        glass: options.glass || 'None',   // Ensure glass is always present
        unitPriceBeforeGst: unitPriceBeforeGst, // This is the price with options, before GST
        gstPercentage: gstPercentage
    };

    // Add any other dynamic options to the itemToBuyNow object
    for (const key in options) {
        if (!['size', 'frame', 'glass'].includes(key)) {
            itemToBuyNow[key] = options[key];
        }
    }

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
 * @param {Object} options - Object containing selected options (size, frame, glass, or dynamic).
 */
async function addToCart(sku, quantity, options) {
    const itemData = {
        sku: sku,
        quantity: quantity,
        ...options // Spread all collected options directly
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
<<<<<<< HEAD
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
=======
            showCustomAlert(data.message || "Item added to cart!", "success", true); // Show "Go To Cart" link
            // ✅ Real-time update: Use total_quantity from the response
            if (data.total_quantity !== undefined) {
                console.log("Updating cart count from response:", data.total_quantity);
                localStorage.setItem('cartCount', data.total_quantity);
                updateCartCountDisplay(); // Update the badge immediately
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
>>>>>>> a3989ae (SQL v2)
        showCustomAlert("An error occurred. Please try again.", "danger");
    }
}

// Global update for cart count display (used in _base.html and other pages)
function updateCartCountDisplay() {
    const count = localStorage.getItem('cartCount');
    const badge = document.getElementById('cart-count');
<<<<<<< HEAD
=======
    console.log("updateCartCountDisplay called. Current localStorage cartCount:", count);
>>>>>>> a3989ae (SQL v2)

    if (badge) {
        const displayCount = parseInt(count) || 0;
        badge.textContent = displayCount;

        // Force it to show only if count > 0
        if (displayCount > 0) {
            badge.style.display = 'inline-block';
<<<<<<< HEAD
        } else {
            badge.style.display = 'none';
        }
    } else {
        console.warn("🛑 cart-count badge not found in DOM");
=======
            console.log("Cart badge updated to:", displayCount);
        } else {
            badge.style.display = 'none';
            console.log("Cart badge hidden (count is 0).");
        }
    } else {
        console.warn("🛑 cart-count badge not found in DOM.");
>>>>>>> a3989ae (SQL v2)
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
    console.log("Fetching cart count from server...");
    try {
        const response = await fetch('/get_cart_count');
        const data = await response.json();
        if (data.success) {
            console.log("Fetched cart count from server:", data.cart_count);
            localStorage.setItem('cartCount', data.cart_count); // Use data.cart_count as per backend
            updateCartCountDisplay();
        } else {
            console.error("Failed to fetch cart count from server:", data.message);
        }
    } catch (error) {
        console.error("Error fetching cart count from server:", error);
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


    // --- Event Listeners for Product Card Buttons (all_products.html) ---

<<<<<<< HEAD
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
=======
    // Initialize price display and attach event listeners for each product card
    document.querySelectorAll('.product-card').forEach(productCard => {
        // Initial price calculation and display
        calculateAndDisplayPrice(productCard);

        // Attach listeners for quantity changes
        const quantityInput = productCard.querySelector('.quantity-input');
        if (quantityInput) {
            quantityInput.addEventListener('change', () => calculateAndDisplayPrice(productCard));
            quantityInput.addEventListener('input', () => calculateAndDisplayPrice(productCard)); // For live updates as user types
        }

        // Attach listeners for option changes (radio buttons)
        productCard.querySelectorAll('.option-group input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => calculateAndDisplayPrice(productCard));
        });

        // 1. Add to Cart Buttons
        productCard.querySelector('.add-to-cart-btn')?.addEventListener('click', async (event) => {
            event.preventDefault();
            const { sku, quantity, selectedOptions } = calculateAndDisplayPrice(productCard); // Get latest calculated values
            if (!sku || isNaN(quantity) || quantity < 1) {
>>>>>>> a3989ae (SQL v2)
                showCustomAlert('Please select a valid product and quantity.', 'danger');
                return;
            }
            try {
                await addToCart(sku, quantity, selectedOptions);
            } catch (error) {
                console.error("Error in Add to Cart button click:", error);
                showCustomAlert("Failed to add item to cart. Please try again.", 'danger');
            }
        });

<<<<<<< HEAD
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
=======
        // 2. Buy Now Buttons
        productCard.querySelector('.buy-now-btn')?.addEventListener('click', async (event) => {
            event.preventDefault();
            const { sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, gstPercentage } = calculateAndDisplayPrice(productCard); // Get latest calculated values
            if (!sku || !name || !imageUrl || isNaN(quantity) || quantity < 1) {
>>>>>>> a3989ae (SQL v2)
                showCustomAlert('Please select a valid product and quantity for direct purchase.', 'danger');
                return;
            }
            try {
                await buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, gstPercentage);
            } catch (error) {
                console.error("Error in Buy Now button click:", error);
                showCustomAlert("Failed to process direct purchase. Please try again.", 'danger');
            }
        });
    });


    // --- Modal Event Listeners (for forms within the product details modal) ---
    // Ensure your modal forms and their inputs have the correct IDs/classes as used here

    // Function to update modal price
    function updateModalPrice() {
        const modal = document.getElementById('productModal');
        if (!modal) return;

        const basePrice = parseFloat(modal.querySelector('#modalPrice')?.dataset.originalPrice || 0);
        const gstPercentage = parseFloat(modal.querySelector('#modalPrice')?.dataset.gstPercentage || 0);
        const category = modal.querySelector('#modalCategory')?.textContent.replace('Category: ', ''); // Extract category
        const quantity = parseInt(modal.querySelector('.modal-quantity-input')?.value || '1', 10);

        let currentUnitPriceBeforeGst = basePrice;
        let selectedOptions = {};

        // Handle hardcoded options for 'Paintings' and 'photos' in modal
        if (category === 'Paintings' || category === 'photos') {
            const sizeSelect = modal.querySelector('.modal-size-select');
            if (sizeSelect && sizeSelect.value !== 'default') {
                const selectedOption = sizeSelect.options[sizeSelect.selectedIndex];
                currentUnitPriceBeforeGst += parseFloat(selectedOption.dataset.additionalPrice || 0);
                selectedOptions.size = selectedOption.value;
            } else {
                 selectedOptions.size = 'Original'; // Default
            }

            const frameSelect = modal.querySelector('.modal-frame-select');
            if (frameSelect && frameSelect.value !== 'default') {
                const selectedOption = frameSelect.options[frameSelect.selectedIndex];
                currentUnitPriceBeforeGst += parseFloat(selectedOption.dataset.additionalPrice || 0);
                selectedOptions.frame = selectedOption.value;
            } else {
                selectedOptions.frame = 'None'; // Default
            }

            const glassSelect = modal.querySelector('.modal-glass-select');
            if (glassSelect && glassSelect.value !== 'default') {
                const selectedOption = glassSelect.options[glassSelect.selectedIndex];
                currentUnitPriceBeforeGost += parseFloat(selectedOption.dataset.additionalPrice || 0);
                selectedOptions.glass = selectedOption.value;
            } else {
                selectedOptions.glass = 'None'; // Default
            }
        }
        
        // Handle dynamic custom options in modal (if implemented in modal structure)
        // This part assumes your modal HTML structure for custom options mirrors the product card's radio buttons
        // If your modal uses <select> for custom options, you'll need to adapt this.
        modal.querySelectorAll('.modal-option-group').forEach(groupDiv => { // Assuming a class 'modal-option-group'
            const groupName = groupDiv.dataset.optionGroup;
            const selectedOption = groupDiv.querySelector(`input[name^="${groupName}-"]:checked`);
            if (selectedOption) {
                currentUnitPriceBeforeGst += parseFloat(selectedOption.dataset.additionalPrice || 0);
                selectedOptions[groupName] = selectedOption.value;
            }
        });


        const totalBeforeGst = currentUnitPriceBeforeGst * quantity;
        const gstAmount = (totalBeforeGst * gstPercentage) / 100;
        const finalTotal = totalBeforeGst + gstAmount;

        const modalFinalPriceSpan = modal.querySelector('#modalFinalPrice'); // Assuming a span with this ID in modal
        if (modalFinalPriceSpan) {
            modalFinalPriceSpan.textContent = finalTotal.toFixed(2);
        }

        return {
            unitPriceBeforeGst: currentUnitPriceBeforeGst,
            totalPriceBeforeGst: totalBeforeGst,
            gstAmount: gstAmount,
            finalTotal: finalTotal,
            selectedOptions: selectedOptions,
            quantity: quantity,
            gstPercentage: gstPercentage
        };
    }

    // Attach listeners for modal quantity and option changes
    const productModalElement = document.getElementById('productModal');
    if (productModalElement) {
        productModalElement.addEventListener('shown.bs.modal', () => {
            // Recalculate and display price when modal is shown
            updateModalPrice();

            // Attach listeners to modal inputs/selects
            const modalQuantityInput = productModalElement.querySelector('.modal-quantity-input');
            if (modalQuantityInput) {
                modalQuantityInput.addEventListener('change', updateModalPrice);
                modalQuantityInput.addEventListener('input', updateModalPrice);
            }

            productModalElement.querySelectorAll('.modal-size-select, .modal-frame-select, .modal-glass-select').forEach(select => {
                select.addEventListener('change', updateModalPrice);
            });
            // If you have dynamic custom options in the modal, add listeners here too
            productModalElement.querySelectorAll('.modal-option-group input[type="radio"]').forEach(radio => {
                radio.addEventListener('change', updateModalPrice);
            });
        });
    }


    // Modal Add to Cart Form
    document.querySelectorAll('.modal-add-to-cart-form').forEach(form => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();

            const sku = form.querySelector('#modalSku')?.value;
            const { quantity, selectedOptions } = updateModalPrice(); // Get latest calculated values from modal

            if (!sku || isNaN(quantity) || quantity < 1) {
                showCustomAlert('Please select a valid product and quantity from the modal.', 'danger');
                return;
            }

            try {
                await addToCart(sku, quantity, selectedOptions);
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

            const sku = form.querySelector('#modalBuySku')?.value;
            const { name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, gstPercentage } = updateModalPrice(); // Get latest calculated values from modal

            if (!sku || !name || !imageUrl || isNaN(quantity) || quantity < 1) {
                showCustomAlert('Please select a valid product and quantity for direct purchase from the modal.', 'danger');
                return;
            }

            try {
                await buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, gstPercentage);
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
    document.querySelectorAll('.view-details-btn, .product-image').forEach(element => {
        element.addEventListener('click', (event) => {
            event.preventDefault();
            const card = element.closest('.product-card');
            if (!card) return;

            const sku = card.dataset.sku;
<<<<<<< HEAD
            const name = card.querySelector('.product-card-title')?.textContent.trim(); // Changed from .card-title
            const imageUrl = card.querySelector('img')?.src; // Changed from .product-image
            const description = card.querySelector('.product-description')?.textContent.trim();
            const originalPrice = card.dataset.basePrice; // Changed from .originalPrice
            const category = card.dataset.category; // Ensure this is set on .product-card
            const gstPercentage = card.dataset.gstPercentage; // Ensure this is set on .product-card
=======
            const name = card.querySelector('.product-card-title')?.textContent.trim();
            const imageUrl = card.querySelector('img')?.src;
            const description = card.querySelector('.product-description')?.textContent.trim();
            const originalPrice = card.dataset.basePrice;
            const category = card.dataset.category;
            const gstPercentage = card.dataset.gstPercentage;
>>>>>>> a3989ae (SQL v2)

            // Populate the modal with details from the clicked card
            document.getElementById('modalImage').src = imageUrl;
            document.getElementById('modalTitle').textContent = name;
            document.getElementById('modalDescription').textContent = description;
            document.getElementById('modalCategory').textContent = `Category: ${category}`;
            document.getElementById('modalPrice').textContent = `Price: ₹${originalPrice}`; // This is the base price, final price will be calculated
            document.getElementById('modalPrice').dataset.originalPrice = originalPrice;
            document.getElementById('modalPrice').dataset.gstPercentage = gstPercentage;

            document.getElementById('modalSku').value = sku;
            document.getElementById('modalBuySku').value = sku;

            // Reset modal quantity to 1
            const modalQuantityInput = document.querySelector('#productModal .modal-quantity-input');
            if (modalQuantityInput) {
                modalQuantityInput.value = 1;
            }

            // Reset or populate modal's option selectors
            // This part needs to dynamically set the options in the modal based on the artwork's custom_options
            const modalBody = document.querySelector('#productModal .modal-body');
            // Clear previous dynamic options
            modalBody.querySelectorAll('.modal-option-group').forEach(group => group.remove());
            modalBody.querySelectorAll('.modal-size-select, .modal-frame-select, .modal-glass-select').forEach(select => {
                select.value = 'default'; // Reset hardcoded selects
            });

            // Recreate option elements in the modal based on the product card's data-custom-options
            const customOptionsData = JSON.parse(card.dataset.customOptions || '{}');
            const categoryFromCard = card.dataset.category;

            // Handle hardcoded options for Paintings/Photos in modal
            if (categoryFromCard === 'Paintings' || categoryFromCard === 'photos') {
                const sizeSelect = modalBody.querySelector('.modal-size-select');
                if (sizeSelect) {
                    sizeSelect.innerHTML = `<option value="default" data-additional-price="0">Select Size</option>
                                            <option value="Original" data-additional-price="0">Original (+₹0.00)</option>`;
                    if (card.dataset.sizeA4 > 0) sizeSelect.innerHTML += `<option value="A4" data-additional-price="${card.dataset.sizeA4}">A4 (+₹${parseFloat(card.dataset.sizeA4).toFixed(2)})</option>`;
                    if (card.dataset.sizeA5 > 0) sizeSelect.innerHTML += `<option value="A5" data-additional-price="${card.dataset.sizeA5}">A5 (+₹${parseFloat(card.dataset.sizeA5).toFixed(2)})</option>`;
                    if (card.dataset.sizeLetter > 0) sizeSelect.innerHTML += `<option value="Letter" data-additional-price="${card.dataset.sizeLetter}">Letter (+₹${parseFloat(card.dataset.sizeLetter).toFixed(2)})</option>`;
                    if (card.dataset.sizeLegal > 0) sizeSelect.innerHTML += `<option value="Legal" data-additional-price="${card.dataset.sizeLegal}">Legal (+₹${parseFloat(card.dataset.sizeLegal).toFixed(2)})</option>`;
                    sizeSelect.value = 'Original'; // Default to Original
                }

                const frameSelect = modalBody.querySelector('.modal-frame-select');
                if (frameSelect) {
                    frameSelect.innerHTML = `<option value="default" data-additional-price="0">Select Frame</option>
                                             <option value="None" data-additional-price="0">None (+₹0.00)</option>`;
                    if (card.dataset.frameWooden > 0) frameSelect.innerHTML += `<option value="Wooden" data-additional-price="${card.dataset.frameWooden}">Wooden (+₹${parseFloat(card.dataset.frameWooden).toFixed(2)})</option>`;
                    if (card.dataset.frameMetal > 0) frameSelect.innerHTML += `<option value="Metal" data-additional-price="${card.dataset.frameMetal}">Metal (+₹${parseFloat(card.dataset.frameMetal).toFixed(2)})</option>`;
                    if (card.dataset.framePvc > 0) frameSelect.innerHTML += `<option value="PVC" data-additional-price="${card.dataset.framePvc}">PVC (+₹${parseFloat(card.dataset.framePvc).toFixed(2)})</option>`;
                    frameSelect.value = 'None'; // Default to None
                }

                const glassSelect = modalBody.querySelector('.modal-glass-select');
                if (glassSelect) {
                    glassSelect.innerHTML = `<option value="default" data-additional-price="0">Select Glass</option>
                                             <option value="None" data-additional-price="0">None (+₹0.00)</option>`;
                    if (card.dataset.glassPrice > 0) glassSelect.innerHTML += `<option value="Standard" data-additional-price="${card.dataset.glassPrice}">Standard (+₹${parseFloat(card.dataset.glassPrice).toFixed(2)})</option>`;
                    glassSelect.value = 'None'; // Default to None
                }
            }


            // Render dynamic custom options in the modal
            for (const groupName in customOptionsData) {
                if (customOptionsData.hasOwnProperty(groupName)) {
                    const options = customOptionsData[groupName];
                    const groupDiv = document.createElement('div');
                    groupDiv.className = 'mb-1 modal-option-group'; // Add a class for modal dynamic options
                    groupDiv.dataset.optionGroup = groupName;
                    groupDiv.innerHTML = `<label class="fw-bold d-block">${groupName.charAt(0).toUpperCase() + groupName.slice(1)}</label>`;
                    
                    let firstOptionChecked = false;
                    for (const label in options) {
                        if (options.hasOwnProperty(label)) {
                            const price = options[label];
                            const radioId = `modal-${groupName}-${label}-${sku}`; // Unique ID for modal radio
                            groupDiv.innerHTML += `
                                <label class="me-2">
                                    <input type="radio" name="${groupName}-${sku}" value="${label}" data-additional-price="${price}" id="${radioId}" ${!firstOptionChecked ? 'checked' : ''}> ${label} (+₹${parseFloat(price).toFixed(2)})
                                </label>
                            `;
                            firstOptionChecked = true;
                        }
                    }
                    modalBody.appendChild(groupDiv);
                }
            }
            // Re-attach listeners to newly created dynamic option radios in modal
            modalBody.querySelectorAll('.modal-option-group input[type="radio"]').forEach(radio => {
                radio.addEventListener('change', updateModalPrice);
            });


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
// End of DOMContentLoaded event listener   