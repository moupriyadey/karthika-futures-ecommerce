// ✅ main.js script started execution.
console.log("✅ main.js script started execution.");

// --- Global utility functions ---

function showCustomAlert(message, type = 'info', showCartLink = false) {
    const container = document.getElementById('flash-messages-container') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.className = `custom-alert alert-${type}`;
    alertDiv.style.zIndex = 9999;

    // --- IMPORTANT DEBUGGING LOGS ---
    console.log("DEBUG: showCustomAlert received message TYPE:", typeof message);
    console.log("DEBUG: showCustomAlert received message CONTENT:", message);
    // --- END DEBUGGING LOGS ---

    // Ensure the message is always a string, even if an object is passed.
    let contentHtml = `<div class="custom-alert-message">${typeof message === 'object' ? JSON.stringify(message) : message}</div>`;
    
    if (showCartLink) {
        contentHtml += `<a href="/cart" class="btn btn-primary mt-3">Go To Cart</a>`;
    }
    alertDiv.innerHTML = contentHtml;
    container.appendChild(alertDiv);

    setTimeout(() => alertDiv.remove(), 5000);
}

function getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (window.csrfToken) headers['X-CSRFToken'] = window.csrfToken;
    return headers;
}

async function addToCart(sku, name, imageUrl, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, quantity, selectedOptions) {
    console.log("DEBUG: addToCart function started.");
    console.log("DEBUG: Add to Cart payload being sent:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage });

    try {
        const response = await fetch('/add-to-cart', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ 
                sku, 
                name, 
                imageUrl, 
                unit_price_before_gst: unitPriceBeforeGst, 
                cgst_percentage: cgstPercentage, 
                sgst_percentage: sgstPercentage, 
                igst_percentage: igstPercentage, 
                ugst_percentage: ugstPercentage, 
                cess_percentage: cessPercentage, 
                quantity, 
                selected_options: selectedOptions 
            })
        });
        
        console.log("DEBUG: Response received from /add-to-cart. Status:", response.status, "OK:", response.ok);
        
        const data = await response.json();
        console.log("DEBUG: Parsed JSON data from /add-to-cart:", data); 

        if (response.ok && data.success) {
            console.log("DEBUG: Add to Cart SUCCESS path entered. Data:", data);
            if (data.cart_count !== undefined) {
                localStorage.setItem('cartCount', data.cart_count);
                updateCartCountDisplay(); // Update the cart badge
                console.log("DEBUG: Cart count updated and display function called.");
            } else {
                console.warn("DEBUG: No 'cart_count' found in successful /add-to-cart response.");
            }
            console.log("DEBUG: Initiating immediate redirect to /cart.");
            window.location.href = '/cart'; // CRITICAL: Immediate redirect on success
            // Adding a return here to ensure no further JS executes on the current page
            return; 
        } else {
            // This path is for failures (response.ok is false or data.success is false)
            console.error("DEBUG: Add to Cart FAILURE path entered. Server message:", data.message);
            showCustomAlert(data.message || 'Failed to add item to cart. Please check stock.', 'danger');
        }
    } catch (error) {
        console.error('DEBUG: Error during addToCart fetch operation:', error);
        showCustomAlert('An unexpected error occurred while adding to cart. Please try again.', 'danger');
    }
    console.log("DEBUG: addToCart function finished (or caught error).");
}

