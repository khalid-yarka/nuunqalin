// ============================================
// PDF.JS VIEWER – Full Functionality
// ============================================

(function() {
    'use strict';

    // Configuration
    const MIN_SCALE = 0.5;
    const MAX_SCALE = 2.5;
    const SCALE_STEP = 0.1;

    // State
    let pdfDoc = null;
    let currentPage = 1;
    let totalPages = 0;
    let scale = 1.0;
    let canvas = null;
    let ctx = null;

    // DOM Elements
    const container = document.getElementById('pdfContainer');
    const canvasContainer = document.getElementById('pdfCanvasContainer');
    const loading = document.getElementById('pdfLoading');
    const controls = document.getElementById('pdfControls');
    
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');
    const pageInfo = document.getElementById('pageInfo');
    const zoomInBtn = document.getElementById('zoomIn');
    const zoomOutBtn = document.getElementById('zoomOut');
    const zoomLevel = document.getElementById('zoomLevel');
    const fullscreenBtn = document.getElementById('fullscreenBtn');

    // ============================================
    // SECURITY MEASURES
    // ============================================

    function disableContextMenu() {
        const viewer = document.getElementById('pdfViewerWrapper');
        if (viewer) {
            viewer.addEventListener('contextmenu', function(e) {
                e.preventDefault();
                return false;
            });
        }
    }

    function disableShortcuts() {
        document.addEventListener('keydown', function(e) {
            // Ctrl+S (Save)
            if (e.ctrlKey && e.key === 's') {
                e.preventDefault();
                showToast('Saving is disabled for this document.');
                return false;
            }
            // Ctrl+P (Print)
            if (e.ctrlKey && e.key === 'p') {
                e.preventDefault();
                showToast('Printing is disabled for this document.');
                return false;
            }
            // F12 (Dev Tools)
            if (e.key === 'F12') {
                e.preventDefault();
                return false;
            }
            // Ctrl+Shift+I (Dev Tools)
            if (e.ctrlKey && e.shiftKey && e.key === 'I') {
                e.preventDefault();
                return false;
            }
            // Ctrl+U (View Source)
            if (e.ctrlKey && e.key === 'u') {
                e.preventDefault();
                return false;
            }
        });
    }

    // ============================================
    // TOAST NOTIFICATION
    // ============================================

    function showToast(message) {
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #1A1A2E;
            color: white;
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 500;
            z-index: 9999;
            box-shadow: 0 4px 14px rgba(0,0,0,0.2);
            animation: fadeIn 0.3s ease;
            max-width: 90%;
            text-align: center;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(function() {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.4s ease';
            setTimeout(function() {
                toast.remove();
            }, 400);
        }, 3000);
    }

    // ============================================
    // PDF LOADING & RENDERING
    // ============================================

    function loadPDF(url) {
        if (!url) {
            loading.innerHTML = `
                <div style="font-size: 48px; opacity: 0.4; margin-bottom: 12px;">⚠️</div>
                <h3 style="font-size: 18px; font-weight: 600; color: var(--text);">No PDF URL provided</h3>
                <p style="font-size: 14px; color: var(--text-secondary); margin-top: 4px;">The PDF could not be loaded.</p>
            `;
            controls.style.display = 'none';
            return;
        }

        loading.style.display = 'block';
        controls.style.display = 'none';

        pdfjsLib.getDocument(url).promise
            .then(function(pdf) {
                pdfDoc = pdf;
                totalPages = pdf.numPages;
                currentPage = 1;
                scale = 1.0;
                
                controls.style.display = 'flex';
                updateControls();
                renderPage(currentPage);
                loading.style.display = 'none';
            })
            .catch(function(error) {
                loading.innerHTML = `
                    <div style="font-size: 48px; opacity: 0.4; margin-bottom: 12px;">⚠️</div>
                    <h3 style="font-size: 18px; font-weight: 600; color: var(--text);">Failed to load PDF</h3>
                    <p style="font-size: 14px; color: var(--text-secondary); margin-top: 4px;">${error.message}</p>
                    <a href="#" id="telegramFallback" target="_blank" 
                       style="display: inline-block; margin-top: 16px; padding: 10px 24px; background: #0088CC; color: white; border-radius: var(--radius-sm); text-decoration: none; font-weight: 600; transition: var(--transition);">
                        <i class="fab fa-telegram-plane"></i> Download from Telegram
                    </a>
                `;
                controls.style.display = 'none';
                console.error('Error loading PDF:', error);
                
                // Set Telegram fallback link
                const fallback = document.getElementById('telegramFallback');
                if (fallback) {
                    fallback.href = document.querySelector('.btn-telegram')?.href || '#';
                }
            });
    }

    function renderPage(pageNum) {
        if (!pdfDoc) return;

        pdfDoc.getPage(pageNum).then(function(page) {
            const viewport = page.getViewport({ scale: scale });
            
            if (!canvas) {
                canvas = document.createElement('canvas');
                canvasContainer.appendChild(canvas);
                ctx = canvas.getContext('2d');
            }
            
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            canvas.style.width = viewport.width + 'px';
            canvas.style.height = viewport.height + 'px';
            
            const renderContext = {
                canvasContext: ctx,
                viewport: viewport
            };
            
            page.render(renderContext).promise.then(function() {
                updateControls();
            });
        });
    }

    // ============================================
    // NAVIGATION CONTROLS
    // ============================================

    function updateControls() {
        if (pageInfo) {
            pageInfo.textContent = currentPage + ' / ' + totalPages;
        }
        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
        if (zoomLevel) zoomLevel.textContent = Math.round(scale * 100) + '%';
        
        if (zoomInBtn) zoomInBtn.disabled = scale >= MAX_SCALE;
        if (zoomOutBtn) zoomOutBtn.disabled = scale <= MIN_SCALE;
    }

    function goToPage(pageNum) {
        if (pageNum < 1 || pageNum > totalPages) return;
        currentPage = pageNum;
        renderPage(currentPage);
    }

    function changeZoom(delta) {
        let newScale = scale + delta;
        newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
        if (newScale !== scale) {
            scale = newScale;
            renderPage(currentPage);
        }
    }

    // ============================================
    // EVENT LISTENERS
    // ============================================

    function initEvents() {
        // Page navigation
        if (prevBtn) {
            prevBtn.addEventListener('click', function() {
                goToPage(currentPage - 1);
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', function() {
                goToPage(currentPage + 1);
            });
        }

        // Keyboard navigation
        document.addEventListener('keydown', function(e) {
            if (e.key === 'ArrowLeft' && !e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault();
                goToPage(currentPage - 1);
            }
            else if (e.key === 'ArrowRight' && !e.ctrlKey && !e.altKey && !e.metaKey) {
                e.preventDefault();
                goToPage(currentPage + 1);
            }
            else if (e.key === 'Escape' && document.fullscreenElement) {
                document.exitFullscreen();
            }
        });

        // Zoom controls
        if (zoomInBtn) {
            zoomInBtn.addEventListener('click', function() {
                changeZoom(SCALE_STEP);
            });
        }

        if (zoomOutBtn) {
            zoomOutBtn.addEventListener('click', function() {
                changeZoom(-SCALE_STEP);
            });
        }

        // Fullscreen
        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', function() {
                const wrapper = document.getElementById('pdfViewerWrapper');
                if (!document.fullscreenElement) {
                    wrapper.requestFullscreen().catch(function(err) {
                        showToast('Fullscreen mode not supported.');
                    });
                } else {
                    document.exitFullscreen();
                }
            });
        }

        // Update fullscreen button icon
        document.addEventListener('fullscreenchange', function() {
            if (document.fullscreenElement) {
                fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i> Exit';
            } else {
                fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i> Fullscreen';
            }
        });
    }

    // ============================================
    // INITIALIZE
    // ============================================

    function init(pdfUrl) {
        disableContextMenu();
        disableShortcuts();
        initEvents();
        loadPDF(pdfUrl);
    }

    // Export for use in templates
    window.PDFViewer = {
        init: init,
        loadPDF: loadPDF,
        goToPage: goToPage,
        changeZoom: changeZoom,
        showToast: showToast
    };

})();