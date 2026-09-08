// ============================================
// USER SETTINGS - Complete Logic
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    const sections = document.querySelectorAll('.settings-section');
    const navItems = document.querySelectorAll('.settings-nav-item');
    const unsavedIndicator = document.getElementById('unsaved-indicator');
    let unsavedChanges = false;
    let currentSection = 'profile';

    // ---------- Navigation ----------
    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const sectionId = this.dataset.section;
            showSection(sectionId);
        });
    });

    function showSection(id) {
        sections.forEach(sec => sec.classList.remove('active'));
        document.getElementById(id).classList.add('active');
        navItems.forEach(nav => nav.classList.remove('active'));
        document.querySelector(`.settings-nav-item[data-section="${id}"]`).classList.add('active');
        currentSection = id;
        // Update URL hash without scrolling
        history.pushState(null, '', '# ' + id);
    }

    // Restore section from hash
    if (window.location.hash) {
        const hash = window.location.hash.replace('#', '');
        const target = document.querySelector(`.settings-nav-item[data-section="${hash}"]`);
        if (target) showSection(hash);
    }

    // ---------- Unsaved changes ----------
    function markUnsaved() {
        if (!unsavedChanges) {
            unsavedChanges = true;
            unsavedIndicator.style.display = 'block';
        }
    }

    function clearUnsaved() {
        unsavedChanges = false;
        unsavedIndicator.style.display = 'none';
    }

    // Watch all inputs/toggles in forms
    document.querySelectorAll('.settings-form input, .settings-form select, .settings-form textarea').forEach(el => {
        el.addEventListener('change', markUnsaved);
        el.addEventListener('input', markUnsaved);
    });

    // Beforeunload confirmation
    window.addEventListener('beforeunload', function(e) {
        if (unsavedChanges) {
            e.preventDefault();
            e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
        }
    });

    // ---------- Toast helper ----------
    function showToast(message, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            alert(message);
        }
    }

    // ---------- AJAX submit helper ----------
    function submitForm(url, data, formId) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast(result.message || 'Saved!', 'success');
                clearUnsaved();
            } else {
                let msg = result.error || 'Error saving.';
                if (result.errors) {
                    msg = Object.values(result.errors).join(' ');
                }
                showToast(msg, 'error');
            }
            return result;
        })
        .catch(() => {
            showToast('Network error. Please try again.', 'error');
        });
    }

    // ---------- PROFILE ----------
    const profileForm = document.getElementById('profile-form');
    profileForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            first_name: document.getElementById('first_name').value.trim(),
            last_name: document.getElementById('last_name').value.trim(),
            middle_name: document.getElementById('middle_name').value.trim(),
            school: document.getElementById('school_manual').style.display !== 'none' ?
                    document.getElementById('school_manual').value.trim() :
                    document.getElementById('school_select').value,
            grade: document.getElementById('grade').value,
            city: document.getElementById('city').value.trim(),
            location: document.getElementById('location').value,
            curriculum: document.getElementById('curriculum').value.trim()
        };
        // Manual school check: if select is 'manual' but input empty, block
        if (document.getElementById('school_select').value === 'manual' && !data.school) {
            showToast('Please enter your school name.', 'error');
            return;
        }
        submitForm('/settings/update-profile', data, 'profile-form');
    });

    // ---------- PUBLIC ID ----------
    const editIdBtn = document.getElementById('editIdBtn');
    const regenerateIdBtn = document.getElementById('regenerateIdBtn');
    const saveIdBtn = document.getElementById('saveIdBtn');
    const cancelIdBtn = document.getElementById('cancelIdBtn');
    const editIdInput = document.getElementById('editIdInput');
    const publicIdFeedback = document.getElementById('publicIdFeedback');

    if (regenerateIdBtn) {
        regenerateIdBtn.addEventListener('click', function() {
            if (!confirm('Regenerate a new random public ID? This cannot be undone.')) return;
            submitForm('/settings/update-public-id', { action: 'regenerate' })
                .then(result => {
                    if (result.success && result.public_id) {
                        document.querySelector('.current-id').textContent = '#' + result.public_id;
                        publicIdFeedback.innerHTML = '<span style="color:#10B981;">✅ New public ID: ' + result.public_id + '</span>';
                    }
                });
        });
    }

    if (editIdBtn) {
        editIdBtn.addEventListener('click', function() {
            editIdBtn.style.display = 'none';
            editIdInput.style.display = 'inline-block';
            saveIdBtn.style.display = 'inline-block';
            cancelIdBtn.style.display = 'inline-block';
            editIdInput.value = '';
            editIdInput.focus();
            publicIdFeedback.innerHTML = '';
        });
        cancelIdBtn.addEventListener('click', function() {
            editIdBtn.style.display = 'inline-block';
            editIdInput.style.display = 'none';
            saveIdBtn.style.display = 'none';
            cancelIdBtn.style.display = 'none';
            publicIdFeedback.innerHTML = '';
        });
        saveIdBtn.addEventListener('click', function() {
            const newId = editIdInput.value.trim().toUpperCase();
            if (!newId || !/^[A-Z0-9]{4}$/.test(newId)) {
                publicIdFeedback.innerHTML = '<span style="color:#EF4444;">❌ ID must be exactly 4 characters: letters A-Z and digits 0-9.</span>';
                return;
            }
            submitForm('/settings/update-public-id', { action: 'edit', public_id: newId })
                .then(result => {
                    if (result.success && result.public_id) {
                        document.querySelector('.current-id').textContent = '#' + result.public_id;
                        publicIdFeedback.innerHTML = '<span style="color:#10B981;">✅ Public ID updated to ' + result.public_id + '</span>';
                        editIdBtn.style.display = 'inline-block';
                        editIdInput.style.display = 'none';
                        saveIdBtn.style.display = 'none';
                        cancelIdBtn.style.display = 'none';
                    }
                });
        });
    }

    // ---------- APPEARANCE ----------
    const appearanceForm = document.getElementById('appearance-form');
    const themeOptions = document.querySelectorAll('.theme-option');
    const accentOptions = document.querySelectorAll('.accent-option');
    const compactToggle = document.getElementById('compact_mode');

    // Restore selected theme
    const savedTheme = document.querySelector('.theme-option.active')?.dataset.theme || 'system';
    themeOptions.forEach(opt => {
        opt.classList.toggle('active', opt.dataset.theme === savedTheme);
    });

    themeOptions.forEach(opt => {
        opt.addEventListener('click', function() {
            themeOptions.forEach(o => o.classList.remove('active'));
            this.classList.add('active');
            // Live preview
            const theme = this.dataset.theme;
            if (typeof window.applyTheme === 'function') {
                window.applyTheme(theme);
            }
            markUnsaved();
        });
    });

    accentOptions.forEach(btn => {
        btn.addEventListener('click', function() {
            accentOptions.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            document.getElementById('accent_color').value = this.dataset.accent;
            // Apply accent via CSS variable (optional)
            document.documentElement.style.setProperty('--primary', getComputedStyle(this).backgroundColor);
            markUnsaved();
        });
    });
    // Set initial active accent
    const initialAccent = document.getElementById('accent_color').value || 'red';
    accentOptions.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.accent === initialAccent);
    });

    appearanceForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            theme: document.querySelector('.theme-option.active')?.dataset.theme || 'system',
            accent: document.getElementById('accent_color').value,
            font_size: document.getElementById('font_size').value,
            compact_mode: compactToggle.checked
        };
        submitForm('/settings/update-appearance', data, 'appearance-form');
    });

    // ---------- QUIZ PREFERENCES ----------
    const quizForm = document.getElementById('quiz-prefs-form');
    // Populate default subject dropdown
    const subjectSelect = document.getElementById('default_subject');
    if (userSubjects && userSubjects.length) {
        userSubjects.forEach(sub => {
            const opt = document.createElement('option');
            opt.value = sub.code;
            opt.textContent = sub.name;
            if (sub.code === '{{ settings.default_subject }}') opt.selected = true;
            subjectSelect.appendChild(opt);
        });
    }

    quizForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            default_question_count: parseInt(document.getElementById('default_question_count').value),
            default_difficulty: parseInt(document.getElementById('default_difficulty').value),
            default_subject: document.getElementById('default_subject').value,
            show_correct_immediately: document.getElementById('show_correct_immediately').checked ? 1 : 0,
            skip_rating_after_quiz: document.getElementById('skip_rating_after_quiz').checked ? 1 : 0,
            auto_skip_enabled: document.getElementById('auto_skip_enabled').checked ? 1 : 0
        };
        submitForm('/settings/update-quiz-preferences', data, 'quiz-prefs-form');
    });

    // ---------- NOTIFICATIONS ----------
    const notifForm = document.getElementById('notif-form');
    notifForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const toggles = notifForm.querySelectorAll('.toggle-switch input');
        const data = {};
        toggles.forEach(t => {
            data[t.id] = t.checked ? 1 : 0;
        });
        submitForm('/settings/update-notifications', data, 'notif-form');
    });

    // ---------- PRIVACY ----------
    const privacyForm = document.getElementById('privacy-form');
    privacyForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            show_on_leaderboard: document.getElementById('show_on_leaderboard').checked ? 1 : 0,
            show_public_id: document.getElementById('show_public_id').checked ? 1 : 0,
        };
        submitForm('/settings/update-privacy', data, 'privacy-form');
    });

    // ---------- PASSWORD ----------
    const passwordForm = document.getElementById('password-form');
    const strengthBar = document.getElementById('password-strength');
    const matchMsg = document.getElementById('password-match');

    document.getElementById('new_password').addEventListener('input', function() {
        const val = this.value;
        let strength = 'weak';
        if (val.length >= 8 && /[A-Z]/.test(val) && /[a-z]/.test(val) && /\d/.test(val) && /[^A-Za-z0-9]/.test(val)) {
            strength = 'strong';
        } else if (val.length >= 8) {
            strength = 'medium';
        }
        strengthBar.innerHTML = `<div class="fill ${strength}"></div>`;
        checkPasswordMatch();
    });

    document.getElementById('confirm_password').addEventListener('input', checkPasswordMatch);

    function checkPasswordMatch() {
        const newPw = document.getElementById('new_password').value;
        const confirmPw = document.getElementById('confirm_password').value;
        if (!confirmPw) {
            matchMsg.textContent = '';
            matchMsg.className = 'password-match';
            return;
        }
        if (newPw === confirmPw) {
            matchMsg.textContent = '✅ Passwords match';
            matchMsg.className = 'password-match match';
        } else {
            matchMsg.textContent = '❌ Passwords do not match';
            matchMsg.className = 'password-match no-match';
        }
    }

    passwordForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const current = document.getElementById('current_password').value;
        const newPw = document.getElementById('new_password').value;
        const confirm = document.getElementById('confirm_password').value;
        if (newPw !== confirm) {
            showToast('Passwords do not match.', 'error');
            return;
        }
        if (newPw.length < 8) {
            showToast('New password must be at least 8 characters.', 'error');
            return;
        }
        if (!confirm('Are you sure you want to change your password? You will be logged out.')) return;

        submitForm('/settings/change-password', {
            current_password: current,
            new_password: newPw,
            confirm_password: confirm
        }).then(result => {
            if (result.success) {
                setTimeout(() => window.location.href = '/logout', 2000);
            }
        });
    });

    // ---------- LIVE QUIZ DEFAULTS ----------
    const liveQuizForm = document.getElementById('livequiz-form');
    if (liveQuizForm) {
        liveQuizForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const data = {
                default_time_per_question: parseInt(document.getElementById('default_time_per_question').value),
                default_max_participants: parseInt(document.getElementById('default_max_participants').value),
                default_privacy: parseInt(document.querySelector('input[name="default_privacy"]:checked').value)
            };
            submitForm('/settings/update-live-quiz-defaults', data, 'livequiz-form');
        });
    }

    // ---------- TIER LOCKED FEATURES ----------
    // Auto-advance toggle for Danbe: upgrade button
    document.querySelectorAll('.upgrade-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const feature = this.dataset.feature;
            const requiredTier = this.dataset.requiredTier || 'dhexe';
            if (typeof window.openSafkaPreview === 'function') {
                window.openSafkaPreview({ feature: feature, requiredTier: requiredTier });
            }
        });
    });

    // Toggle disabled for locked features
    document.querySelectorAll('.toggle-item.locked input[type="checkbox"]').forEach(cb => {
        cb.disabled = true;
        cb.closest('.toggle-item').addEventListener('click', function(e) {
            if (e.target.tagName !== 'INPUT') {
                const upgradeBtn = this.querySelector('.upgrade-btn');
                if (upgradeBtn) upgradeBtn.click();
            }
        });
    });

    // Hide/show curriculum based on location
    window.toggleCurriculum = function() {
        const loc = document.getElementById('location').value;
        const row = document.getElementById('curriculum_row');
        if (loc === 'PL') {
            row.style.display = 'block';
            document.getElementById('curriculum').required = true;
        } else {
            row.style.display = 'none';
            document.getElementById('curriculum').required = false;
            document.getElementById('curriculum').value = '';
        }
    };
    window.toggleCurriculum();

    // School manual toggle
    window.toggleSchoolManual = function() {
        const select = document.getElementById('school_select');
        const manual = document.getElementById('school_manual');
        if (select.value === 'manual') {
            manual.style.display = 'block';
            manual.required = true;
        } else {
            manual.style.display = 'none';
            manual.required = false;
            manual.value = '';
        }
    };
    // Populate school dropdown with default list from registration (simplified)
    // This would normally be passed from backend, but we can include a small static list or fetch.
    // For now, we'll let the user select 'manual' only.
    // In a real app, you'd pass the school list from the backend.

    // Handle form submission with unsaved flag clear
    document.querySelectorAll('.settings-form').forEach(form => {
        form.addEventListener('submit', function() {
            // The submitForm function will clear unsaved on success.
        });
    });

    console.log('✅ Settings.js loaded');
});