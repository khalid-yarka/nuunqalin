// static/js/dashboard.js
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

    const currentPath = window.location.pathname;
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(function(item) {
        const href = item.getAttribute('href');
        if (href && href !== '#') {
            if (currentPath === href || (href !== '/' && currentPath.startsWith(href))) {
                item.classList.add('active');
            }
        }
    });

    // ============================================
    // THEME TOGGLE – Updated to use NuunSettings API
    // ============================================
    (function() {
        const toggleBtn = document.getElementById('themeToggle');
        const icon = document.getElementById('themeIcon');
        if (!toggleBtn || !icon) return;

        const themes = ['light', 'dark', 'system'];
        const themeIcons = {
            light: 'fa-sun',
            dark: 'fa-moon',
            system: 'fa-desktop'
        };

        function getCurrentTheme() {
            return document.documentElement.getAttribute('data-theme') || 'system';
        }

        function applyTheme(theme) {
            // Delegate to NuunSettings for persistence
            if (typeof NuunSettings !== 'undefined' && NuunSettings.initialized) {
                NuunSettings.set('appearance.theme', theme);
            } else {
                // Fallback (should not happen in normal flow)
                if (theme === 'system') {
                    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
                } else {
                    document.documentElement.setAttribute('data-theme', theme);
                }
                localStorage.setItem('preferred-theme', theme);
                // Update icon
                icon.className = 'fas ' + (themeIcons[theme] || 'fa-sun');
            }
            // Optimistically update icon
            icon.className = 'fas ' + (themeIcons[theme] || 'fa-sun');
        }

        function cycleTheme() {
            const current = getCurrentTheme();
            let idx = themes.indexOf(current);
            if (idx === -1) idx = 2; // default to system
            const next = themes[(idx + 1) % themes.length];
            applyTheme(next);
        }

        // Set initial icon based on current theme
        const initial = getCurrentTheme();
        icon.className = 'fas ' + (themeIcons[initial] || 'fa-sun');

        toggleBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            cycleTheme();
        });

        // Listen for system preference changes when in 'system' mode
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
            const current = document.documentElement.getAttribute('data-theme');
            if (current === 'system') {
                document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    })();
});