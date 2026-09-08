// static/js/platform-settings.js
/**
 * NuunPlatform Global Settings Runtime
 * Single source of truth for user preferences.
 * Enhanced with error handling, read-back verification, and session sync.
 */
(function() {
    'use strict';

    const NuunSettings = {
        settings: {},
        initialized: false,
        pendingRequests: {},

        // Initialize with server-provided settings
        init(initialSettings) {
            if (this.initialized) return;
            this.settings = initialSettings || {};
            this.applyAll();
            this.initialized = true;
            console.log('✅ NuunSettings initialized with', Object.keys(this.settings).length, 'settings');
        },

        // Apply all settings to the DOM
        applyAll() {
            this.applyTheme(this.settings['appearance.theme']);
            this.applyAccent(this.settings['appearance.accent']);
            this.applyFontSize(this.settings['appearance.font_size']);
            this.applyCompactMode(this.settings['appearance.compact_mode']);
            this.applyReducedMotion(this.settings['appearance.reduced_motion']);
        },

        // --- Individual apply methods ---
        applyTheme(theme) {
            if (!theme) return;
            const html = document.documentElement;
            if (theme === 'system') {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                html.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
            } else {
                html.setAttribute('data-theme', theme);
            }
            // Update toggle icons if present
            document.querySelectorAll('.theme-toggle-icon').forEach(el => {
                if (theme === 'dark') el.className = 'fas fa-moon';
                else if (theme === 'light') el.className = 'fas fa-sun';
                else el.className = 'fas fa-desktop';
            });
            localStorage.setItem('preferred-theme', theme);
        },

        applyAccent(color) {
            if (!color) return;
            const accentMap = {
                'red': '#FF3138',
                'blue': '#3B82F6',
                'green': '#10B981',
                'purple': '#8B5CF6',
                'orange': '#F59E0B'
            };
            const hex = accentMap[color] || '#FF3138';
            const root = document.documentElement;
            root.style.setProperty('--primary', hex);
            root.style.setProperty('--primary-hover', this._darken(hex, 0.15));
            // Improved lighten: use a more sophisticated method that works on dark backgrounds
            root.style.setProperty('--primary-light', this._lighten(hex, 0.88));
            localStorage.setItem('preferred-accent', color);
        },

        applyFontSize(size) {
            if (!size) return;
            const sizes = { small: '14px', medium: '16px', large: '18px' };
            document.documentElement.style.setProperty('--base-font-size', sizes[size] || '16px');
            localStorage.setItem('preferred-font-size', size);
        },

        applyCompactMode(enabled) {
            document.documentElement.classList.toggle('compact-mode', !!enabled);
            localStorage.setItem('preferred-compact', enabled ? '1' : '0');
        },

        applyReducedMotion(enabled) {
            document.documentElement.classList.toggle('reduced-motion', !!enabled);
            localStorage.setItem('preferred-reduced-motion', enabled ? '1' : '0');
        },

        // --- Utility with improved contrast ---
        _darken(hex, amount) {
            let r = parseInt(hex.slice(1,3), 16);
            let g = parseInt(hex.slice(3,5), 16);
            let b = parseInt(hex.slice(5,7), 16);
            r = Math.max(0, Math.round(r - r * amount));
            g = Math.max(0, Math.round(g - g * amount));
            b = Math.max(0, Math.round(b - b * amount));
            return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
        },

        _lighten(hex, amount) {
            let r = parseInt(hex.slice(1,3), 16);
            let g = parseInt(hex.slice(3,5), 16);
            let b = parseInt(hex.slice(5,7), 16);
            // Calculate luminance to adjust the lightening amount for better contrast
            const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
            // For dark colors, lighten more; for light colors, lighten less
            const adjustedAmount = luminance < 0.3 ? Math.min(amount + 0.1, 0.95) : amount;
            r = Math.min(255, Math.round(r + (255 - r) * (1 - adjustedAmount)));
            g = Math.min(255, Math.round(g + (255 - g) * (1 - adjustedAmount)));
            b = Math.min(255, Math.round(b + (255 - b) * (1 - adjustedAmount)));
            return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
        },

        // --- API methods with error handling and read-back ---
        get(key) {
            return this.settings[key];
        },

        set(key, value) {
            const old = this.settings[key];
            this.settings[key] = value;
            this.applyAll();

            return fetch('/settings/api', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                body: JSON.stringify({ [key]: value })
            })
            .then(response => {
                if (!response.ok) {
                    return response.json().then(data => {
                        throw new Error(data.error || 'Server error');
                    });
                }
                return response.json();
            })
            .then(data => {
                if (!data.success) {
                    throw new Error(data.error || 'Update failed');
                }
                if (data.settings) {
                    this.settings = data.settings;
                } else {
                    return this.refresh();
                }
                this.applyAll();
                if (typeof window.showToast === 'function') {
                    window.showToast('Setting updated', 'success');
                }
                return data;
            })
            .catch(err => {
                this.settings[key] = old;
                this.applyAll();
                if (typeof window.showToast === 'function') {
                    window.showToast('Failed to update: ' + err.message, 'error');
                } else {
                    console.error('Settings update failed:', err);
                }
                throw err;
            });
        },

        refresh() {
            return fetch('/settings/api', {
                method: 'GET',
                headers: {
                    'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
                }
            })
            .then(response => response.json())
            .then(data => {
                this.settings = data;
                this.applyAll();
                return data;
            })
            .catch(err => {
                console.error('Failed to refresh settings:', err);
                throw err;
            });
        }
    };

    window.NuunSettings = NuunSettings;

    document.addEventListener('DOMContentLoaded', function() {
        const settingsScript = document.getElementById('nuun-settings-data');
        if (settingsScript) {
            try {
                const initial = JSON.parse(settingsScript.textContent);
                NuunSettings.init(initial);
            } catch (e) {
                console.warn('Failed to parse settings data', e);
            }
        }
    });

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        if (NuunSettings.settings['appearance.theme'] === 'system') {
            document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
        }
    });
})();