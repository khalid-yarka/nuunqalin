// ============================================
// USER SETTINGS – Client-side Logic
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    const tabs = document.querySelectorAll('.tab-btn');
    const panels = {
        profile: document.getElementById('panel-profile'),
        appearance: document.getElementById('panel-appearance'),
        quiz: document.getElementById('panel-quiz'),
        notifications: document.getElementById('panel-notifications'),
        privacy: document.getElementById('panel-privacy'),
    };
    const unsavedIndicator = document.getElementById('unsaved-indicator');

    // ---------- Tab Switching ----------
    tabs.forEach(btn => {
        btn.addEventListener('click', function() {
            tabs.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            const tab = this.dataset.tab;
            Object.keys(panels).forEach(key => {
                panels[key].classList.toggle('active', key === tab);
            });
            // Hide unsaved indicator when switching tabs (optional)
            unsavedIndicator.style.display = 'none';
        });
    });

    // ---------- Unsaved Changes Detection ----------
    function markUnsaved() {
        unsavedIndicator.style.display = 'block';
    }

    // Watch all inputs and toggles
    document.querySelectorAll('.settings-form input, .settings-form select').forEach(el => {
        el.addEventListener('change', markUnsaved);
        el.addEventListener('input', markUnsaved);
    });
    document.querySelectorAll('.toggle-switch input').forEach(el => {
        el.addEventListener('change', markUnsaved);
    });

    // ---------- Profile Form ----------
    const profileForm = document.getElementById('profile-form');
    profileForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            first_name: document.getElementById('first_name').value.trim(),
            last_name: document.getElementById('last_name').value.trim(),
            middle_name: document.getElementById('middle_name').value.trim(),
            school: document.getElementById('school').value.trim(),
            grade: document.getElementById('grade').value.trim(),
            city: document.getElementById('city').value.trim(),
            location: document.getElementById('location').value.trim(),
        };
        // Simple validation
        if (data.first_name.length < 4 || !/^[A-Za-z]+$/.test(data.first_name)) {
            showToast('First name must be at least 4 letters and contain only letters.', 'error');
            return;
        }
        if (data.last_name.length < 4 || !/^[A-Za-z]+$/.test(data.last_name)) {
            showToast('Last name must be at least 4 letters and contain only letters.', 'error');
            return;
        }
        fetch('/settings/update-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('✅ Profile updated!', 'success');
                unsavedIndicator.style.display = 'none';
            } else {
                showToast(result.error || 'Error updating profile.', 'error');
            }
        })
        .catch(() => showToast('Network error. Please try again.', 'error'));
    });

    // ---------- Theme Selector ----------
    const themeOptions = document.querySelectorAll('.theme-option');
    const saveThemeBtn = document.getElementById('save-theme-btn');
    let selectedTheme = document.querySelector('.theme-option.active')?.dataset.theme || 'system';

    themeOptions.forEach(opt => {
        opt.addEventListener('click', function() {
            themeOptions.forEach(o => o.classList.remove('active'));
            this.classList.add('active');
            selectedTheme = this.dataset.theme;
            // Live preview – apply theme immediately
            document.documentElement.setAttribute('data-theme', selectedTheme === 'system' ? 
                (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : 
                selectedTheme);
            markUnsaved();
        });
    });

    saveThemeBtn.addEventListener('click', function() {
        fetch('/settings/update-appearance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme: selectedTheme })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('🎨 Theme updated!', 'success');
                unsavedIndicator.style.display = 'none';
                // Store preference server-side; also set local storage for consistency
                localStorage.setItem('preferred-theme', selectedTheme);
            } else {
                showToast(result.error || 'Error updating theme.', 'error');
            }
        })
        .catch(() => showToast('Network error.', 'error'));
    });

    // Restore theme from server settings
    const currentTheme = document.querySelector('.theme-option.active')?.dataset.theme || 'system';
    selectedTheme = currentTheme;

    // ---------- Quiz Preferences ----------
    const quizForm = document.getElementById('quiz-prefs-form');
    quizForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            default_question_count: parseInt(document.getElementById('default_question_count').value),
            default_difficulty: parseInt(document.getElementById('default_difficulty').value),
            show_correct_immediately: document.getElementById('show_correct_immediately').checked ? 1 : 0,
            skip_rating_after_quiz: document.getElementById('skip_rating_after_quiz').checked ? 1 : 0,
        };
        fetch('/settings/update-quiz-preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('📝 Quiz preferences saved!', 'success');
                unsavedIndicator.style.display = 'none';
            } else {
                showToast(result.error || 'Error saving quiz preferences.', 'error');
            }
        })
        .catch(() => showToast('Network error.', 'error'));
    });

    // ---------- Notification Preferences ----------
    const notifForm = document.getElementById('notif-form');
    notifForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const toggles = notifForm.querySelectorAll('.toggle-switch input');
        const data = {};
        toggles.forEach(t => {
            data[t.id] = t.checked ? 1 : 0;
        });
        fetch('/settings/update-notifications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('🔔 Notification settings saved!', 'success');
                unsavedIndicator.style.display = 'none';
            } else {
                showToast(result.error || 'Error saving notifications.', 'error');
            }
        })
        .catch(() => showToast('Network error.', 'error'));
    });

    // ---------- Privacy Settings ----------
    const privacyForm = document.getElementById('privacy-form');
    privacyForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const data = {
            show_on_leaderboard: document.getElementById('show_on_leaderboard').checked ? 1 : 0,
            show_public_id: document.getElementById('show_public_id').checked ? 1 : 0,
        };
        fetch('/settings/update-privacy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('🔒 Privacy settings saved!', 'success');
                unsavedIndicator.style.display = 'none';
            } else {
                showToast(result.error || 'Error saving privacy settings.', 'error');
            }
        })
        .catch(() => showToast('Network error.', 'error'));
    });

    // ---------- Change Password ----------
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
        if (confirmPw.length === 0) {
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

        fetch('/settings/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: current, new_password: newPw, confirm_password: confirm })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast('✅ Password changed. Please log in again.', 'success');
                // Force logout after a short delay
                setTimeout(() => {
                    window.location.href = '/logout';
                }, 2000);
            } else {
                showToast(result.error || 'Error changing password.', 'error');
            }
        })
        .catch(() => showToast('Network error.', 'error'));
    });

    // ---------- Toast Helper ----------
    function showToast(message, type) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, type);
        } else {
            alert(message);
        }
    }
});