async function buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge) {
    console.log("DEBUG: buyNow function called with:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge });
    const itemToBuyNow = { 
        sku, 
        name, 
        imageUrl, 
        selected_options: selectedOptions, 
        quantity, 
        unit_price_before_gst: unitPriceBeforeGst, 
        cgst_percentage: cgstPercentage, 
        sgst_percentage: sgstPercentage, 
        igst_percentage: igstPercentage, 
        ugst_percentage: ugstPercentage, 
        cess_percentage: cessPercentage, 
        shipping_charge: shippingCharge 
    };

    if (!window.isUserLoggedIn) {
        console.log("DEBUG: User not logged in for Buy Now. Storing item and redirecting to login.");
        sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
        sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form'); // This might be used by your Flask login route
        window.location.href = window.userLoginUrl || '/user-login'; // Fallback to /user-login if userLoginUrl not set
        return;
    }

    try {
        const response = await fetch('/create_direct_order', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(itemToBuyNow)
        });
        const data = await response.json();
        console.log("DEBUG: Response data from /create_direct_order:", data); 

        if (response.ok && data.success) {
            console.log("DEBUG: Buy Now SUCCESS. Redirecting to:", data.redirect_url);
            window.location.href = data.redirect_url;
        } else {
            console.error('DEBUG: Direct order initiation failed. Server message:', data.message);
            showCustomAlert(data.message || 'Failed to initiate direct purchase. Please try again.', 'danger');
        }
    } catch (error) {
        console.error('DEBUG: Error initiating direct purchase:', error);
        showCustomAlert('An error occurred during direct purchase setup. Please try again.', 'danger');
    }
}

function updateCartCountDisplay() {
    let cartCount = parseInt(localStorage.getItem('cartCount')) || 0;
    const cartCountBadge = document.getElementById('cart-count');
    if (cartCountBadge) {
        cartCountBadge.textContent = cartCount;
        // Only display the badge if count is greater than 0
        cartCountBadge.style.display = cartCount > 0 ? 'inline-block' : 'none';
    }
    console.log("main.js: Cart count updated to:", cartCount);
}

// Expose functions to the global window object so they can be called from HTML onclick attributes
window.showCustomAlert = showCustomAlert;
window.addToCart = addToCart;
window.buyNow = buyNow;
window.updateCartCountDisplay = updateCartCountDisplay;
console.log("main.js: Global functions (addToCart, buyNow, showCustomAlert, updateCartCountDisplay) exposed to window.");


// --- Carousel functions (MOVED OUTSIDE DOMContentLoaded for global access) ---

