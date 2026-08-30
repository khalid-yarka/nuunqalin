// ============================================
// DASHBOARD JAVASCRIPT
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    // ============================================
    // SIDEBAR TOGGLE (Mobile)
    // ============================================
    
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    function toggleSidebar() {
        sidebar.classList.toggle('open');
        if (overlay) {
            overlay.classList.toggle('active');
        }
        document.body.style.overflow = sidebar.classList.contains('open') ? 'hidden' : '';
    }
    
    function closeSidebar() {
        sidebar.classList.remove('open');
        if (overlay) {
            overlay.classList.remove('active');
        }
        document.body.style.overflow = '';
    }
    
    if (menuToggle) {
        menuToggle.addEventListener('click', toggleSidebar);
    }
    
    if (overlay) {
        overlay.addEventListener('click', closeSidebar);
    }
    
    // Close sidebar on escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });
    
    // Close sidebar on window resize (if going from mobile to desktop)
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768 && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });
    
    // ============================================
    // ACTIVE NAV LINK
    // ============================================
    
    // Get current page path
    const currentPath = window.location.pathname;
    
    // Find all nav items
    const navItems = document.querySelectorAll('.nav-item');
    
    navItems.forEach(function(item) {
        const href = item.getAttribute('href');
        if (href && href !== '#') {
            // Check if current path matches or starts with href
            if (currentPath === href || (href !== '/' && currentPath.startsWith(href))) {
                item.classList.add('active');
            }
        }
    });

    // ============================================
    // THEME POPOVER
    // ============================================
    
    (function() {
        const toggleBtn = document.getElementById('themeToggle');
        const popover = document.getElementById('themePopover');
        const options = popover?.querySelectorAll('.theme-option');

        if (!toggleBtn || !popover) return;

        // Load saved theme from localStorage
        const savedTheme = localStorage.getItem('preferred-theme') || 'system';

        // Highlight active option
        function highlightActive(theme) {
            options.forEach(opt => {
                opt.classList.toggle('active', opt.dataset.theme === theme);
            });
        }

        // Apply theme (reuse the global function from main.js)
        function applyTheme(theme) {
            // This function is already defined in main.js
            // We'll call it, but ensure it's available
            if (typeof window.applyTheme === 'function') {
                window.applyTheme(theme);
            } else {
                // Fallback: simple implementation
                if (theme === 'system') {
                    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
                } else {
                    document.documentElement.setAttribute('data-theme', theme);
                }
                localStorage.setItem('preferred-theme', theme);
            }
            highlightActive(theme);
        }

        // Set initial active
        highlightActive(savedTheme);

        // Toggle popover
        toggleBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            popover.classList.toggle('open');
        });

        // Close popover on outside click
        document.addEventListener('click', function(e) {
            if (!popover.contains(e.target) && e.target !== toggleBtn) {
                popover.classList.remove('open');
            }
        });

        // Option click
        options.forEach(opt => {
            opt.addEventListener('click', function(e) {
                e.stopPropagation();
                const theme = this.dataset.theme;
                applyTheme(theme);
                popover.classList.remove('open');
            });
        });

        // Listen for system preference changes when in 'system' mode
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
            const current = localStorage.getItem('preferred-theme') || 'system';
            if (current === 'system') {
                document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    })();
});