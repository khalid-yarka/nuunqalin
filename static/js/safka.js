// ============================================
// SAFKA SHEET – Feature & Upgrade Modals
// ============================================

(function() {
    'use strict';

    let backdrop, sheet, content, closeBtn, handle;
    let isOpen = false;
    let isDragging = false;
    let dragStartY = 0;
    let sheetOffsetY = 0;
    let currentMode = 'upgrade';

    let upgradeState = {
        tier: null,
        duration: 'yearly',
        originalPrice: 0,
        discountCode: null,
        discountAmount: 0,
        finalPrice: 0,
        step: 1,
        requestId: null,
        note: '',
        feature: null,
        message: null
    };

    const PRICES = {
        dhexe: { monthly: 1.25, term: 3.00, yearly: 5.00 },
        hore:  { monthly: 2.00, term: 4.50, yearly: 7.00 }
    };

    const FEATURES = {
        dhexe: [
            '📊 Advanced analytics & progress charts',
            '⚡ Host live quizzes (up to 50 participants)',
            '💾 Save up to 50 questions',
            '📝 30 quiz attempts per day',
            '🔍 Subject filters for PDFs',
            '🏆 Expanded achievements',
            '🔑 Unlock accent colours',
            '📅 Daily digest notifications'
        ],
        hore: [
            '📈 Full analytics & historical trends',
            '💎 Access to all premium PDF resources',
            '♾️ Unlimited quiz attempts',
            '♾️ Unlimited saved items',
            '🎯 Full live quiz hosting & scheduling',
            '🏅 All achievements & badges',
            '📊 Personal learning insights',
            '📧 Weekly summary reports',
            '🔍 Advanced search filters',
            '⭐ Priority support'
        ]
    };

    function init() {
        backdrop = document.getElementById('safkaBackdrop');
        sheet = document.getElementById('safkaSheet');
        content = document.getElementById('safkaTrack');
        closeBtn = document.getElementById('safkaClose');
        handle = document.getElementById('safkaHandle');

        if (!backdrop || !sheet || !content) {
            console.warn('Safka sheet elements not found.');
            return;
        }

        backdrop.addEventListener('click', closeSheet);
        if (closeBtn) closeBtn.addEventListener('click', closeSheet);

        if (handle) {
            handle.addEventListener('mousedown', onDragStart);
            handle.addEventListener('touchstart', onDragStartTouch, { passive: false });
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isOpen) closeSheet();
        });

        window.openSafkaPreview = openSafkaPreview;
        window.closeSafkaSheet = closeSheet;
        window.openUpgradeSheet = function(tier) {
            openSafkaPreview({ mode: 'upgrade', requiredTier: tier });
        };

        document.addEventListener('click', function(e) {
            const target = e.target.closest('[data-tier-locked]');
            if (target) {
                e.preventDefault();
                const feature = target.dataset.feature || null;
                const requiredTier = target.dataset.requiredTier || 'dhexe';
                openSafkaPreview({ mode: 'upgrade', feature: feature, requiredTier: requiredTier });
            }
        });
    }

    function openSafkaPreview(options) {
        options = options || {};
        currentMode = options.mode || 'upgrade';
        upgradeState.feature = options.feature || null;
        upgradeState.message = options.message || null;

        const pagination = document.getElementById('safkaPagination');
        if (pagination) pagination.style.display = 'none';

        renderUpgradeSheet(options.requiredTier || 'hore');

        sheet.style.transform = 'translateY(0)';
        sheet.classList.add('active');
        backdrop.classList.add('active');
        document.body.style.overflow = 'hidden';
        isOpen = true;
    }

    function closeSheet() {
        if (!isOpen) return;
        sheet.style.transform = 'translateY(100%)';
        sheet.classList.remove('active');
        backdrop.classList.remove('active');
        document.body.style.overflow = '';
        isOpen = false;

        upgradeState = {
            step: 1, tier: null, duration: 'yearly', originalPrice: 0,
            discountCode: null, discountAmount: 0, finalPrice: 0,
            requestId: null, note: '', feature: null, message: null
        };
    }

    function renderUpgradeSheet(highlightTier) {
        upgradeState.step = 1;
        upgradeState.tier = highlightTier || null;
        upgradeState.duration = 'yearly';
        updatePrices();
        renderStep1();
    }

    function updatePrices() {
        if (upgradeState.tier) {
            upgradeState.originalPrice = PRICES[upgradeState.tier][upgradeState.duration] || 0;
            upgradeState.finalPrice = upgradeState.originalPrice - upgradeState.discountAmount;
            if (upgradeState.finalPrice < 0) upgradeState.finalPrice = 0;
        }
    }

    function renderStep1() {
        const tier = upgradeState.tier;
        const contextMsg = upgradeState.message
            ? '<div style="background: var(--primary-light); color: var(--text); padding: 10px 14px; border-radius: 10px; margin-bottom: 12px; font-size: 13px; line-height: 1.45;">' +
              escapeHtml(upgradeState.message) +
              '</div>'
            : '';

        const html = `
            <div class="safka-upgrade-step" data-step="1">
                <div class="safka-step-header">
                    <h2>Upgrade Your Plan</h2>
                    <div class="safka-step-dots">
                        <span class="dot active"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                    </div>
                </div>
                ${contextMsg}
                <div class="safka-plan-grid">
                    <div class="safka-plan-card ${tier === 'dhexe' ? 'selected' : ''}" data-tier="dhexe">
                        <div class="safka-plan-header">
                            <span class="safka-tier-icon">🔓</span>
                            <span class="safka-tier-name">Dhexe</span>
                            <span class="safka-tier-price">From $1.25</span>
                        </div>
                        <ul class="safka-feature-badges">
                            <li>📊 Analytics</li>
                            <li>⚡ Live Host</li>
                            <li>💾 50 Saves</li>
                            <li>📝 30/day Quizzes</li>
                        </ul>
                        <div class="safka-tap-hint">Tap to view</div>
                    </div>
                    <div class="safka-plan-card ${tier === 'hore' ? 'selected' : ''}" data-tier="hore">
                        <div class="safka-plan-header">
                            <span class="safka-tier-icon">⭐</span>
                            <span class="safka-tier-name">Hore</span>
                            <span class="safka-tier-price">From $2.00</span>
                        </div>
                        <ul class="safka-feature-badges">
                            <li>📈 Full Analytics</li>
                            <li>💎 Premium PDFs</li>
                            <li>♾️ Unlimited</li>
                            <li>⭐ Priority Support</li>
                        </ul>
                        <div class="safka-tap-hint">Tap to view</div>
                    </div>
                </div>
                <div class="safka-reassurance">
                    🔒 Admin approval required. No payment collected here.
                </div>
            </div>
        `;
        content.innerHTML = html;

        document.querySelectorAll('.safka-plan-card').forEach(card => {
            card.addEventListener('click', function() {
                upgradeState.tier = this.dataset.tier;
                upgradeState.duration = 'yearly';
                updatePrices();
                renderStep2();
            });
        });
    }

    function renderStep2() {
        const tier = upgradeState.tier;
        const features = FEATURES[tier] || [];
        const price = PRICES[tier];
        const durations = ['monthly', 'term', 'yearly'];
        const durationLabels = { monthly: 'Monthly', term: 'Term (4 mo)', yearly: 'Yearly' };
        const selectedDuration = upgradeState.duration;

        let html = `
            <div class="safka-upgrade-step" data-step="2">
                <div class="safka-step-header">
                    <button class="safka-back-btn">←</button>
                    <h2>${tier.toUpperCase()}</h2>
                    <div class="safka-step-dots">
                        <span class="dot"></span>
                        <span class="dot active"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                    </div>
                </div>
                <div class="safka-feature-list">
                    <div class="safka-feature-list-header">
                        <span class="safka-price-range">From $${price.monthly}/month</span>
                    </div>
                    <ul>
        `;
        features.forEach(f => { html += `<li>✅ ${f}</li>`; });
        html += `
                    </ul>
                </div>
                <div class="safka-duration-picker">
        `;
        durations.forEach(d => {
            const active = d === selectedDuration ? 'active' : '';
            html += `<button class="safka-duration-pill ${active}" data-duration="${d}">${durationLabels[d]}<br><span class="safka-duration-price">$${price[d]}</span></button>`;
        });
        html += `
                </div>
                <div class="safka-step-actions">
                    <button class="safka-back-link">← Back to Plans</button>
                    <button class="safka-primary-btn" id="safkaUpgradeNow">Upgrade Now →</button>
                </div>
            </div>
        `;
        content.innerHTML = html;

        document.querySelectorAll('.safka-duration-pill').forEach(pill => {
            pill.addEventListener('click', function() {
                upgradeState.duration = this.dataset.duration;
                updatePrices();
                renderStep2();
            });
        });

        const backLink = document.querySelector('.safka-back-link');
        if (backLink) backLink.addEventListener('click', renderStep1);
        const backBtn = document.querySelector('.safka-back-btn');
        if (backBtn) backBtn.addEventListener('click', renderStep1);

        const upgradeBtn = document.getElementById('safkaUpgradeNow');
        if (upgradeBtn) upgradeBtn.addEventListener('click', renderStep3);
    }

    function renderStep3() {
        const tier = upgradeState.tier;
        const duration = upgradeState.duration;
        const price = PRICES[tier][duration];
        const discount = upgradeState.discountAmount;
        const finalPrice = price - discount;

        const badgeStyle = discount > 0 ? '' : 'style="display:none;"';
        const badgeText = discount > 0 ? `-$${discount.toFixed(2)}` : '-$0.00';

        let html = `
            <div class="safka-upgrade-step" data-step="3">
                <div class="safka-step-header">
                    <button class="safka-back-btn">←</button>
                    <h2>Submit Request</h2>
                    <div class="safka-step-dots">
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot active"></span>
                        <span class="dot"></span>
                    </div>
                </div>
                <div class="safka-plan-summary">
                    <span class="safka-summary-tier">${tier.toUpperCase()} — ${duration.charAt(0).toUpperCase() + duration.slice(1)}</span>
                    <span class="safka-summary-price" id="safkaSummaryPrice">$${finalPrice.toFixed(2)}</span>
                    <span class="safka-discount-badge" id="safkaDiscountBadge" ${badgeStyle}>${badgeText}</span>
                </div>
                <div class="safka-discount-section">
                    <input type="text" id="safkaDiscountInput" placeholder="Discount code" value="${upgradeState.discountCode || ''}">
                    <button id="safkaApplyDiscount">Apply</button>
                    <div id="safkaDiscountFeedback"></div>
                </div>
                <div class="safka-form-fields">
                    <div class="safka-field readonly">
                        <label>Name</label>
                        <input type="text" value="${escapeHtml(window.userName || 'User')}" readonly>
                    </div>
                    <div class="safka-field readonly">
                        <label>Phone</label>
                        <input type="text" value="${escapeHtml(window.userPhone || '')}" readonly>
                    </div>
                    <div class="safka-field">
                        <label>Note (optional)</label>
                        <textarea id="safkaNote" rows="2" placeholder="Any special request?">${escapeHtml(upgradeState.note || '')}</textarea>
                    </div>
                </div>
                <div class="safka-step-actions">
                    <button class="safka-back-link">← Back</button>
                    <button class="safka-primary-btn" id="safkaSubmitRequest">Submit Request</button>
                </div>
            </div>
        `;
        content.innerHTML = html;

        const applyBtn = document.getElementById('safkaApplyDiscount');
        if (applyBtn) {
            applyBtn.addEventListener('click', function() {
                const code = document.getElementById('safkaDiscountInput').value.trim();
                if (!code) return;

                const feedbackEl = document.getElementById('safkaDiscountFeedback');
                feedbackEl.innerHTML = '<span style="color: var(--text-muted);">Checking…</span>';

                fetch('/upgrade/api/validate-discount', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': getCsrfToken()
                    },
                    body: JSON.stringify({
                        code: code,
                        tier: upgradeState.tier,
                        duration: upgradeState.duration
                    })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.valid) {
                        upgradeState.discountCode = code;
                        upgradeState.discountAmount = data.discount_amount || 0;
                        upgradeState.finalPrice = data.final_price;
                        feedbackEl.innerHTML = '<span style="color:#10B981;">✅ ' + escapeHtml(data.message || 'Applied!') + '</span>';

                        const priceEl = document.getElementById('safkaSummaryPrice');
                        if (priceEl) priceEl.textContent = '$' + upgradeState.finalPrice.toFixed(2);

                        const badgeEl = document.getElementById('safkaDiscountBadge');
                        if (badgeEl) {
                            badgeEl.textContent = '-$' + upgradeState.discountAmount.toFixed(2);
                            badgeEl.style.display = '';
                        }
                    } else {
                        feedbackEl.innerHTML = '<span style="color:#EF4444;">❌ ' + escapeHtml(data.message || 'Invalid code') + '</span>';
                    }
                })
                .catch(() => {
                    feedbackEl.innerHTML = '<span style="color:#EF4444;">❌ Network error. Try again.</span>';
                });
            });
        }

        const backLink = document.querySelector('.safka-back-link');
        if (backLink) backLink.addEventListener('click', renderStep2);
        const backBtn = document.querySelector('.safka-back-btn');
        if (backBtn) backBtn.addEventListener('click', renderStep2);

        const submitBtn = document.getElementById('safkaSubmitRequest');
        if (submitBtn) {
            submitBtn.addEventListener('click', function() {
                const noteEl = document.getElementById('safkaNote');
                upgradeState.note = noteEl ? noteEl.value.trim() : '';

                const btn = this;
                btn.disabled = true;
                btn.innerHTML = 'Submitting…';

                fetch('/upgrade/api/request', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': getCsrfToken()
                    },
                    body: JSON.stringify({
                        tier: upgradeState.tier,
                        duration: upgradeState.duration,
                        discount_code: upgradeState.discountCode || null,
                        note: upgradeState.note
                    })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        upgradeState.requestId = data.request_id;
                        renderStep4();
                    } else {
                        alert('Error: ' + (data.message || 'Unknown error'));
                        btn.disabled = false;
                        btn.innerHTML = 'Submit Request';
                    }
                })
                .catch(() => {
                    alert('Network error. Please try again.');
                    btn.disabled = false;
                    btn.innerHTML = 'Submit Request';
                });
            });
        }
    }

    function renderStep4() {
        const tier = upgradeState.tier;
        const duration = upgradeState.duration;
        const finalPrice = upgradeState.finalPrice;
        const requestId = upgradeState.requestId;

        // Build admin request URL
        const baseUrl = window.baseUrl || window.location.origin;
        const requestUrl = baseUrl.replace(/\/$/, '') + '/upgrade/admin/upgrade-requests/' + encodeURIComponent(requestId);

        // Message body sent to the admin via WhatsApp
        const messageBody =
            'Hello Admin, I have submitted an upgrade request.\n\n' +
            '📌 Request ID: ' + requestId + '\n' +
            '👤 Name: ' + (window.userName || 'User') + '\n' +
            '📞 Phone: ' + (window.userPhone || '') + '\n' +
            '🏷️ Plan: ' + tier.toUpperCase() + ' — ' + (duration.charAt(0).toUpperCase() + duration.slice(1)) + '\n' +
            '💰 Amount: $' + finalPrice.toFixed(2) + '\n\n' +
            '🔗 Review here:\n' + requestUrl;

        // Direct to admin number (digits only, no +)
        const adminPhone = (window.upgradeAdminPhone || '').replace(/[^\d]/g, '');
        const whatsappUrl = adminPhone
            ? 'https://wa.me/' + adminPhone + '?text=' + encodeURIComponent(messageBody)
            : 'https://wa.me/?text=' + encodeURIComponent(messageBody);

        const html = `
            <div class="safka-upgrade-step" data-step="4">
                <div class="safka-step-header">
                    <h2>✅ Request Submitted!</h2>
                    <div class="safka-step-dots">
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot active"></span>
                    </div>
                </div>
                <div class="safka-success-icon">
                    <svg viewBox="0 0 24 24" width="64" height="64">
                        <circle cx="12" cy="12" r="10" fill="none" stroke="#10B981" stroke-width="2"/>
                        <path d="M7 12l3 3 7-7" stroke="#10B981" stroke-width="2" fill="none"
                              stroke-dasharray="20" stroke-dashoffset="20" class="safka-check-path"/>
                    </svg>
                </div>
                <div class="safka-success-details">
                    <p class="safka-request-id">Request ID: <strong>${escapeHtml(requestId)}</strong></p>
                    <p class="safka-summary">${tier.toUpperCase()} — ${duration.charAt(0).toUpperCase() + duration.slice(1)} ($${finalPrice.toFixed(2)})</p>
                    <p class="safka-next-step">📱 The admin will contact you via WhatsApp to complete payment.</p>
                    <a href="${whatsappUrl}" target="_blank" rel="noopener" class="safka-whatsapp-btn">
                        <i class="fab fa-whatsapp"></i> Notify Admin on WhatsApp
                    </a>
                    <button class="safka-close-btn" onclick="closeSafkaSheet()">✕ Close</button>
                </div>
            </div>
        `;
        content.innerHTML = html;

        setTimeout(() => {
            const path = document.querySelector('.safka-check-path');
            if (path) path.style.strokeDashoffset = '0';
        }, 100);
    }

    function onDragStart(e) {
        if (!isOpen) return;
        isDragging = true;
        dragStartY = e.clientY;
        sheetOffsetY = 0;
        sheet.classList.add('dragging');
        document.addEventListener('mousemove', onDragMove);
        document.addEventListener('mouseup', onDragEnd);
        e.preventDefault();
    }
    function onDragMove(e) {
        if (!isDragging) return;
        const delta = e.clientY - dragStartY;
        if (delta > 0) {
            sheet.style.transform = 'translateY(' + delta + 'px)';
            sheetOffsetY = delta;
        }
    }
    function onDragEnd() {
        if (!isDragging) return;
        isDragging = false;
        sheet.classList.remove('dragging');
        document.removeEventListener('mousemove', onDragMove);
        document.removeEventListener('mouseup', onDragEnd);
        if (sheetOffsetY > 80) closeSheet();
        else sheet.style.transform = 'translateY(0)';
    }
    function onDragStartTouch(e) {
        if (!isOpen) return;
        const touch = e.touches[0];
        isDragging = true;
        dragStartY = touch.clientY;
        sheetOffsetY = 0;
        sheet.classList.add('dragging');
        document.addEventListener('touchmove', onDragMoveTouch, { passive: false });
        document.addEventListener('touchend', onDragEndTouch, { passive: false });
        e.preventDefault();
    }
    function onDragMoveTouch(e) {
        if (!isDragging) return;
        const touch = e.touches[0];
        const delta = touch.clientY - dragStartY;
        if (delta > 0) {
            sheet.style.transform = 'translateY(' + delta + 'px)';
            sheetOffsetY = delta;
        }
        e.preventDefault();
    }
    function onDragEndTouch() {
        if (!isDragging) return;
        isDragging = false;
        sheet.classList.remove('dragging');
        document.removeEventListener('touchmove', onDragMoveTouch);
        document.removeEventListener('touchend', onDragEndTouch);
        if (sheetOffsetY > 80) closeSheet();
        else sheet.style.transform = 'translateY(0)';
    }

    function getCsrfToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.content;
        const input = document.querySelector('input[name="csrf_token"]');
        if (input) return input.value;
        return '';
    }

    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();