function enableAutoScrollCarousel(carouselId) {
    const carousel = document.getElementById(carouselId);
    let scrollDirection = 1; // 1 for right, -1 for left
    let scrollingPaused = false;
    let animationFrameId;
    // Attach scrollTimeout directly to carousel element to manage state per carousel
    carousel._scrollTimeout = null; 

    if (!carousel) {
        console.warn(`Carousel with ID '${carouselId}' not found. Auto-scroll not enabled.`);
        return;
    }

    // Clear any existing clones to prevent duplicates on re-init (important if function is called multiple times)
    Array.from(carousel.children).filter(child => child.dataset.clone).forEach(clone => clone.remove());

    const originalItems = Array.from(carousel.children); // Get original items AFTER clearing old clones
    if (originalItems.length === 0) {
        console.warn(`Carousel with ID '${carouselId}' has no children. Auto-scroll not enabled.`);
        return;
    }

    const itemWidth = originalItems[0].offsetWidth || 300; // Fallback if width is 0 initially
    const visibleItemsCount = Math.ceil(carousel.clientWidth / itemWidth);
    const numClones = visibleItemsCount + 2; // Clone slightly more than visible for seamless wrap-around

    // Append clones of the beginning items to the end
    for (let i = 0; i < numClones; i++) {
        const clone = originalItems[i % originalItems.length].cloneNode(true);
        clone.dataset.clone = 'true'; // Mark as clone
        carousel.appendChild(clone);
    }

    // Prepend clones of the ending items to the beginning
    for (let i = originalItems.length - 1; i >= originalItems.length - numClones && i >= 0; i--) {
        const clone = originalItems[i].cloneNode(true);
        clone.dataset.clone = 'true'; // Mark as clone
        carousel.prepend(clone);
    }

    // Set initial scroll position to the start of the original content (after prepended clones)
    carousel.scrollLeft = numClones * itemWidth;

    const startAutoScroll = () => {
        if (animationFrameId) cancelAnimationFrame(animationFrameId); // Ensure previous frame is cancelled
        scrollingPaused = false; // Ensure it's not paused
        animationFrameId = requestAnimationFrame(scrollStep); // Start the animation loop
    };

    const stopAutoScroll = () => {
        if (animationFrameId) cancelAnimationFrame(animationFrameId); // Cancel the animation loop
        scrollingPaused = true; // Set paused flag
    };

    const scrollStep = () => {
        if (!scrollingPaused) {
            // If scrolling right and reached end of original content (before appended clones)
            if (carousel.scrollLeft >= (originalItems.length + numClones - 1) * itemWidth) {
                // Jump back to the start of the original content (after prepended clones)
                carousel.scrollLeft = numClones * itemWidth;
            }
            carousel.scrollLeft += scrollDirection * 0.2; // Smooth scroll speed
        }
        animationFrameId = requestAnimationFrame(scrollStep); // Continue the animation loop
    };

    // Expose these control functions directly on the carousel element
    carousel._startAutoScroll = startAutoScroll;
    carousel._stopAutoScroll = stopAutoScroll;

    // Event listeners for user interaction
    carousel.addEventListener('mouseenter', stopAutoScroll); // On hover, stop
    carousel.addEventListener('mouseleave', () => {
        clearTimeout(carousel._scrollTimeout); // Clear any pending resume
        carousel._scrollTimeout = setTimeout(startAutoScroll, 100); // Resume shortly after mouse leaves
    });

    // Touch events for mobile swiping
    carousel.addEventListener('touchstart', () => {
        stopAutoScroll(); // Immediately stop auto-scroll on touch start
        clearTimeout(carousel._scrollTimeout); // Clear any pending auto-resume from other interactions
    }, { passive: true });

    carousel.addEventListener('touchend', () => {
        // After touch ends, wait a moment before resuming auto-scroll
        clearTimeout(carousel._scrollTimeout); // Clear any pending resume
        carousel._scrollTimeout = setTimeout(startAutoScroll, 500); // Resume after 500ms of inactivity
    }, { passive: true });

    // Scroll event to handle both manual scrolls and momentum scrolls, ensuring seamless looping
    carousel.addEventListener('scroll', () => {
        // As soon as scrolling occurs, pause auto-scroll
        stopAutoScroll();
        clearTimeout(carousel._scrollTimeout); // Clear any pending resume

        // Handle seamless looping for manual scrolls
        const maxScrollLeft = (originalItems.length + numClones) * itemWidth; 
        const minScrollLeft = numClones * itemWidth; 

        if (carousel.scrollLeft <= 0) { // If scrolled to the very beginning (into prepended clones)
            carousel.scrollLeft = maxScrollLeft - originalItems.length * itemWidth; // Jump to equivalent end of original content
        } else if (carousel.scrollLeft >= maxScrollLeft - itemWidth) { // If scrolled to the very end (into appended clones, just before the last clone)
            carousel.scrollLeft = minScrollLeft; // Jump to equivalent start of original content
        }

        // Set a timeout to resume auto-scroll if no more scrolling occurs for 1 second
        carousel._scrollTimeout = setTimeout(startAutoScroll, 1000); // Resume after 1 second of scroll inactivity
    }, { passive: true });

    startAutoScroll(); // Start auto-scroll initially when the carousel is enabled
}

// Global scrollCarousel function
window.scrollCarousel = function (carouselId, direction) {
    const carousel = document.getElementById(carouselId);
    if (!carousel) return;

    // Use a more dynamic item width (adjust selector as needed for your items)
    const firstItem = carousel.querySelector('.artwork-card, .product-card, .category-card'); 
    const itemWidth = firstItem ? firstItem.offsetWidth + (parseFloat(getComputedStyle(firstItem).marginLeft) * 2 || 0) : 344; 

    const scrollAmount = itemWidth; // Scroll exactly one item width
    carousel.scrollBy({ left: direction * scrollAmount, behavior: 'smooth' });
};


