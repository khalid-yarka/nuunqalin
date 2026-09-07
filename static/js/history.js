// static/js/history.js
// Complete history page JavaScript with defensive rendering and debugging logs

document.addEventListener('DOMContentLoaded', function() {
    let currentPage = 1;
    let perPage = 20;
    let loading = false;
    let hasMore = true;
    let filters = {};

    const timelineList = document.getElementById('timelineList');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const filterType = document.getElementById('filterType');
    const filterStartDate = document.getElementById('filterStartDate');
    const filterEndDate = document.getElementById('filterEndDate');
    const filterSearch = document.getElementById('filterSearch');

    // Load initial stats
    fetchStats();

    // Load first page
    loadEntries(true);

    // Event listeners for filters (debounced)
    let debounceTimer;
    function applyFilters() {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            currentPage = 1;
            hasMore = true;
            if (timelineList) {
                timelineList.innerHTML = '';
            }
            loadEntries(true);
        }, 400);
    }

    if (filterType) filterType.addEventListener('change', applyFilters);
    if (filterStartDate) filterStartDate.addEventListener('change', applyFilters);
    if (filterEndDate) filterEndDate.addEventListener('change', applyFilters);
    if (filterSearch) filterSearch.addEventListener('input', applyFilters);

    // Load more
    window.loadMore = function() {
        if (!loading && hasMore) {
            loadEntries(false);
        }
    };

    // Export
    window.exportHistory = function() {
        const params = buildParams();
        window.location.href = '/history/api/export?' + params;
    };

    function buildParams() {
        const params = new URLSearchParams();
        if (filterType && filterType.value) {
            params.set('types', filterType.value);
        }
        if (filterStartDate && filterStartDate.value) {
            params.set('start_date', filterStartDate.value);
        }
        if (filterEndDate && filterEndDate.value) {
            params.set('end_date', filterEndDate.value);
        }
        if (filterSearch && filterSearch.value) {
            params.set('search', filterSearch.value);
        }
        return params.toString();
    }

    function loadEntries(reset) {
        if (loading) return;
        loading = true;
        if (reset) {
            currentPage = 1;
            hasMore = true;
        }

        const params = buildParams();
        // Add pagination parameters
        const url = '/history/api/entries?' + params + '&page=' + currentPage + '&per_page=' + perPage;
        console.log('History API request URL:', url);

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    throw new Error('HTTP error ' + response.status);
                }
                return response.json();
            })
            .then(data => {
                loading = false;
                console.log('History API response:', data);

                if (data.error) {
                    console.error('API error:', data.error);
                    showEmptyState('Error loading history: ' + data.error);
                    return;
                }

                const entries = data.entries || [];
                const total = data.pagination ? data.pagination.total : 0;

                if (reset) {
                    if (timelineList) timelineList.innerHTML = '';
                }

                if (entries.length === 0 && reset) {
                    showEmptyState('No history entries found.');
                    if (loadMoreBtn) loadMoreBtn.style.display = 'none';
                    hasMore = false;
                    return;
                }

                // Group by date
                const groups = {};
                entries.forEach(entry => {
                    // Safely extract date
                    let dateStr = 'Unknown';
                    if (entry.created_at) {
                        try {
                            dateStr = entry.created_at.split('T')[0];
                        } catch (e) {
                            dateStr = 'Unknown';
                        }
                    }
                    if (!groups[dateStr]) groups[dateStr] = [];
                    groups[dateStr].push(entry);
                });

                let html = '';
                for (const [date, items] of Object.entries(groups)) {
                    const label = formatDate(date);
                    html += `<div class="history-day-group"><div class="day-label">${label}</div>`;
                    items.forEach(item => {
                        html += renderEntry(item);
                    });
                    html += '</div>';
                }

                if (reset) {
                    if (timelineList) timelineList.innerHTML = html;
                } else {
                    if (timelineList) timelineList.insertAdjacentHTML('beforeend', html);
                }

                // Update pagination state
                const totalPages = data.pagination ? data.pagination.pages : 0;
                if (currentPage < totalPages) {
                    if (loadMoreBtn) loadMoreBtn.style.display = 'block';
                    hasMore = true;
                } else {
                    if (loadMoreBtn) loadMoreBtn.style.display = 'none';
                    hasMore = false;
                }
                currentPage++;
            })
            .catch(err => {
                console.error('History fetch error:', err);
                loading = false;
                showEmptyState('Failed to load history. Please try again.');
            });
    }

    function renderEntry(entry) {
        // Defensive: ensure entry exists and has minimal fields
        if (!entry) return '';

        const iconMap = {
            'quiz_attempt': '✅',
            'live_quiz': '⚡',
            'achievement': '🏆',
            'save': '💾',
            'pdf_view': '📄',
            'pdf_download': '⬇️',
            'like': '❤️',
            'report': '⚠️'
        };
        const icon = iconMap[entry.entry_type] || '📌';

        let title = entry.entry_type ? entry.entry_type.replace('_', ' ') : 'Unknown';
        let meta = '';
        let timeAgo = '';

        // Safe time formatting
        if (entry.created_at) {
            try {
                timeAgo = getTimeAgo(entry.created_at);
            } catch (e) {
                timeAgo = 'Invalid date';
            }
        } else {
            timeAgo = 'Unknown date';
        }

        // Parse metadata safely
        let metaData = {};
        try {
            if (entry.metadata) {
                metaData = typeof entry.metadata === 'string' ? JSON.parse(entry.metadata) : entry.metadata;
            }
        } catch (e) {
            // ignore
        }

        // Build title and meta based on entry_type
        switch (entry.entry_type) {
            case 'quiz_attempt':
                const subject = metaData.subject || 'Unknown';
                const score = metaData.score || 0;
                const total = metaData.total || 0;
                const pct = metaData.percentage || 0;
                title = `${subject} Quiz`;
                meta = `Score: ${score}/${total} (${pct}%)`;
                break;
            case 'live_quiz':
                const lqSubject = metaData.subject || 'Unknown';
                const rank = metaData.rank || '-';
                title = `Live Quiz: ${lqSubject}`;
                meta = `Rank: #${rank}`;
                break;
            case 'achievement':
                const achName = metaData.name || 'Achievement';
                title = `Unlocked: ${achName}`;
                meta = metaData.icon || '';
                break;
            case 'save':
                const contentType = metaData.content_type || 'item';
                title = `Saved ${contentType}`;
                break;
            case 'pdf_view':
            case 'pdf_download':
                const pdfTitle = metaData.title || 'PDF';
                title = `${entry.entry_type === 'pdf_view' ? 'Viewed' : 'Downloaded'}: ${pdfTitle}`;
                break;
            case 'like':
                title = entry.action === 'liked' ? '❤️ Liked a question' : '💔 Unliked a question';
                break;
            case 'report':
                title = '⚠️ Reported a question';
                break;
            default:
                if (entry.action) {
                    title = entry.action.charAt(0).toUpperCase() + entry.action.slice(1) + ' ' + (entry.entry_type || 'item');
                } else {
                    title = entry.entry_type || 'Unknown event';
                }
        }

        return `
            <div class="history-entry">
                <span class="entry-icon">${icon}</span>
                <div class="entry-content">
                    <div class="entry-title">${title}</div>
                    ${meta ? `<div class="entry-meta">${meta}</div>` : ''}
                </div>
                <div class="entry-time">${timeAgo}</div>
            </div>
        `;
    }

    function showEmptyState(message) {
        if (!timelineList) return;
        timelineList.innerHTML = `
            <div class="history-empty">
                <span class="icon">📭</span>
                <h3>No history entries</h3>
                <p>${message || 'Start learning to build your history!'}</p>
            </div>
        `;
        if (loadMoreBtn) loadMoreBtn.style.display = 'none';
        hasMore = false;
    }

    function formatDate(dateStr) {
        if (!dateStr || dateStr === 'Unknown') return 'Unknown date';
        const today = new Date().toISOString().split('T')[0];
        const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
        if (dateStr === today) return 'Today';
        if (dateStr === yesterday) return 'Yesterday';
        return dateStr;
    }

    function getTimeAgo(isoDate) {
        if (!isoDate) return 'Unknown';
        try {
            const diff = (Date.now() - new Date(isoDate).getTime()) / 1000;
            if (diff < 60) return 'Just now';
            if (diff < 3600) return Math.floor(diff/60) + 'm ago';
            if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
            if (diff < 604800) return Math.floor(diff/86400) + 'd ago';
            return new Date(isoDate).toLocaleDateString();
        } catch (e) {
            return 'Unknown date';
        }
    }

    function fetchStats() {
        fetch('/history/api/stats')
            .then(response => {
                if (!response.ok) throw new Error('Stats HTTP error');
                return response.json();
            })
            .then(data => {
                const statTotal = document.getElementById('statTotal');
                const statQuizzes = document.getElementById('statQuizzes');
                const statAchievements = document.getElementById('statAchievements');
                const statSaves = document.getElementById('statSaves');
                const statAvgScore = document.getElementById('statAvgScore');

                if (statTotal) statTotal.textContent = data.total || 0;
                if (statQuizzes) statQuizzes.textContent = data.quizzes || 0;
                if (statAchievements) statAchievements.textContent = data.achievements || 0;
                if (statSaves) statSaves.textContent = data.saves || 0;
                if (statAvgScore) statAvgScore.textContent = (data.avg_score || 0) + '%';
            })
            .catch(err => console.error('Stats fetch error:', err));
    }
});