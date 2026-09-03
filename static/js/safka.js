// ============================================
// SAFKA PREVIEW SYSTEM – Nuunqalin
// ============================================

(function() {
    'use strict';

    // ----- DOM References -----
    let backdrop, sheet, track, slides, dots, closeBtn, handle;
    let currentSlide = 0;
    let totalSlides = 3;
    let isDragging = false;
    let startX = 0;
    let currentX = 0;
    let isOpen = false;
    let targetFeature = null;
    let targetRequiredTier = null;

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

        // Load slides content
        renderSlides();

        // Event listeners
        backdrop.addEventListener('click', closeSheet);
        closeBtn.addEventListener('click', closeSheet);
        handle.addEventListener('mousedown', startDrag);
        handle.addEventListener('touchstart', startDragTouch, { passive: true });

        // Keyboard
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && isOpen) {
                closeSheet();
            }
        });

        // Dots
        dots.forEach(function(dot, idx) {
            dot.addEventListener('click', function() {
                goToSlide(idx);
            });
        });

        // Expose open function globally
        window.openSafkaPreview = openSafkaPreview;

        // Check for hash on load (optional)
        // handle hash if needed
    }

    // ----- Render Slides (static content) -----
    function renderSlides() {
        // We'll define slides as HTML strings for simplicity.
        // In a real implementation, this could be fetched or templated.
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
                // optional preview
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

        // Build track HTML
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

        // Update dots count
        totalSlides = slidesData.length;
        // If dots already exist, update active class
        updateDots();
    }

    // ----- Navigation -----
    function goToSlide(index) {
        if (index < 0) index = 0;
        if (index >= totalSlides) index = totalSlides - 1;
        currentSlide = index;
        track.style.transform = `translateX(-${currentSlide * 100}%)`;
        updateDots();
        // Update slide content if needed (e.g., show locked preview based on feature)
        // For now, we just update the slide.
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

        // Store for potential use
        targetFeature = feature;
        targetRequiredTier = requiredTier;

        // If a specific feature is requested, we could highlight it or jump to the appropriate slide.
        // For now, we'll open the sheet and maybe set the slide based on requiredTier.
        if (requiredTier) {
            const tierMap = {
                'danbe': 0,
                'dhexe': 1,
                'hore': 2
            };
            const slideIndex = tierMap[requiredTier];
            if (slideIndex !== undefined) {
                goToSlide(slideIndex);
            }
        } else {
            // Default to Dhexe (middle) as a balanced preview
            goToSlide(1);
        }

        sheet.classList.add('active');
        backdrop.classList.add('active');
        document.body.style.overflow = 'hidden';
        isOpen = true;
    }

    // ----- Close Sheet -----
    function closeSheet() {
        sheet.classList.remove('active');
        backdrop.classList.remove('active');
        document.body.style.overflow = '';
        isOpen = false;
        targetFeature = null;
        targetRequiredTier = null;
    }

    // ----- Drag / Swipe (desktop mouse) -----
    function startDrag(e) {
        if (!isOpen) return;
        isDragging = true;
        startX = e.clientX;
        document.addEventListener('mousemove', onDragMove);
        document.addEventListener('mouseup', endDrag);
        e.preventDefault();
    }

    function onDragMove(e) {
        if (!isDragging) return;
        currentX = e.clientX;
        const diff = currentX - startX;
        // If diff > 50, close
        if (diff > 80) {
            closeSheet();
            endDrag(e);
        } else if (diff < -80) {
            // Next slide? We'll implement simple next/prev on drag later.
            // For now, we'll ignore.
        }
    }

    function endDrag(e) {
        isDragging = false;
        document.removeEventListener('mousemove', onDragMove);
        document.removeEventListener('mouseup', endDrag);
    }

    // ----- Touch Drag -----
    let touchStartX = 0;
    let touchStartY = 0;
    let touchMoved = false;

    function startDragTouch(e) {
        if (!isOpen) return;
        const touch = e.touches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
        touchMoved = false;
        // We'll use a touchmove listener on the document
        document.addEventListener('touchmove', onTouchMove, { passive: true });
        document.addEventListener('touchend', onTouchEnd, { passive: true });
    }

    function onTouchMove(e) {
        if (!isOpen) return;
        const touch = e.touches[0];
        const deltaX = touch.clientX - touchStartX;
        const deltaY = touch.clientY - touchStartY;
        if (Math.abs(deltaX) > 20 || Math.abs(deltaY) > 20) {
            touchMoved = true;
        }
        // If swiping down more than up, close
        if (deltaY > 60) {
            closeSheet();
            document.removeEventListener('touchmove', onTouchMove);
            document.removeEventListener('touchend', onTouchEnd);
        }
    }

    function onTouchEnd(e) {
        document.removeEventListener('touchmove', onTouchMove);
        document.removeEventListener('touchend', onTouchEnd);
    }

    // ----- Expose to global -----
    window.openSafkaPreview = openSafkaPreview;
    window.closeSafkaSheet = closeSheet;

    // ----- Init on DOM ready -----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();