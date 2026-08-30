// ============================================
// MAIN.JS - GLOBAL UTILITIES
// ============================================

document.addEventListener('DOMContentLoaded', function() {

    // ============================================
    // THEME PERSISTENCE (Global)
    // ============================================

    // Define global applyTheme function
    window.applyTheme = function(theme) {
        if (theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
            localStorage.setItem('preferred-theme', 'system');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('preferred-theme', theme);
        }
        // Update floating toggle icon if present (login/register)
        const icon = document.getElementById('fabThemeIcon');
        if (icon) {
            if (theme === 'system') icon.className = 'fas fa-desktop';
            else if (theme === 'dark') icon.className = 'fas fa-moon';
            else icon.className = 'fas fa-sun';
        }
        // Also update dashboard toggle if present (handled by its own logic)
    };

    // Apply saved theme on load
    (function() {
        const savedTheme = localStorage.getItem('preferred-theme') || 'system';
        window.applyTheme(savedTheme);

        // Listen for system changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
            const current = localStorage.getItem('preferred-theme') || 'system';
            if (current === 'system') {
                document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
            }
        });
    })();

    // ============================================
    // TOAST SYSTEM
    // ============================================
    window.showToast = function(message, type, duration) {
        type = type || 'info';
        duration = duration || 4000;

        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.innerHTML = `
            <span class="toast-icon">
                <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : type === 'warning' ? 'fa-exclamation-triangle' : 'fa-info-circle'}"></i>
            </span>
            <span class="toast-message">${message}</span>
            <button class="toast-close">&times;</button>
        `;

        container.appendChild(toast);

        // Auto dismiss
        const timeout = setTimeout(function() {
            toast.remove();
        }, duration);

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', function() {
            clearTimeout(timeout);
            toast.remove();
        });

        // Hover pause
        toast.addEventListener('mouseenter', function() {
            clearTimeout(timeout);
        });
        toast.addEventListener('mouseleave', function() {
            setTimeout(function() {
                toast.remove();
            }, 1500);
        });
    };

    // ============================================
    // AUTO-DISMISS FLASH MESSAGES
    // ============================================
    const flashContainer = document.getElementById('flashContainer');
    if (flashContainer) {
        setTimeout(function() {
            flashContainer.style.transition = 'opacity 0.5s ease';
            flashContainer.style.opacity = '0';
            setTimeout(function() {
                flashContainer.remove();
            }, 500);
        }, 5000);
    }

    // ============================================
    // CSRF TOKEN HELPER (for AJAX)
    // ============================================
    window.getCsrfToken = function() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.content;
        const input = document.querySelector('input[name="csrf_token"]');
        if (input) return input.value;
        return '';
    };

    // ============================================
    // NOTIFICATION DROPDOWN TOGGLE
    // ============================================
    const notifToggle = document.getElementById('notificationToggle');
    const notifDropdown = document.getElementById('notificationDropdown');

    if (notifToggle && notifDropdown) {
        notifToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            notifDropdown.classList.toggle('open');
        });

        document.addEventListener('click', function(e) {
            if (!notifDropdown.contains(e.target) && e.target !== notifToggle) {
                notifDropdown.classList.remove('open');
            }
        });
    }

    console.log('✅ NuunPlatform main.js loaded');
});