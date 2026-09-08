// static/js/platform-settings.js
(function() {
    'use strict';

    const NuunSettings = {
        settings: {},
        initialized: false,

        init(initialSettings) {
            if (this.initialized) return;
            this.settings = initialSettings || {};
            this.applyAll();
            this.initialized = true;
        },

        applyAll() {
            this.applyTheme(this.settings['appearance.theme']);
            this.applyAccent(this.settings['appearance.accent']);
            this.applyFontSize(this.settings['appearance.font_size']);
            this.applyCompactMode(this.settings['appearance.compact_mode']);
            this.applyReducedMotion(this.settings['appearance.reduced_motion']);
        },

        applyTheme(theme) {
            if (!theme) return;
            const html = document.documentElement;
            if (theme === 'system') {
                const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                html.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
            } else {
                html.setAttribute('data-theme', theme);
            }
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
            root.style.setProperty('--primary-hover', this._darken(hex, 0.1));
            root.style.setProperty('--primary-light', this._lighten(hex, 0.85));
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

        _darken(hex, amount) {
            let r = parseInt(hex.slice(1,3), 16);
            let g = parseInt(hex.slice(3,5), 16);
            let b = parseInt(hex.slice(5,7), 16);
            r = Math.max(0, r - r * amount);
            g = Math.max(0, g - g * amount);
            b = Math.max(0, b - b * amount);
            return `#${Math.round(r).toString(16).padStart(2,'0')}${Math.round(g).toString(16).padStart(2,'0')}${Math.round(b).toString(16).padStart(2,'0')}`;
        },

        _lighten(hex, amount) {
            let r = parseInt(hex.slice(1,3), 16);
            let g = parseInt(hex.slice(3,5), 16);
            let b = parseInt(hex.slice(5,7), 16);
            r = Math.min(255, r + (255 - r) * (1 - amount));
            g = Math.min(255, g + (255 - g) * (1 - amount));
            b = Math.min(255, b + (255 - b) * (1 - amount));
            return `#${Math.round(r).toString(16).padStart(2,'0')}${Math.round(g).toString(16).padStart(2,'0')}${Math.round(b).toString(16).padStart(2,'0')}`;
        },

        get(key) {
            return this.settings[key];
        },

        set(key, value) {
            const old = this.settings[key];
            this.settings[key] = value;
            this.applyAll();
            fetch('/settings/api', {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
                },
                body: JSON.stringify({ [key]: value })
            })
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    this.settings[key] = old;
                    this.applyAll();
                    if (typeof window.showToast === 'function') {
                        window.showToast(data.error || 'Failed to update.', 'error');
                    }
                } else {
                    this.settings = data.settings || this.settings;
                    this.applyAll();
                }
            })
            .catch(() => {
                this.settings[key] = old;
                this.applyAll();
                if (typeof window.showToast === 'function') {
                    window.showToast('Network error.', 'error');
                }
            });
        }
    };

    window.NuunSettings = NuunSettings;

    document.addEventListener('DOMContentLoaded', function() {
        const script = document.getElementById('nuun-settings-data');
        if (script) {
            try {
                const initial = JSON.parse(script.textContent);
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