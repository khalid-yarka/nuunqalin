// ============================================
// LIVE QUIZ JAVASCRIPT
// ============================================

// ============================================
// NOTIFICATION HELPERS
// ============================================

function playNotificationSound() {
    try {
        // Create audio context
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        
        // Create oscillator
        const oscillator = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        
        // Set frequency (A note)
        oscillator.frequency.value = 440;
        oscillator.type = 'sine';
        
        // Set volume
        gainNode.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.5);
        
        // Play
        oscillator.start(audioCtx.currentTime);
        oscillator.stop(audioCtx.currentTime + 0.5);
    } catch (e) {
        // Silently fail if audio not supported
    }
}

function sendBrowserNotification(title, body, url) {
    if (!("Notification" in window)) {
        return;
    }
    
    if (Notification.permission === "granted") {
        const notification = new Notification(title, {
            body: body,
            icon: '/static/images/logo.png',
            tag: 'live-quiz',
            requireInteraction: true
        });
        
        notification.onclick = function() {
            window.focus();
            if (url) {
                window.location.href = url;
            }
            notification.close();
        };
    } else if (Notification.permission !== "denied") {
        Notification.requestPermission().then(function(permission) {
            if (permission === "granted") {
                sendBrowserNotification(title, body, url);
            }
        });
    }
}

function notifyQuizStarted(quizId, quizTitle) {
    // Sound
    playNotificationSound();
    
    // In-app toast
    window.showToast('🚀 Quiz "' + quizTitle + '" has started! Get ready!', 'success', 5000);
    
    // Browser notification
    sendBrowserNotification(
        '🚀 Quiz Started!',
        '"' + quizTitle + '" has started. Join now!',
        '/live-quiz/play/' + quizId
    );
}

// ============================================
// SHARE HELPERS
// ============================================

function shareLiveQuiz(joinCode, platform) {
    const url = window.location.origin + '/live-quiz/join';
    const text = `🎯 Join my live quiz!\n📌 Join Code: ${joinCode}\n🔗 ${url}`;
    
    if (platform === 'whatsapp') {
        window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank');
    } else if (platform === 'telegram') {
        window.open(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`, '_blank');
    } else {
        // Copy link
        navigator.clipboard.writeText(text).then(function() {
            window.showToast('Link copied to clipboard!', 'success');
        });
    }
}

// ============================================
// QUIZ STATE MANAGEMENT
// ============================================

class LiveQuizManager {
    constructor(quizId) {
        this.quizId = quizId;
        this.participantId = null;
        this.currentQuestion = null;
        this.timer = null;
        this.isAnswered = false;
        this.isRated = false;
        this.listeners = {};
    }
    
    on(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);
    }
    
    emit(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(cb => cb(data));
        }
    }
    
    async join() {
        // Implementation
    }
    
    async start() {
        // Implementation
    }
    
    async submitAnswer(questionId, answer) {
        // Implementation
    }
    
    async submitRating(questionId, rating) {
        // Implementation
    }
    
    async skipQuestion(questionId) {
        // Implementation
    }
    
    async getLeaderboard() {
        // Implementation
    }
}

// ============================================
// EXPOSE GLOBALLY
// ============================================

window.LiveQuizManager = LiveQuizManager;
window.playNotificationSound = playNotificationSound;
window.sendBrowserNotification = sendBrowserNotification;
window.notifyQuizStarted = notifyQuizStarted;
window.shareLiveQuiz = shareLiveQuiz;