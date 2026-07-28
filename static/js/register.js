// ============================================
// REGISTRATION PAGE JAVASCRIPT
// ============================================

// ============================================
// SCHOOL DATA
// ============================================
const schoolData = {
    'SO': ['Mogadishu Secondary School', 'Kismayo High School', 'Baidoa School', 'Jowhar Academy'],
    'PL': ['Garowe Secondary School', 'Bosaso High School', 'Galkayo School', 'Qardho Academy'],
    'SL': ['Sheikh Secondary School', 'Amoud School', 'Hargeisa High School', 'Burco Academy']
};

// ============================================
// UPDATE SCHOOL DROPDOWN
// ============================================
function updateSchools() {
    const location = document.getElementById('location').value;
    const schoolSelect = document.getElementById('school');
    const manualDiv = document.getElementById('schoolManual');

    // Clear existing options
    schoolSelect.innerHTML = '<option value="">Select School</option>';

    if (location && schoolData[location]) {
        schoolData[location].forEach(function(school) {
            const option = document.createElement('option');
            option.value = school;
            option.textContent = school;
            schoolSelect.appendChild(option);
        });
    }

    // Add manual option as last item
    const manualOption = document.createElement('option');
    manualOption.value = 'manual';
    manualOption.textContent = '✏️ Add school manually';
    manualOption.style.color = '#FF3138';
    manualOption.style.fontWeight = '600';
    schoolSelect.appendChild(manualOption);

    // Hide manual input by default
    manualDiv.classList.remove('active');
    document.getElementById('schoolManualInput').value = '';
}

// ============================================
// HANDLE SCHOOL SELECT
// ============================================
function handleSchoolSelect() {
    const schoolSelect = document.getElementById('school');
    const manualDiv = document.getElementById('schoolManual');

    if (schoolSelect.value === 'manual') {
        manualDiv.classList.add('active');
        document.getElementById('schoolManualInput').focus();
        schoolSelect.removeAttribute('required');
    } else {
        manualDiv.classList.remove('active');
        document.getElementById('schoolManualInput').value = '';
        schoolSelect.setAttribute('required', 'required');
    }
}

// ============================================
// TOGGLE PASSWORD
// ============================================
function togglePassword(fieldId) {
    const input = document.getElementById(fieldId);
    const icon = document.getElementById(fieldId + 'Icon');

    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'fas fa-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'fas fa-eye';
    }
}

// ============================================
// VALIDATION HELPERS
// ============================================
function showError(wrapperId, errorId) {
    const wrapper = document.getElementById(wrapperId);
    if (wrapper) wrapper.classList.add('error');
    const error = document.getElementById(errorId);
    if (error) error.classList.add('visible');
}

function hideError(wrapperId, errorId) {
    const wrapper = document.getElementById(wrapperId);
    if (wrapper) wrapper.classList.remove('error');
    const error = document.getElementById(errorId);
    if (error) error.classList.remove('visible');
}

// ============================================
// REAL-TIME VALIDATION
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    // Phone validation
    const phoneInput = document.getElementById('phone');
    if (phoneInput) {
        phoneInput.addEventListener('input', function() {
            const val = this.value.replace(/\D/g, '');
            if (val.length >= 9) {
                hideError('phoneWrapper', 'phoneError');
            } else {
                showError('phoneWrapper', 'phoneError');
            }
        });
    }

    // Password validation
    const passwordInput = document.getElementById('password');
    if (passwordInput) {
        passwordInput.addEventListener('input', function() {
            if (this.value.length >= 8) {
                hideError('passwordWrapper', 'passwordError');
            } else {
                showError('passwordWrapper', 'passwordError');
            }
            checkConfirmMatch();
        });
    }

    // Confirm password validation
    const confirmInput = document.getElementById('confirmPassword');
    if (confirmInput) {
        confirmInput.addEventListener('input', function() {
            checkConfirmMatch();
        });
    }

    // Initialize school dropdown
    updateSchools();
});

// ============================================
// CHECK CONFIRM PASSWORD MATCH
// ============================================
function checkConfirmMatch() {
    const pass = document.getElementById('password');
    const confirm = document.getElementById('confirmPassword');
    
    if (!pass || !confirm) return;

    if (confirm.value.length > 0 && pass.value !== confirm.value) {
        showError('confirmWrapper', 'confirmError');
    } else if (confirm.value.length > 0 && pass.value === confirm.value) {
        hideError('confirmWrapper', 'confirmError');
    }
}