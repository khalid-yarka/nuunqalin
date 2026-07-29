// ============================================
// MAIN JAVASCRIPT
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    // ============================================
    // TOAST NOTIFICATIONS
    // ============================================
    
    // Convert old flash messages to toasts
    const flashContainer = document.getElementById('flashContainer');
    if (flashContainer) {
        const flashMessages = flashContainer.querySelectorAll('.flash-message');
        flashMessages.forEach(function(msg) {
            const category = msg.classList.contains('flash-success') ? 'success' :
                           msg.classList.contains('flash-error') ? 'error' :
                           msg.classList.contains('flash-info') ? 'info' : 'warning';
            const message = msg.textContent.trim();
            showToast(message, category);
            msg.remove();
        });
        flashContainer.remove();
    }

    // ============================================
    // DARK MODE - FIXED
    // ============================================
    
    const darkModeToggle = document.getElementById('darkModeToggle');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
    
    // Get saved theme or system preference
    let currentTheme = localStorage.getItem('theme') || 
                      (prefersDark.matches ? 'dark' : 'light');
    
    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        currentTheme = theme;
        
        // Update toggle icon
        if (darkModeToggle) {
            const moonIcon = darkModeToggle.querySelector('.moon-icon');
            const sunIcon = darkModeToggle.querySelector('.sun-icon');
            if (theme === 'dark') {
                if (moonIcon) moonIcon.style.display = 'none';
                if (sunIcon) sunIcon.style.display = 'inline-block';
            } else {
                if (moonIcon) moonIcon.style.display = 'inline-block';
                if (sunIcon) sunIcon.style.display = 'none';
            }
        }
    }
    
    // Apply initial theme
    setTheme(currentTheme);
    
    // Toggle theme on click - with error handling
    if (darkModeToggle) {
        darkModeToggle.addEventListener('click', function(e) {
            e.preventDefault();
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            setTheme(newTheme);
        });
    } else {
        // Fallback: find by class if ID fails
        const toggleBtn = document.querySelector('.dark-mode-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', function(e) {
                e.preventDefault();
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                setTheme(newTheme);
            });
        }
    }
    
    // Listen for system theme changes
    prefersDark.addEventListener('change', function(e) {
        if (!localStorage.getItem('theme')) {
            setTheme(e.matches ? 'dark' : 'light');
        }
    });

    // ============================================
    // TOAST FUNCTIONS
    // ============================================
    
    function showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toast-container');
        if (!container) {
            // Fallback: create container
            const newContainer = document.createElement('div');
            newContainer.id = 'toast-container';
            newContainer.style.cssText = `
                position: fixed; top: 20px; right: 20px; z-index: 99999;
                display: flex; flex-direction: column; gap: 10px;
                max-width: 380px; width: 100%; pointer-events: none;
            `;
            document.body.appendChild(newContainer);
        }
        
        const toastContainer = document.getElementById('toast-container');
        if (!toastContainer) return;
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };
        
        toast.innerHTML = `
            <span class="toast-icon"><i class="fas ${icons[type] || icons.info}"></i></span>
            <span class="toast-content">${message}</span>
            <button class="toast-close" aria-label="Close">&times;</button>
        `;
        
        toastContainer.appendChild(toast);
        
        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.addEventListener('click', function() {
            removeToast(toast);
        });
        
        const timeout = setTimeout(function() {
            removeToast(toast);
        }, duration);
        
        toast.addEventListener('mouseenter', function() {
            clearTimeout(timeout);
        });
        
        toast.addEventListener('mouseleave', function() {
            setTimeout(function() {
                removeToast(toast);
            }, duration);
        });
        
        return toast;
    }
    
    function removeToast(toast) {
        if (toast.classList.contains('toast-removing')) return;
        toast.classList.add('toast-removing');
        setTimeout(function() {
            toast.remove();
        }, 300);
    }
    
    window.showToast = showToast;

    // ============================================
    // LOADING STATES
    // ============================================
    
    document.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function() {
            const btn = this.querySelector('button[type="submit"]');
            if (btn) {
                const originalText = btn.innerHTML;
                btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
                btn.disabled = true;
                
                setTimeout(function() {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }, 30000);
            }
        });
    });

    // ============================================
    // AUTO-CLOSE LEGACY FLASH MESSAGES
    // ============================================
    
    document.querySelectorAll('.flash-message:not([data-toast])').forEach(function(msg) {
        setTimeout(function() {
            if (msg) {
                msg.style.opacity = '0';
                msg.style.transform = 'translateY(-10px)';
                msg.style.transition = 'all 0.4s ease';
                setTimeout(function() {
                    msg.remove();
                }, 400);
            }
        }, 5000);
    });
});

// ============================================
// UTILITY FUNCTIONS
// ============================================

function togglePassword(btn) {
    const input = btn.parentElement.querySelector('input');
    const icon = btn.querySelector('i');
    
    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'fas fa-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'fas fa-eye';
    }
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function() {
            window.showToast('Copied to clipboard!', 'success');
        }).catch(function() {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
        window.showToast('Copied to clipboard!', 'success');
    } catch (e) {
        window.showToast('Failed to copy.', 'error');
    }
    document.body.removeChild(textarea);
}