// ============================================
// REGISTRATION VALIDATION – STRICT
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    // DOM refs
    const form = document.getElementById('registerForm');
    const firstName = document.getElementById('firstName');
    const lastName = document.getElementById('lastName');
    const city = document.getElementById('city');
    const schoolSelect = document.getElementById('school');
    const schoolManualInput = document.getElementById('schoolManualInput');
    const phone = document.getElementById('phone');
    const password = document.getElementById('password');
    const confirmPassword = document.getElementById('confirmPassword');
    const locationSelect = document.getElementById('location');
    const gradeSelect = document.getElementById('grade');

    const submitBtn = form.querySelector('button[type="submit"]');

    // Error message elements
    const nameError = document.getElementById('nameError');
    const cityError = document.getElementById('cityError');
    const schoolError = document.getElementById('schoolError');
    const schoolManualError = document.getElementById('schoolManualError');
    const phoneError = document.getElementById('phoneError');
    const passwordError = document.getElementById('passwordError');
    const confirmError = document.getElementById('confirmError');
    const locationError = document.getElementById('locationError');
    const gradeError = document.getElementById('gradeError');

    // Field states
    const fieldStates = {
        firstName: false,
        lastName: false,
        city: false,
        school: false,
        phone: false,
        password: false,
        confirm: false,
        location: false,
        grade: false
    };

    // ============================================
    // VALIDATION FUNCTIONS
    // ============================================

    function validateFirstName() {
        const val = firstName.value.trim();
        const valid = val.length >= 4 && /^[A-Za-z]+$/.test(val);
        showErrorState(firstName, nameError, valid, 'Must be at least 4 letters, no numbers');
        fieldStates.firstName = valid;
        return valid;
    }

    function validateLastName() {
        const val = lastName.value.trim();
        const valid = val.length >= 4 && /^[A-Za-z]+$/.test(val);
        showErrorState(lastName, nameError, valid, 'Must be at least 4 letters, no numbers');
        fieldStates.lastName = valid;
        return valid;
    }

    function validateCity() {
        const val = city.value.trim();
        const valid = val.length >= 5 && /^[A-Za-z\s]+$/.test(val);
        showErrorState(city, cityError, valid, 'Must be at least 5 letters, only letters');
        fieldStates.city = valid;
        return valid;
    }

    function validateSchool() {
        const selected = schoolSelect.value;
        let valid = false;
        if (selected === 'manual') {
            const manual = schoolManualInput.value.trim();
            const words = manual.split(/\s+/).filter(w => w.length > 0);
            valid = words.length >= 2 && words.every(w => w.length >= 4 && /^[A-Za-z]+$/.test(w));
            showErrorState(schoolManualInput, schoolManualError, valid, 'Min 2 words, each 4+ letters, no numbers');
            if (valid) hideError(schoolSelect, schoolError);
        } else {
            valid = selected !== '';
            showErrorState(schoolSelect, schoolError, valid, 'Please select or enter your school');
            if (valid) hideError(schoolManualInput, schoolManualError);
        }
        fieldStates.school = valid;
        return valid;
    }

    function validatePhone() {
        const val = phone.value.replace(/\D/g, '');
        const valid = val.length === 9;
        showErrorState(phone, phoneError, valid, 'Must be exactly 9 digits (e.g., 612345678)');
        fieldStates.phone = valid;
        return valid;
    }

    function validatePassword() {
        const val = password.value;
        const valid = val.length >= 8;
        showErrorState(password, passwordError, valid, 'Minimum 8 characters');
        fieldStates.password = valid;
        if (confirmPassword.value.length > 0) validateConfirm();
        return valid;
    }

    function validateConfirm() {
        const valid = confirmPassword.value === password.value && password.value.length >= 8;
        showErrorState(confirmPassword, confirmError, valid, 'Passwords do not match');
        fieldStates.confirm = valid;
        return valid;
    }

    function validateLocation() {
        const valid = locationSelect.value !== '';
        showErrorState(locationSelect, locationError, valid, 'Please select your location');
        fieldStates.location = valid;
        return valid;
    }

    function validateGrade() {
        const valid = gradeSelect.value !== '';
        showErrorState(gradeSelect, gradeError, valid, 'Please select your grade');
        fieldStates.grade = valid;
        return valid;
    }

    // ============================================
    // UI HELPERS
    // ============================================

    function showErrorState(element, errorEl, valid, message) {
        const wrapper = element.closest('.input-wrapper');
        if (!wrapper) return;
        if (!valid) {
            wrapper.classList.add('error');
            errorEl.textContent = message;
            errorEl.classList.add('visible');
        } else {
            wrapper.classList.remove('error');
            errorEl.classList.remove('visible');
        }
    }

    function hideError(element, errorEl) {
        const wrapper = element.closest('.input-wrapper');
        if (wrapper) wrapper.classList.remove('error');
        if (errorEl) errorEl.classList.remove('visible');
    }

    function updateSubmitButton() {
        const allValid = Object.values(fieldStates).every(v => v === true);
        submitBtn.disabled = !allValid;
        submitBtn.style.opacity = allValid ? '1' : '0.6';
    }

    // ============================================
    // EVENT BINDINGS – only on blur/change/submit
    // ============================================

    firstName.addEventListener('blur', function() {
        validateFirstName();
        updateSubmitButton();
    });
    lastName.addEventListener('blur', function() {
        validateLastName();
        updateSubmitButton();
    });
    city.addEventListener('blur', function() {
        validateCity();
        updateSubmitButton();
    });
    phone.addEventListener('blur', function() {
        validatePhone();
        updateSubmitButton();
    });
    password.addEventListener('blur', function() {
        validatePassword();
        updateSubmitButton();
    });
    confirmPassword.addEventListener('blur', function() {
        validateConfirm();
        updateSubmitButton();
    });

    locationSelect.addEventListener('change', function() {
        validateLocation();
        updateSubmitButton();
    });
    gradeSelect.addEventListener('change', function() {
        validateGrade();
        updateSubmitButton();
    });
    schoolSelect.addEventListener('change', function() {
        validateSchool();
        updateSubmitButton();
    });
    schoolManualInput.addEventListener('blur', function() {
        validateSchool();
        updateSubmitButton();
    });

    // ============================================
    // VALIDATE ALL ON SUBMIT
    // ============================================

    function validateAll() {
        validateFirstName();
        validateLastName();
        validateCity();
        validatePhone();
        validatePassword();
        validateConfirm();
        validateLocation();
        validateGrade();
        validateSchool();
        updateSubmitButton();
    }

    form.addEventListener('submit', function(e) {
        validateAll();
        if (submitBtn.disabled) {
            e.preventDefault();
            const firstInvalid = document.querySelector('.input-wrapper.error input, .input-wrapper.error select');
            if (firstInvalid) {
                firstInvalid.focus();
                if (typeof window.showToast === 'function') {
                    window.showToast('Please fix the highlighted fields.', 'error');
                } else {
                    alert('Please fix the highlighted fields.');
                }
            }
        }
    });

    // Initial state: button disabled, but NO errors shown
    updateSubmitButton();
    // No initial validation call – errors only appear on interaction
});