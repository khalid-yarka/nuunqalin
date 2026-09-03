// ============================================
// SAFKA PREVIEW SYSTEM – Nuunqalin
// Professional Upgrade Sheet
// ============================================

(function() {
    'use strict';

    // ----- DOM References -----
    let backdrop, sheet, track, dots, closeBtn, handle;
    let currentSlide = 0;
    let totalSlides = 3;
    let isOpen = false;
    let isDragging = false;
    let isSwiping = false;
    let dragStartY = 0;
    let dragCurrentY = 0;
    let sheetOffsetY = 0;
    let swipeStartX = 0;
    let swipeCurrentX = 0;
    let targetFeature = null;
    let targetRequiredTier = null;
    let isAnimating = false;

    // ----- Constants -----
    const CLOSE_THRESHOLD = 80;
    const SWIPE_THRESHOLD = 40;

    // ----- Initialization -----
    function init() {
        backdrop = document.getElementById('safkaBackdrop');
        sheet = document.getElementById('safkaSheet');
        track = document.getElementById('safkaTrack');
        closeBtn = document.getElementById('safkaClose');
        handle = document.getElementById('safkaHandle');
        dots = document.querySelectorAll('.safka-pagination__dot');

        if (!backdrop || !sheet || !track) {
            console.warn('Safka sheet elements not found.');
            return;
        }

        // Render slides
        renderSlides();

        // Event listeners
        backdrop.addEventListener('click', closeSheet);
        closeBtn.addEventListener('click', closeSheet);

        // Drag to dismiss (handle)
        handle.addEventListener('mousedown', onDragStart);
        handle.addEventListener('touchstart', onDragStartTouch, { passive: false });

        // Swipe on carousel
        const carousel = document.querySelector('.safka-carousel');
        if (carousel) {
            carousel.addEventListener('mousedown', onSwipeStart);
            carousel.addEventListener('touchstart', onSwipeStartTouch, { passive: false });
        }

        // Keyboard
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isOpen) {
                closeSheet();
            }
            if (e.key === 'ArrowLeft' && isOpen) {
                goToSlide(currentSlide - 1);
            }
            if (e.key === 'ArrowRight' && isOpen) {
                goToSlide(currentSlide + 1);
            }
        });

        // Dots
        dots.forEach(function(dot, idx) {
            dot.addEventListener('click', function() {
                if (isAnimating) return;
                goToSlide(idx);
            });
        });

        // Expose global functions
        window.openSafkaPreview = openSafkaPreview;
        window.closeSafkaSheet = closeSheet;
        window.triggerUpgrade = triggerUpgrade;

        // Global click listener for locked features
        document.addEventListener('click', function(e) {
            const target = e.target.closest('[data-tier-locked]');
            if (target) {
                e.preventDefault();
                const feature = target.dataset.feature || null;
                const requiredTier = target.dataset.requiredTier || 'dhexe';
                triggerUpgrade(feature, requiredTier);
            }
        });

        // Add click animation to interactive elements inside sheet
        sheet.addEventListener('mousedown', function(e) {
            const btn = e.target.closest('.safka-pagination__dot, .safka-sheet__close, [data-tier-locked]');
            if (btn) {
                btn.classList.add('safka-click-pulse');
                setTimeout(() => btn.classList.remove('safka-click-pulse'), 300);
            }
        });
    }

    // ----- Render Slides -----
    function renderSlides() {
        const slidesData = [
            {
                id: 'danbe',
                title: 'Safka Danbe',
                subtitle: 'The foundation. Start your learning journey with essential tools.',
                badge: 'Foundation',
                badgeClass: 'safka-slide__badge--danbe',
                features: [
                    { icon: '📊', name: 'Basic Statistics', desc: 'Track your progress and scores.' },
                    { icon: '🏁', name: 'Basic Achievements', desc: 'Earn rewards as you learn.' },
                    { icon: '📝', name: 'Basic Explanations', desc: 'Understand right and wrong answers.' },
                    { icon: '👤', name: 'Basic Profile', desc: 'Personalize your learning space.' },
                    { icon: '📚', name: 'Daily Quiz Access', desc: 'Up to 10 questions per quiz.' },
                ],
                locked: false,
            },
            {
                id: 'dhexe',
                title: 'Safka Dhexe',
                subtitle: 'Go deeper. Unlock advanced analytics, more resources, and greater control.',
                badge: 'Advanced',
                badgeClass: 'safka-slide__badge--dhexe',
                features: [
                    { icon: '📈', name: 'Advanced Analytics', desc: 'Detailed performance insights.' },
                    { icon: '🔍', name: 'Subject Filters', desc: 'Find resources by subject.' },
                    { icon: '💾', name: '50 Saved Items', desc: 'Bookmark your favorite content.' },
                    { icon: '📝', name: '30 Quiz Attempts/Day', desc: 'Practice more, learn faster.' },
                    { icon: '⚡', name: 'Live Quiz Hosting', desc: 'Create and host live quizzes.' },
                    { icon: '🏆', name: 'Expanded Achievements', desc: 'More badges to unlock.' },
                ],
                locked: false,
                preview: {
                    type: 'analytics',
                    title: 'Advanced Analytics Preview',
                    content: '📊 Subject performance trends, percentile ranking, and detailed progress charts.',
                }
            },
            {
                id: 'hore',
                title: 'Safka Hore',
                subtitle: 'The complete Nuun experience. Unlimited learning, full analytics, and premium resources.',
                badge: 'Complete',
                badgeClass: 'safka-slide__badge--hore',
                features: [
                    { icon: '📊', name: 'Full Analytics', desc: 'Complete historical trends and comparisons.' },
                    { icon: '💎', name: 'Premium Resources', desc: 'Access exclusive study materials.' },
                    { icon: '💾', name: 'Unlimited Saved Items', desc: 'Save everything you love.' },
                    { icon: '📝', name: 'Unlimited Quiz Attempts', desc: 'Practice as much as you want.' },
                    { icon: '⚡', name: 'Full Live Quiz', desc: 'All hosting and scheduling features.' },
                    { icon: '🏆', name: 'Complete Achievements', desc: 'All badges and progress insights.' },
                ],
                locked: false,
                preview: {
                    type: 'premium_resources',
                    title: 'Premium Resources Preview',
                    content: '📘 Advanced subject guides, practice tests, and expert explanations.',
                }
            }
        ];

        let trackHTML = '';
        slidesData.forEach(function(slide, idx) {
            let featureCards = '';
            slide.features.forEach(function(f) {
                featureCards += `
                    <div class="safka-feature-card">
                        <span class="safka-feature-card__icon">${f.icon}</span>
                        <div class="safka-feature-card__name">${f.name}</div>
                        <div class="safka-feature-card__desc">${f.desc}</div>
                    </div>
                `;
            });

            let previewHTML = '';
            if (slide.preview) {
                previewHTML = `
                    <div class="safka-preview-locked">
                        <span class="safka-preview-locked__label">Preview</span>
                        <div class="safka-preview-locked__content">
                            <div style="padding: 12px; background: var(--surface); border-radius: 8px; border: 1px solid var(--border);">
                                <strong>${slide.preview.title}</strong>
                                <p style="margin: 4px 0 0; font-size: 13px; color: var(--text-secondary);">${slide.preview.content}</p>
                            </div>
                        </div>
                        <div class="safka-preview-locked__overlay">
                            <span>🔒 ${slide.badge}</span>
                        </div>
                    </div>
                `;
            }

            trackHTML += `
                <div class="safka-slide" data-slide="${idx}">
                    <div class="safka-slide__badge ${slide.badgeClass}">${slide.badge}</div>
                    <div class="safka-slide__title">${slide.title}</div>
                    <div class="safka-slide__subtitle">${slide.subtitle}</div>
                    ${previewHTML}
                    <div class="safka-features">
                        ${featureCards}
                    </div>
                </div>
            `;
        });

        track.innerHTML = trackHTML;
        totalSlides = slidesData.length;
        updateDots();
    }

    // ----- Navigation -----
    function goToSlide(index) {
        if (isAnimating) return;
        if (index < 0) index = 0;
        if (index >= totalSlides) index = totalSlides - 1;
        if (index === currentSlide) return;

        isAnimating = true;
        currentSlide = index;
        track.style.transform = `translateX(-${currentSlide * 100}%)`;
        updateDots();

        setTimeout(() => {
            isAnimating = false;
        }, 500);
    }

    function updateDots() {
        dots.forEach(function(dot, idx) {
            if (idx === currentSlide) {
                dot.classList.add('active');
            } else {
                dot.classList.remove('active');
            }
        });
    }

    // ----- Open Sheet -----
    function openSafkaPreview(options) {
        options = options || {};
        const feature = options.feature || null;
        const requiredTier = options.requiredTier || null;

        targetFeature = feature;
        targetRequiredTier = requiredTier;

        if (requiredTier) {
            const tierMap = {
                'danbe': 0,
                'dhexe': 1,
                'hore': 2
            };
            const slideIndex = tierMap[requiredTier];
            if (slideIndex !== undefined) {
                currentSlide = slideIndex;
                track.style.transform = `translateX(-${currentSlide * 100}%)`;
                updateDots();
            }
        } else {
            goToSlide(1);
        }

        sheet.style.transform = 'translateY(0)';
        sheet.classList.add('active');
        backdrop.classList.add('active');
        document.body.style.overflow = 'hidden';
        isOpen = true;
        sheetOffsetY = 0;
    }

    // ----- Close Sheet -----
    function closeSheet() {
        if (!isOpen) return;
        sheet.style.transform = 'translateY(100%)';
        sheet.classList.remove('active');
        backdrop.classList.remove('active');
        document.body.style.overflow = '';
        isOpen = false;
        targetFeature = null;
        targetRequiredTier = null;
        sheetOffsetY = 0;
    }

    // ----- Trigger Upgrade (for locked features) -----
    function triggerUpgrade(feature, requiredTier) {
        openSafkaPreview({ feature: feature, requiredTier: requiredTier });
    }

    // ----- Drag to Dismiss (Mouse) -----
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
            sheet.style.transform = `translateY(${delta}px)`;
            sheetOffsetY = delta;
        }
    }

    function onDragEnd(e) {
        if (!isDragging) return;
        isDragging = false;
        sheet.classList.remove('dragging');
        document.removeEventListener('mousemove', onDragMove);
        document.removeEventListener('mouseup', onDragEnd);

        if (sheetOffsetY > CLOSE_THRESHOLD) {
            closeSheet();
        } else {
            sheet.style.transform = 'translateY(0)';
            sheetOffsetY = 0;
        }
    }

    // ----- Drag to Dismiss (Touch) -----
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
            sheet.style.transform = `translateY(${delta}px)`;
            sheetOffsetY = delta;
        }
        e.preventDefault();
    }

    function onDragEndTouch(e) {
        if (!isDragging) return;
        isDragging = false;
        sheet.classList.remove('dragging');
        document.removeEventListener('touchmove', onDragMoveTouch);
        document.removeEventListener('touchend', onDragEndTouch);

        if (sheetOffsetY > CLOSE_THRESHOLD) {
            closeSheet();
        } else {
            sheet.style.transform = 'translateY(0)';
            sheetOffsetY = 0;
        }
    }

    // ----- Swipe on Carousel (Mouse) -----
    function onSwipeStart(e) {
        if (!isOpen) return;
        isSwiping = true;
        swipeStartX = e.clientX;
        track.classList.add('swiping');
        document.addEventListener('mousemove', onSwipeMove);
        document.addEventListener('mouseup', onSwipeEnd);
        e.preventDefault();
    }

    function onSwipeMove(e) {
        if (!isSwiping) return;
        const delta = e.clientX - swipeStartX;
        // We could move the track partially, but we'll keep simple: if delta exceeds threshold, change slide.
        // For now, we just track the delta; we'll decide on end.
        swipeCurrentX = delta;
    }

    function onSwipeEnd(e) {
        if (!isSwiping) return;
        isSwiping = false;
        track.classList.remove('swiping');
        document.removeEventListener('mousemove', onSwipeMove);
        document.removeEventListener('mouseup', onSwipeEnd);

        if (swipeCurrentX < -SWIPE_THRESHOLD) {
            goToSlide(currentSlide + 1);
        } else if (swipeCurrentX > SWIPE_THRESHOLD) {
            goToSlide(currentSlide - 1);
        }
        swipeCurrentX = 0;
    }

    // ----- Swipe on Carousel (Touch) -----
    function onSwipeStartTouch(e) {
        if (!isOpen) return;
        const touch = e.touches[0];
        isSwiping = true;
        swipeStartX = touch.clientX;
        track.classList.add('swiping');
        document.addEventListener('touchmove', onSwipeMoveTouch, { passive: false });
        document.addEventListener('touchend', onSwipeEndTouch, { passive: false });
        e.preventDefault();
    }

    function onSwipeMoveTouch(e) {
        if (!isSwiping) return;
        const touch = e.touches[0];
        swipeCurrentX = touch.clientX - swipeStartX;
        e.preventDefault();
    }

    function onSwipeEndTouch(e) {
        if (!isSwiping) return;
        isSwiping = false;
        track.classList.remove('swiping');
        document.removeEventListener('touchmove', onSwipeMoveTouch);
        document.removeEventListener('touchend', onSwipeEndTouch);

        if (swipeCurrentX < -SWIPE_THRESHOLD) {
            goToSlide(currentSlide + 1);
        } else if (swipeCurrentX > SWIPE_THRESHOLD) {
            goToSlide(currentSlide - 1);
        }
        swipeCurrentX = 0;
    }

    // ----- Init on DOM ready -----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();