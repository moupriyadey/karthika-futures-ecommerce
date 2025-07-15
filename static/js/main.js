console.log("✅ main.js script started execution.");

function showCustomAlert(message, type = 'info', showCartLink = false) {
    const container = document.getElementById('flash-messages-container') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.className = `custom-alert alert-${type}`;
    alertDiv.style.zIndex = 9999;

    let contentHtml = `<div class="custom-alert-message">${message}</div>`;
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
    console.log("addToCart called from main.js:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage });
    try {
        const response = await fetch('/add-to-cart', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ sku, name, imageUrl, unit_price_before_gst: unitPriceBeforeGst, cgst_percentage: cgstPercentage, sgst_percentage: sgstPercentage, igst_percentage: igstPercentage, ugst_percentage: ugstPercentage, cess_percentage: cessPercentage, quantity, selected_options: selectedOptions })
        });
        const data = await response.json();

        if (response.ok && data.success) {
            if (data.cart_count !== undefined) {
                localStorage.setItem('cartCount', data.cart_count);
                updateCartCountDisplay();
            }
            window.location.href = '/cart';
        } else {
            console.error("Failed to add item to cart:", data.message);
            showCustomAlert(data.message || 'Failed to add item to cart.', 'danger');
        }
    } catch (error) {
        console.error('Error adding to cart:', error);
        showCustomAlert('An error occurred. Please try again.', 'danger');
    }
}

async function buyNow(sku, name, imageUrl, selectedOptions, quantity, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge) {
    console.log("buyNow called from main.js:", { sku, name, quantity, selectedOptions, unitPriceBeforeGst, cgstPercentage, sgstPercentage, igstPercentage, ugstPercentage, cessPercentage, shippingCharge });
    const itemToBuyNow = { sku, name, imageUrl, selected_options: selectedOptions, quantity, unit_price_before_gst: unitPriceBeforeGst, cgst_percentage: cgstPercentage, sgst_percentage: sgstPercentage, igst_percentage: igstPercentage, ugst_percentage: ugstPercentage, cess_percentage: cessPercentage, shipping_charge: shippingCharge };

    if (!window.isUserLoggedIn) {
        sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
        sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form');
        window.location.href = window.userLoginUrl;
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
            window.location.href = data.redirect_url;
        } else {
            console.error('Direct order initiation failed:', data.message);
            showCustomAlert(data.message || 'Failed to initiate direct purchase.', 'danger');
        }
    } catch (error) {
        console.error('Error initiating direct purchase:', error);
        showCustomAlert('An error occurred during direct purchase setup. Please try again.', 'danger');
    }
}

function updateCartCountDisplay() {
    let cartCount = parseInt(localStorage.getItem('cartCount')) || 0;
    const cartCountBadge = document.getElementById('cart-count');
    if (cartCountBadge) {
        cartCountBadge.textContent = cartCount;
        cartCountBadge.style.display = cartCount > 0 ? 'inline-block' : 'none';
    }
    console.log("main.js: Cart count updated to:", cartCount);
}

window.showCustomAlert = showCustomAlert;
window.addToCart = addToCart;
window.buyNow = buyNow;
window.updateCartCountDisplay = updateCartCountDisplay;
console.log("main.js: Global functions (addToCart, buyNow, showCustomAlert, updateCartCountDisplay) exposed to window.");

document.addEventListener('DOMContentLoaded', () => {
    console.log("main.js: DOMContentLoaded fired.");
    updateCartCountDisplay();

    function enableAutoScrollCarousel(carouselId) {
        const carousel = document.getElementById(carouselId);
        let scrollDirection = 1;
        let scrollingPaused = false;

        if (!carousel) return;

        const scrollStep = () => {
            if (!scrollingPaused) {
                if (carousel.scrollLeft + carousel.clientWidth >= carousel.scrollWidth) {
                    scrollDirection = -1;
                } else if (carousel.scrollLeft <= 0) {
                    scrollDirection = 1;
                }
                carousel.scrollLeft += scrollDirection * 0.5;
            }
            requestAnimationFrame(scrollStep);
        };

        carousel.addEventListener('mouseenter', () => scrollingPaused = true);
        carousel.addEventListener('mouseleave', () => scrollingPaused = false);

        requestAnimationFrame(scrollStep);
    }

    enableAutoScrollCarousel('featured-artworks-carousel');
    enableAutoScrollCarousel('all-products-carousel');

    document.querySelectorAll('[id^="category-carousel-"]').forEach(carousel => {
  const carouselId = carousel.id;
  enableAutoScrollCarousel(carouselId);
});

if (window.location.pathname.includes('/all-products')) {
  document.querySelectorAll('[id^="category-carousel-"]').forEach(carousel => {
    enableAutoScrollCarousel(carousel.id);
  });
}


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

            const modalQuantityInput = document.getElementById('modalQuantity');
            const modalCalculatedPriceSpan = document.getElementById('modalCalculatedPrice');

            const optionSelectors = document.querySelectorAll('[data-option-group]');
            let optionTotal = 0;
            const selectedOptions = {};

            optionSelectors.forEach(select => {
                const group = select.getAttribute('data-option-group');
                const value = select.value;
                if (value && select.selectedOptions[0]) {
                    const priceAddon = parseFloat(select.selectedOptions[0].getAttribute('data-price') || '0');
                    optionTotal += priceAddon;
                    selectedOptions[group] = value;
                }
            });

            const quantity = parseInt(modalQuantityInput.value);
            let totalPriceBeforeGST = (modalOriginalPrice + optionTotal) * quantity;

            let gstRate = 0;
            if (modalGstType === 'intra_state') gstRate = modalCgstPercentage + modalSgstPercentage;
            else if (modalGstType === 'inter_state') gstRate = modalIgstPercentage;
            else if (modalGstType === 'union_territory') gstRate = modalCgstPercentage + modalUgstPercentage;

            gstRate += modalCessPercentage;
            const gstAmount = (totalPriceBeforeGST * gstRate) / 100;

            const totalPrice = totalPriceBeforeGST + gstAmount + (modalShippingCharge * quantity);

            modalCalculatedPriceSpan.innerText = `₹${totalPrice.toFixed(2)}`;
        }

        document.getElementById('modalQuantity')?.addEventListener('input', updateModalPrice);
        document.querySelectorAll('[data-option-group]')?.forEach(select => {
            select.addEventListener('change', updateModalPrice);
        });

        updateModalPrice();
    }

    const leftBtn = document.getElementById('scrollLeftBtn');
    const rightBtn = document.getElementById('scrollRightBtn');
    const featuredCarousel = document.getElementById('featured-artworks-carousel');

    if (leftBtn && rightBtn && featuredCarousel) {
        leftBtn.onclick = () => featuredCarousel.scrollLeft -= 200;
        rightBtn.onclick = () => featuredCarousel.scrollLeft += 200;
    }
});
