function showCustomAlert(message, type = 'info') {
    const container = document.getElementById('flash-messages-container') || document.body;
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} flash-message position-fixed top-0 end-0 m-3 shadow`;
    alertDiv.style.zIndex = 9999;
    alertDiv.textContent = message;
    container.appendChild(alertDiv);
    setTimeout(() => alertDiv.remove(), 5000);
}

async function buyNow(sku, name, imageUrl, options, quantity) {
    const payload = { sku, name, imageUrl, options, quantity };
    try {
        const response = await fetch("/purchase-form", {
            method: "POST",
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            window.location.href = "/purchase-form";
        } else {
            showCustomAlert("Failed to place order. Try again.", 'danger');
        }
    } catch (err) {
        showCustomAlert("Error placing order.", 'danger');
    }
}

async function addToCart(sku, name, imageUrl, options, quantity) {
    const payload = {
        sku,
        quantity,
        size: options.size,
        frame: options.frame,
        glass: options.glass
    };
    try {
        const response = await fetch("/add-to-cart", {
            method: "POST",
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            showCustomAlert(result.message || "Item added to cart!", "success");

            const cartCountElement = document.getElementById('cart-count');
            if (cartCountElement && result.total_quantity !== undefined) {
                cartCountElement.textContent = result.total_quantity;
                cartCountElement.style.display = result.total_quantity > 0 ? 'inline-block' : 'none';
            }
        } else {
            showCustomAlert(result.message || "Failed to add to cart.", "danger");
        }
    } catch (err) {
        showCustomAlert("Error adding to cart.", 'danger');
    }
}

document.addEventListener('DOMContentLoaded', function () {
    fetch('/update_cart_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.success && data.total_quantity !== undefined) {
            const cartCountElement = document.getElementById('cart-count');
            if (cartCountElement) {
                cartCountElement.textContent = data.total_quantity;
                cartCountElement.style.display = data.total_quantity > 0 ? 'inline-block' : 'none';
            }
        }
    });

    document.querySelectorAll('.artwork-card').forEach(card => {
        const sizeSelect = card.querySelector('.size-select');
        const frameSelect = card.querySelector('.frame-select');
        const glassSelect = card.querySelector('.glass-select');
        const quantityInput = card.querySelector('.quantity-input');
        const addToCartBtn = card.querySelector('.add-to-cart-btn');
        const buyNowBtn = card.querySelector('.buy-now-btn');
        const viewDetailsBtn = card.querySelector('.view-details-btn');
        const cardImage = card.querySelector('.clickable-image');
        const finalPriceElement = card.querySelector('.final-price');
        const originalBasePrice = parseFloat(card.dataset.originalPrice || 0);
        const gstPercentage = parseFloat(card.dataset.gstPercentage || 0);
        const category = card.dataset.category;

        function calculateAndDisplayPrice(currentCard) {
            let currentBasePrice = originalBasePrice;
            let selectedSize = 'Original', selectedFrame = 'None', selectedGlass = 'None';
            let sizePrice = 0, framePrice = 0, glassPrice = 0;

            if (sizeSelect?.tagName === 'SELECT') {
                const selectedOption = sizeSelect.options[sizeSelect.selectedIndex];
                selectedSize = sizeSelect.value;
                sizePrice = parseFloat(selectedOption?.dataset.price || 0);
            } else if (sizeSelect?.type === 'hidden') {
                selectedSize = sizeSelect.value;
                sizePrice = parseFloat(sizeSelect.dataset.price || 0);
            }

            if (frameSelect?.tagName === 'SELECT') {
                const selectedOption = frameSelect.options[frameSelect.selectedIndex];
                selectedFrame = frameSelect.value;
                framePrice = parseFloat(selectedOption?.dataset.price || 0);
            } else if (frameSelect?.type === 'hidden') {
                selectedFrame = frameSelect.value;
                framePrice = parseFloat(frameSelect.dataset.price || 0);
            }

            if (glassSelect?.tagName === 'SELECT') {
                const selectedOption = glassSelect.options[glassSelect.selectedIndex];
                selectedGlass = glassSelect.value;
                glassPrice = parseFloat(selectedOption?.dataset.price || 0);
            } else if (glassSelect?.type === 'hidden') {
                selectedGlass = glassSelect.value;
                glassPrice = parseFloat(glassSelect.dataset.price || 0);
            }

            if (category === 'Paintings') {
                currentBasePrice += sizePrice + framePrice + glassPrice;
            }

            let selectedQuantity = parseInt(quantityInput?.value || 1);
            let maxStock = parseInt(quantityInput?.max || 9999);

            if (selectedQuantity > maxStock) {
                selectedQuantity = maxStock;
                quantityInput.value = selectedQuantity;
                showCustomAlert(`Only ${maxStock} available. Quantity adjusted.`, 'warning');
            } else if (selectedQuantity < 1) {
                selectedQuantity = 1;
                quantityInput.value = selectedQuantity;
            }

            const priceBeforeGst = currentBasePrice * selectedQuantity;
            const gstAmount = priceBeforeGst * (gstPercentage / 100);
            const finalCalculatedPrice = priceBeforeGst + gstAmount;

            finalPriceElement.textContent = `₹${finalCalculatedPrice.toFixed(2)}`;
            currentCard.dataset.calculatedUnitPrice = currentBasePrice.toFixed(2);
            currentCard.dataset.currentQuantity = selectedQuantity;
            currentCard.dataset.currentSize = selectedSize;
            currentCard.dataset.currentFrame = selectedFrame;
            currentCard.dataset.currentGlass = selectedGlass;
        }

        sizeSelect?.addEventListener('change', () => calculateAndDisplayPrice(card));
        frameSelect?.addEventListener('change', () => calculateAndDisplayPrice(card));
        glassSelect?.addEventListener('change', () => calculateAndDisplayPrice(card));
        quantityInput?.addEventListener('input', () => calculateAndDisplayPrice(card));
        quantityInput?.addEventListener('change', () => calculateAndDisplayPrice(card));
        calculateAndDisplayPrice(card);

        addToCartBtn?.addEventListener('click', async function () {
            const sku = this.dataset.sku;
            const name = this.dataset.name;
            const imageUrl = this.dataset.image;
            const currentQuantity = parseInt(card.dataset.currentQuantity);
            const options = {
                size: category === 'Paintings' ? card.dataset.currentSize : 'Original',
                frame: category === 'Paintings' ? card.dataset.currentFrame : 'None',
                glass: category === 'Paintings' ? card.dataset.currentGlass : 'None',
            };

            await addToCart(sku, name, imageUrl, options, currentQuantity);
        });

        buyNowBtn?.addEventListener('click', async function () {
            const sku = this.dataset.sku;
            const name = this.dataset.name;
            const imageUrl = this.dataset.image;
            const selectedQuantity = parseInt(card.dataset.currentQuantity);
            const options = {
                size: category === 'Paintings' ? card.dataset.currentSize : 'Original',
                frame: category === 'Paintings' ? card.dataset.currentFrame : 'None',
                glass: category === 'Paintings' ? card.dataset.currentGlass : 'None',
            };

            const isLoggedIn = typeof window.isUserLoggedIn !== 'undefined' && window.isUserLoggedIn;

            if (!isLoggedIn) {
                const itemToBuyNow = { sku, name, imageUrl, options, quantity: selectedQuantity };
                sessionStorage.setItem('itemToBuyNow', JSON.stringify(itemToBuyNow));
                sessionStorage.setItem('redirect_after_login_endpoint', 'purchase_form');
                window.location.href = '/user-login?next=' + encodeURIComponent(window.location.pathname + window.location.search) + '&login_prompt=buy_now';
                return;
            }

            await buyNow(sku, name, imageUrl, options, selectedQuantity);
        });

        viewDetailsBtn?.addEventListener('click', (event) => {
            event.preventDefault();
            const modalImage = document.getElementById('modalImage');
            const imageModal = document.getElementById('imageModal');
            const imageSrc = viewDetailsBtn.dataset.imageSrc;
            if (modalImage && imageModal && imageSrc) {
                modalImage.src = imageSrc;
                imageModal.style.display = 'flex';
            } else {
                showCustomAlert("Image preview not available.", 'warning');
            }
        });

        cardImage?.addEventListener('click', (event) => {
            event.preventDefault();
            const modalImage = document.getElementById('modalImage');
            const imageModal = document.getElementById('imageModal');
            if (modalImage && imageModal) {
                modalImage.src = cardImage.src;
                imageModal.style.display = 'flex';
            } else {
                showCustomAlert("Image preview not available.", 'warning');
            }
        });
    });
});