// --- DOMContentLoaded listener ---
document.addEventListener('DOMContentLoaded', () => {
    console.log("main.js: DOMContentLoaded fired.");
    updateCartCountDisplay();

    // Initialize all carousels that need auto-scrolling and infinite looping
    const carouselsToInitialize = [
        'featured-artworks-carousel', // For index.html
    ];

    // Add all category carousels from all_products.html if they exist
    document.querySelectorAll('[id^="category-carousel-"]').forEach(carousel => {
        carouselsToInitialize.push(carousel.id);
    });

    carouselsToInitialize.forEach(carouselId => {
        const carouselElement = document.getElementById(carouselId);
        if (carouselElement) {
            enableAutoScrollCarousel(carouselId);
        } else {
            console.warn(`Carousel with ID '${carouselId}' not found for initialization.`);
        }
    });

    // Fix for left/right arrow buttons on the featured artworks carousel
    const featuredLeftBtn = document.getElementById('scroll-left-featured'); 
    const featuredRightBtn = document.getElementById('scroll-right-featured'); 
    const featuredCarousel = document.getElementById('featured-artworks-carousel');

    if (featuredLeftBtn && featuredRightBtn && featuredCarousel) {
        featuredLeftBtn.addEventListener('click', () => {
            window.scrollCarousel('featured-artworks-carousel', -1);
            if (featuredCarousel._stopAutoScroll) {
                featuredCarousel._stopAutoScroll();
                clearTimeout(featuredCarousel._scrollTimeout); 
                featuredCarousel._scrollTimeout = setTimeout(featuredCarousel._startAutoScroll, 1000); 
            }
        });
        featuredRightBtn.addEventListener('click', () => {
            window.scrollCarousel('featured-artworks-carousel', 1);
            if (featuredCarousel._stopAutoScroll) {
                featuredCarousel._stopAutoScroll();
                clearTimeout(featuredCarousel._scrollTimeout); 
                featuredCarousel._scrollTimeout = setTimeout(featuredCarousel._startAutoScroll, 1000); 
            }
        });
    }

    // Handle click events for category carousel buttons if they exist
    // This assumes your category carousel buttons have a parent div with `data-carousel-id` and child elements with classes `scroll-left` and `scroll-right`.
    document.querySelectorAll('.category-carousel-controls').forEach(controlDiv => {
        const carouselId = controlDiv.dataset.carouselId; 
        if (carouselId) {
            const leftBtnCat = controlDiv.querySelector('.scroll-left');
            const rightBtnCat = controlDiv.querySelector('.scroll-right');
            if (leftBtnCat && rightBtnCat) {
                leftBtnCat.addEventListener('click', () => {
                    window.scrollCarousel(carouselId, -1);
                    const carouselElement = document.getElementById(carouselId);
                    if (carouselElement && carouselElement._stopAutoScroll) {
                        carouselElement._stopAutoScroll();
                        clearTimeout(carouselElement._scrollTimeout);
                        carouselElement._scrollTimeout = setTimeout(carouselElement._startAutoScroll, 1000);
                    }
                });
                rightBtnCat.addEventListener('click', () => {
                    window.scrollCarousel(carouselId, 1);
                    const carouselElement = document.getElementById(carouselId);
                    if (carouselElement && carouselElement._stopAutoScroll) {
                        carouselElement._stopAutoScroll();
                        clearTimeout(carouselElement._scrollTimeout);
                        carouselElement._scrollTimeout = setTimeout(carouselElement._startAutoScroll, 1000);
                    }
                });
            }
        }
    });


    // Modal price update logic (from product_detail.html's modal)
    // This part is crucial for product_detail.html
    const productModalElement = document.getElementById('productModal');
    if (productModalElement) {
        function updateModalPrice() {
            const modalOriginalPrice = parseFloat(document.getElementById('modalOriginalPrice').value);
            const modalCgstPercentage = parseFloat(document.getElementById('modalCgstPercentage').value);
            const modalSgstPercentage = parseFloat(document.getElementById('modalSgstPercentage').value);
            const modalIgstPercentage = parseFloat(document.getElementById('modalIgstPercentage').value);
            const modalUgstPercentage = parseFloat(document.getElementById('modalUgstPercentage').value);
            const modalCessPercentage = parseFloat(document.getElementById('modalCessPercentage').value);
            const modalGstType = document.getElementById('modalGstType').value;
            const modalShippingCharge = parseFloat(document.getElementById('modalShippingCharge').value);
            const modalShippingSlabSize = parseInt(document.getElementById('modalShippingSlabSize')?.value) || 3;

            const modalQuantityInput = document.getElementById('modalQuantity');
            const modalCalculatedPriceSpan = document.getElementById('modalCalculatedPrice');
            const modalStockSpan = document.getElementById('modalStock');

            const quantity = parseInt(modalQuantityInput.value);
            const selectedOptions = {};

            let basePriceWithOptions = modalOriginalPrice;

            productModalElement.querySelectorAll('.modal-option-select').forEach(selectElement => {
                const groupName = selectElement.dataset.groupName;
                const selectedValue = selectElement.value;

                if (selectedValue && selectedValue !== 'default') {
                    const parts = selectedValue.split('|');
                    const optionLabel = parts[0];
                    const optionPrice = parseFloat(parts[1]);
                    basePriceWithOptions += optionPrice;
                    selectedOptions[groupName] = optionLabel;
                }
            });

            const totalBeforeGst = basePriceWithOptions * quantity;

            let totalGstRate = 0;
            if (modalGstType === 'intra_state') {
                totalGstRate = modalCgstPercentage + modalSgstPercentage;
            } else if (modalGstType === 'inter_state') {
                totalGstRate = modalIgstPercentage;
            } else if (modalGstType === 'union_territory') {
                totalGstRate = modalCgstPercentage + modalUgstPercentage;
            }
            totalGstRate += modalCessPercentage;

            const gstAmount = (totalBeforeGst * totalGstRate) / 100;
            const totalShippingCharge = Math.ceil(quantity / modalShippingSlabSize) * modalShippingCharge;
            const finalPrice = totalBeforeGst + gstAmount + totalShippingCharge;

            modalCalculatedPriceSpan.textContent = finalPrice.toFixed(2);

            const currentStock = parseInt(modalStockSpan.dataset.initialStock);
            if (currentStock === 0 || quantity > currentStock) {
                document.getElementById('modalAddToCartBtn').disabled = true;
                document.getElementById('modalBuyNowBtn').disabled = true;
                modalStockSpan.textContent = currentStock === 0 ? "Out of Stock" : `Only ${currentStock} units available`;
            } else {
                document.getElementById('modalAddToCartBtn').disabled = false;
                document.getElementById('modalBuyNowBtn').disabled = false;
                modalStockSpan.textContent = `${currentStock}`;
            }

            // Return the calculated details for use by Add to Cart/Buy Now buttons in the modal
            return {
                name: document.getElementById('modalArtworkName').value,
                imageUrl: document.getElementById('modalArtworkImageUrl').value,
                selectedOptions: selectedOptions,
                quantity: quantity,
                unitPriceBeforeGst: basePriceWithOptions,
                cgstPercentage: modalCgstPercentage,
                sgstPercentage: modalSgstPercentage,
                igstPercentage: modalIgstPercentage,
                ugstPercentage: modalUgstPercentage,
                cessPercentage: modalCessPercentage,
                shippingCharge: modalShippingCharge
            };
        }

        document.getElementById('modalQuantity')?.addEventListener('input', updateModalPrice);
        document.querySelectorAll('[data-option-group]')?.forEach(select => {
            select.addEventListener('change', updateModalPrice);
        });

        // Initial call for modal price
        updateModalPrice();
    }
    // Cart logic from the original index.html's DOMContentLoaded
    if (!window.isUserLoggedIn) {
        localStorage.removeItem('cartCount');
        window.updateCartCountDisplay?.();
    }
});
